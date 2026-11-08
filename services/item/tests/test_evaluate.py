from pathlib import Path
from unittest.mock import MagicMock
import pytest

from fridge_item.config import Config, save
from fridge_item.evaluate import evaluate_command, score
from fridge_item.geometry import DoorLine


def test_score_exact():
    expected = [("PUT", "juice"), ("TAKE", "juice")]
    got = [("PUT", "juice"), ("TAKE", "juice")]
    res = score(expected, got)
    assert res == {"correct": 2, "missed": 0, "extra": 0}


def test_score_missed_and_extra():
    expected = [("PUT", "juice"), ("TAKE", "coke")]
    got = [("PUT", "juice"), ("PUT", "milk")]
    res = score(expected, got)
    assert res == {"correct": 1, "missed": 1, "extra": 1}


def test_score_empty():
    assert score([], []) == {"correct": 0, "missed": 0, "extra": 0}


def test_score_all_missed():
    expected = [("PUT", "juice")]
    got = []
    assert score(expected, got) == {"correct": 0, "missed": 1, "extra": 0}


def test_score_all_extra():
    expected = []
    got = [("TAKE", "coke")]
    assert score(expected, got) == {"correct": 0, "missed": 0, "extra": 1}


def test_score_duplicates():
    expected = [("PUT", "juice"), ("PUT", "juice")]
    got = [("PUT", "juice")]
    assert score(expected, got) == {"correct": 1, "missed": 1, "extra": 0}


def test_score_order_independent():
    expected = [("PUT", "juice"), ("TAKE", "coke")]
    got = [("TAKE", "coke"), ("PUT", "juice")]
    assert score(expected, got) == {"correct": 2, "missed": 0, "extra": 0}


def test_evaluate_fresh_detector_per_clip(tmp_path: Path, monkeypatch):
    labels_file = tmp_path / "labels.csv"
    labels_file.write_text("clip1.mp4,PUT,juice\nclip2.mp4,TAKE,juice\n")

    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    (clips_dir / "clip1.mp4").touch()
    (clips_dir / "clip2.mp4").touch()

    cfg_file = tmp_path / "config.json"
    save(
        Config(
            roi=(0, 0, 10, 10),
            line=DoorLine((0, 5), (10, 5), (5, 0)),
            door_on=100.0,
            door_off=50.0,
            prompts=["juice"],
            hand_label="hand",
        ),
        cfg_file,
    )

    monkeypatch.setattr("fridge_item.stream.iter_frames", lambda src: iter([]))

    created_detectors = []

    def fake_factory(prompts, hand_label):
        detector = MagicMock(return_value=[])
        created_detectors.append((prompts, hand_label, detector))
        return detector

    evaluate_command(
        labels_path=str(labels_file),
        clips_dir=str(clips_dir),
        config_path=str(cfg_file),
        detector_factory=fake_factory,
    )

    assert len(created_detectors) == 2
    assert created_detectors[0][0] == ["juice"]
    assert created_detectors[1][0] == ["juice"]


def test_evaluate_missing_clip_raises_file_not_found(tmp_path: Path):
    labels_file = tmp_path / "labels.csv"
    labels_file.write_text("nonexistent.mp4,PUT,juice\n")

    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()

    cfg_file = tmp_path / "config.json"
    save(
        Config(
            roi=(0, 0, 10, 10),
            line=DoorLine((0, 5), (10, 5), (5, 0)),
            door_on=100.0,
            door_off=50.0,
        ),
        cfg_file,
    )

    with pytest.raises(FileNotFoundError) as exc_info:
        evaluate_command(
            labels_path=str(labels_file),
            clips_dir=str(clips_dir),
            config_path=str(cfg_file),
            detector_factory=lambda prompts, hand_label: MagicMock(),
        )

    assert "nonexistent.mp4" in str(exc_info.value)
