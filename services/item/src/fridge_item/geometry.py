from dataclasses import dataclass
from typing import Literal

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


@dataclass(frozen=True)
class Track:
    id: int
    kind: Literal["hand", "item"]
    box: Box
    conf: float
    label: str


@dataclass(frozen=True)
class DoorLine:
    p1: Point
    p2: Point
    inside: Point
    margin: float = 15.0
