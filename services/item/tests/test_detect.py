from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from fridge_item.geometry import Box, DoorLine, Track
from fridge_item.detect import to_tracks, Detector
from fridge_item.draw import overlay
from fridge_item.__main__ import parse_args, probe_command


def test_drops_rows_without_id():
    xyxy = np.array([[10.0, 20.0, 30.0, 40.0], [50.0, 60.0, 70.0, 80.0]])
    conf = np.array([0.9, 0.8])
    cls = np.array([0, 1])
    names = {0: "hand", 1: "bottle"}

    # Case 1: ids is None
    tracks_none = to_tracks(
        xyxy=xyxy,
        ids=None,
        conf=conf,
        cls=cls,
        names=names,
        hand_label="hand",
    )
    assert tracks_none == []

    # Case 2: ids contains a NaN / missing ID
    ids_with_nan = np.array([np.nan, 3.0])
    tracks_filtered = to_tracks(
        xyxy=xyxy,
        ids=ids_with_nan,
        conf=conf,
        cls=cls,
        names=names,
        hand_label="hand",
    )
    assert len(tracks_filtered) == 1
    assert tracks_filtered[0].id == 3
    assert tracks_filtered[0].label == "bottle"


def test_hand_kind():
    xyxy = np.array(
        [
            [10.0, 20.0, 30.0, 40.0],
            [50.0, 60.0, 70.0, 80.0],
            [15.0, 25.0, 35.0, 45.0],
        ]
    )
    ids = np.array([1, 2, 5])
    conf = np.array([0.95, 0.82, 0.75])
    cls = np.array([0, 1, 2])
    names = {0: "hand", 1: "milk carton", 2: "can"}

    tracks = to_tracks(
        xyxy=xyxy,
        ids=ids,
        conf=conf,
        cls=cls,
        names=names,
        hand_label="hand",
    )
    assert len(tracks) == 3

    # Row 0: class is "hand" -> kind == "hand"
    assert tracks[0].id == 1
    assert tracks[0].kind == "hand"
    assert tracks[0].label == "hand"
    assert tracks[0].conf == 0.95
    assert tracks[0].box == Box(10.0, 20.0, 30.0, 40.0)

    # Row 1: class is "milk carton" -> kind == "item"
    assert tracks[1].id == 2
    assert tracks[1].kind == "item"
    assert tracks[1].label == "milk carton"
    assert tracks[1].conf == 0.82
    assert tracks[1].box == Box(50.0, 60.0, 70.0, 80.0)

    # Row 2: class is "can" -> kind == "item"
    assert tracks[2].id == 5
    assert tracks[2].kind == "item"
    assert tracks[2].label == "can"
    assert tracks[2].conf == 0.75
    assert tracks[2].box == Box(15.0, 25.0, 35.0, 45.0)


def test_custom_hand_label():
    xyxy = np.array([[1.0, 2.0, 3.0, 4.0]])
    ids = np.array([10])
    conf = np.array([0.9])
    cls = np.array([0])
    names = {0: "user_hand"}

    tracks = to_tracks(
        xyxy=xyxy,
        ids=ids,
        conf=conf,
        cls=cls,
        names=names,
        hand_label="user_hand",
    )
    assert len(tracks) == 1
    assert tracks[0].kind == "hand"
    assert tracks[0].label == "user_hand"


def test_empty_detections():
    xyxy = np.empty((0, 4))
    ids = np.empty((0,))
    conf = np.empty((0,))
    cls = np.empty((0,))
    names = {0: "hand"}

    tracks = to_tracks(
        xyxy=xyxy,
        ids=ids,
        conf=conf,
        cls=cls,
        names=names,
        hand_label="hand",
    )
    assert tracks == []


def test_detector_mocked():
    with patch("ultralytics.YOLOE") as mock_yoloe_cls:
        mock_model = MagicMock()
        mock_yoloe_cls.return_value = mock_model
        mock_model.get_text_pe.return_value = "dummy_embeddings"
        mock_model.names = {0: "hand", 1: "bottle"}

        detector = Detector(prompts=["hand", "bottle"], hand_label="hand", weights="test.pt")
        mock_yoloe_cls.assert_called_once_with("test.pt")
        mock_model.get_text_pe.assert_called_once_with(["hand", "bottle"])
        mock_model.set_classes.assert_called_once_with(["hand", "bottle"], "dummy_embeddings")

        # Mock results returned by track
        mock_box = MagicMock()
        import torch

        mock_box.xyxy = torch.tensor([[10.0, 20.0, 30.0, 40.0]])
        mock_box.id = torch.tensor([1.0])
        mock_box.conf = torch.tensor([0.91])
        mock_box.cls = torch.tensor([0.0])

        mock_result = MagicMock()
        mock_result.boxes = mock_box
        mock_result.names = {0: "hand", 1: "bottle"}
        mock_model.track.return_value = [mock_result]

        dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        tracks = detector(dummy_frame)

        mock_model.track.assert_called_once_with(dummy_frame, persist=True, verbose=False)
        assert len(tracks) == 1
        assert tracks[0].id == 1
        assert tracks[0].kind == "hand"
        assert tracks[0].label == "hand"
        assert pytest.approx(tracks[0].conf, 0.01) == 0.91


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


def test_probe_parser():
    args = parse_args(["probe", "video.mp4", "annotated.mp4"])
    assert args.subcommand == "probe"
    assert args.clip == "video.mp4"
    assert args.out == "annotated.mp4"
    assert args.config == "config.json"

    args_custom = parse_args(["probe", "clip.mp4", "out.mp4", "--config", "custom.json"])
    assert args_custom.clip == "clip.mp4"
    assert args_custom.out == "out.mp4"
    assert args_custom.config == "custom.json"


def test_probe_main_dispatch():
    from fridge_item.__main__ import main
    with patch("fridge_item.__main__.probe_command") as mock_probe:
        main(["probe", "in.mp4", "out.mp4", "--config", "conf.json"])
        mock_probe.assert_called_once_with("in.mp4", "out.mp4", "conf.json")


def test_probe_command_flow(tmp_path: Path):
    from fridge_item.config import Config

    cfg = Config(
        roi=(0, 0, 50, 50),
        line=DoorLine(p1=(0.0, 25.0), p2=(50.0, 25.0), inside=(25.0, 40.0)),
        door_on=100.0,
        door_off=50.0,
        prompts=["hand", "bottle"],
    )
    dummy_frame = np.full((100, 100, 3), 120, dtype=np.uint8)
    frames = [(dummy_frame, "2026-11-07T20:00:00.000Z")]

    out_video = tmp_path / "out.mp4"

    mock_detector = MagicMock()
    mock_detector.return_value = [
        Track(id=1, kind="hand", box=Box(10.0, 10.0, 30.0, 30.0), conf=0.9, label="hand")
    ]
    mock_writer = MagicMock()

    with patch("fridge_item.config.load", return_value=cfg), \
         patch("fridge_item.detect.Detector", return_value=mock_detector), \
         patch("fridge_item.__main__.iter_frames", return_value=iter(frames)), \
         patch("cv2.VideoWriter", return_value=mock_writer):
        probe_command("test_clip.mp4", str(out_video), config_path="dummy.json")

    mock_detector.assert_called_once_with(dummy_frame)
    mock_writer.write.assert_called_once()
    mock_writer.release.assert_called_once()
