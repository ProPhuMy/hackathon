import threading
import time
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from src.stream import LatestFrameReader, iter_frames, split_jpegs


def test_split_two_frames():
    a, b = b"\xff\xd8AAA\xff\xd9", b"\xff\xd8BB\xff\xd9"
    frames, rest = split_jpegs(b"junk" + a + b)
    assert frames == [a, b] and rest == b""


def test_split_keeps_partial_tail():
    frames, rest = split_jpegs(b"\xff\xd8AAA\xff\xd9\xff\xd8BB")
    assert frames == [b"\xff\xd8AAA\xff\xd9"] and rest == b"\xff\xd8BB"


def test_split_empty_and_no_markers():
    frames, rest = split_jpegs(b"")
    assert frames == [] and rest == b""
    frames, rest = split_jpegs(b"random characters without jpeg markers")
    assert frames == [] and rest == b""


def test_latest_frame_reader_returns_frame_once():
    # Create valid JPEG bytes
    img = np.zeros((20, 20, 3), dtype=np.uint8)
    _, encoded = cv2.imencode(".jpg", img)
    jpeg_bytes = bytes(encoded)

    mock_resp = MagicMock()
    # Stream one frame followed by chunk wait
    mock_resp.iter_content.return_value = [jpeg_bytes]
    mock_resp.__enter__.return_value = mock_resp

    with patch("requests.Session.get", return_value=mock_resp):
        reader = LatestFrameReader("http://mock-cam/video")
        try:
            # Poll for the decoded frame
            start = time.time()
            frame_data = None
            while time.time() - start < 2.0:
                frame_data = reader.latest()
                if frame_data is not None:
                    break
                time.sleep(0.01)

            assert frame_data is not None
            frame, ts = frame_data
            assert frame.shape == (20, 20, 3)
            assert isinstance(ts, str) and ts.endswith("Z")

            # Calling latest() again immediately should return None (each frame returned once)
            assert reader.latest() is None
        finally:
            reader.stop()


def test_latest_frame_reader_prints_exception_and_retries(capsys):

    attempts = 0
    second_attempt_event = threading.Event()

    def fake_get(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts >= 2:
            second_attempt_event.set()
        raise ConnectionError("connection failed: wrong URL")

    with patch("requests.Session.get", side_effect=fake_get):
        reader = LatestFrameReader("http://invalid-cam-url/video")
        try:
            assert second_attempt_event.wait(timeout=2.5), "Did not retry after failure"
            assert attempts >= 2
        finally:
            reader.stop()

    captured = capsys.readouterr()
    assert "connection failed: wrong URL" in captured.out


def test_iter_frames_from_video_file(tmp_path):
    video_path = str(tmp_path / "test.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(video_path, fourcc, 15.0, (30, 30))
    for i in range(3):
        frame = np.full((30, 30, 3), fill_value=i * 50, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    frames = list(iter_frames(video_path))
    assert len(frames) == 3
    for frame, ts in frames:
        assert frame.shape == (30, 30, 3)
        assert isinstance(ts, str) and ts.endswith("Z")
