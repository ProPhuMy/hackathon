import numpy as np
import pytest
from src.calibration import fit_baseline, measure


def encounter(person, vector):
    return {'person_id': person, 'observations': [(t, np.array(vector), 1.) for t in (0., .2, .4, .6)]}


def scores(vector):
    return {'a': float(vector[0]), 'b': float(vector[1])}


def test_fit_and_evaluate_count_encounters_including_strangers():
    data = [encounter('a', [1., 0.]), encounter('b', [0., 1.]), encounter(None, [-1., 0.])]
    policy, report = fit_baseline(data, scores)
    assert report['known_correct'] == 2
    assert report['unknown_false_accepts'] == 0
    assert report['known_total'] == 2
    assert report['unknown_total'] == 1
    assert measure(data, scores, policy) == report


def test_fit_requires_known_and_stranger_data():
    with pytest.raises(ValueError, match='known and stranger'):
        fit_baseline([encounter('a', [1., 0.])], scores)


def test_brief_wrong_identity_counts_as_failure():
    data = [encounter('a', [0., 1.])]
    report = measure(data, scores, dict(accept=.8, reject=.1, margin=.1))
    assert report['wrong_known'] == 1
    assert report['known_correct'] == 0
