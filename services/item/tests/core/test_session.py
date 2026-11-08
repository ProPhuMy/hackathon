"""Crossing detection and in/out pairing into PUT/TAKE trips."""
import numpy as np
import pytest

from conftest import hand, item
from src.core.geometry import Box, Track
from src.core.session import Crossing, DoorSession, Trip


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
    # stamped at the hand going in, while the face is still visible to the person camera
    assert trip.ts == "2026-11-07T20:00:02.000Z"
    assert trip.confidence == 0.85


def test_take_after_long_rummage_keeps_in_time(line):
    session = DoorSession(line)
    session.update([hand(1, 100.0, 50.0)], ts="t0")
    session.update([hand(1, 100.0, 150.0)], ts="t_in")  # empty hand goes in
    for i in range(5):  # several seconds inside the fridge
        session.update([hand(1, 100.0, 160.0)], ts=f"t_inside_{i}")
    res = session.update([hand(1, 100.0, 50.0), item(20, 100.0, 50.0)], ts="t_out")
    assert [(t.type, t.ts) for t in res] == [("TAKE", "t_in")]


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
