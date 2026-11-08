import json
from pathlib import Path
from unittest.mock import MagicMock
from jsonschema import Draft202012Validator
import numpy as np
import pytest

from fridge_item.config import Config
from fridge_item.gallery import ItemGallery
from fridge_item.geometry import Box, DoorLine, Track
from fridge_item.pipeline import ItemPipeline
from fridge_item.session import Trip

SCHEMA = json.loads(
    (Path(__file__).parents[3] / "contracts" / "item.event.schema.json").read_text()
)


@pytest.fixture(autouse=True)
def guard_no_yoloe(monkeypatch):
    """Ensure tests never load or download real models."""
    monkeypatch.setattr("ultralytics.YOLOE", MagicMock())



def hand(id: int, cx: float, cy: float, conf: float = 0.9) -> Track:
    return Track(
        id=id,
        kind="hand",
        box=Box(cx - 10.0, cy - 10.0, cx + 10.0, cy + 10.0),
        conf=conf,
        label="hand",
    )


def item(id: int, cx: float, cy: float, label: str = "bottle", conf: float = 0.85) -> Track:
    return Track(
        id=id,
        kind="item",
        box=Box(cx - 10.0, cy - 10.0, cx + 10.0, cy + 10.0),
        conf=conf,
        label=label,
    )


class ScriptedDetector:
    def __init__(self, script: list[list[Track]]) -> None:
        self.script = script
        self.call_count = 0

    def __call__(self, frame: np.ndarray) -> list[Track]:
        idx = self.call_count
        self.call_count += 1
        if idx < len(self.script):
            return self.script[idx]
        return []


def test_put_then_take_events(tmp_path: Path):
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)
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


def test_door_closed_does_not_call_detector(tmp_path: Path):
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)
    gallery = ItemGallery(tmp_path / "gallery.json")
    detector = ScriptedDetector([])
    pipeline = ItemPipeline(cfg=cfg, detect=detector, gallery=gallery)

    dark_frame = np.full((300, 300, 3), 10, dtype=np.uint8)
    events = pipeline.process(dark_frame, ts="2026-11-07T20:00:00.000Z")

    assert events == []
    assert detector.call_count == 0
    assert pipeline.tracks == []
    assert pipeline.door_open is False


def test_door_close_flushes_unpaired_trip(tmp_path: Path):
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)
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


def test_take_unknown_item(tmp_path: Path):
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)
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


def test_embed_called_when_provided(tmp_path: Path):
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)
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


def test_pipeline_two_takes_resolved_with_take_many(tmp_path: Path):
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)
    gallery = ItemGallery(tmp_path / "gallery.json")

    id1 = gallery.add("bottle", embedding=np.array([1.0, 0.0]))
    id2 = gallery.add("bottle", embedding=np.array([0.0, 1.0]))

    # Hand 1 holding bottle (id 10), Hand 2 holding bottle (id 20)
    # Hand 1 crop gives [0.1, 0.9] (matches id2)
    # Hand 2 crop gives [0.9, 0.1] (matches id1)
    def fake_embed(crop: np.ndarray) -> np.ndarray:
        if crop[0, 0, 0] == 10:
            return np.array([0.1, 0.9])
        return np.array([0.9, 0.1])

    # Script:
    # Frame 0: Hands outside empty
    # Frame 1: Hands inside empty (crossing in)
    # Frame 2: Hands outside holding bottles (crossing out -> 2 TAKEs!)
    frame1 = np.full((300, 300, 3), 200, dtype=np.uint8)
    frame1[40:60, 40:60] = 10  # bottle 10 at y=50, x=50
    frame1[40:60, 140:160] = 20  # bottle 20 at y=50, x=150

    script = [
        # Call 0: Hands outside empty
        [hand(1, 50.0, 50.0), hand(2, 150.0, 50.0)],
        # Call 1: Hands inside empty
        [hand(1, 50.0, 150.0), hand(2, 150.0, 150.0)],
        # Call 2: Hands outside holding items
        [
            hand(1, 50.0, 50.0),
            Track(10, "item", Box(40.0, 40.0, 60.0, 60.0), 0.9, "bottle"),
            hand(2, 150.0, 50.0),
            Track(20, "item", Box(140.0, 40.0, 160.0, 60.0), 0.9, "bottle"),
        ],
    ]
    detector = ScriptedDetector(script)
    pipeline = ItemPipeline(cfg=cfg, detect=detector, gallery=gallery, embed=fake_embed)

    pipeline.process(frame1, ts="2026-11-07T20:00:00.000Z")
    pipeline.process(frame1, ts="2026-11-07T20:00:01.000Z")
    events = pipeline.process(frame1, ts="2026-11-07T20:00:02.000Z")

    assert len(events) == 2
    assert events[0]["type"] == "TAKE"
    assert events[1]["type"] == "TAKE"
    # Hand 1 held bottle 10 (crop pixel 10 -> embedding [0.1, 0.9] -> matches id2)
    assert events[0]["item_id"] == id2
    # Hand 2 held bottle 20 (crop pixel 20 -> embedding [0.9, 0.1] -> matches id1)
    assert events[1]["item_id"] == id1
    assert gallery.items() == {}


