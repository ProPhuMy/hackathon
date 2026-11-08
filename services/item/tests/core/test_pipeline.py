"""ItemPipeline frame loop: door gating, sessions, flush on close, embed/segment hooks."""
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
from jsonschema import Draft202012Validator

from conftest import SCHEMA, ScriptedDetector, hand, item
from src.core.gallery import ItemGallery
from src.core.pipeline import ItemPipeline


def test_put_then_take_events(tmp_path: Path, cfg):
    gallery = ItemGallery(tmp_path / "gallery.json")

    # Scripted calls for detector:
    # Session 1 (calls 0..3): PUT bottle
    # Session 2 (calls 4..6): TAKE bottle
    script = [
        # Call 0: Hand outside holding bottle
        [hand(1, 100.0, 50.0, conf=0.9), item(10, 100.0, 50.0, label="bottle", conf=0.8)],
        # Call 1: Hand inside holding bottle (crossing in)
        [hand(1, 100.0, 150.0, conf=0.9), item(10, 100.0, 150.0, label="bottle", conf=0.8)],
        # Call 2: Hand inside empty
        [hand(1, 100.0, 150.0, conf=0.9)],
        # Call 3: Hand outside empty (crossing out -> PUT completed)
        [hand(1, 100.0, 50.0, conf=0.9)],
        # Call 4: Hand outside empty
        [hand(2, 100.0, 50.0, conf=0.95)],
        # Call 5: Hand inside empty (crossing in)
        [hand(2, 100.0, 150.0, conf=0.95)],
        # Call 6: Hand outside holding bottle (crossing out -> TAKE completed)
        [hand(2, 100.0, 50.0, conf=0.95), item(20, 100.0, 50.0, label="bottle", conf=0.85)],
    ]
    detector = ScriptedDetector(script)
    pipeline = ItemPipeline(cfg=cfg, detect=detector, gallery=gallery)

    dark_frame = np.full((300, 300, 3), 10, dtype=np.uint8)
    bright_frame = np.full((300, 300, 3), 200, dtype=np.uint8)

    all_events = []

    # Frame 0: Dark (door closed)
    all_events.extend(pipeline.process(dark_frame, ts="2026-11-07T20:00:00.000Z"))
    assert detector.call_count == 0

    # Session 1: Door open
    all_events.extend(pipeline.process(bright_frame, ts="2026-11-07T20:00:01.000Z"))
    all_events.extend(pipeline.process(bright_frame, ts="2026-11-07T20:00:02.000Z"))
    all_events.extend(pipeline.process(bright_frame, ts="2026-11-07T20:00:03.000Z"))
    all_events.extend(pipeline.process(bright_frame, ts="2026-11-07T20:00:04.000Z"))

    # Door closes
    all_events.extend(pipeline.process(dark_frame, ts="2026-11-07T20:00:05.000Z"))
    assert detector.call_count == 4

    # Session 2: Door opens again
    all_events.extend(pipeline.process(bright_frame, ts="2026-11-07T20:00:06.000Z"))
    all_events.extend(pipeline.process(bright_frame, ts="2026-11-07T20:00:07.000Z"))
    all_events.extend(pipeline.process(bright_frame, ts="2026-11-07T20:00:08.000Z"))

    # Door closes
    all_events.extend(pipeline.process(dark_frame, ts="2026-11-07T20:00:09.000Z"))
    assert detector.call_count == 7

    assert len(all_events) == 2
    put_event, take_event = all_events

    validator = Draft202012Validator(SCHEMA)
    validator.validate(put_event)
    validator.validate(take_event)

    assert put_event["type"] == "PUT"
    assert take_event["type"] == "TAKE"
    assert put_event["item_label"] == "bottle"
    assert take_event["item_label"] == "bottle"
    assert put_event["item_id"] == take_event["item_id"]
    assert 0.0 <= put_event["confidence"] <= 1.0
    assert 0.0 <= take_event["confidence"] <= 1.0


def test_door_closed_does_not_call_detector(tmp_path: Path, cfg):
    gallery = ItemGallery(tmp_path / "gallery.json")
    detector = ScriptedDetector([])
    pipeline = ItemPipeline(cfg=cfg, detect=detector, gallery=gallery)

    dark_frame = np.full((300, 300, 3), 10, dtype=np.uint8)
    events = pipeline.process(dark_frame, ts="2026-11-07T20:00:00.000Z")

    assert events == []
    assert detector.call_count == 0
    assert pipeline.tracks == []
    assert pipeline.door_open is False


def test_door_close_flushes_unpaired_trip(tmp_path: Path, cfg):
    gallery = ItemGallery(tmp_path / "gallery.json")
    script = [
        [hand(1, 100.0, 50.0), item(10, 100.0, 50.0, label="can", conf=0.8)],
        [hand(1, 100.0, 150.0), item(10, 100.0, 150.0, label="can", conf=0.8)],
    ]
    detector = ScriptedDetector(script)
    pipeline = ItemPipeline(cfg=cfg, detect=detector, gallery=gallery)

    bright_frame = np.full((300, 300, 3), 200, dtype=np.uint8)
    dark_frame = np.full((300, 300, 3), 10, dtype=np.uint8)

    ev1 = pipeline.process(bright_frame, ts="2026-11-07T20:00:01.000Z")
    assert ev1 == []
    ev2 = pipeline.process(bright_frame, ts="2026-11-07T20:00:02.000Z")
    assert ev2 == []

    # Door closes before hand leaves: session.close() emits PUT
    ev3 = pipeline.process(dark_frame, ts="2026-11-07T20:00:03.000Z")
    assert len(ev3) == 1
    assert ev3[0]["type"] == "PUT"
    assert ev3[0]["item_label"] == "can"
    Draft202012Validator(SCHEMA).validate(ev3[0])


