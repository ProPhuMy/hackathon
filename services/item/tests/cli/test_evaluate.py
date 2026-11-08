from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.cli.evaluate import evaluate_command, score
from src.config import Config, save
from src.core.geometry import DoorLine


def write_eval_inputs(tmp_path: Path, labels: str, clips: list[str], prompts: list[str] | None) -> tuple[str, str, str]:
    """labels.csv, clips/ with empty clip files, and config.json; returns their paths as str."""
    labels_file = tmp_path / "labels.csv"
    labels_file.write_text(labels)
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    for clip in clips:
        (clips_dir / clip).touch()
    cfg_file = tmp_path / "config.json"
    extra = {} if prompts is None else {"prompts": prompts, "hand_label": "hand"}
    save(
        Config(roi=(0, 0, 10, 10), line=DoorLine((0, 5), (10, 5), (5, 0)), door_on=100.0, door_off=50.0, **extra),
        cfg_file,
    )
    return str(labels_file), str(clips_dir), str(cfg_file)


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
    labels, clips, cfg = write_eval_inputs(
        tmp_path, "clip1.mp4,PUT,juice\nclip2.mp4,TAKE,juice\n", ["clip1.mp4", "clip2.mp4"], ["juice"]
    )
    monkeypatch.setattr("src.cli.evaluate.iter_frames", lambda src: iter([]))

    created_detectors = []

    def fake_factory(prompts, hand_label):
        detector = MagicMock(return_value=[])
        created_detectors.append((prompts, hand_label, detector))
        return detector

    evaluate_command(labels_path=labels, clips_dir=clips, config_path=cfg, detector_factory=fake_factory)

    assert len(created_detectors) == 2
    assert created_detectors[0][0] == ["juice"]
    assert created_detectors[1][0] == ["juice"]


def test_evaluate_missing_clip_raises_file_not_found(tmp_path: Path):
    labels, clips, cfg = write_eval_inputs(tmp_path, "nonexistent.mp4,PUT,juice\n", [], None)

    with pytest.raises(FileNotFoundError) as exc_info:
        evaluate_command(
            labels_path=labels,
            clips_dir=clips,
            config_path=cfg,
            detector_factory=lambda prompts, hand_label: MagicMock(),
        )

    assert "nonexistent.mp4" in str(exc_info.value)


def test_evaluate_with_embed_instantiates_embedder_once(tmp_path: Path, monkeypatch, pipelines_built):
    labels, clips, cfg = write_eval_inputs(
        tmp_path, "clip1.mp4,PUT,juice\nclip2.mp4,TAKE,juice\n", ["clip1.mp4", "clip2.mp4"], ["juice"]
    )
    monkeypatch.setattr("src.cli.evaluate.iter_frames", lambda src: iter([]))
    mock_embedder_instance = MagicMock()
    mock_embedder_cls = MagicMock(return_value=mock_embedder_instance)
    monkeypatch.setattr("src.vision.embed.Embedder", mock_embedder_cls)

    evaluate_command(
        labels_path=labels,
        clips_dir=clips,
        config_path=cfg,
        detector_factory=lambda prompts, hand_label: MagicMock(),
        embed=True,
    )

    mock_embedder_cls.assert_called_once()
    assert len(pipelines_built) == 2
    assert pipelines_built[0].embed is mock_embedder_instance
    assert pipelines_built[1].embed is mock_embedder_instance


def test_evaluate_with_holding_mask_instantiates_segmenter_once(tmp_path: Path, monkeypatch, pipelines_built):
    labels, clips, cfg = write_eval_inputs(
        tmp_path, "clip1.mp4,PUT,juice\nclip2.mp4,TAKE,juice\n", ["clip1.mp4", "clip2.mp4"], ["juice"]
    )
    monkeypatch.setattr("src.cli.evaluate.iter_frames", lambda src: iter([]))
    mock_segmenter_instance = MagicMock()
    mock_segmenter_cls = MagicMock(return_value=mock_segmenter_instance)
    monkeypatch.setattr("src.vision.segment.Segmenter", mock_segmenter_cls)

    evaluate_command(
        labels_path=labels,
        clips_dir=clips,
        config_path=cfg,
        detector_factory=lambda prompts, hand_label: MagicMock(),
        holding="mask",
    )

    mock_segmenter_cls.assert_called_once()
    assert len(pipelines_built) == 2
    assert pipelines_built[0].segment is mock_segmenter_instance
    assert pipelines_built[1].segment is mock_segmenter_instance


def test_evaluate_command_selects_gdino(tmp_path: Path, monkeypatch):
    labels, clips, cfg = write_eval_inputs(tmp_path, "clip1.mp4,PUT,milk\n", ["clip1.mp4"], ["milk"])
    monkeypatch.setattr("src.cli.evaluate.iter_frames", lambda src: iter([]))
    mock_gdino = MagicMock()
    mock_gdino.return_value = []
    mock_factory = MagicMock(return_value=mock_gdino)

    with patch("src.vision.gdino.GDinoDetector", mock_factory):
        evaluate_command(labels_path=labels, clips_dir=clips, config_path=cfg, detector="gdino")

    mock_factory.assert_called_once_with(["milk"], "hand")
