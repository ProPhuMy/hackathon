import numpy as np
import pytest
from fridge_item.geometry import Box, DoorLine, Point, Track, held_item


def test_side_inside_outside():
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    assert line.side((100.0, 150.0)) == 1
    assert line.side((100.0, 50.0)) == -1


def test_side_zero_within_margin():
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0), margin=15.0)
    assert line.side((100.0, 105.0)) == 0


def test_side_reversed_line_and_vertical():
    # Reversed line direction (p2 -> p1) should preserve inside vs outside
    rev_line = DoorLine(p1=(200.0, 100.0), p2=(0.0, 100.0), inside=(100.0, 200.0))
    assert rev_line.side((100.0, 150.0)) == 1
    assert rev_line.side((100.0, 50.0)) == -1

    # Vertical line: x = 100, inside is to the right (x=200)
    vert_line = DoorLine(p1=(100.0, 0.0), p2=(100.0, 200.0), inside=(200.0, 100.0), margin=10.0)
    assert vert_line.side((150.0, 100.0)) == 1
    assert vert_line.side((50.0, 100.0)) == -1
    assert vert_line.side((105.0, 100.0)) == 0  # within margin


def test_side_degenerate_line():
    # Zero-length line
    deg_line = DoorLine(p1=(50.0, 50.0), p2=(50.0, 50.0), inside=(100.0, 100.0))
    assert deg_line.side((60.0, 60.0)) == 0

    # Inside point on the line
    on_line = DoorLine(p1=(0.0, 0.0), p2=(100.0, 100.0), inside=(50.0, 50.0))
    assert on_line.side((10.0, 80.0)) == 0


def test_held_item_picks_max_overlap():
    hand = Track(
        id=1,
        kind="hand",
        box=Box(x1=0.0, y1=0.0, x2=100.0, y2=100.0),
        conf=0.9,
        label="hand",
    )
    # item1 overlap: intersection = (50..100)x(0..100) = 5000, area = 10000 -> 0.50
    item1 = Track(
        id=2,
        kind="item",
        box=Box(x1=50.0, y1=0.0, x2=150.0, y2=100.0),
        conf=0.85,
        label="coke",
    )
    # item2 overlap: intersection = (20..100)x(0..100) = 8000, area = 8000 -> 1.00
    item2 = Track(
        id=3,
        kind="item",
        box=Box(x1=20.0, y1=0.0, x2=100.0, y2=100.0),
        conf=0.88,
        label="milk",
    )
    picked = held_item(hand, [item1, item2])
    assert picked == item2


def test_held_item_none_below_threshold():
    hand = Track(
        id=1,
        kind="hand",
        box=Box(x1=0.0, y1=0.0, x2=100.0, y2=100.0),
        conf=0.9,
        label="hand",
    )
    # item overlap: intersection = (90..100)x(0..100) = 1000, area = 10000 -> 0.10 (< 0.15)
    item = Track(
        id=2,
        kind="item",
        box=Box(x1=90.0, y1=0.0, x2=190.0, y2=100.0),
        conf=0.85,
        label="coke",
    )
    assert held_item(hand, [item]) is None
    assert held_item(hand, []) is None


def test_held_item_exact_threshold_and_zero_area():
    hand = Track(
        id=1,
        kind="hand",
        box=Box(x1=0.0, y1=0.0, x2=100.0, y2=100.0),
        conf=0.9,
        label="hand",
    )
    # item overlap: intersection = (85..100)x(0..100) = 1500, area = 10000 -> 0.15 (== min_overlap)
    item_exact = Track(
        id=2,
        kind="item",
        box=Box(x1=85.0, y1=0.0, x2=185.0, y2=100.0),
        conf=0.85,
        label="coke",
    )
    assert held_item(hand, [item_exact], min_overlap=0.15) == item_exact

    # Zero area item
    item_zero = Track(
        id=3,
        kind="item",
        box=Box(x1=50.0, y1=50.0, x2=50.0, y2=50.0),
        conf=0.85,
        label="ghost",
    )
    assert held_item(hand, [item_zero]) is None


def test_held_item_mask_overlap():
    hand = Track(
        id=1,
        kind="hand",
        box=Box(x1=0.0, y1=0.0, x2=50.0, y2=100.0),
        conf=0.9,
        label="hand",
    )
    # item1 mask has 100 pixels: x in [0, 50], y in [0, 2] -> 50*2 = 100 pixels.
    # Hand covers all 100 pixels -> overlap = 1.0.
    mask1 = np.zeros((200, 200), dtype=bool)
    mask1[0:2, 0:50] = True
    item1 = Track(
        id=2,
        kind="item",
        box=Box(x1=0.0, y1=0.0, x2=200.0, y2=200.0),
        conf=0.85,
        label="coke",
    )

    # item2 mask has 100 pixels: x in [60, 110], y in [0, 2].
    # Hand (x in [0, 50]) covers 0 pixels -> overlap = 0.0.
    mask2 = np.zeros((200, 200), dtype=bool)
    mask2[0:2, 60:110] = True
    item2 = Track(
        id=3,
        kind="item",
        box=Box(x1=0.0, y1=0.0, x2=200.0, y2=200.0),
        conf=0.88,
        label="milk",
    )

    masks = {item1.id: mask1, item2.id: mask2}
    picked = held_item(hand, [item1, item2], masks=masks)
    assert picked == item1

    # Empty mask has 0 overlap -> returns None
    empty_mask = np.zeros((200, 200), dtype=bool)
    picked_empty = held_item(hand, [item1], masks={item1.id: empty_mask})
    assert picked_empty is None


def test_held_item_mask_missing_fallback():
    hand = Track(
        id=1,
        kind="hand",
        box=Box(x1=0.0, y1=0.0, x2=100.0, y2=100.0),
        conf=0.9,
        label="hand",
    )
    # item1 has no mask in masks dict: falls back to box overlap.
    # Hand (0..100, 0..100) and item1 (50..150, 0..100): intersection = 5000, area = 10000 -> 0.50.
    item1 = Track(
        id=2,
        kind="item",
        box=Box(x1=50.0, y1=0.0, x2=150.0, y2=100.0),
        conf=0.85,
        label="coke",
    )
    # item2 has a mask in dict, but hand covers 0 pixels of it -> overlap = 0.0.
    mask2 = np.zeros((200, 200), dtype=bool)
    mask2[150:160, 150:160] = True
    item2 = Track(
        id=3,
        kind="item",
        box=Box(x1=20.0, y1=0.0, x2=100.0, y2=100.0),
        conf=0.88,
        label="milk",
    )

    masks = {item2.id: mask2}
    picked = held_item(hand, [item1, item2], masks=masks)
    assert picked == item1