def test_take_unknown_item(tmp_path: Path, cfg):
    gallery = ItemGallery(tmp_path / "gallery.json")  # empty gallery
    script = [
        [hand(1, 100.0, 50.0)],
        [hand(1, 100.0, 150.0)],
        [hand(1, 100.0, 50.0), item(10, 100.0, 50.0, label="unknown_fruit", conf=0.9)],
    ]
    detector = ScriptedDetector(script)
    pipeline = ItemPipeline(cfg=cfg, detect=detector, gallery=gallery)

    bright_frame = np.full((300, 300, 3), 200, dtype=np.uint8)
    pipeline.process(bright_frame, ts="2026-11-07T20:00:01.000Z")
    pipeline.process(bright_frame, ts="2026-11-07T20:00:02.000Z")
    events = pipeline.process(bright_frame, ts="2026-11-07T20:00:03.000Z")

    assert len(events) == 1
    ev = events[0]
    Draft202012Validator(SCHEMA).validate(ev)
    assert ev["type"] == "TAKE"
    assert ev["item_id"] == "unknown"
    assert ev["confidence"] == 0.1


def test_embed_called_when_provided(tmp_path: Path, cfg):
    gallery = ItemGallery(tmp_path / "gallery.json")
    mock_embed = MagicMock(return_value=np.array([0.1, 0.2, 0.3]))

    # Hand enters with item
    script = [
        [hand(1, 100.0, 50.0), item(10, 100.0, 50.0, label="snack", conf=0.85)],
        [hand(1, 100.0, 150.0), item(10, 100.0, 150.0, label="snack", conf=0.85)],
    ]
    detector = ScriptedDetector(script)
    pipeline = ItemPipeline(cfg=cfg, detect=detector, gallery=gallery, embed=mock_embed)

    bright_frame = np.full((300, 300, 3), 200, dtype=np.uint8)
    dark_frame = np.full((300, 300, 3), 10, dtype=np.uint8)

    pipeline.process(bright_frame, ts="2026-11-07T20:00:01.000Z")
    pipeline.process(bright_frame, ts="2026-11-07T20:00:02.000Z")
    events = pipeline.process(dark_frame, ts="2026-11-07T20:00:03.000Z")

    assert len(events) == 1
    assert mock_embed.call_count == 1
    # Check that embed argument was a numpy array (the crop)
    crop_arg = mock_embed.call_args[0][0]
    assert isinstance(crop_arg, np.ndarray)
    assert crop_arg.size > 0


def test_pipeline_segment_called_only_when_door_open(tmp_path: Path, cfg):
    gallery = ItemGallery(tmp_path / "gallery.json")

    hand_tr = hand(1, 100.0, 50.0)
    item_tr = item(10, 100.0, 50.0, label="milk")
    script = [
        [hand_tr, item_tr],
    ]
    detector = ScriptedDetector(script)

    fake_mask = np.zeros((300, 300), dtype=bool)
    mock_segment = MagicMock(return_value={10: fake_mask})

    pipeline = ItemPipeline(
        cfg=cfg,
        detect=detector,
        gallery=gallery,
        segment=mock_segment,
    )

    dark_frame = np.full((300, 300, 3), 10, dtype=np.uint8)
    bright_frame = np.full((300, 300, 3), 200, dtype=np.uint8)

    # 1. Door closed -> segment not called
    pipeline.process(dark_frame, ts="2026-11-07T20:00:00.000Z")
    assert mock_segment.call_count == 0

    # 2. Door open -> segment called once with frame and ONLY item tracks
    pipeline.process(bright_frame, ts="2026-11-07T20:00:01.000Z")
    assert mock_segment.call_count == 1
    call_args, _ = mock_segment.call_args
    assert np.array_equal(call_args[0], bright_frame)
    assert call_args[1] == [item_tr]

    # 3. Door closed -> segment not called again
    pipeline.process(dark_frame, ts="2026-11-07T20:00:02.000Z")
    assert mock_segment.call_count == 1


def test_close_flushes_open_session(tmp_path: Path, cfg):
    gallery = ItemGallery(tmp_path / "gallery.json")
    script = [
        [hand(1, 100.0, 50.0), item(10, 100.0, 50.0, label="yogurt", conf=0.88)],
        [hand(1, 100.0, 150.0), item(10, 100.0, 150.0, label="yogurt", conf=0.88)],
    ]
    detector = ScriptedDetector(script)
    pipeline = ItemPipeline(cfg=cfg, detect=detector, gallery=gallery)

    bright_frame = np.full((300, 300, 3), 200, dtype=np.uint8)
    pipeline.process(bright_frame, ts="2026-11-07T20:00:01.000Z")
    pipeline.process(bright_frame, ts="2026-11-07T20:00:02.000Z")

    # Stream ends while door is still open
    flushed = pipeline.close()
    assert len(flushed) == 1
    ev = flushed[0]
    assert ev["type"] == "PUT"
    assert ev["item_label"] == "yogurt"
    Draft202012Validator(SCHEMA).validate(ev)
    assert pipeline.session is None


def test_close_with_no_open_session(tmp_path: Path, cfg):
    gallery = ItemGallery(tmp_path / "gallery.json")
    pipeline = ItemPipeline(cfg=cfg, detect=ScriptedDetector([]), gallery=gallery)

    assert pipeline.close() == []
