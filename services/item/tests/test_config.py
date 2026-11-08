import cv2
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from src.config import Config, DEFAULT_PROMPTS, load, save, calibrate
from src.geometry import Box, DoorLine, Track
from src.__main__ import parse_args


def test_config_roundtrip(tmp_path: Path):
    line = DoorLine(
        p1=(12.5, 34.0),
        p2=(100.0, 45.5),
        inside=(50.0, 80.0),
        margin=15.0,
    )
    cfg = Config(
        roi=(10, 20, 200, 150),
        line=line,
        door_on=160.0,
        door_off=110.0,
        prompts=DEFAULT_PROMPTS,
        hand_label="hand",
    )
    cfg_path = tmp_path / "config.json"
    save(cfg, cfg_path)
    loaded = load(cfg_path)

    assert loaded == cfg
    assert loaded.roi == (10, 20, 200, 150)
    assert loaded.line.p1 == (12.5, 34.0)
    assert loaded.line.p2 == (100.0, 45.5)
    assert loaded.line.inside == (50.0, 80.0)
    assert loaded.line.margin == 15.0
    assert loaded.door_on == 160.0
    assert loaded.door_off == 110.0
    assert loaded.prompts == DEFAULT_PROMPTS
    assert loaded.hand_label == "hand"


def test_config_defaults():
    line = DoorLine(p1=(0.0, 0.0), p2=(10.0, 10.0), inside=(5.0, 15.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)
    assert cfg.prompts == DEFAULT_PROMPTS
    assert cfg.hand_label == "hand"
    assert cfg.line.margin == 15.0


def test_geometry_box():
    b1 = Box(0.0, 0.0, 10.0, 10.0)
    assert b1.center() == (5.0, 5.0)
    assert b1.area() == 100.0

    b2 = Box(5.0, 5.0, 15.0, 15.0)
    assert b1.intersection(b2) == 25.0

    b3 = Box(20.0, 20.0, 30.0, 30.0)
    assert b1.intersection(b3) == 0.0

    # Inverted box coordinates should have 0 area
    b_inv = Box(10.0, 10.0, 0.0, 0.0)
    assert b_inv.area() == 0.0


def test_geometry_track():
    box = Box(1.0, 2.0, 3.0, 4.0)
    track = Track(id=7, kind="hand", box=box, conf=0.95, label="hand")
    assert track.id == 7
    assert track.kind == "hand"
    assert track.box == box
    assert track.conf == 0.95
    assert track.label == "hand"


def test_calibrate_parser():
    args = parse_args(["calibrate", "http://localhost:8080/video"])
    assert args.subcommand == "calibrate"
    assert args.source == "http://localhost:8080/video"
    assert args.out == "config.json"

    args2 = parse_args(["calibrate", "clip.mp4", "--out", "my_config.json"])
    assert args2.source == "clip.mp4"
    assert args2.out == "my_config.json"


def test_calibrate_main_dispatch():
    from src.__main__ import main
    with patch("src.__main__.calibrate") as mock_cal:
        main(["calibrate", "http://camera/stream", "--out", "out.json"])
        mock_cal.assert_called_once_with("http://camera/stream", "out.json")


def test_calibrate_empty_stream():
    with patch("src.config.iter_frames", return_value=iter([])):
        with pytest.raises(ValueError, match="No frames available"):
            calibrate("empty_source")


def test_calibrate_aborted_points():
    dummy_frame = np.full((50, 50, 3), 10, dtype=np.uint8)
    with patch("src.config.iter_frames", return_value=iter([(dummy_frame, "ts")])), \
         patch("cv2.selectROI", return_value=(0, 0, 10, 10)), \
         patch("cv2.namedWindow"), \
         patch("cv2.imshow"), \
         patch("cv2.destroyWindow"), \
         patch("cv2.setMouseCallback"), \
         patch("cv2.waitKey", return_value=27):  # ESC key
        with pytest.raises(RuntimeError, match="Calibration aborted"):
            calibrate("source")


def test_load_default_margin_and_prompts(tmp_path: Path):
    cfg_file = tmp_path / "legacy_cfg.json"
    import json
    cfg_file.write_text(
        json.dumps({
            "roi": [0, 0, 10, 10],
            "line": {"p1": [0, 0], "p2": [10, 10], "inside": [5, 5]},
            "door_on": 120.0,
            "door_off": 80.0,
        })
    )
    loaded = load(cfg_file)
    assert loaded.line.margin == 15.0
    assert loaded.prompts == DEFAULT_PROMPTS
    assert loaded.hand_label == "hand"


def test_calibrate_invalid_roi_raises(tmp_path: Path):
    out_file = tmp_path / "config.json"
    dummy_frame = np.full((100, 100, 3), 40, dtype=np.uint8)

    with patch("src.config.iter_frames", return_value=iter([(dummy_frame, "ts")])), \
         patch("cv2.selectROI", return_value=(0, 0, 0, 0)), \
         patch("cv2.namedWindow"), \
         patch("cv2.imshow"), \
         patch("cv2.destroyWindow"), \
         patch("cv2.setMouseCallback"), \
         patch("cv2.waitKey", return_value=27):
        with pytest.raises(ValueError, match="width and height must be positive"):
            calibrate("dummy_source", out_file)

    assert not out_file.exists()


def test_calibrate_one_frame_source_exhaustion_on_open(tmp_path: Path):
    out_file = tmp_path / "config.json"
    dummy_frame = np.full((100, 100, 3), 50, dtype=np.uint8)

    # Only one frame in the entire source
    frames = [(dummy_frame, "2026-11-07T19:40:00.000Z")]

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

    with patch("src.config.iter_frames", return_value=iter(frames)), \
         patch("cv2.selectROI", return_value=(10, 20, 30, 40)), \
         patch("cv2.namedWindow"), \
         patch("cv2.imshow"), \
         patch("cv2.destroyWindow"), \
         patch("cv2.destroyAllWindows"), \
         patch("cv2.setMouseCallback", side_effect=fake_set_mouse_callback), \
         patch("cv2.waitKey", side_effect=fake_wait_key):
        with pytest.raises(ValueError, match="exhausted"):
            calibrate("dummy_source", out_file)

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

    mouse_callbacks = []

    def fake_set_mouse_callback(winname, callback, param=None):
        mouse_callbacks.append(callback)

    def fake_wait_key(delay):
        if mouse_callbacks:
            cb = mouse_callbacks[0]
            # Click 1: p1
            cb(cv2.EVENT_LBUTTONDOWN, 15, 25, 0, None)
            # Click 2: p2
            cb(cv2.EVENT_LBUTTONDOWN, 85, 25, 0, None)
            # Click 3: inside
            cb(cv2.EVENT_LBUTTONDOWN, 50, 70, 0, None)
        return 13

    with patch("src.config.iter_frames", return_value=iter(frames)), \
         patch("cv2.selectROI", return_value=(10, 20, 30, 40)), \
         patch("cv2.namedWindow"), \
         patch("cv2.imshow"), \
         patch("cv2.destroyWindow"), \
         patch("cv2.destroyAllWindows"), \
         patch("cv2.setMouseCallback", side_effect=fake_set_mouse_callback), \
         patch("cv2.waitKey", side_effect=fake_wait_key):

        cfg = calibrate("dummy_source", out_file)

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

    with patch("src.config.iter_frames", return_value=iter(frames)), \
         patch("cv2.selectROI", return_value=(10, 20, 30, 40)), \
         patch("cv2.namedWindow"), \
         patch("cv2.imshow"), \
         patch("cv2.destroyWindow"), \
         patch("cv2.destroyAllWindows"), \
         patch("cv2.setMouseCallback", side_effect=fake_set_mouse_callback), \
         patch("cv2.waitKey", side_effect=fake_wait_key):

        with pytest.raises(ValueError, match="brighter"):
            calibrate("dummy_source", out_file)

    assert not out_file.exists()
