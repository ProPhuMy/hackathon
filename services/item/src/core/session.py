"""Door session: pairs a hand's in/out crossings of the door line into PUT/TAKE trips."""
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from .geometry import DoorLine, Track, held_item


def _same_crop(a: np.ndarray | None, b: np.ndarray | None) -> bool:
    if a is None or b is None:
        return a is b
    return bool(np.array_equal(a, b))


# The custom __eq__ compares crops by content; hash=False keeps the generated __hash__
# off the ndarray (and off `hand`, which __eq__ ignores when either side is None).
@dataclass(frozen=True)
class Crossing:
    direction: Literal["in", "out"]
    held: Track | None
    ts: str
    crop: np.ndarray | None = field(hash=False)
    hand: Track | None = field(default=None, hash=False)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Crossing):
            return False
        if (self.direction, self.held, self.ts) != (other.direction, other.held, other.ts):
            return False
        if self.hand is not None and other.hand is not None and self.hand != other.hand:
            return False
        return _same_crop(self.crop, other.crop)


@dataclass(frozen=True)
class Trip:
    type: Literal["PUT", "TAKE"]
    item: Track
    ts: str
    crop: np.ndarray | None = field(hash=False)
    confidence: float

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Trip):
            return False
        if (self.type, self.item, self.ts, self.confidence) != (
            other.type,
            other.item,
            other.ts,
            other.confidence,
        ):
            return False
        return _same_crop(self.crop, other.crop)


def _trip(type: Literal["PUT", "TAKE"], crossing: Crossing, ts: str | None = None) -> Trip:
    """Trip for the crossing that carried the item; confidence = min(hand, item)."""
    held = crossing.held
    conf = min(crossing.hand.conf, held.conf) if crossing.hand is not None else held.conf
    return Trip(type=type, item=held, ts=ts or crossing.ts, crop=crossing.crop, confidence=conf)


class DoorSession:
    def __init__(self, line: DoorLine) -> None:
        self.line = line
        self.hand_sides: dict[int, int] = {}
        self.pending_in: list[Crossing] = []
        self.pending_out: list[Crossing] = []
        self.hand_crops: dict[int, tuple[int, float, np.ndarray | None]] = {}

    def update(
        self,
        tracks: list[Track],
        ts: str,
        frame: np.ndarray | None = None,
        masks: dict[int, np.ndarray] | None = None,
    ) -> list[Trip]:
        hands = [t for t in tracks if t.kind == "hand"]
        items = [t for t in tracks if t.kind == "item"]
        trips: list[Trip] = []

        # Update best crop per hand ID for the item currently held
        for hand in hands:
            held = held_item(hand, items, masks=masks)
            if held is None:
                self.hand_crops.pop(hand.id, None)
            else:
                crop: np.ndarray | None = None
                area = 0.0
                if frame is not None:
                    h, w = frame.shape[:2]
                    x1 = max(0, min(w, int(held.box.x1)))
                    y1 = max(0, min(h, int(held.box.y1)))
                    x2 = max(0, min(w, int(held.box.x2)))
                    y2 = max(0, min(h, int(held.box.y2)))
                    if x2 > x1 and y2 > y1:
                        c = frame[y1:y2, x1:x2]
                        if c.size > 0:
                            crop = c.copy()
                            area = float(c.shape[0] * c.shape[1])

                if hand.id not in self.hand_crops or self.hand_crops[hand.id][0] != held.id:
                    self.hand_crops[hand.id] = (held.id, area, crop)
                else:
                    prev_area = self.hand_crops[hand.id][1]
                    if crop is not None and area > prev_area:
                        self.hand_crops[hand.id] = (held.id, area, crop)

        for hand in hands:
            side = self.line.side(hand.box.center())
            if side == 0:
                continue

            if hand.id not in self.hand_sides:
                self.hand_sides[hand.id] = side
                continue

            prev_side = self.hand_sides[hand.id]
            if side == prev_side:
                continue

            self.hand_sides[hand.id] = side

            if prev_side == -1 and side == 1:
                direction: Literal["in", "out"] = "in"
            elif prev_side == 1 and side == -1:
                direction = "out"
            else:
                continue

            held = held_item(hand, items, masks=masks)
            crop: np.ndarray | None = None
            if held is not None and hand.id in self.hand_crops and self.hand_crops[hand.id][0] == held.id:
                best = self.hand_crops[hand.id][2]
                crop = best.copy() if best is not None else None

            crossing = Crossing(
                direction=direction,
                held=held,
                ts=ts,
                crop=crop,
                hand=hand,
            )

            if direction == "in":
                self.pending_in.append(crossing)
            else:
                if self.pending_in:
                    c_in = self.pending_in.pop(0)
                    trip = self._pair(c_in, crossing)
                    if trip is not None:
                        trips.append(trip)
                else:
                    self.pending_out.append(crossing)

        return trips

    def _pair(self, c_in: Crossing, c_out: Crossing) -> Trip | None:
        if c_in.held is not None and c_out.held is None:
            return _trip("PUT", c_in)
        if c_in.held is None and c_out.held is not None:
            # ts = hand going in: the person still faces the face camera then; while rummaging
            # they turn away, and the backend can only match a face seen within ~3 s
            return _trip("TAKE", c_out, ts=c_in.ts)
        return None

    def close(self) -> list[Trip]:
        trips = [_trip("PUT", c) for c in self.pending_in if c.held is not None]
        trips += [_trip("TAKE", c) for c in self.pending_out if c.held is not None]
        self.pending_in.clear()
        self.pending_out.clear()
        self.hand_sides.clear()
        self.hand_crops.clear()
        return trips
