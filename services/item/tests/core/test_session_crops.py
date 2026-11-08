"""Best-crop tracking per hand and mask-based holding inside DoorSession."""
import numpy as np

from conftest import hand, item
from src.core.geometry import Box, Track
from src.core.session import DoorSession


def test_crop_extraction(line):
    session = DoorSession(line)
    frame = np.zeros((300, 300, 3), dtype=np.uint8)
    frame[140:160, 90:110] = 255

    h_start = hand(1, 100.0, 50.0)
    it_start = item(10, 100.0, 50.0)
    session.update([h_start, it_start], ts="t0")

    h_in = hand(1, 100.0, 150.0)
    it_in = item(10, 100.0, 150.0)  # box: 90..110, 140..160
    session.update([h_in, it_in], ts="t1", frame=frame)

    h_out = hand(1, 100.0, 50.0)
    res = session.update([h_out], ts="t2")
    assert len(res) == 1
    assert res[0].crop is not None
    assert res[0].crop.shape == (20, 20, 3)
    assert np.all(res[0].crop == 255)


def test_crop_clamping_and_out_of_bounds(line):
    session = DoorSession(line)

    # 200x200 frame (y > 115 is inside). Box partially outside in x: x in [-10, 20], y in [120, 140]
    # is clamped to x in [0, 20], y in [120, 140].
    frame_large = np.ones((200, 200, 3), dtype=np.uint8)
    h_out = hand(1, 100.0, 50.0)
    it_clamp = Track(1, "item", Box(-10.0, 120.0, 20.0, 140.0), 0.9, "clamped")
    session.update([h_out], ts="t0")

    h_in_box = Track(1, "hand", Box(-5.0, 125.0, 15.0, 135.0), 0.9, "hand")
    session.update([h_in_box, it_clamp], ts="t1", frame=frame_large)

    # Cross out empty
    res = session.update([hand(1, 100.0, 50.0)], ts="t2")
    assert len(res) == 1
    assert res[0].crop is not None
    # x clamped to 0..20 (w=20), y is 120..140 (h=20)
    assert res[0].crop.shape == (20, 20, 3)

    # Box completely outside bounds (x in [300, 350] on 200x200 frame) -> crop is None
    session2 = DoorSession(line)
    it_outside = Track(2, "item", Box(300.0, 120.0, 350.0, 140.0), 0.9, "outside")
    h2_out = hand(2, 100.0, 50.0)
    session2.update([h2_out], ts="t0")
    h2_in = Track(2, "hand", Box(300.0, 120.0, 350.0, 140.0), 0.9, "hand")
    session2.update([h2_in, it_outside], ts="t1", frame=frame_large)
    res2 = session2.update([hand(2, 100.0, 50.0)], ts="t2")
    assert len(res2) == 1
    assert res2[0].crop is None


def test_trip_crop_is_largest_held(line):
    session = DoorSession(line)
    frame = np.ones((300, 300, 3), dtype=np.uint8)

    # Frame 0: Hand outside holding item (small box: 10x10)
    h0 = hand(1, 100.0, 50.0)
    b0 = Track(10, "item", Box(95.0, 45.0, 105.0, 55.0), 0.85, "bottle")
    session.update([h0, b0], ts="t0", frame=frame)

    # Frame 1: Hand outside holding item (large box: 40x40) -> grows
    h1 = hand(1, 100.0, 50.0)
    b1 = Track(10, "item", Box(80.0, 30.0, 120.0, 70.0), 0.85, "bottle")
    session.update([h1, b1], ts="t1", frame=frame)

    # Frame 2: Hand crosses in holding item (medium box: 20x20) -> shrinks at crossing
    h2 = hand(1, 100.0, 150.0)
    b2 = Track(10, "item", Box(90.0, 140.0, 110.0, 160.0), 0.85, "bottle")
    session.update([h2, b2], ts="t2", frame=frame)

    # Frame 3: Hand crosses out empty
    h3 = hand(1, 100.0, 50.0)
    trips = session.update([h3], ts="t3", frame=frame)

    assert len(trips) == 1
    assert trips[0].type == "PUT"
    assert trips[0].crop is not None
    # Crop shape must equal the largest held box (40x40), not the 20x20 crossing box
    assert trips[0].crop.shape == (40, 40, 3)
    # Ensure it is a copy, not a view of the frame
    frame[:] = 0
    assert np.all(trips[0].crop == 1)


