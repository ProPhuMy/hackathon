from datetime import datetime, timezone
import cv2
import numpy as np
import pytest
from fridge_person.capture import Capture, source_value
from fridge_person.runtime import segment_id


def test_source_parsing_and_missing_replay_origin(tmp_path):
    assert source_value('0') == 0
    assert source_value('./0') == './0'
    clip = tmp_path / 'clip.avi'
    clip.touch()
    with pytest.raises(ValueError):
        Capture(str(clip))


def test_recorded_capture_preserves_video_time_and_shuts_down(tmp_path):
    clip = tmp_path / 'clip.avi'
    writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*'MJPG'), 5, (64, 64))
    assert writer.isOpened()
    for _ in range(5):
        writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
    writer.release()
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Capture(str(clip), origin) as capture:
        frames = list(capture)
    assert len(frames) == 5
    times = [datetime.fromisoformat(ts.replace('Z', '+00:00')) for _, _, ts in frames]
    assert (times[-1] - times[0]).total_seconds() == pytest.approx(.8)
    assert not capture.process.is_alive()


def test_segment_ids_survive_restarts(tmp_path):
    path = tmp_path / 'counter.json'
    assert segment_id(path) == 0
    assert segment_id(path) == 1
