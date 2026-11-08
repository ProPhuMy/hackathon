import numpy as np
import pytest
from fridge_item.geometry import Box, DoorLine, Track
from fridge_item.session import Crossing, DoorSession, Trip


def hand(id: int, cx: float, cy: float, conf: float = 0.9) -> Track:
    return Track(
        id=id,
        kind="hand",
        box=Box(cx - 10.0, cy - 10.0, cx + 10.0, cy + 10.0),
        conf=conf,
        label="hand",
    )


def item(id: int, cx: float, cy: float, label: str = "bottle", conf: float = 0.85) -> Track:
    return Track(
        id=id,
        kind="item",
        box=Box(cx - 10.0, cy - 10.0, cx + 10.0, cy + 10.0),
        conf=conf,
        label=label,
    )


@pytest.fixture
def line() -> DoorLine:
    # y = 100 line. Inside is y = 200. Margin is 15.
    # y < 85 is outside (-1), y > 115 is inside (+1), 85 <= y <= 115 is margin (0).
    return DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))


def test_put(line):
    session = DoorSession(line)
    b = item(10, 100.0, 50.0, label="bottle", conf=0.8)
    h = hand(1, 100.0, 50.0, conf=0.9)

    # Frame 1: outside
    res1 = session.update([h, b], ts="2026-11-07T20:00:01.000Z")
    assert res1 == []

    # Frame 2: inside (crossing in)
    h_in = hand(1, 100.0, 150.0, conf=0.9)
    b_in = item(10, 100.0, 150.0, label="bottle", conf=0.8)
    res2 = session.update([h_in, b_in], ts="2026-11-07T20:00:02.000Z")
    assert res2 == []

    # Frame 3: inside empty hand
    h_in_empty = hand(1, 100.0, 150.0, conf=0.9)
    res3 = session.update([h_in_empty], ts="2026-11-07T20:00:03.000Z")
    assert res3 == []

    # Frame 4: outside empty hand (crossing out)
    h_out = hand(1, 100.0, 50.0, conf=0.9)
    res4 = session.update([h_out], ts="2026-11-07T20:00:04.000Z")
    assert len(res4) == 1
    trip = res4[0]
    assert trip.type == "PUT"
    assert trip.item.label == "bottle"
    assert trip.item.id == 10
    assert trip.ts == "2026-11-07T20:00:02.000Z"
    assert trip.confidence == 0.8


def test_take(line):
    session = DoorSession(line)
    h1 = hand(1, 100.0, 50.0, conf=0.9)
    session.update([h1], ts="2026-11-07T20:00:01.000Z")

    # crosses in empty
    h2 = hand(1, 100.0, 150.0, conf=0.9)
    res_in = session.update([h2], ts="2026-11-07T20:00:02.000Z")
    assert res_in == []

    # crosses out holding item
    h3 = hand(1, 100.0, 50.0, conf=0.95)
    b = item(20, 100.0, 50.0, label="coke", conf=0.85)
    res_out = session.update([h3, b], ts="2026-11-07T20:00:03.000Z")
    assert len(res_out) == 1
    trip = res_out[0]
    assert trip.type == "TAKE"
    assert trip.item.label == "coke"
    assert trip.item.id == 20
    assert trip.ts == "2026-11-07T20:00:03.000Z"
    assert trip.confidence == 0.85


def test_touch_no_event(line):
    session = DoorSession(line)
    h1 = hand(1, 100.0, 50.0)
    b1 = item(10, 100.0, 50.0)
    session.update([h1, b1], ts="2026-11-07T20:00:01.000Z")

    # crosses in holding
    h2 = hand(1, 100.0, 150.0)
    b2 = item(10, 100.0, 150.0)
    res_in = session.update([h2, b2], ts="2026-11-07T20:00:02.000Z")
    assert res_in == []

    # crosses out holding
    h3 = hand(1, 100.0, 50.0)
    b3 = item(10, 100.0, 50.0)
    res_out = session.update([h3, b3], ts="2026-11-07T20:00:03.000Z")
    assert res_out == []
    assert session.close() == []


def test_pairs_across_track_ids(line):
    session = DoorSession(line)
    # hand 1 holding bottle crosses in
    h1_out = hand(1, 100.0, 50.0)
    b_out = item(10, 100.0, 50.0, label="bottle")
    session.update([h1_out, b_out], ts="2026-11-07T20:00:01.000Z")

    h1_in = hand(1, 100.0, 150.0)
    b_in = item(10, 100.0, 150.0, label="bottle")
    session.update([h1_in, b_in], ts="2026-11-07T20:00:02.000Z")

    # hand 7 first seen inside
    h7_in = hand(7, 100.0, 150.0)
    session.update([h7_in], ts="2026-11-07T20:00:03.000Z")

    # hand 7 crosses out empty
    h7_out = hand(7, 100.0, 50.0)
    res = session.update([h7_out], ts="2026-11-07T20:00:04.000Z")
    assert len(res) == 1
    assert res[0].type == "PUT"
    assert res[0].item.label == "bottle"


