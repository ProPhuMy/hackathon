from __future__ import annotations

from typing import Callable
import numpy as np

from fridge_item.config import Config
from fridge_item.door import DoorDetector
from fridge_item.events import item_event
from fridge_item.gallery import ItemGallery
from fridge_item.geometry import Track
from fridge_item.session import DoorSession, Trip


class ItemPipeline:
    def __init__(
        self,
        cfg: Config,
        detect: Callable[[np.ndarray], list[Track]],
        gallery: ItemGallery,
        embed: Callable[[np.ndarray], np.ndarray] | None = None,
    ) -> None:
        self.cfg = cfg
        self.detect = detect
        self.gallery = gallery
        self.embed = embed
        self.door_detector = DoorDetector(roi=cfg.roi, on=cfg.door_on, off=cfg.door_off)
        self.session: DoorSession | None = None
        self.tracks: list[Track] = []
        self.door_open: bool = False

    def process(self, frame: np.ndarray, ts: str) -> list[dict]:
        is_open = self.door_detector.update(frame)
        self.door_open = is_open

        if not is_open:
            self.tracks = []
            return self.close()
        else:
            if self.session is None:
                self.session = DoorSession(self.cfg.line)
            tracks = self.detect(frame)
            self.tracks = tracks
            trips = self.session.update(tracks, ts, frame)
            return self._trips_to_events(trips)

    def close(self) -> list[dict]:
        """Flush and close any open door session, returning the resulting events."""
        if self.session is not None:
            trips = self.session.close()
            self.session = None
            return self._trips_to_events(trips)
        return []


    def _trips_to_events(self, trips: list[Trip]) -> list[dict]:
        trip_embs: list[np.ndarray | None] = []
        for trip in trips:
            emb = None
            if self.embed is not None and trip.crop is not None:
                emb = self.embed(trip.crop)
            trip_embs.append(emb)

        take_indices = [
            i
            for i, (trip, emb) in enumerate(zip(trips, trip_embs))
            if trip.type == "TAKE" and emb is not None
        ]
        take_results: dict[int, tuple[str, float]] = {}

        events: list[dict] = []
        for i, (trip, emb) in enumerate(zip(trips, trip_embs)):
            if trip.type == "PUT":
                item_id = self.gallery.add(trip.item.label, emb)
                confidence = trip.confidence
            elif trip.type == "TAKE":
                if len(take_indices) >= 2:
                    if not take_results:
                        queries = [
                            (trips[idx].item.label, trip_embs[idx])  # type: ignore[arg-type]
                            for idx in take_indices
                        ]
                        matches = self.gallery.take_many(queries)
                        for idx, match in zip(take_indices, matches):
                            take_results[idx] = match
                    item_id, score = take_results[i]
                else:
                    item_id, score = self.gallery.take(trip.item.label, emb)

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
