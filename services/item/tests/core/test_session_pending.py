"""Pending crossings: FIFO pairing of in/out crossings and flushing unpaired ones on close."""
from conftest import hand, item
from src.core.session import DoorSession


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
