from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from src.cli.probe import probe_command
from src.config import Config
from src.core.geometry import Box, DoorLine, Track


def test_probe_command_flow(tmp_path: Path):

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

    with patch("src.cli.probe.load", return_value=cfg), \
         patch("src.vision.detect.Detector", return_value=mock_detector), \
         patch("src.cli.probe.iter_frames", return_value=iter(frames)), \
         patch("cv2.VideoWriter", return_value=mock_writer):
        probe_command("test_clip.mp4", str(out_video), config_path="dummy.json")

    mock_detector.assert_called_once_with(dummy_frame)
    mock_writer.write.assert_called_once()
    mock_writer.release.assert_called_once()


def test_probe_command_selects_gdino(tmp_path: Path):

    cfg = Config(
        roi=(0, 0, 50, 50),
        line=DoorLine(p1=(0.0, 25.0), p2=(50.0, 25.0), inside=(25.0, 40.0)),
        door_on=100.0,
        door_off=50.0,
        prompts=["milk"],
    )
    dummy_frame = np.full((100, 100, 3), 120, dtype=np.uint8)
    frames = [(dummy_frame, "2026-11-07T20:00:00.000Z")]

    mock_gdino = MagicMock()
    mock_gdino.return_value = []
    mock_writer = MagicMock()

    with patch("src.cli.probe.load", return_value=cfg), \
         patch("src.vision.gdino.GDinoDetector", return_value=mock_gdino) as mock_gdino_cls, \
         patch("src.cli.probe.iter_frames", return_value=iter(frames)), \
         patch("cv2.VideoWriter", return_value=mock_writer):
        probe_command("clip.mp4", str(tmp_path / "out.mp4"), detector="gdino")

    mock_gdino_cls.assert_called_once_with(prompts=cfg.prompts, hand_label=cfg.hand_label)
    mock_gdino.assert_called_once_with(dummy_frame)