def test_two_embedded_takes_plus_one_cropless_take_in_close(tmp_path: Path):
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)
    gallery = ItemGallery(tmp_path / "gallery.json")

    id1 = gallery.add("bottle", embedding=np.array([1.0, 0.0]))
    id2 = gallery.add("bottle", embedding=np.array([0.0, 1.0]))
    id3 = gallery.add("apple")

    def fake_embed(crop: np.ndarray) -> np.ndarray:
        if crop[0, 0, 0] == 10:
            return np.array([0.9, 0.1])
        return np.array([0.1, 0.9])

    pipeline = ItemPipeline(cfg=cfg, detect=lambda f: [], gallery=gallery, embed=fake_embed)

    crop1 = np.full((10, 10, 3), 10, dtype=np.uint8)
    crop2 = np.full((10, 10, 3), 20, dtype=np.uint8)
    t1 = Trip(type="TAKE", item=Track(1, "item", Box(0, 0, 10, 10), 0.9, "bottle"), ts="t1", crop=crop1, confidence=0.9)
    t2 = Trip(type="TAKE", item=Track(2, "item", Box(0, 0, 10, 10), 0.9, "apple"), ts="t2", crop=None, confidence=0.85)
    t3 = Trip(type="TAKE", item=Track(3, "item", Box(0, 0, 10, 10), 0.9, "bottle"), ts="t3", crop=crop2, confidence=0.9)

    events = pipeline._trips_to_events([t1, t2, t3])
    assert len(events) == 3
    assert events[0]["type"] == "TAKE"
    assert events[0]["item_id"] == id1
    assert events[1]["type"] == "TAKE"
    assert events[1]["item_id"] == id3
    assert events[2]["type"] == "TAKE"
    assert events[2]["item_id"] == id2
    assert gallery.items() == {}


def test_put_then_take_in_one_call_matches_just_put_item(tmp_path: Path):
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)
    gallery = ItemGallery(tmp_path / "gallery.json")

    def fake_embed(crop: np.ndarray) -> np.ndarray:
        return np.array([1.0, 0.0])

    pipeline = ItemPipeline(cfg=cfg, detect=lambda f: [], gallery=gallery, embed=fake_embed)

    crop = np.ones((10, 10, 3), dtype=np.uint8)
    t_put = Trip(type="PUT", item=Track(1, "item", Box(0, 0, 10, 10), 0.9, "soda"), ts="t1", crop=crop, confidence=0.9)
    t_take = Trip(type="TAKE", item=Track(2, "item", Box(0, 0, 10, 10), 0.9, "soda"), ts="t2", crop=crop, confidence=0.9)

    events = pipeline._trips_to_events([t_put, t_take])
    assert len(events) == 2
    assert events[0]["type"] == "PUT"
    assert events[1]["type"] == "TAKE"
    assert events[1]["item_id"] == events[0]["item_id"]
    assert gallery.items() == {}


