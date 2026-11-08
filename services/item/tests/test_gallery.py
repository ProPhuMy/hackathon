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

    g2 = ItemGallery(gallery_path)
    taken_id, score = g2.take("apple", embedding=np.array([0.1, 0.2, 0.3]))
    assert taken_id == item_id
    assert score == pytest.approx(1.0)


def test_take_by_embedding_picks_nearest(tmp_path: Path):
    gallery = ItemGallery(tmp_path / "gallery.json")
    id1 = gallery.add("bottle", embedding=np.array([1.0, 0.0, 0.0]))
    id2 = gallery.add("bottle", embedding=np.array([0.0, 1.0, 0.0]))

    taken_id, score = gallery.take("bottle", embedding=np.array([0.1, 0.9, 0.0]))
    assert taken_id == id2
    assert score > 0.9
    assert gallery.items() == {id1: {"label": "bottle", "embedding": [1.0, 0.0, 0.0]}}


def test_take_many_assigns_one_to_one(tmp_path: Path):
    gallery = ItemGallery(tmp_path / "gallery.json")
    id1 = gallery.add("bottle", embedding=np.array([1.0, 0.0]))
    id2 = gallery.add("bottle", embedding=np.array([0.0, 1.0]))

    query_b = ("bottle", np.array([0.1, 0.9]))
    query_a = ("bottle", np.array([0.9, 0.1]))

    assignments = gallery.take_many([query_b, query_a])
    assert len(assignments) == 2
    assert assignments[0][0] == id2
    assert assignments[1][0] == id1
    assert assignments[0][1] > 0.9
    assert assignments[1][1] > 0.9
    assert gallery.items() == {}


def test_take_many_extra_query_unknown(tmp_path: Path):
    gallery = ItemGallery(tmp_path / "gallery.json")
    id1 = gallery.add("apple", embedding=np.array([1.0, 0.0]))
    id2 = gallery.add("banana", embedding=np.array([0.0, 1.0]))

    q1 = ("apple", np.array([1.0, 0.0]))
    q2 = ("banana", np.array([0.0, 1.0]))
    q3 = ("orange", np.array([0.5, 0.5]))

    assignments = gallery.take_many([q1, q2, q3])
    assert len(assignments) == 3
    assert assignments[0][0] == id1
    assert assignments[0][1] == pytest.approx(1.0)
    assert assignments[1][0] == id2
    assert assignments[1][1] == pytest.approx(1.0)
    assert assignments[2] == ("unknown", 0.0)
    assert gallery.items() == {}


def test_take_tie_breaking(tmp_path: Path):
    gallery = ItemGallery(tmp_path / "gallery.json")
    vec = np.array([1.0, 0.0])
    # id1 is older, label "juice"
    id1 = gallery.add("juice", embedding=vec)
    # id2 is newer, label "milk"
    id2 = gallery.add("milk", embedding=vec)
    # id3 is newest, label "juice"
    id3 = gallery.add("juice", embedding=vec)

    # Query with label "juice" and identical vector:
    # id1 and id3 have matching label, id1 is older than id3 -> id1 wins
    taken1, score1 = gallery.take("juice", embedding=vec)
    assert taken1 == id1
    assert score1 == pytest.approx(1.0)

    # Next query for "milk":
    # id2 has matching label -> id2 wins over id3
    taken2, score2 = gallery.take("milk", embedding=vec)
    assert taken2 == id2
    assert score2 == pytest.approx(1.0)

    # Finally id3
    taken3, score3 = gallery.take("milk", embedding=vec)
    assert taken3 == id3
    assert score3 == pytest.approx(1.0)


def test_take_many_no_embeddings_falls_back_to_labels(tmp_path: Path):
    gallery = ItemGallery(tmp_path / "gallery.json")
    id1 = gallery.add("milk")
    id2 = gallery.add("coke")

    # Both stored items have no embeddings
    res = gallery.take_many([("coke", np.array([1.0, 0.0])), ("milk", np.array([0.0, 1.0]))])
    assert len(res) == 2
    assert res[0] == (id2, 1.0)
    assert res[1] == (id1, 1.0)
    assert gallery.items() == {}




def test_empty_file_raises_value_error(tmp_path: Path):
    path = tmp_path / "gallery.json"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        ItemGallery(path)
    assert str(path) in str(excinfo.value)
    assert "fix or delete" in str(excinfo.value).lower()


def test_non_dict_json_raises_value_error(tmp_path: Path):
    path = tmp_path / "gallery.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        ItemGallery(path)
    assert str(path) in str(excinfo.value)
    assert "fix or delete" in str(excinfo.value).lower()


def test_item_missing_id_raises_value_error(tmp_path: Path):
    path = tmp_path / "gallery.json"
    path.write_text('{"items": [{"label": "milk"}]}', encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        ItemGallery(path)
    assert str(path) in str(excinfo.value)
    assert "fix or delete" in str(excinfo.value).lower()


def test_item_empty_id_or_missing_label_raises_value_error(tmp_path: Path):
    path1 = tmp_path / "gallery1.json"
    path1.write_text('{"items": [{"id": "", "label": "milk"}]}', encoding="utf-8")
    with pytest.raises(ValueError) as excinfo1:
        ItemGallery(path1)
    assert str(path1) in str(excinfo1.value)

    path2 = tmp_path / "gallery2.json"
    path2.write_text('{"items": [{"id": "item_123"}]}', encoding="utf-8")
    with pytest.raises(ValueError) as excinfo2:
        ItemGallery(path2)
    assert str(path2) in str(excinfo2.value)

