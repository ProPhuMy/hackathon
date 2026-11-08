import numpy as np

from src.core.geometry import Box, DoorLine, Track
from src.draw import overlay


def test_overlay():
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    frame_orig = frame.copy()
    line = DoorLine(p1=(10.0, 50.0), p2=(190.0, 50.0), inside=(100.0, 100.0))
    tracks = [
        Track(id=1, kind="hand", box=Box(20.0, 30.0, 60.0, 70.0), conf=0.9, label="hand"),
        Track(id=2, kind="item", box=Box(80.0, 90.0, 120.0, 130.0), conf=0.85, label="bottle"),
    ]
    events = [{"type": "PUT", "item_id": "item-123", "item_label": "bottle"}]

    out = overlay(frame, tracks, line, door_open=True, events=events)
    assert out.shape == frame.shape
    assert out.dtype == frame.dtype
    # The overlay returns a modified image while leaving original frame intact
    assert np.array_equal(frame, frame_orig)
    assert not np.array_equal(out, frame)