def test_take_put_take_ordering_resolves_put_first(tmp_path: Path):
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)
    gallery = ItemGallery(tmp_path / "gallery.json")
    id_a = gallery.add("snack", embedding=np.array([0.0, 1.0]))

    def fake_embed(crop: np.ndarray) -> np.ndarray:
        if crop[0, 0, 0] == 1:
            return np.array([0.0, 1.0])
        return np.array([1.0, 0.0])

    pipeline = ItemPipeline(cfg=cfg, detect=lambda f: [], gallery=gallery, embed=fake_embed)

    crop_a = np.full((10, 10, 3), 1, dtype=np.uint8)
    crop_b = np.full((10, 10, 3), 2, dtype=np.uint8)

    t1 = Trip(type="TAKE", item=Track(1, "item", Box(0, 0, 10, 10), 0.9, "snack"), ts="t1", crop=crop_a, confidence=0.9)
    t2 = Trip(type="PUT", item=Track(2, "item", Box(0, 0, 10, 10), 0.9, "snack"), ts="t2", crop=crop_b, confidence=0.9)
    t3 = Trip(type="TAKE", item=Track(3, "item", Box(0, 0, 10, 10), 0.9, "snack"), ts="t3", crop=crop_b, confidence=0.9)

    events = pipeline._trips_to_events([t1, t2, t3])
    assert len(events) == 3
    assert events[0]["type"] == "TAKE"
    assert events[0]["item_id"] == id_a
    assert events[1]["type"] == "PUT"
    assert events[2]["type"] == "TAKE"
    assert events[2]["item_id"] == events[1]["item_id"]
    assert gallery.items() == {}




def test_cli_parse_args():
    from fridge_item.__main__ import parse_args

    args = parse_args(["run", "--source", "test.mp4", "--dry-run"])
    assert args.subcommand == "run"
    assert args.source == "test.mp4"
    assert args.config == "config.json"
    assert args.gallery == "data/gallery.json"
    assert args.broker == "localhost:19092"
    assert args.dry_run is True
    assert args.debug_video is None
    assert args.embed is False
    assert args.holding == "box"

    args2 = parse_args(
        [
            "run",
            "--source",
            "http://192.168.1.10:8080/video",
            "--config",
            "custom_cfg.json",
            "--gallery",
            "custom_gallery.json",
            "--broker",
            "10.0.0.1:9092",
            "--debug-video",
            "out.mp4",
            "--embed",
            "--holding",
            "mask",
        ]
    )
    assert args2.source == "http://192.168.1.10:8080/video"
    assert args2.config == "custom_cfg.json"
    assert args2.gallery == "custom_gallery.json"
    assert args2.broker == "10.0.0.1:9092"
    assert args2.dry_run is False
    assert args2.debug_video == "out.mp4"
    assert args2.embed is True
    assert args2.holding == "mask"

    args_eval = parse_args(["evaluate", "--embed"])
    assert args_eval.subcommand == "evaluate"
    assert args_eval.embed is True
    assert args_eval.holding == "box"

    args_eval2 = parse_args(["evaluate", "--holding", "mask"])
    assert args_eval2.subcommand == "evaluate"
    assert args_eval2.holding == "mask"


