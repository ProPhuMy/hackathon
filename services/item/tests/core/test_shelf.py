from src.core.geometry import Box, Track
from src.core.shelf import shelf_diff


def make_item(id: int, label: str, box: Box, conf: float = 0.9) -> Track:
    return Track(id=id, kind="item", box=box, conf=conf, label=label)


def make_hand(id: int, box: Box, conf: float = 0.9) -> Track:
    return Track(id=id, kind="hand", box=box, conf=conf, label="hand")


def test_shelf_diff_added():
    before = []
    item_after = make_item(1, "coke", Box(10.0, 10.0, 50.0, 50.0))
    after = [item_after]

    added, removed = shelf_diff(before, after)
    assert added == [item_after]
    assert removed == []


def test_shelf_diff_removed():
    item_before = make_item(1, "coke", Box(10.0, 10.0, 50.0, 50.0))
    before = [item_before]
    after = []

    added, removed = shelf_diff(before, after)
    assert added == []
    assert removed == [item_before]


def test_shelf_diff_moved_within_iou():
    # item shifted slightly, IoU >= 0.3
    # b1: (0, 0, 100, 100) area 10000
    # b2: (10, 0, 110, 100) area 10000, inter 9000, union 11000 -> IoU 0.818
    b1 = Box(0.0, 0.0, 100.0, 100.0)
    b2 = Box(10.0, 0.0, 110.0, 100.0)
    item_before = make_item(1, "milk", b1)
    item_after = make_item(2, "milk", b2)

    added, removed = shelf_diff([item_before], [item_after], iou_min=0.3)
    assert added == []
    assert removed == []


def test_shelf_diff_moved_below_iou_min():
    # item shifted far, IoU < 0.3
    # b1: (0, 0, 100, 100)
    # b2: (80, 0, 180, 100) inter 20x100=2000, union 18000 -> IoU 0.111
    b1 = Box(0.0, 0.0, 100.0, 100.0)
    b2 = Box(80.0, 0.0, 180.0, 100.0)
    item_before = make_item(1, "milk", b1)
    item_after = make_item(2, "milk", b2)

    added, removed = shelf_diff([item_before], [item_after], iou_min=0.3)
    assert added == [item_after]
    assert removed == [item_before]


def test_shelf_diff_same_label_two_items():
    # Two items with label "coke" in before.
    # item1 at (0, 0, 100, 100)
    # item2 at (200, 200, 300, 300)
    # After has one item with label "coke" at (5, 5, 105, 105) (very close to item1).
    # Greedy highest IoU matches item3 to item1.
    # item2 is removed, nothing added.
    item1 = make_item(1, "coke", Box(0.0, 0.0, 100.0, 100.0))
    item2 = make_item(2, "coke", Box(200.0, 200.0, 300.0, 300.0))
    item3 = make_item(3, "coke", Box(5.0, 5.0, 105.0, 105.0))

    added, removed = shelf_diff([item1, item2], [item3], iou_min=0.3)
    assert added == []
    assert removed == [item2]


def test_shelf_diff_ignores_non_item_tracks():
    hand_before = make_hand(99, Box(0.0, 0.0, 50.0, 50.0))
    hand_after = make_hand(99, Box(10.0, 10.0, 60.0, 60.0))
    item_before = make_item(1, "juice", Box(100.0, 100.0, 150.0, 150.0))

    added, removed = shelf_diff([hand_before, item_before], [hand_after])
    assert added == []
    assert removed == [item_before]
