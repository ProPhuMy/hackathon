"""`run` command: model wiring, event printing/publishing, debug video, latency log, shutdown order."""
import json
import sys
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from conftest import SCHEMA, ScriptedDetector, hand, item
from src.cli.run import run_command
from src.config import save
from src.events import item_event

TS = "2026-11-07T20:00:01.000Z"


def stub_run(monkeypatch, frames, events=None, detector=None):
    """Fake the YOLOE detector and the frame source; if `events` is given every process() returns it."""
    monkeypatch.setattr("src.vision.detect.Detector", detector or MagicMock())
    monkeypatch.setattr("src.cli.run.iter_frames", lambda src: iter(frames))
    if events is not None:
        monkeypatch.setattr("src.core.pipeline.ItemPipeline.process", lambda self, f, ts: events)


def fake_kafka(monkeypatch, producer: MagicMock) -> MagicMock:
    """Install a fake confluent_kafka whose Producer() returns `producer`; returns the Producer class mock."""
    producer_cls = MagicMock(return_value=producer)
    monkeypatch.setitem(sys.modules, "confluent_kafka", MagicMock(Producer=producer_cls))
    return producer_cls


def run(cfg_file: Path, tmp_path: Path, **kwargs) -> None:
    run_command(
        source="dummy_src",
        config_path=str(cfg_file),
        gallery_path=str(tmp_path / "gallery.json"),
        **kwargs,
    )


def test_cli_run_command_with_holding_mask(tmp_path: Path, monkeypatch, cfg_file, pipelines_built):
    test_ev = item_event("PUT", "item_123", "bottle", 0.9, ts=TS)
    frame = np.full((300, 300, 3), 10, dtype=np.uint8)

    mock_segmenter_instance = MagicMock()
    mock_segmenter_cls = MagicMock(return_value=mock_segmenter_instance)
    monkeypatch.setattr("src.vision.segment.Segmenter", mock_segmenter_cls)

    stub_run(monkeypatch, [(frame, TS)], events=[test_ev])

    run(cfg_file, tmp_path, dry_run=True, holding="mask")

    mock_segmenter_cls.assert_called_once()
    assert len(pipelines_built) == 1
    assert pipelines_built[0].segment is mock_segmenter_instance


def test_cli_run_command_with_embed(tmp_path: Path, monkeypatch, cfg_file):
    test_ev = item_event("PUT", "item_123", "bottle", 0.9, ts=TS)
    frame = np.full((300, 300, 3), 10, dtype=np.uint8)

    mock_embedder_cls = MagicMock(return_value=MagicMock())
    monkeypatch.setattr("src.vision.embed.Embedder", mock_embedder_cls)
    stub_run(monkeypatch, [(frame, TS)], events=[test_ev])

    run(cfg_file, tmp_path, dry_run=True, embed=True)

    mock_embedder_cls.assert_called_once()


def test_cli_run_command_dry_run(tmp_path: Path, monkeypatch, capsys, cfg_file):
    test_ev = item_event("PUT", "item_123", "bottle", 0.9, ts=TS)
    frame = np.full((300, 300, 3), 10, dtype=np.uint8)
    stub_run(monkeypatch, [(frame, TS)], events=[test_ev])

    run(cfg_file, tmp_path, dry_run=True)

    captured = capsys.readouterr().out
    assert json.loads(captured.strip()) == test_ev


def test_cli_run_command_kafka_publish(tmp_path: Path, monkeypatch, cfg_file):
    test_ev = item_event("PUT", "item_456", "can", 0.88, ts=TS)
    frame = np.full((300, 300, 3), 10, dtype=np.uint8)
    stub_run(monkeypatch, [(frame, TS)], events=[test_ev])
    mock_producer_instance = MagicMock()
    mock_producer_cls = fake_kafka(monkeypatch, mock_producer_instance)

    run(cfg_file, tmp_path, broker="custom_broker:19092", dry_run=False)

    mock_producer_cls.assert_called_once_with({"bootstrap.servers": "custom_broker:19092"})
    mock_producer_instance.produce.assert_called_once_with(
        "item.event",
        key=test_ev["event_id"],
        value=json.dumps(test_ev, ensure_ascii=False),
        on_delivery=ANY,
    )
    mock_producer_instance.poll.assert_called_once_with(0)
    mock_producer_instance.flush.assert_called_once_with(10)


def test_cli_run_command_debug_video(tmp_path: Path, monkeypatch, cfg_file):
    frame = np.full((100, 100, 3), 10, dtype=np.uint8)
    stub_run(monkeypatch, [(frame, TS)], events=[])
    mock_writer = MagicMock()
    monkeypatch.setattr("cv2.VideoWriter", MagicMock(return_value=mock_writer))

    run(cfg_file, tmp_path, dry_run=True, debug_video=str(tmp_path / "debug.mp4"))

    mock_writer.write.assert_called_once()
    mock_writer.release.assert_called_once()