def test_cli_run_command_with_holding_mask(tmp_path: Path, monkeypatch, capsys):
    from fridge_item.__main__ import run_command
    from fridge_item.config import Config, save
    from fridge_item.events import item_event

    cfg_file = tmp_path / "cfg.json"
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    save(Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0), cfg_file)

    test_ev = item_event("PUT", "item_123", "bottle", 0.9, ts="2026-11-07T20:00:01.000Z")
    frame = np.full((300, 300, 3), 10, dtype=np.uint8)

    mock_segmenter_instance = MagicMock()
    mock_segmenter_cls = MagicMock(return_value=mock_segmenter_instance)
    monkeypatch.setattr("fridge_item.segment.Segmenter", mock_segmenter_cls)

    pipelines_built = []
    from fridge_item.pipeline import ItemPipeline
    original_init = ItemPipeline.__init__

    def spy_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        pipelines_built.append(self)

    monkeypatch.setattr("fridge_item.pipeline.ItemPipeline.__init__", spy_init)

    monkeypatch.setattr("fridge_item.detect.Detector", MagicMock())
    monkeypatch.setattr(
        "fridge_item.__main__.iter_frames",
        lambda src: [(frame, "2026-11-07T20:00:01.000Z")],
    )
    monkeypatch.setattr(
        "fridge_item.pipeline.ItemPipeline.process",
        lambda self, f, ts: [test_ev],
    )

    run_command(
        source="dummy_src",
        config_path=str(cfg_file),
        gallery_path=str(tmp_path / "gallery.json"),
        dry_run=True,
        holding="mask",
    )

    mock_segmenter_cls.assert_called_once()
    assert len(pipelines_built) == 1
    assert pipelines_built[0].segment is mock_segmenter_instance



def test_cli_run_command_with_embed(tmp_path: Path, monkeypatch, capsys):
    from fridge_item.__main__ import run_command
    from fridge_item.config import Config, save
    from fridge_item.events import item_event

    cfg_file = tmp_path / "cfg.json"
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    save(Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0), cfg_file)

    test_ev = item_event("PUT", "item_123", "bottle", 0.9, ts="2026-11-07T20:00:01.000Z")
    frame = np.full((300, 300, 3), 10, dtype=np.uint8)

    mock_embedder_instance = MagicMock()
    mock_embedder_cls = MagicMock(return_value=mock_embedder_instance)
    monkeypatch.setattr("fridge_item.embed.Embedder", mock_embedder_cls)

    monkeypatch.setattr("fridge_item.detect.Detector", MagicMock())
    monkeypatch.setattr(
        "fridge_item.__main__.iter_frames",
        lambda src: [(frame, "2026-11-07T20:00:01.000Z")],
    )
    monkeypatch.setattr(
        "fridge_item.pipeline.ItemPipeline.process",
        lambda self, f, ts: [test_ev],
    )

    run_command(
        source="dummy_src",
        config_path=str(cfg_file),
        gallery_path=str(tmp_path / "gallery.json"),
        dry_run=True,
        embed=True,
    )

    mock_embedder_cls.assert_called_once()



def test_cli_run_command_dry_run(tmp_path: Path, monkeypatch, capsys):
    from fridge_item.__main__ import run_command
    from fridge_item.config import Config, save
    from fridge_item.events import item_event

    cfg_file = tmp_path / "cfg.json"
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    save(Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0), cfg_file)

    test_ev = item_event("PUT", "item_123", "bottle", 0.9, ts="2026-11-07T20:00:01.000Z")
    frame = np.full((300, 300, 3), 10, dtype=np.uint8)

    monkeypatch.setattr("fridge_item.detect.Detector", MagicMock())
    monkeypatch.setattr(
        "fridge_item.__main__.iter_frames",
        lambda src: [(frame, "2026-11-07T20:00:01.000Z")],
    )
    monkeypatch.setattr(
        "fridge_item.pipeline.ItemPipeline.process",
        lambda self, f, ts: [test_ev],
    )

    run_command(
        source="dummy_src",
        config_path=str(cfg_file),
        gallery_path=str(tmp_path / "gallery.json"),
        dry_run=True,
    )

    captured = capsys.readouterr().out
    assert json.loads(captured.strip()) == test_ev


