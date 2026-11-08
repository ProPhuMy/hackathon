from src.storage import segment_id


def test_segment_ids_survive_restarts(tmp_path):
    path = tmp_path / 'counter.json'
    assert segment_id(path) == 0
    assert segment_id(path) == 1
