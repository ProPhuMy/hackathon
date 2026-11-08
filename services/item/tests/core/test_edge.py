"""Item-centric trips for a top-down camera: items vanishing past / appearing at the door line."""
from conftest import hand, item
from src.core.edge import LOST_UPDATES, EdgeSession


def run(session, frames):
    trips = []
    for k, tracks in enumerate(frames):
        trips += session.update(tracks, ts=f"2026-11-08T09:00:{k:02d}.000Z")
    for k in range(LOST_UPDATES + 1):  # the item leaves view; its path finishes once it is lost
        trips += session.update([], ts=f"2026-11-08T09:01:{k:02d}.000Z")
    return trips


def test_held_item_that_vanishes_past_the_door_is_a_put(line):
    # line y=100, inside y>100; the bottle is carried from outside to just past the line, then hidden.
    trips = run(EdgeSession(line), [[hand(1, 100.0, y), item(10, 100.0, y)] for y in (20.0, 60.0, 95.0, 110.0)])
    assert [(t.type, t.item.label, t.ts) for t in trips] == [("PUT", "bottle", "2026-11-08T09:00:03.000Z")]


def test_held_item_that_appears_at_the_door_and_leaves_is_a_take(line):
    trips = run(EdgeSession(line), [[hand(1, 100.0, y), item(10, 100.0, y)] for y in (105.0, 80.0, 40.0, 0.0)])
    assert [(t.type, t.item.label, t.ts) for t in trips] == [("TAKE", "bottle", "2026-11-08T09:00:00.000Z")]


def test_item_never_in_a_hand_is_ignored(line):
    # e.g. the door's own shelves, detected as "box", swinging away from the line as the door closes
    trips = run(EdgeSession(line), [[item(10, 100.0, y, label="box")] for y in (105.0, 80.0, 40.0)])
    assert trips == []


def test_held_item_moving_around_away_from_the_door_is_ignored(line):
    trips = run(EdgeSession(line), [[hand(1, 100.0, y), item(10, 100.0, y)] for y in (-300.0, -250.0, -350.0)])
    assert trips == []


def test_close_finishes_paths_still_in_view(line):
    session = EdgeSession(line)
    for k, y in enumerate((20.0, 60.0, 110.0)):
        session.update([hand(1, 100.0, y), item(10, 100.0, y)], ts=f"2026-11-08T09:00:{k:02d}.000Z")
    assert [t.type for t in session.close()] == ["PUT"]
    assert session.close() == []