def test_cli_run_command_kafka_publish(tmp_path: Path, monkeypatch):
    import sys
    from unittest.mock import MagicMock
    from fridge_item.__main__ import run_command
    from fridge_item.config import Config, save
    from fridge_item.events import item_event

    cfg_file = tmp_path / "cfg.json"
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    save(Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0), cfg_file)

    test_ev = item_event("PUT", "item_456", "can", 0.88, ts="2026-11-07T20:00:01.000Z")
    frame = np.full((300, 300, 3), 10, dtype=np.uint8)

    monkeypatch.setattr("fridge_item.detect.Detector", MagicMock())
    monkeypatch.setattr(
        "fridge_item.__main__.iter_frames",
        lambda src: [(frame, "2026-11-07T20:00:01.000Z")],
    )
    monkeypatch.setattr(
        "fridge_item.pipeline.ItemPipeline.process",
        lambda self, f, ts: [test_ev],
    )

    mock_producer_instance = MagicMock()
    mock_producer_cls = MagicMock(return_value=mock_producer_instance)

    mock_kafka_mod = MagicMock()
    mock_kafka_mod.Producer = mock_producer_cls
    monkeypatch.setitem(sys.modules, "confluent_kafka", mock_kafka_mod)

    run_command(
        source="dummy_src",
        config_path=str(cfg_file),
        gallery_path=str(tmp_path / "gallery.json"),
        broker="custom_broker:19092",
        dry_run=False,
    )

    from unittest.mock import ANY
    mock_producer_cls.assert_called_once_with({"bootstrap.servers": "custom_broker:19092"})
    mock_producer_instance.produce.assert_called_once_with(
        "item.event",
        key=test_ev["event_id"],
        value=json.dumps(test_ev, ensure_ascii=False),
        on_delivery=ANY,
    )
    mock_producer_instance.poll.assert_called_once_with(0)
    mock_producer_instance.flush.assert_called_once_with(10)


def test_cli_run_command_debug_video(tmp_path: Path, monkeypatch):
    from fridge_item.__main__ import run_command
    from fridge_item.config import Config, save

    cfg_file = tmp_path / "cfg.json"
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    save(Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0), cfg_file)

    frame = np.full((100, 100, 3), 10, dtype=np.uint8)
    monkeypatch.setattr("fridge_item.detect.Detector", MagicMock())
    monkeypatch.setattr(
        "fridge_item.__main__.iter_frames",
        lambda src: [(frame, "2026-11-07T20:00:01.000Z")],
    )
    monkeypatch.setattr(
        "fridge_item.pipeline.ItemPipeline.process",
        lambda self, f, ts: [],
    )

    out_video = tmp_path / "debug.mp4"
    mock_writer = MagicMock()
    monkeypatch.setattr("cv2.VideoWriter", MagicMock(return_value=mock_writer))

    run_command(
        source="dummy_src",
        config_path=str(cfg_file),
        gallery_path=str(tmp_path / "gallery.json"),
        dry_run=True,
        debug_video=str(out_video),
    )

    mock_writer.write.assert_called_once()
    mock_writer.release.assert_called_once()


def test_cli_run_latency_print(tmp_path: Path, monkeypatch, capsys):
    from fridge_item.__main__ import run_command
    from fridge_item.config import Config, save

    cfg_file = tmp_path / "cfg.json"
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    save(Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0), cfg_file)

    frame = np.full((50, 50, 3), 10, dtype=np.uint8)
    frames = [(frame, f"2026-11-07T20:00:{i:02d}.000Z") for i in range(100)]
    monkeypatch.setattr("fridge_item.detect.Detector", MagicMock())
    monkeypatch.setattr("fridge_item.__main__.iter_frames", lambda src: iter(frames))
    monkeypatch.setattr("fridge_item.pipeline.ItemPipeline.process", lambda self, f, ts: [])

    run_command(
        source="dummy_src",
        config_path=str(cfg_file),
        gallery_path=str(tmp_path / "gallery.json"),
        dry_run=True,
    )

    out = capsys.readouterr().out
    assert "Frame 100: detector p50=" in out
    assert "process p50=" in out


def test_close_flushes_open_session(tmp_path: Path):
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)
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


def test_close_with_no_open_session(tmp_path: Path):
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)
    gallery = ItemGallery(tmp_path / "gallery.json")
    pipeline = ItemPipeline(cfg=cfg, detect=ScriptedDetector([]), gallery=gallery)

    assert pipeline.close() == []


def test_pipeline_segment_called_only_when_door_open(tmp_path: Path):
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)
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



