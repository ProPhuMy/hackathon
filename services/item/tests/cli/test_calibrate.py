from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from src.cli.calibrate import calibrate_command


@contextmanager
def headless_gui(frames, roi=(10, 20, 30, 40)):
    """Stub cv2 windows; the first waitKey clicks p1=(15, 25), p2=(85, 25), inside=(50, 70)."""
    mouse_callbacks = []

    def fake_set_mouse_callback(winname, callback, param=None):
        mouse_callbacks.append(callback)

    def fake_wait_key(delay):
        if mouse_callbacks:
            cb = mouse_callbacks[0]
            cb(cv2.EVENT_LBUTTONDOWN, 15, 25, 0, None)
            cb(cv2.EVENT_LBUTTONDOWN, 85, 25, 0, None)
            cb(cv2.EVENT_LBUTTONDOWN, 50, 70, 0, None)
        return 13

    with ExitStack() as stack:
        stack.enter_context(patch("src.cli.calibrate.iter_frames", return_value=iter(frames)))
        stack.enter_context(patch("cv2.selectROI", return_value=roi))
        for name in ["namedWindow", "imshow", "destroyWindow", "destroyAllWindows"]:
            stack.enter_context(patch(f"cv2.{name}"))
        stack.enter_context(patch("cv2.setMouseCallback", side_effect=fake_set_mouse_callback))
        stack.enter_context(patch("cv2.waitKey", side_effect=fake_wait_key))
        yield


def test_calibrate_empty_stream():
    with patch("src.cli.calibrate.iter_frames", return_value=iter([])):
        with pytest.raises(ValueError, match="No frames available"):
            calibrate_command("empty_source")


def test_calibrate_aborted_points():
    dummy_frame = np.full((50, 50, 3), 10, dtype=np.uint8)
    with patch("src.cli.calibrate.iter_frames", return_value=iter([(dummy_frame, "ts")])), \
         patch("cv2.selectROI", return_value=(0, 0, 10, 10)), \
         patch("cv2.namedWindow"), \
         patch("cv2.imshow"), \
         patch("cv2.destroyWindow"), \
         patch("cv2.setMouseCallback"), \
         patch("cv2.waitKey", return_value=27):  # ESC key
        with pytest.raises(RuntimeError, match="Calibration aborted"):
            calibrate_command("source")


def test_calibrate_invalid_roi_raises(tmp_path: Path):
    out_file = tmp_path / "config.json"
    dummy_frame = np.full((100, 100, 3), 40, dtype=np.uint8)

    with patch("src.cli.calibrate.iter_frames", return_value=iter([(dummy_frame, "ts")])), \
         patch("cv2.selectROI", return_value=(0, 0, 0, 0)), \
         patch("cv2.namedWindow"), \
         patch("cv2.imshow"), \
         patch("cv2.destroyWindow"), \
         patch("cv2.setMouseCallback"), \
         patch("cv2.waitKey", return_value=27):
        with pytest.raises(ValueError, match="width and height must be positive"):
            calibrate_command("dummy_source", out_file)

    assert not out_file.exists()


def test_calibrate_one_frame_source_exhaustion_on_open(tmp_path: Path):
    out_file = tmp_path / "config.json"
    dummy_frame = np.full((100, 100, 3), 50, dtype=np.uint8)

    # Only one frame in the entire source
    with headless_gui([(dummy_frame, "2026-11-07T19:40:00.000Z")]):
        with pytest.raises(ValueError, match="exhausted"):
            calibrate_command("dummy_source", out_file)

    assert not out_file.exists()


def test_calibrate_logic(tmp_path: Path):
    out_file = tmp_path / "config.json"
    dummy_frame = np.full((100, 100, 3), 40, dtype=np.uint8)
    closed_frame = np.full((100, 100, 3), 50, dtype=np.uint8)
    open_frame = np.full((100, 100, 3), 150, dtype=np.uint8)

    # Frame generator simulates first frame, closed door frame, and open door frame
    frames = [
        (dummy_frame, "2026-11-07T19:40:00.000Z"),
        (closed_frame, "2026-11-07T19:40:00.066Z"),
        (open_frame, "2026-11-07T19:40:00.133Z"),
    ]
    with headless_gui(frames):
        cfg = calibrate_command("dummy_source", out_file)

    assert out_file.exists()
    assert cfg.roi == (10, 20, 30, 40)
    assert cfg.line.p1 == (15.0, 25.0)
    assert cfg.line.p2 == (85.0, 25.0)
    assert cfg.line.inside == (50.0, 70.0)
    # c = 50, o = 150
    # door_on = 50 + 0.6 * 100 = 110.0
    # door_off = 50 + 0.4 * 100 = 90.0
    assert pytest.approx(cfg.door_on) == 110.0
    assert pytest.approx(cfg.door_off) == 90.0


def test_calibrate_insufficient_brightness_diff_raises(tmp_path: Path):
    out_file = tmp_path / "config.json"
    dummy_frame = np.full((100, 100, 3), 40, dtype=np.uint8)
    closed_frame = np.full((100, 100, 3), 100, dtype=np.uint8)
    open_frame = np.full((100, 100, 3), 105, dtype=np.uint8)

    frames = [
        (dummy_frame, "2026-11-07T19:40:00.000Z"),
        (closed_frame, "2026-11-07T19:40:00.066Z"),
        (open_frame, "2026-11-07T19:40:00.133Z"),
    ]
    with headless_gui(frames):
        with pytest.raises(ValueError, match="barely changed"):
            calibrate_command("dummy_source", out_file)

    assert not out_file.exists()


def test_calibrate_accepts_a_door_that_darkens_when_opened(tmp_path: Path):
    out_file = tmp_path / "config.json"
    frames = [
        (np.full((100, 100, 3), 40, dtype=np.uint8), "2026-11-07T19:40:00.000Z"),
        (np.full((100, 100, 3), 150, dtype=np.uint8), "2026-11-07T19:40:00.066Z"),  # closed
        (np.full((100, 100, 3), 50, dtype=np.uint8), "2026-11-07T19:40:00.133Z"),  # open: darker
    ]
    with headless_gui(frames):
        cfg = calibrate_command("dummy_source", out_file)
    # c = 150, o = 50: on = 150 - 60 = 90, off = 150 - 40 = 110, so on < off marks "open is darker".
    assert pytest.approx(cfg.door_on) == 90.0
    assert pytest.approx(cfg.door_off) == 110.0
