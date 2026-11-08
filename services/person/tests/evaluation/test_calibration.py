import numpy as np
import pytest
from src.evaluation.calibration import fit_baseline, measure


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


def test_threshold_is_the_middle_of_the_working_range_not_its_edge():
    # Known people score .85, a stranger .35: accept .4 through .8 all name both and reject the stranger.
    # The strictest working value (.8) sits right under the known scores, so a small drop leaves people
    # unnamed; the middle (.6) has the most room on both sides.
    # Unit vectors (evidence averages unit vectors), so these are the cosine scores themselves.
    k = (1 - .85 ** 2) ** .5
    data = [encounter('a', [.85, k]), encounter('b', [k, .85]), encounter(None, [.35, -(1 - .35 ** 2) ** .5])]
    policy, report = fit_baseline(data, scores)
    assert policy['accept'] == .6
    assert report['known_correct'] == 2 and report['unknown_rejected'] == 1
    assert report['wrong_known'] == report['unknown_false_accepts'] == 0
