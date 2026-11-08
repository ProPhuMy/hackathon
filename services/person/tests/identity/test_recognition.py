import numpy as np
import pytest

from src.identity.recognition import Evidence, decision


def test_evidence_requires_count_span_and_resets_on_contradiction():
    evidence = Evidence()
    x = np.array([1., 0.])
    assert evidence.observe(x, 1., 0.) is None
    assert evidence.observe(x, 1., .2) is None
    assert np.allclose(evidence.observe(x, 1., .4), x)
    assert evidence.observe(-x, 1., .6) is None
    assert len(evidence.samples) == 1


def test_expiry_requires_three_new_observations():
    evidence = Evidence()
    for t in (0., .2, .4):
        evidence.observe(np.array([1., 0.]), 1., t)
    assert evidence.observe(np.array([1., 0.]), 1., 2.) is None
    assert len(evidence.samples) == 1


def test_ambiguous_is_not_stranger():
    assert decision({'a': .8, 'b': .79}, .7, .2, .1) is None
    assert decision({'a': .1, 'b': .0}, .7, .2, .1) == (None, 0.)
    assert decision({'a': .9, 'b': .1}, .7, .2, .1) == ('a', .95)


def test_invalid_policy_and_vectors_are_rejected():
    with pytest.raises(ValueError):
        decision({'a': .9}, .2, .7, .1)
    with pytest.raises(ValueError):
        Evidence().observe(np.array([float('nan')]), 1., 0.)


def test_baseline_resets_on_ambiguity_and_new_identity():
    from src.identity.recognition import Baseline
    policy = dict(accept=.8, reject=.2, margin=.1)
    engine = Baseline(lambda v: {'a': float(v[0]), 'b': float(v[1])}, policy)
    x = np.array([1., 0.])
    assert engine.observe(x, 1., 0.) is None
    assert engine.observe(x, 1., .2) is None
    assert engine.observe(x, 1., .4)[0] == 'a'
    generation = engine.generation
    assert engine.observe(np.array([0., 1.]), 1., .6) is None
    assert engine.generation > generation
    assert engine.observe(np.array([0., 1.]), 1., .8) is None
    assert engine.observe(np.array([0., 1.]), 1., 1.)[0] == 'b'