def test_cli_run_latency_print(tmp_path: Path, monkeypatch, capsys, cfg_file):
    frame = np.full((50, 50, 3), 10, dtype=np.uint8)
    frames = [(frame, f"2026-11-07T20:00:{i:02d}.000Z") for i in range(100)]
    stub_run(monkeypatch, frames, events=[])

    run(cfg_file, tmp_path, dry_run=True)

    out = capsys.readouterr().out
    assert "Frame 100: detector p50=" in out
    assert "process p50=" in out


def test_run_command_selects_gdino(tmp_path: Path, monkeypatch, cfg):
    cfg.prompts = ["milk"]
    cfg_file = tmp_path / "config.json"
    save(cfg, cfg_file)
    monkeypatch.setattr("src.cli.run.iter_frames", lambda src: iter([]))
    mock_gdino_cls = MagicMock(return_value=MagicMock())

    with patch("src.vision.gdino.GDinoDetector", mock_gdino_cls):
        run(cfg_file, tmp_path, dry_run=True, detector="gdino")

    mock_gdino_cls.assert_called_once_with(prompts=["milk"], hand_label="hand")


def test_cli_run_command_flushes_on_shutdown(tmp_path: Path, monkeypatch, capsys, cfg_file):
    script = [
        [hand(1, 100.0, 50.0), item(10, 100.0, 50.0, label="juice", conf=0.85)],
        [hand(1, 100.0, 150.0), item(10, 100.0, 150.0, label="juice", conf=0.85)],
    ]
    detector = ScriptedDetector(script)
    bright_frame = np.full((300, 300, 3), 200, dtype=np.uint8)
    frames = [
        (bright_frame, "2026-11-07T20:00:01.000Z"),
        (bright_frame, "2026-11-07T20:00:02.000Z"),
    ]
    stub_run(monkeypatch, frames, detector=lambda *args, **kwargs: detector)

    run(cfg_file, tmp_path, dry_run=True)

    out = capsys.readouterr().out.strip()
    ev = json.loads(out)
    assert ev["type"] == "PUT"
    assert ev["item_label"] == "juice"
    Draft202012Validator(SCHEMA).validate(ev)


def test_shutdown_cleanup_on_flush_error(tmp_path: Path, monkeypatch, cfg_file):
    frame = np.full((100, 100, 3), 10, dtype=np.uint8)
    stub_run(monkeypatch, [(frame, TS)], events=[])
    flushed_ev = item_event("PUT", "item_err", "coke", 0.9, ts="2026-11-07T20:00:02.000Z")
    monkeypatch.setattr("src.core.pipeline.ItemPipeline.close", lambda self: [flushed_ev])

    mock_producer_instance = MagicMock()
    mock_producer_instance.produce.side_effect = RuntimeError("Kafka buffer full")
    fake_kafka(monkeypatch, mock_producer_instance)
    mock_writer = MagicMock()
    monkeypatch.setattr("cv2.VideoWriter", MagicMock(return_value=mock_writer))

    with pytest.raises(RuntimeError, match="Kafka buffer full"):
        run(
            cfg_file,
            tmp_path,
            broker="localhost:19092",
            dry_run=False,
            debug_video=str(tmp_path / "out.mp4"),
        )

    mock_producer_instance.flush.assert_called_once_with(10)
    mock_writer.release.assert_called_once()


def test_shutdown_order_and_flush_warning_and_delivery_callback(tmp_path: Path, monkeypatch, capsys, cfg_file):
    frame = np.full((100, 100, 3), 10, dtype=np.uint8)
    ev = item_event("PUT", "item-1", "coke", 0.9, ts=TS)
    stub_run(monkeypatch, [(frame, TS)], events=[ev])
    monkeypatch.setattr("src.core.pipeline.ItemPipeline.close", lambda self: [])

    call_order = []
    mock_writer = MagicMock()
    mock_writer.release.side_effect = lambda: call_order.append("release")
    monkeypatch.setattr("cv2.VideoWriter", MagicMock(return_value=mock_writer))

    mock_producer_instance = MagicMock()
    mock_producer_instance.flush.side_effect = lambda timeout=None: (call_order.append(f"flush({timeout})"), 2)[1]
    fake_kafka(monkeypatch, mock_producer_instance)

    run(
        cfg_file,
        tmp_path,
        broker="localhost:19092",
        dry_run=False,
        debug_video=str(tmp_path / "out.mp4"),
    )

    # 1. Writer release before producer flush
    assert call_order == ["release", "flush(10)"]
    mock_producer_instance.flush.assert_called_once_with(10)
    mock_writer.release.assert_called_once()

    # 2. Warning mentioning 2
    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    assert "2" in combined_output
    assert "warning" in combined_output.lower()

    # 3. on_delivery callback passed to produce
    produce_calls = mock_producer_instance.produce.call_args_list
    assert len(produce_calls) >= 1
    on_delivery_cb = produce_calls[0].kwargs.get("on_delivery")
    assert callable(on_delivery_cb)

    # Test delivery callback prints "kafka delivery failed: <err>" when err is set
    capsys.readouterr()
    on_delivery_cb("broker disconnected", None)
    cb_out = capsys.readouterr().out
    assert "kafka delivery failed: broker disconnected" in cb_out