def test_jitter_on_line_no_crossing(line):
    session = DoorSession(line)
    # hand oscillates between (100, 98) and (100, 103) (inside the margin) for 10 frames
    for i in range(10):
        cy = 98.0 if i % 2 == 0 else 103.0
        h = hand(1, 100.0, cy)
        res = session.update([h], ts=f"2026-11-07T20:00:{i:02d}.000Z")
        assert res == []

    assert session.close() == []


def test_close_flushes_unpaired(line):
    # session 1: holding in, door closes -> close() returns one PUT
    s1 = DoorSession(line)
    h1 = hand(1, 100.0, 50.0)
    b1 = item(10, 100.0, 50.0, label="milk")
    s1.update([h1, b1], ts="2026-11-07T20:00:01.000Z")
    h2 = hand(1, 100.0, 150.0)
    b2 = item(10, 100.0, 150.0, label="milk")
    s1.update([h2, b2], ts="2026-11-07T20:00:02.000Z")
    flushed1 = s1.close()
    assert len(flushed1) == 1
    assert flushed1[0].type == "PUT"
    assert flushed1[0].item.label == "milk"
    assert s1.close() == []

    # session 2: only holding out -> one TAKE
    s2 = DoorSession(line)
    h_in = hand(2, 100.0, 150.0)
    s2.update([h_in], ts="2026-11-07T20:00:03.000Z")  # first seen inside
    h_out = hand(2, 100.0, 50.0)
    b_out = item(20, 100.0, 50.0, label="yogurt")
    s2.update([h_out, b_out], ts="2026-11-07T20:00:04.000Z")
    flushed2 = s2.close()
    assert len(flushed2) == 1
    assert flushed2[0].type == "TAKE"
    assert flushed2[0].item.label == "yogurt"
    assert s2.close() == []


def test_ts_is_held_crossing(line):
    session = DoorSession(line)
    ts_in = "2026-11-07T20:00:01.123Z"
    ts_out = "2026-11-07T20:00:04.999Z"

    h_out = hand(1, 100.0, 50.0)
    b_out = item(10, 100.0, 50.0)
    session.update([h_out, b_out], ts="2026-11-07T20:00:00.000Z")

    h_in = hand(1, 100.0, 150.0)
    b_in = item(10, 100.0, 150.0)
    session.update([h_in, b_in], ts=ts_in)

    h_exit = hand(1, 100.0, 50.0)
    res = session.update([h_exit], ts=ts_out)
    assert len(res) == 1
    assert res[0].type == "PUT"
    assert res[0].ts == ts_in


def test_confidence_calculation(line):
    session = DoorSession(line)
    # PUT: min(hand.conf, item.conf) at in crossing
    h_start = hand(1, 100.0, 50.0, conf=0.9)
    it_start = item(10, 100.0, 50.0, conf=0.7)
    session.update([h_start, it_start], ts="t0")

    h_in = hand(1, 100.0, 150.0, conf=0.85)
    it_in = item(10, 100.0, 150.0, conf=0.72)
    session.update([h_in, it_in], ts="t1")

    h_out = hand(1, 100.0, 50.0, conf=0.99)
    res = session.update([h_out], ts="t2")
    assert len(res) == 1
    assert res[0].confidence == pytest.approx(0.72)

    # TAKE: min(hand.conf, item.conf) at out crossing
    session2 = DoorSession(line)
    h_start2 = hand(2, 100.0, 50.0, conf=0.95)
    session2.update([h_start2], ts="t0")

    h_in2 = hand(2, 100.0, 150.0, conf=0.95)
    session2.update([h_in2], ts="t1")

    h_out2 = hand(2, 100.0, 50.0, conf=0.6)
    it_out2 = item(20, 100.0, 50.0, conf=0.88)
    res2 = session2.update([h_out2, it_out2], ts="t2")
    assert len(res2) == 1
    assert res2[0].confidence == pytest.approx(0.6)


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


def test_first_seen_at_zero_and_margin_behavior(line):
    session = DoorSession(line)
    # Hand first seen inside margin (y=100)
    h_zero = hand(1, 100.0, 100.0)
    assert session.update([h_zero], ts="t0") == []

    # Hand moves inside fridge (y=150) -> first non-zero side recorded, not a crossing!
    h_inside = hand(1, 100.0, 150.0)
    assert session.update([h_inside], ts="t1") == []

    # Hand moves to margin (y=100) -> side 0 changes nothing
    h_margin = hand(1, 100.0, 100.0)
    assert session.update([h_margin], ts="t2") == []

    # Hand moves outside (y=50) with held item -> crossing "out"!
    it = item(10, 100.0, 50.0, label="juice")
    h_outside = hand(1, 100.0, 50.0)
    res = session.update([h_outside, it], ts="t3")
    # No pending in, so it's in pending_out
    assert res == []

    # Door closes -> TAKE
    flushed = session.close()
    assert len(flushed) == 1
    assert flushed[0].type == "TAKE"
    assert flushed[0].item.label == "juice"


