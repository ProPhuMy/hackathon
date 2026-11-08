"""--shelf-check: before/after shelf diff as a second opinion when the hand logic misses an event."""
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from conftest import SCHEMA, ScriptedDetector, hand, item
from src.core.gallery import ItemGallery
from src.core.pipeline import ItemPipeline


def test_pipeline_shelf_check_put_when_hand_logic_silent(tmp_path: Path, cfg):

    # Frame 1: door open, coke on shelf, no hand (before snapshot)
    # Frame 2: door open, hand present inside (no line crossing), last hand ts
    # Frame 3: door open, coke and juice on shelf, no hand (after snapshot)
    script = [
        [item(10, 50.0, 150.0, label="coke")],
        [hand(1, 50.0, 150.0), item(10, 50.0, 150.0, label="coke"), item(20, 150.0, 150.0, label="juice")],
        [item(10, 50.0, 150.0, label="coke"), item(20, 150.0, 150.0, label="juice")],
    ]

    dark_frame = np.full((300, 300, 3), 10, dtype=np.uint8)
    bright_frame = np.full((300, 300, 3), 200, dtype=np.uint8)

    # 1. With shelf_check=True: emits one PUT for juice with conf 0.3 and ts of last hand frame
    gallery1 = ItemGallery(tmp_path / "gallery1.json")
    pipeline_on = ItemPipeline(
        cfg=cfg,
        detect=ScriptedDetector(script),
        gallery=gallery1,
        shelf_check=True,
    )
    events_on = []
    events_on.extend(pipeline_on.process(bright_frame, ts="2026-11-07T20:00:01.000Z"))
    events_on.extend(pipeline_on.process(bright_frame, ts="2026-11-07T20:00:02.000Z"))
    events_on.extend(pipeline_on.process(bright_frame, ts="2026-11-07T20:00:03.000Z"))
    events_on.extend(pipeline_on.process(dark_frame, ts="2026-11-07T20:00:04.000Z"))

    assert len(events_on) == 1
    assert events_on[0]["type"] == "PUT"
    assert events_on[0]["item_label"] == "juice"
    assert events_on[0]["confidence"] == pytest.approx(0.3)
    assert events_on[0]["ts"] == "2026-11-07T20:00:02.000Z"
    Draft202012Validator(SCHEMA).validate(events_on[0])

    # 2. With shelf_check=False: no event emitted
    gallery2 = ItemGallery(tmp_path / "gallery2.json")
    pipeline_off = ItemPipeline(
        cfg=cfg,
        detect=ScriptedDetector(script),
        gallery=gallery2,
        shelf_check=False,
    )
    events_off = []
    events_off.extend(pipeline_off.process(bright_frame, ts="2026-11-07T20:00:01.000Z"))
    events_off.extend(pipeline_off.process(bright_frame, ts="2026-11-07T20:00:02.000Z"))
    events_off.extend(pipeline_off.process(bright_frame, ts="2026-11-07T20:00:03.000Z"))
    events_off.extend(pipeline_off.process(dark_frame, ts="2026-11-07T20:00:04.000Z"))

    assert events_off == []


def test_pipeline_shelf_check_no_duplicate_put(tmp_path: Path, cfg):
    gallery = ItemGallery(tmp_path / "gallery.json")

    # Hand logic emits a PUT for the bottle; the shelf diff then sees the same bottle added
    # and must not emit it again.
    # Call 0: door open, no hand, no items -> before = []
    # Calls 1..4: hand carries the bottle in and leaves empty (crossing out -> PUT)
    # Call 5: door open, no hand, bottle on shelf -> after = [bottle]
    script_with_before = [
        [],
        [hand(1, 100.0, 50.0), item(10, 100.0, 50.0, label="bottle")],
        [hand(1, 100.0, 150.0), item(10, 100.0, 150.0, label="bottle")],
        [hand(1, 100.0, 150.0)],
        [hand(1, 100.0, 50.0)],
        [item(10, 100.0, 150.0, label="bottle")],
    ]

    dark_frame = np.full((300, 300, 3), 10, dtype=np.uint8)
    bright_frame = np.full((300, 300, 3), 200, dtype=np.uint8)

    pipeline = ItemPipeline(
        cfg=cfg,
        detect=ScriptedDetector(script_with_before),
        gallery=gallery,
        shelf_check=True,
    )

    all_events = []
    for i in range(len(script_with_before)):
        evs = pipeline.process(bright_frame, ts=f"2026-11-07T20:00:0{i}.000Z")
        all_events.extend(evs)

    # Door closes: shelf diff runs, sees bottle added, but PUT was already emitted!
    close_events = pipeline.process(dark_frame, ts="2026-11-07T20:00:10.000Z")
    all_events.extend(close_events)

    # Exactly one PUT was emitted during the session, and no duplicate PUT on close
    assert len(all_events) == 1
    assert all_events[0]["type"] == "PUT"
    assert all_events[0]["item_label"] == "bottle"


def test_pipeline_shelf_check_take_fallback_last_open_ts(tmp_path: Path, cfg):
    gallery = ItemGallery(tmp_path / "gallery.json")
    gallery.add("juice")

    # No hand ever seen in this session
    script = [
        [item(10, 50.0, 150.0, label="juice")],  # before snapshot
        [],  # after snapshot (empty shelf)
    ]

    dark_frame = np.full((300, 300, 3), 10, dtype=np.uint8)
    bright_frame = np.full((300, 300, 3), 200, dtype=np.uint8)

    pipeline = ItemPipeline(
        cfg=cfg,
        detect=ScriptedDetector(script),
        gallery=gallery,
        shelf_check=True,
    )

    events = []
    events.extend(pipeline.process(bright_frame, ts="2026-11-07T20:00:01.000Z"))
    events.extend(pipeline.process(bright_frame, ts="2026-11-07T20:00:02.000Z"))
    events.extend(pipeline.process(dark_frame, ts="2026-11-07T20:00:03.000Z"))

    assert len(events) == 1
    assert events[0]["type"] == "TAKE"
    assert events[0]["item_label"] == "juice"
    # Because no hand was ever seen, ts is the ts of the last open frame (frame 2)
    assert events[0]["ts"] == "2026-11-07T20:00:02.000Z"
    assert events[0]["confidence"] == pytest.approx(0.3)
    Draft202012Validator(SCHEMA).validate(events[0])


def test_pipeline_close_flushes_shelf_check(tmp_path: Path, cfg):
    gallery = ItemGallery(tmp_path / "gallery.json")

    script = [
        [item(10, 50.0, 150.0, label="coke")],
        [item(10, 50.0, 150.0, label="coke"), item(20, 150.0, 150.0, label="milk")],
    ]

    bright_frame = np.full((300, 300, 3), 200, dtype=np.uint8)

    pipeline = ItemPipeline(
        cfg=cfg,
        detect=ScriptedDetector(script),
        gallery=gallery,
        shelf_check=True,
    )

    pipeline.process(bright_frame, ts="2026-11-07T20:00:01.000Z")
    pipeline.process(bright_frame, ts="2026-11-07T20:00:02.000Z")
    # Stream ends while door is still open: close() called explicitly
    events = pipeline.close()

    assert len(events) == 1
    assert events[0]["type"] == "PUT"
    assert events[0]["item_label"] == "milk"
    assert events[0]["confidence"] == pytest.approx(0.3)
    assert events[0]["ts"] == "2026-11-07T20:00:02.000Z"

    # Calling close() again returns empty and does not repeat
    assert pipeline.close() == []
