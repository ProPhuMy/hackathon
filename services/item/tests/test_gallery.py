from pathlib import Path
import numpy as np
import pytest

from fridge_item.gallery import ItemGallery


def test_add_then_take_same_label(tmp_path: Path):
    gallery = ItemGallery(tmp_path / "gallery.json")
    item_id = gallery.add("milk")

    taken_id, score = gallery.take("milk")
    assert taken_id == item_id
    assert score == 1.0
    assert gallery.items() == {}


def test_take_empty_returns_unknown(tmp_path: Path):
    gallery = ItemGallery(tmp_path / "gallery.json")
    taken_id, score = gallery.take("milk")
    assert taken_id == "unknown"
    assert score == 0.0


def test_take_other_label_low_score(tmp_path: Path):
    gallery = ItemGallery(tmp_path / "gallery.json")
    item_id = gallery.add("yogurt")

    taken_id, score = gallery.take("juice")
    assert taken_id == item_id
    assert score == 0.3
    assert gallery.items() == {}


def test_persists_across_instances(tmp_path: Path):
    gallery_path = tmp_path / "gallery.json"
    g1 = ItemGallery(gallery_path)
    item_id = g1.add("cheese")

    g2 = ItemGallery(gallery_path)
    assert item_id in g2.items()
    assert g2.items()[item_id]["label"] == "cheese"

    taken_id, score = g2.take("cheese")
    assert taken_id == item_id
    assert score == 1.0

    g3 = ItemGallery(gallery_path)
    assert g3.items() == {}


def test_oldest_item_matched_first(tmp_path: Path):
    gallery = ItemGallery(tmp_path / "gallery.json")
    id1 = gallery.add("soda")
    id2 = gallery.add("soda")

    taken_id1, score1 = gallery.take("soda")
    assert taken_id1 == id1
    assert score1 == 1.0

    taken_id2, score2 = gallery.take("soda")
    assert taken_id2 == id2
    assert score2 == 1.0


def test_embedding_stored_and_persisted(tmp_path: Path):
    gallery_path = tmp_path / "nested" / "gallery.json"
    gallery = ItemGallery(gallery_path)
    emb = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    item_id = gallery.add("apple", embedding=emb)

    items = gallery.items()
    assert item_id in items
    assert items[item_id]["label"] == "apple"
    assert isinstance(items[item_id]["embedding"], list)
    assert np.allclose(items[item_id]["embedding"], [0.1, 0.2, 0.3])

    # In this task, take ignores embedding argument
    g2 = ItemGallery(gallery_path)
    taken_id, score = g2.take("apple", embedding=np.array([0.5, 0.6]))
    assert taken_id == item_id
    assert score == 1.0