def test_cli_run_command_flushes_on_shutdown(tmp_path: Path, monkeypatch, capsys):
    from fridge_item.__main__ import run_command
    from fridge_item.config import Config, save

    cfg_file = tmp_path / "cfg.json"
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    save(Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0), cfg_file)

    script = [
        [hand(1, 100.0, 50.0), item(10, 100.0, 50.0, label="juice", conf=0.85)],
        [hand(1, 100.0, 150.0), item(10, 100.0, 150.0, label="juice", conf=0.85)],
    ]
    detector = ScriptedDetector(script)
    monkeypatch.setattr("fridge_item.detect.Detector", lambda *args, **kwargs: detector)

    bright_frame = np.full((300, 300, 3), 200, dtype=np.uint8)
    frames = [
        (bright_frame, "2026-11-07T20:00:01.000Z"),
        (bright_frame, "2026-11-07T20:00:02.000Z"),
    ]
    monkeypatch.setattr("fridge_item.__main__.iter_frames", lambda src: iter(frames))

    run_command(
        source="dummy_src",
        config_path=str(cfg_file),
        gallery_path=str(tmp_path / "gallery.json"),
        dry_run=True,
    )

    out = capsys.readouterr().out.strip()
    ev = json.loads(out)
    assert ev["type"] == "PUT"
    assert ev["item_label"] == "juice"
    Draft202012Validator(SCHEMA).validate(ev)


def test_shutdown_cleanup_on_flush_error(tmp_path: Path, monkeypatch):
    import sys
    from unittest.mock import MagicMock
    from fridge_item.__main__ import run_command
    from fridge_item.config import Config, save
    from fridge_item.events import item_event

    cfg_file = tmp_path / "cfg.json"
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    save(Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0), cfg_file)

    frame = np.full((100, 100, 3), 10, dtype=np.uint8)
    monkeypatch.setattr("fridge_item.detect.Detector", MagicMock())
    monkeypatch.setattr(
        "fridge_item.__main__.iter_frames",
        lambda src: [(frame, "2026-11-07T20:00:01.000Z")],
    )

    flushed_ev = item_event("PUT", "item_err", "coke", 0.9, ts="2026-11-07T20:00:02.000Z")
    monkeypatch.setattr(
        "fridge_item.pipeline.ItemPipeline.process",
        lambda self, f, ts: [],
    )
    monkeypatch.setattr(
        "fridge_item.pipeline.ItemPipeline.close",
        lambda self: [flushed_ev],
    )

    mock_producer_instance = MagicMock()
    mock_producer_instance.produce.side_effect = RuntimeError("Kafka buffer full")
    mock_producer_cls = MagicMock(return_value=mock_producer_instance)

    mock_kafka_mod = MagicMock()
    mock_kafka_mod.Producer = mock_producer_cls
    monkeypatch.setitem(sys.modules, "confluent_kafka", mock_kafka_mod)

    mock_writer = MagicMock()
    monkeypatch.setattr("cv2.VideoWriter", MagicMock(return_value=mock_writer))

    out_video = tmp_path / "out.mp4"
    with pytest.raises(RuntimeError, match="Kafka buffer full"):
        run_command(
            source="dummy_src",
            config_path=str(cfg_file),
            gallery_path=str(tmp_path / "gallery.json"),
            broker="localhost:19092",
            dry_run=False,
            debug_video=str(out_video),
        )

    mock_producer_instance.flush.assert_called_once_with(10)
    mock_writer.release.assert_called_once()


