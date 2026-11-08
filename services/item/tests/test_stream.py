import time
from unittest.mock import MagicMock, patch
import cv2
import numpy as np
import pytest

from fridge_item.stream import LatestFrameReader, iter_frames, split_jpegs
from fridge_item.__main__ import parse_args, record_command


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


def test_record_cli_arg_parsing():
    args = parse_args(["record", "http://localhost:8080/video", "out.mp4"])
    assert args.subcommand == "record"
    assert args.url == "http://localhost:8080/video"
    assert args.out == "out.mp4"


def test_record_command(tmp_path):
    out_video = tmp_path / "rec.mp4"
    frame_mock = np.zeros((40, 40, 3), dtype=np.uint8)

    with patch(
        "fridge_item.__main__.iter_frames",
        return_value=[
            (frame_mock, "2026-11-07T19:40:00.000Z"),
            (frame_mock, "2026-11-07T19:40:00.066Z"),
        ],
    ):
        record_command("http://dummy", str(out_video))

    assert out_video.exists()
    assert out_video.stat().st_size > 0


def test_latest_frame_reader_prints_exception_and_retries(capsys):
    import threading

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

