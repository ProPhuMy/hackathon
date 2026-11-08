from __future__ import annotations

from typing import Callable
import numpy as np

from .config import Config
from .door import DoorDetector
from .events import item_event
from .gallery import ItemGallery
from .geometry import Track
from .session import DoorSession, Trip
from .shelf import shelf_diff


class ItemPipeline:
    def __init__(
        self,
        cfg: Config,
        detect: Callable[[np.ndarray], list[Track]],
        gallery: ItemGallery,
        embed: Callable[[np.ndarray], np.ndarray] | None = None,
        segment: Callable[[np.ndarray, list[Track]], dict[int, np.ndarray]] | None = None,
        shelf_check: bool = False,
    ) -> None:
        self.cfg = cfg
        self.detect = detect
        self.gallery = gallery
        self.embed = embed
        self.segment = segment
        self.shelf_check = shelf_check
        self.door_detector = DoorDetector(roi=cfg.roi, on=cfg.door_on, off=cfg.door_off)
        self.session: DoorSession | None = None
        self.tracks: list[Track] = []
        self.door_open: bool = False
        self._shelf_before: list[Track] | None = None
        self._shelf_after: list[Track] | None = None
        self._last_hand_ts: str | None = None
        self._last_open_ts: str | None = None
        self._emitted_put_labels: set[str] = set()
        self._emitted_take_labels: set[str] = set()

    def process(self, frame: np.ndarray, ts: str) -> list[dict]:
        is_open = self.door_detector.update(frame)
        self.door_open = is_open

        if not is_open:
            self.tracks = []
            return self.close()
        else:
            if self.session is None:
                self.session = DoorSession(self.cfg.line)
                self._shelf_before = None
                self._shelf_after = None
                self._last_hand_ts = None
                self._last_open_ts = None
                self._emitted_put_labels.clear()
                self._emitted_take_labels.clear()

            tracks = self.detect(frame)
            self.tracks = tracks
            self._last_open_ts = ts

            has_hand = any(t.kind == "hand" for t in tracks)
            if has_hand:
                self._last_hand_ts = ts
            else:
                items = [t for t in tracks if t.kind == "item"]
                if self._shelf_before is None:
                    self._shelf_before = list(items)
                self._shelf_after = list(items)

            item_tracks = [t for t in tracks if t.kind == "item"]
            masks = (
                self.segment(frame, item_tracks)
                if self.segment is not None
                else None
            )
            trips = self.session.update(tracks, ts, frame, masks=masks)
            events = self._trips_to_events(trips)
            for ev in events:
                if ev["type"] == "PUT":
                    self._emitted_put_labels.add(ev["item_label"])
                elif ev["type"] == "TAKE":
                    self._emitted_take_labels.add(ev["item_label"])
            return events

    def close(self) -> list[dict]:
        """Flush and close any open door session, returning the resulting events."""
        if self.session is not None:
            trips = self.session.close()
            self.session = None
            events = self._trips_to_events(trips)
            for ev in events:
                if ev["type"] == "PUT":
                    self._emitted_put_labels.add(ev["item_label"])
                elif ev["type"] == "TAKE":
                    self._emitted_take_labels.add(ev["item_label"])

            if (
                self.shelf_check
                and self._shelf_before is not None
                and self._shelf_after is not None
            ):
                added, removed = shelf_diff(self._shelf_before, self._shelf_after)
                shelf_ts = self._last_hand_ts or self._last_open_ts or ""
                shelf_trips: list[Trip] = []
                for item in added:
                    if item.label not in self._emitted_put_labels:
                        shelf_trips.append(
                            Trip(
                                type="PUT",
                                item=item,
                                ts=shelf_ts,
                                crop=None,
                                confidence=0.3,
                            )
                        )
                for item in removed:
                    if item.label not in self._emitted_take_labels:
                        shelf_trips.append(
                            Trip(
                                type="TAKE",
                                item=item,
                                ts=shelf_ts,
                                crop=None,
                                confidence=0.3,
                            )
                        )
                if shelf_trips:
                    shelf_events = self._trips_to_events(shelf_trips)
                    events.extend(shelf_events)

            self._shelf_before = None
            self._shelf_after = None
            self._last_hand_ts = None
            self._last_open_ts = None
            self._emitted_put_labels.clear()
            self._emitted_take_labels.clear()
            return events
        return []


    def _trips_to_events(self, trips: list[Trip]) -> list[dict]:
        trip_embs: list[np.ndarray | None] = []
        for trip in trips:
            emb = None
            if self.embed is not None and trip.crop is not None:
                emb = self.embed(trip.crop)
            trip_embs.append(emb)

        # (a) First do every PUT's gallery.add in trip order
        put_results: dict[int, tuple[str, float]] = {}
        for i, (trip, emb) in enumerate(zip(trips, trip_embs)):
            if trip.type == "PUT":
                item_id = self.gallery.add(trip.item.label, emb)
                put_results[i] = (item_id, trip.confidence)

        # (b) Then resolve TAKEs: if 2 or more TAKEs have embeddings, resolve exactly those
        # with one gallery.take_many call, and resolve every other TAKE with gallery.take
        # in trip order.
        take_results: dict[int, tuple[str, float]] = {}
        embedded_take_indices = [
            i
            for i, (trip, emb) in enumerate(zip(trips, trip_embs))
            if trip.type == "TAKE" and emb is not None
        ]

        if len(embedded_take_indices) >= 2:
            queries = [
                (trips[idx].item.label, trip_embs[idx])  # type: ignore[arg-type]
                for idx in embedded_take_indices
            ]
            matches = self.gallery.take_many(queries)
            for idx, match in zip(embedded_take_indices, matches):
                take_results[idx] = match

            for i, (trip, emb) in enumerate(zip(trips, trip_embs)):
                if trip.type == "TAKE" and i not in take_results:
                    take_results[i] = self.gallery.take(trip.item.label, emb)
        else:
            for i, (trip, emb) in enumerate(zip(trips, trip_embs)):
                if trip.type == "TAKE":
                    take_results[i] = self.gallery.take(trip.item.label, emb)

        # (c) Emit the events in the original trip order. Keep the single shared trip->event path.
        events: list[dict] = []
        for i, trip in enumerate(trips):
            if trip.type == "PUT":
                item_id, confidence = put_results[i]
            elif trip.type == "TAKE":
                item_id, score = take_results[i]
                if item_id == "unknown":
                    confidence = 0.1
                else:
                    confidence = trip.confidence * score
            else:
                continue

            confidence = max(0.0, min(1.0, float(confidence)))
            events.append(
                item_event(
                    type=trip.type,
                    item_id=item_id,
                    item_label=trip.item.label,
                    confidence=confidence,
                    ts=trip.ts,
                )
            )
        return events