def test_shutdown_order_and_flush_warning_and_delivery_callback(tmp_path: Path, monkeypatch, capsys):
    import sys
    from unittest.mock import MagicMock
    from fridge_item.__main__ import run_command
    from fridge_item.config import Config, save
    from fridge_item.events import item_event

    cfg_file = tmp_path / "cfg.json"
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    save(Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0), cfg_file)

    frame = np.full((100, 100, 3), 10, dtype=np.uint8)
    monkeypatch.setattr("fridge_item.detect.Detector", MagicMock())
    monkeypatch.setattr(
        "fridge_item.__main__.iter_frames",
        lambda src: [(frame, "2026-11-07T20:00:01.000Z")],
    )

    ev = item_event("PUT", "item-1", "coke", 0.9, ts="2026-11-07T20:00:01.000Z")
    monkeypatch.setattr(
        "fridge_item.pipeline.ItemPipeline.process",
        lambda self, f, ts: [ev],
    )
    monkeypatch.setattr(
        "fridge_item.pipeline.ItemPipeline.close",
        lambda self: [],
    )

    call_order = []
    mock_writer = MagicMock()
    mock_writer.release.side_effect = lambda: call_order.append("release")
    monkeypatch.setattr("cv2.VideoWriter", MagicMock(return_value=mock_writer))

    mock_producer_instance = MagicMock()
    mock_producer_instance.flush.side_effect = lambda timeout=None: (call_order.append(f"flush({timeout})"), 2)[1]
    mock_producer_cls = MagicMock(return_value=mock_producer_instance)

    mock_kafka_mod = MagicMock()
    mock_kafka_mod.Producer = mock_producer_cls
    monkeypatch.setitem(sys.modules, "confluent_kafka", mock_kafka_mod)

    out_video = tmp_path / "out.mp4"
    run_command(
        source="dummy_src",
        config_path=str(cfg_file),
        gallery_path=str(tmp_path / "gallery.json"),
        broker="localhost:19092",
        dry_run=False,
        debug_video=str(out_video),
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


def test_pipeline_shelf_check_put_when_hand_logic_silent(tmp_path: Path):
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)

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


def test_pipeline_shelf_check_no_duplicate_put(tmp_path: Path):
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)
    gallery = ItemGallery(tmp_path / "gallery.json")

    # Scripted crossing that causes hand logic to emit PUT for bottle:
    # Frame 1: door open, empty shelf, hand outside holding bottle
    # Frame 2: hand inside holding bottle (crossing in)
    # Frame 3: hand inside empty
    # Frame 4: hand outside empty (crossing out -> PUT completed!)
    # Frame 5: door open, bottle on shelf, no hand (after snapshot)
    script = [
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
        detect=ScriptedDetector(script),
        gallery=gallery,
        shelf_check=True,
    )

    all_events = []
    # Frame 1: empty shelf snapshot before not set yet because hand is present!
    # Wait, let's include a frame 0 with door open and no hand so "before" is captured as empty
    # Let's adjust script so before snapshot is captured:
    # Call 0: door open, no hand, no items
    # Call 1..4: hand puts bottle
    # Call 5: door open, no hand, bottle on shelf
    script_with_before = [
        [],  # no hand, no items -> before = []
        [hand(1, 100.0, 50.0), item(10, 100.0, 50.0, label="bottle")],
        [hand(1, 100.0, 150.0), item(10, 100.0, 150.0, label="bottle")],
        [hand(1, 100.0, 150.0)],
        [hand(1, 100.0, 50.0)],
        [item(10, 100.0, 150.0, label="bottle")],  # no hand, bottle -> after = [bottle]
    ]

    pipeline = ItemPipeline(
        cfg=cfg,
        detect=ScriptedDetector(script_with_before),
        gallery=gallery,
        shelf_check=True,
    )

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


def test_pipeline_shelf_check_take_fallback_last_open_ts(tmp_path: Path):
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)
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


def test_cli_shelf_check_flags():
    from fridge_item.__main__ import parse_args

    args_run = parse_args(["run", "--source", "vid.mp4", "--shelf-check"])
    assert args_run.shelf_check is True

    args_run_default = parse_args(["run", "--source", "vid.mp4"])
    assert args_run_default.shelf_check is False

    args_eval = parse_args(["evaluate", "--shelf-check"])
    assert args_eval.shelf_check is True

    args_eval_default = parse_args(["evaluate"])
    assert args_eval_default.shelf_check is False


def test_pipeline_close_flushes_shelf_check(tmp_path: Path):
    line = DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)
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






