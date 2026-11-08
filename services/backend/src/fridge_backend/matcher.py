from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any

from fridge_backend import associate
from fridge_backend import consistency
from fridge_backend.events import fridge_event

MATCHER_VERSION = "3-jpda"  # stored with Codex's replay journal; bump on any change to matching behavior

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parse_ts_ms(ts: str) -> int:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = dt - EPOCH
    return delta.days * 86_400_000 + delta.seconds * 1_000 + delta.microseconds // 1_000


@dataclass(frozen=True)
class MatcherConfig:
    back_ms: int = 5000            # person may be up to 5 s before the item event
    fwd_ms: int = 2000             # ... or up to 2 s after it
    lateness_ms: int = 2000        # allowed out-of-order delay per stream
    idle_timeout_ms: int = 3000    # extra wait (via tick) when the person stream is silent
    person_retention_ms: int = 60000
    threshold: float = 0.5
    association: str = "jpda"      # association algorithm: "nearest", "hungarian", or "jpda"
    sigma_ms: int = 1000           # Gaussian temporal kernel width for track-event time difference
    n_eff_cap: int = 3             # maximum effective count of frames for identity log-odds scaling
    null_prior: float = -2.0       # log-score of the null hypothesis ("nobody identifiable")
    min_gap_ms: int = 1000         # minimum time gap between two events handled by the same person


