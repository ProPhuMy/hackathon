"""Item-centric trips for a camera on top of the fridge looking down its front ("mode": "edge").

From there the hand vanishes behind the door edge exactly when it crosses, and the tracker often misses it,
so hand crossings are unreliable. What stays visible is the item in the hand: one that vanishes just past the
door line went in (PUT), one that first appears at the line and is carried away came out (TAKE).
Same Trip output as DoorSession. Measured 2026-11-08 (RESULTS.md): 3 of 4 labelled trips, no false events.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .geometry import Box, DoorLine, Track, held_item
from .session import Trip

NEAR_PX = 120.0  # first/last seen this close to (or past) the door line: it came out of / went into the fridge
MOVE_PX = 30.0  # and its path moved at least this far toward / away from the door
LOST_UPDATES = 15  # unseen for this many updates (~0.7 s): it has left the view


@dataclass
class _Path:
    first: Track
    first_ts: str
    first_depth: float
    last: Track
    last_ts: str
    last_depth: float
    last_update: int
    conf: float
    held: bool = False
    crop: np.ndarray | None = None
    crop_area: float = 0.0


class EdgeSession:
    def __init__(self, line: DoorLine) -> None:
        self.line = line
        self._update = 0
        self._paths: dict[int, _Path] = {}

    def _depth(self, box: Box) -> float:
        # the corner reaching furthest inside, as for hands in DoorSession
        return max(self.line.depth(p) for p in ((box.x1, box.y1), (box.x2, box.y1), (box.x1, box.y2), (box.x2, box.y2)))

    def update(
        self,
        tracks: list[Track],
        ts: str,
        frame: np.ndarray | None = None,
        masks: dict[int, np.ndarray] | None = None,
    ) -> list[Trip]:
        self._update += 1
        items = [t for t in tracks if t.kind == "item"]
        held_ids = {held.id for hand in tracks if hand.kind == "hand" if (held := held_item(hand, items, masks=masks))}
        for it in items:
            depth = self._depth(it.box)
            path = self._paths.get(it.id)
            if path is None:
                path = self._paths[it.id] = _Path(it, ts, depth, it, ts, depth, self._update, it.conf)
            else:
                path.last, path.last_ts, path.last_depth, path.last_update = it, ts, depth, self._update
                path.conf = max(path.conf, it.conf)
            if it.id in held_ids:
                path.held = True
                if frame is not None:
                    h, w = frame.shape[:2]
                    x1, y1 = max(0, int(it.box.x1)), max(0, int(it.box.y1))
                    x2, y2 = min(w, int(it.box.x2)), min(h, int(it.box.y2))
                    area = float(max(0, x2 - x1) * max(0, y2 - y1))
                    if area > path.crop_area:
                        path.crop, path.crop_area = frame[y1:y2, x1:x2].copy(), area
        lost = [tid for tid, p in self._paths.items() if self._update - p.last_update > LOST_UPDATES]
        return [trip for tid in lost if (trip := self._finish(self._paths.pop(tid)))]

    def close(self) -> list[Trip]:
        trips = [trip for p in self._paths.values() if (trip := self._finish(p))]
        self._paths.clear()
        return trips

    @staticmethod
    def _finish(p: _Path) -> Trip | None:
        if not p.held:  # never carried by a hand, e.g. the door's own shelves swinging with the door
            return None
        if p.last_depth > -NEAR_PX and p.last_depth - p.first_depth >= MOVE_PX:
            return Trip(type="PUT", item=p.last, ts=p.last_ts, crop=p.crop, confidence=p.conf)
        if p.first_depth > -NEAR_PX and p.first_depth - p.last_depth >= MOVE_PX:
            return Trip(type="TAKE", item=p.first, ts=p.first_ts, crop=p.crop, confidence=p.conf)
        return None
