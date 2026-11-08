from fridge_item.evaluate import score


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
