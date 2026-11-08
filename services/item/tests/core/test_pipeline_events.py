"""Trip -> event resolution against the gallery: PUTs first, TAKEs by embedding (take_many) or label."""
from pathlib import Path

import numpy as np

from conftest import ScriptedDetector, hand
from src.core.gallery import ItemGallery
from src.core.geometry import Box, Track
from src.core.pipeline import ItemPipeline
from src.core.session import Trip


def test_pipeline_two_takes_resolved_with_take_many(tmp_path: Path, cfg):
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


def test_two_embedded_takes_plus_one_cropless_take_in_close(tmp_path: Path, cfg):
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


def test_put_then_take_in_one_call_matches_just_put_item(tmp_path: Path, cfg):
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


def test_take_put_take_ordering_resolves_put_first(tmp_path: Path, cfg):
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