def test_empty_pending_flushed_on_close(line):
    # Empty hand crosses in, session closes -> no trip
    s1 = DoorSession(line)
    s1.update([hand(1, 100.0, 50.0)], ts="t0")
    s1.update([hand(1, 100.0, 150.0)], ts="t1")  # crossing in (empty)
    assert s1.close() == []

    # Empty hand crosses out, session closes -> no trip
    s2 = DoorSession(line)
    s2.update([hand(1, 100.0, 150.0)], ts="t0")  # first seen in
    s2.update([hand(1, 100.0, 50.0)], ts="t1")  # crossing out (empty)
    assert s2.close() == []


def test_multiple_pending_in_paired_fifo(line):
    session = DoorSession(line)
    # Hand 1 crosses in holding bottle at t1
    session.update([hand(1, 100.0, 50.0), item(10, 100.0, 50.0, label="bottle")], ts="t0")
    session.update([hand(1, 100.0, 150.0), item(10, 100.0, 150.0, label="bottle")], ts="t1")

    # Hand 2 crosses in holding milk at t2
    session.update([hand(2, 100.0, 50.0), item(20, 100.0, 50.0, label="milk")], ts="t1.5")
    session.update([hand(2, 100.0, 150.0), item(20, 100.0, 150.0, label="milk")], ts="t2")

    # Hand 1 crosses out empty at t3
    res = session.update([hand(1, 100.0, 50.0)], ts="t3")
    # Should pair with the oldest pending "in" (bottle from t1)
    assert len(res) == 1
    assert res[0].type == "PUT"
    assert res[0].item.label == "bottle"
    assert res[0].ts == "t1"

    # Close door: remaining pending "in" (milk from t2) flushes as PUT
    flushed = session.close()
    assert len(flushed) == 1
    assert flushed[0].type == "PUT"
    assert flushed[0].item.label == "milk"
    assert flushed[0].ts == "t2"


def test_multiple_out_without_pending_in(line):
    session = DoorSession(line)
    # Hand 1 crosses out holding apple
    session.update([hand(1, 100.0, 150.0)], ts="t0")
    session.update([hand(1, 100.0, 50.0), item(10, 100.0, 50.0, label="apple")], ts="t1")

    # Hand 2 crosses out holding orange
    session.update([hand(2, 100.0, 150.0)], ts="t2")
    session.update([hand(2, 100.0, 50.0), item(20, 100.0, 50.0, label="orange")], ts="t3")

    flushed = session.close()
    assert len(flushed) == 2
    assert flushed[0].type == "TAKE"
    assert flushed[0].item.label == "apple"
    assert flushed[0].ts == "t1"
    assert flushed[1].type == "TAKE"
    assert flushed[1].item.label == "orange"
    assert flushed[1].ts == "t3"


def test_crop_clamping_and_out_of_bounds(line):
    session = DoorSession(line)
    frame = np.ones((100, 100, 3), dtype=np.uint8)

    # Box partially outside bounds in x: x in [-10, 20], y in [120, 140] (frame w=100, h=100) -> clamped to x in [0, 20], y in [100, 100]?
    # Wait, y must be within [0, 100] for frame, but > 115 is inside for DoorLine!
    # If frame is (200, 200, 3):
    # DoorLine: y > 115 is inside. Frame height is 200.
    # Box partially outside x: x in [-10, 20], y in [120, 140].
    # Clamped to x in [0, 20], y in [120, 140].
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


def test_dataclass_equality_and_init():
    # Positional instantiation with 4 arguments
    c1 = Crossing("in", None, "t0", None)
    c2 = Crossing("in", None, "t0", None)
    assert c1 == c2

    arr1 = np.ones((5, 5), dtype=np.uint8)
    arr2 = np.ones((5, 5), dtype=np.uint8)
    arr3 = np.zeros((5, 5), dtype=np.uint8)

    it = Track(1, "item", Box(0, 0, 10, 10), 0.8, "milk")
    t1 = Trip("PUT", it, "t0", arr1, 0.8)
    t2 = Trip("PUT", it, "t0", arr2, 0.8)
    t3 = Trip("PUT", it, "t0", arr3, 0.8)

    assert t1 == t2
    assert t1 != t3


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




