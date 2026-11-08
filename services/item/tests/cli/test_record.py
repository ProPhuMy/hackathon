from unittest.mock import patch

import numpy as np

from src.cli.record import record_command


def test_record_command(tmp_path):
    out_video = tmp_path / "rec.mp4"
    frame_mock = np.zeros((40, 40, 3), dtype=np.uint8)

    with patch(
        "src.cli.record.iter_frames",
        return_value=[
            (frame_mock, "2026-11-07T19:40:00.000Z"),
            (frame_mock, "2026-11-07T19:40:00.066Z"),
        ],
    ):
        record_command("http://dummy", str(out_video))

    assert out_video.exists()
    assert out_video.stat().st_size > 0


def _stamps(n, step_ms):
    from datetime import datetime, timedelta, timezone
    start = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)
    return [(start + timedelta(milliseconds=i * step_ms)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            for i in range(n)]


def _fps_and_count(path):
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        return cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()


def test_stream_recording_uses_the_measured_frame_rate(tmp_path):
    # A 25 fps camera must not be written as 15 fps: the clip would play 1.7x slow and stretch video time.
    out_video = tmp_path / "rec.mp4"
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    with patch("src.cli.record.iter_frames", return_value=[(frame, ts) for ts in _stamps(60, 40)]):
        record_command("http://dummy", str(out_video))
    fps, count = _fps_and_count(out_video)
    assert round(fps) == 25 and count == 60


def test_short_stream_recording_is_still_saved_at_its_rate(tmp_path):
    out_video = tmp_path / "rec.mp4"
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    with patch("src.cli.record.iter_frames", return_value=[(frame, ts) for ts in _stamps(5, 100)]):
        record_command("http://dummy", str(out_video))
    fps, count = _fps_and_count(out_video)
    assert round(fps) == 10 and count == 5


def test_file_recording_keeps_the_source_frame_rate(tmp_path):
    import cv2
    source = tmp_path / "source.mp4"
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 12.0, (40, 40))
    for _ in range(36):
        writer.write(np.zeros((40, 40, 3), dtype=np.uint8))
    writer.release()
    out_video = tmp_path / "rec.mp4"
    record_command(str(source), str(out_video))
    fps, count = _fps_and_count(out_video)
    assert round(fps) == 12 and count == 36