def test_hand_crop_resets_when_item_changes(line):
    session = DoorSession(line)
    frame = np.ones((300, 300, 3), dtype=np.uint8)

    # Hand 1 holds item 10 (large box: 50x50)
    h0 = hand(1, 100.0, 50.0)
    b0 = Track(10, "item", Box(75.0, 25.0, 125.0, 75.0), 0.85, "bottle")
    session.update([h0, b0], ts="t0", frame=frame)

    # Hand 1 switches to item 20 (medium box: 25x25)
    b1 = Track(20, "item", Box(87.5, 37.5, 112.5, 62.5), 0.85, "can")
    session.update([h0, b1], ts="t1", frame=frame)

    # Hand 1 crosses in holding item 20 (small box: 15x15)
    h_in = hand(1, 100.0, 150.0)
    b2 = Track(20, "item", Box(92.5, 142.5, 107.5, 157.5), 0.85, "can")
    session.update([h_in, b2], ts="t2", frame=frame)

    # Hand 1 crosses out empty
    trips = session.update([hand(1, 100.0, 50.0)], ts="t3", frame=frame)
    assert len(trips) == 1
    assert trips[0].item.id == 20
    # Must be 25x25 (largest for item 20), not 50x50 (from item 10)
    assert trips[0].crop.shape == (25, 25, 3)


def test_session_with_masks(line):
    session = DoorSession(line)
    # Hand at (100, 50), box: (90, 40, 110, 60)
    h0 = hand(1, 100.0, 50.0)
    # Item 10 box overlaps hand by 50% (box: 95..115, 40..60 -> intersection 15*20=300, area 20*20=400 -> 0.75)
    # BUT its mask pixels are at (150..160, 150..160) -> hand covers 0 mask pixels
    it10 = Track(10, "item", Box(95.0, 40.0, 115.0, 60.0), 0.85, "bottle")
    mask10 = np.zeros((300, 300), dtype=bool)
    mask10[150:160, 150:160] = True

    # Item 20 box has zero box overlap with hand (box: 120..140, 40..60)
    # BUT its mask pixels are at (95..105, 45..55) -> completely inside hand box!
    it20 = Track(20, "item", Box(120.0, 40.0, 140.0, 60.0), 0.85, "can")
    mask20 = np.zeros((300, 300), dtype=bool)
    mask20[45:55, 95:105] = True

    masks = {10: mask10, 20: mask20}

    # Frame 1: Hand outside
    session.update([h0, it10, it20], ts="t0", masks=masks)

    # Frame 2: Hand inside (crossing in)
    h1 = hand(1, 100.0, 150.0)
    it10_in = Track(10, "item", Box(95.0, 140.0, 115.0, 160.0), 0.85, "bottle")
    it20_in = Track(20, "item", Box(120.0, 140.0, 140.0, 160.0), 0.85, "can")
    mask10_in = np.zeros((300, 300), dtype=bool)
    mask10_in[250:260, 250:260] = True
    mask20_in = np.zeros((300, 300), dtype=bool)
    mask20_in[145:155, 95:105] = True
    masks_in = {10: mask10_in, 20: mask20_in}
    session.update([h1, it10_in, it20_in], ts="t1", masks=masks_in)

    # Frame 3: Hand inside empty
    session.update([h1], ts="t2")

    # Frame 4: Hand outside empty (crossing out -> PUT trip)
    trips = session.update([h0], ts="t3")
    assert len(trips) == 1
    assert trips[0].type == "PUT"
    assert trips[0].item.id == 20
    assert trips[0].item.label == "can"
