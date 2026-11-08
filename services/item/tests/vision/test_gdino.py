import sys
from unittest.mock import MagicMock

import numpy as np

from src.core.geometry import Box
from src.vision.gdino import GDinoDetector, phrase_to_class, tracker_output_to_tracks


def test_phrase_to_class_exact():
    prompts = ["juice", "milk", "coke"]
    assert phrase_to_class("Milk", prompts) == 1
    assert phrase_to_class("  coke  ", prompts) == 2
    assert phrase_to_class("JUICE", prompts) == 0


def test_phrase_to_class_contained():
    prompts = ["juice", "milk"]
    assert phrase_to_class("carton of milk", prompts) == 1
    assert phrase_to_class("orange juice bottle", prompts) == 0


def test_phrase_to_class_longest_wins():
    prompts = ["milk", "whole milk", "bottle"]
    assert phrase_to_class("a fresh whole milk carton", prompts) == 1
    prompts2 = ["juice", "apple juice", "bottle"]
    assert phrase_to_class("the apple juice bottle", prompts2) == 1


def test_phrase_to_class_no_match():
    prompts = ["milk", "juice"]
    assert phrase_to_class("banana", prompts) is None
    assert phrase_to_class("", prompts) is None
    assert phrase_to_class("milk", []) is None


def test_tracker_output_to_tracks():
    names = {0: "hand", 1: "milk"}
    out = np.array([
        [10.0, 20.0, 30.0, 40.0, 1.0, 0.95, 0.0, 0.0],
        [50.0, 60.0, 70.0, 80.0, 2.0, 0.85, 1.0, 1.0],
    ])
    tracks = tracker_output_to_tracks(out, names, hand_label="hand")
    assert len(tracks) == 2
    assert tracks[0].id == 1
    assert tracks[0].kind == "hand"
    assert tracks[0].label == "hand"
    assert tracks[0].box == Box(10.0, 20.0, 30.0, 40.0)

    assert tracks[1].id == 2
    assert tracks[1].kind == "item"
    assert tracks[1].label == "milk"
    assert tracks[1].box == Box(50.0, 60.0, 70.0, 80.0)

    # Empty tracker output
    assert tracker_output_to_tracks(np.empty((0, 8)), names, hand_label="hand") == []
    assert tracker_output_to_tracks(None, names, hand_label="hand") == []


def test_gdino_detector_bytetrack_thresholds(monkeypatch):

    recorded_configs = []

    class FakeByteTrack:
        def __init__(self, *args, **kwargs):
            recorded_configs.append((args, kwargs))

    monkeypatch.setattr("boxmot.ByteTrack", FakeByteTrack)

    mock_transformers = MagicMock()
    mock_model = MagicMock()
    mock_model.to.return_value = mock_model
    mock_transformers.AutoProcessor.from_pretrained.return_value = MagicMock()
    mock_transformers.AutoModelForZeroShotObjectDetection.from_pretrained.return_value = (
        mock_model
    )
    monkeypatch.setitem(sys.modules, "transformers", mock_transformers)

    GDinoDetector(prompts=["milk"], box_threshold=0.3)

    assert len(recorded_configs) == 1
    args, kwargs = recorded_configs[0]
    config = args[0] if args else kwargs.get("config")
    assert config is not None
    assert config.min_conf == 0.3
    assert config.track_thresh == 0.3
