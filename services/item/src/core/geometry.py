from dataclasses import dataclass
import math
from typing import Literal
import numpy as np

Point = tuple[float, float]


@dataclass(frozen=True)
class Box:
    x1: float
    y1: float
    x2: float
    y2: float

    def center(self) -> Point:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    def area(self) -> float:
        w = max(0.0, self.x2 - self.x1)
        h = max(0.0, self.y2 - self.y1)
        return w * h

    def intersection(self, other: "Box") -> float:
        ix1 = max(self.x1, other.x1)
        iy1 = max(self.y1, other.y1)
        ix2 = min(self.x2, other.x2)
        iy2 = min(self.y2, other.y2)
        w = max(0.0, ix2 - ix1)
        h = max(0.0, iy2 - iy1)
        return w * h

    def iou(self, other: "Box") -> float:
        inter = self.intersection(other)
        if inter <= 0.0:
            return 0.0
        union = self.area() + other.area() - inter
        if union <= 0.0:
            return 0.0
        return inter / union


@dataclass(frozen=True)
class Track:
    id: int
    kind: Literal["hand", "item"]
    box: Box
    conf: float
    label: str

    def area(self) -> float:
        return self.box.area()


@dataclass(frozen=True)
class DoorLine:
    p1: Point
    p2: Point
    inside: Point
    margin: float = 15.0

    def depth(self, pt: Point) -> float:
        """Signed distance from the line: positive on the inside, negative outside, 0 if undefined."""
        dx = self.p2[0] - self.p1[0]
        dy = self.p2[1] - self.p1[1]
        line_len = math.hypot(dx, dy)
        cross_inside = dx * (self.inside[1] - self.p1[1]) - dy * (self.inside[0] - self.p1[0])
        if line_len == 0.0 or cross_inside == 0.0:
            return 0.0
        cross_pt = dx * (pt[1] - self.p1[1]) - dy * (pt[0] - self.p1[0])
        return cross_pt / line_len if cross_inside > 0 else -cross_pt / line_len

    def side(self, pt: Point) -> int:
        d = self.depth(pt)
        if abs(d) < self.margin:
            return 0
        return 1 if d > 0 else -1


def held_item(
    hand: Track,
    items: list[Track],
    min_overlap: float = 0.15,
    masks: dict[int, np.ndarray] | None = None,
) -> Track | None:
    best_item: Track | None = None
    best_overlap = -1.0
    for item in items:
        if masks is not None and item.id in masks and masks[item.id] is not None:
            mask = masks[item.id]
            total_pixels = int(np.count_nonzero(mask))
            if total_pixels <= 0:
                overlap = 0.0
            else:
                h, w = mask.shape[:2]
                hx1 = max(0, min(w, int(round(hand.box.x1))))
                hy1 = max(0, min(h, int(round(hand.box.y1))))
                hx2 = max(0, min(w, int(round(hand.box.x2))))
                hy2 = max(0, min(h, int(round(hand.box.y2))))
                if hx2 <= hx1 or hy2 <= hy1:
                    overlap = 0.0
                else:
                    hand_pixels = int(np.count_nonzero(mask[hy1:hy2, hx1:hx2]))
                    overlap = hand_pixels / total_pixels
        else:
            iarea = item.box.area()
            if iarea <= 0.0:
                continue
            overlap = hand.box.intersection(item.box) / iarea

        if overlap >= min_overlap and overlap > best_overlap:
            best_overlap = overlap
            best_item = item
    return best_item
