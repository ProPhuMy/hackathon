from datetime import datetime, timezone
import cv2
import numpy as np
import pytest
from src.capture import Capture, source_value


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


def test_live_reconnect_yields_reset_boundary_and_drops_old_queue(monkeypatch):
    import queue
    from src import capture as module
    scripts = iter([[('error', 'disconnected')], [('frame', ('new-frame', 3., 'new-ts')), ('end', None)]])
    closed = []
    def start(self):
        self.output = queue.Queue()
        for item in next(scripts):
            self.output.put(item)
    monkeypatch.setattr(Capture, '_start', start, raising=False)
    monkeypatch.setattr(Capture, '_close', lambda self: closed.append(True), raising=False)
    monkeypatch.setattr(module.time, 'sleep', lambda seconds: None)
    with Capture('http://camera/video') as capture:
        frames = iter(capture)
        assert next(frames)[0] is None
        assert next(frames)[0] == 'new-frame'
    assert len(closed) == 2


def test_reconnect_attempts_are_bounded(monkeypatch):
    import queue
    from src import capture as module
    starts = []
    def start(self):
        starts.append(True)
        self.output = queue.Queue()
        self.output.put(('error', 'disconnected'))
    monkeypatch.setattr(Capture, '_start', start, raising=False)
    monkeypatch.setattr(Capture, '_close', lambda self: None, raising=False)
    monkeypatch.setattr(module.time, 'sleep', lambda seconds: None)
    with Capture('http://camera/video') as capture:
        with pytest.raises(RuntimeError, match='reconnect'):
            list(capture)
    assert len(starts) == 4