class Matcher:
    def __init__(self, cfg: MatcherConfig = MatcherConfig()):
        if cfg.association not in ("nearest", "hungarian", "jpda"):
            raise ValueError(f"Unknown association mode: {cfg.association}")
        self.cfg = cfg
        self._state: dict[str, str | None] = {}
        self._seen_event_ids: set[str] = set()
        self._person_buffer: list[tuple[int, dict]] = []   # [(ts_ms, event_dict)]
        self._pending_items: list[tuple[int, dict]] = []   # [(ts_ms, event_dict)]
        self._person_wm: int | None = None
        self._item_wm: int | None = None

    def on_person(self, ev: dict) -> list[dict]:
        event_id = ev["event_id"]
        if event_id in self._seen_event_ids:
            return []
        self._seen_event_ids.add(event_id)

        ts_ms = _parse_ts_ms(ev["ts"])
        if self._person_wm is not None and ts_ms < self._person_wm - self.cfg.lateness_ms:
            logging.warning("Dropping late person.seen event %s (ts=%d, wm=%d)", event_id, ts_ms, self._person_wm)
            return []

        if self._person_wm is None or ts_ms > self._person_wm:
            self._person_wm = ts_ms

        self._person_buffer.append((ts_ms, ev))

        cutoff = self._person_wm - self.cfg.person_retention_ms
        self._person_buffer = [p for p in self._person_buffer if p[0] >= cutoff]

        return self._finalize_ready_items(now_ms=None)

    def on_item(self, ev: dict) -> list[dict]:
        event_id = ev["event_id"]
        if event_id in self._seen_event_ids:
            return []
        self._seen_event_ids.add(event_id)

        ts_ms = _parse_ts_ms(ev["ts"])
        if self._item_wm is not None and ts_ms < self._item_wm - self.cfg.lateness_ms:
            logging.warning("Dropping late item.event event %s (ts=%d, wm=%d)", event_id, ts_ms, self._item_wm)
            return []

        if self._item_wm is None or ts_ms > self._item_wm:
            self._item_wm = ts_ms

        self._pending_items.append((ts_ms, ev))

        return self._finalize_ready_items(now_ms=None)

    def tick(self, now_ts: str) -> list[dict]:
        now_ms = _parse_ts_ms(now_ts)
        return self._finalize_ready_items(now_ms=now_ms)

    def inventory(self) -> dict[str, str | None]:
        return self._state.copy()

    def _finalize_ready_items(self, now_ms: int | None) -> list[dict]:
        if self.cfg.association == "nearest":
            ready_indices: list[int] = []
            for idx, (t, item_ev) in enumerate(self._pending_items):
                is_ready = False
                if self._person_wm is not None and self._person_wm >= t + self.cfg.fwd_ms + self.cfg.lateness_ms:
                    is_ready = True
                elif now_ms is not None and now_ms >= t + self.cfg.fwd_ms + self.cfg.lateness_ms + self.cfg.idle_timeout_ms:
                    is_ready = True

                if is_ready:
                    ready_indices.append(idx)

            if not ready_indices:
                return []

            ready_set = set(ready_indices)
            ready_items = [self._pending_items[i] for i in ready_indices]
            self._pending_items = [item for i, item in enumerate(self._pending_items) if i not in ready_set]

            # Rule 8: Sort ready items by (ts_ms, event_id)
            ready_items.sort(key=lambda x: (x[0], x[1]["event_id"]))

            outputs: list[dict] = []
            for item_ts, item_ev in ready_items:
                # Rule 9: Actor selection (as-of join)
                cand1 = [p for p in self._person_buffer if item_ts - self.cfg.back_ms <= p[0] <= item_ts]
                chosen_person: dict | None = None
                if cand1:
                    chosen_person = min(cand1, key=lambda p: (-p[0], p[1]["event_id"]))[1]
                else:
                    cand2 = [p for p in self._person_buffer if item_ts < p[0] <= item_ts + self.cfg.fwd_ms]
                    if cand2:
                        chosen_person = min(cand2, key=lambda p: (p[0], p[1]["event_id"]))[1]

                if chosen_person is None:
                    person_id = None
                    confidence = 0.0
                else:
                    person_id = chosen_person.get("person_id")
                    confidence = round(float(chosen_person["confidence"]) * float(item_ev["confidence"]), 4)

                owner_id, status = consistency.decide(
                    self._state,
                    item_ev["type"],
                    item_ev["item_id"],
                    person_id,
                    confidence,
                    self.cfg.threshold,
                )

                out_ev = fridge_event(
                    item_ev,
                    person_id=person_id,
                    owner_id=owner_id,
                    confidence=confidence,
                    status=status,
                )

                self._state = consistency.apply(self._state, out_ev)
                outputs.append(out_ev)

            return outputs

        # Batching for "jpda" and "hungarian"
        if not self._pending_items:
            return []

        def _is_item_ready(t: int) -> bool:
            if self._person_wm is not None and self._person_wm >= t + self.cfg.fwd_ms + self.cfg.lateness_ms:
                return True
            if now_ms is not None and now_ms >= t + self.cfg.fwd_ms + self.cfg.lateness_ms + self.cfg.idle_timeout_ms:
                return True
            return False

        # Sort pending items by (ts_ms, event_id)
        sorted_pending = sorted(self._pending_items, key=lambda x: (x[0], x[1]["event_id"]))

        # Group pending items into connected components (batches) under |t_i - t_j| < min_gap_ms
        batches: list[list[tuple[int, dict]]] = []
        for item in sorted_pending:
            if not batches:
                batches.append([item])
            else:
                prev_item = batches[-1][-1]
                if item[0] - prev_item[0] < self.cfg.min_gap_ms:
                    batches[-1].append(item)
                else:
                    batches.append([item])

        # shortcut: a late item is not excluded against already-finalized neighbours, upgrade with the revision field (stage 5)
        ready_batches: list[list[tuple[int, dict]]] = []
        remaining_items: list[tuple[int, dict]] = []
        for batch in batches:
            if all(_is_item_ready(item[0]) for item in batch):
                ready_batches.append(batch)
            else:
                remaining_items.extend(batch)

        if not ready_batches:
            return []

        self._pending_items = remaining_items

        # Finalize batches in order of smallest (ts_ms, event_id)
        ready_batches.sort(key=lambda b: (b[0][0], b[0][1]["event_id"]))

        outputs = []
        for batch in ready_batches:
            # Inside a batch, sort items by (ts_ms, event_id)
            batch.sort(key=lambda x: (x[0], x[1]["event_id"]))
            assignments = associate.assign(
                batch,
                self._person_buffer,
                self.cfg,
                self.cfg.association,
            )

            for (item_ts, item_ev), (person_id, confidence) in zip(batch, assignments):
                owner_id, status = consistency.decide(
                    self._state,
                    item_ev["type"],
                    item_ev["item_id"],
                    person_id,
                    confidence,
                    self.cfg.threshold,
                )

                out_ev = fridge_event(
                    item_ev,
                    person_id=person_id,
                    owner_id=owner_id,
                    confidence=confidence,
                    status=status,
                )

                self._state = consistency.apply(self._state, out_ev)
                outputs.append(out_ev)

        return outputs
