import pytest
from conftest import score_dataset
from src.identity.ensemble import EnsembleEngine, fit_policy, evaluate, predict, candidate_set
from src.identity.gallery import Gallery


def test_fitted_fusion_conformal_and_independent_evaluation():
    policy = fit_policy(score_dataset('dev'), score_dataset('conformal'))
    assert len(policy['coefficients']) == 2
    report = evaluate(policy, score_dataset('test'))
    assert report['known_correct'] == report['known_total'] == 24
    assert report['unknown_false_accepts'] == 0
    assert report['unknown_total'] == 12
    assert report['conformal_known_covered'] == 24


def test_conformal_ties_use_greater_equal_and_strict_alpha():
    calibration = {'a': [.1]*9, 'b': [.1]*9}
    candidates, pvalues = candidate_set({'a': .9, 'b': .1}, calibration)
    assert pvalues == {'a': 1., 'b': .1}
    assert candidates == {'a'}


def test_missing_classes_or_fewer_than_nine_encounters_fail():
    calibration = score_dataset('conformal')
    calibration['encounters'] = calibration['encounters'][:16]
    with pytest.raises(ValueError, match='nine'):
        fit_policy(score_dataset('dev'), calibration)


def test_overlapping_recordings_and_bindings_fail():
    with pytest.raises(ValueError, match='overlap'):
        fit_policy(score_dataset('dev'), score_dataset('dev'))
    conformal = score_dataset('conformal')
    conformal['binding'] = '1'*64
    with pytest.raises(ValueError, match='binding'):
        fit_policy(score_dataset('dev'), conformal)


def test_invalid_or_mismatched_encoder_scores_are_rejected():
    development = score_dataset('dev')
    development['encounters'][0]['adaface'] = {'different': .5}
    with pytest.raises(ValueError, match='identities'):
        fit_policy(development, score_dataset('conformal'))
    development = score_dataset('dev')
    development['encounters'][0]['arcface']['a'] = float('nan')
    with pytest.raises(ValueError, match='finite'):
        fit_policy(development, score_dataset('conformal'))


def test_multiple_candidates_abstain_even_with_high_best_score():
    policy = fit_policy(score_dataset('dev'), score_dataset('conformal'))
    decision = predict(policy, {'a': .9, 'b': .9}, {'a': .9, 'b': .9})
    assert decision['state'] == 'ambiguous'
    assert decision['person_id'] is None


def test_evaluation_cannot_reuse_development_or_conformal_encounters():
    policy = fit_policy(score_dataset('dev'), score_dataset('conformal'))
    with pytest.raises(ValueError, match='overlap'):
        evaluate(policy, score_dataset('dev'))


def test_one_person_gallery_needs_no_fabricated_runner_up():
    development, calibration, test = score_dataset('dev'), score_dataset('conformal'), score_dataset('test')
    for data in (development, calibration, test):
        data['encounters'] = [r for r in data['encounters'] if r['person_id'] != 'b']
        for r in data['encounters']:
            del r['arcface']['b']
            del r['adaface']['b']
    report = evaluate(fit_policy(development, calibration), test)
    assert report['known_correct'] == 12
    assert report['unknown_false_accepts'] == 0


@pytest.mark.parametrize('invalid', [None, {}, {'binding': None, 'prefix_s': 1., 'encounters': []}])
def test_malformed_datasets_fail_clearly(invalid):
    with pytest.raises(ValueError):
        fit_policy(invalid, score_dataset('conformal'))


@pytest.mark.parametrize('field,value', [('prefix_s', 60.), ('fitting_encounters', []),
                                        ('fitting_encounters', [{'session_id': 'x', 'source_sha256': 'bad'}])])
def test_loaded_policy_cannot_disable_prefix_or_leakage_validation(field, value):
    policy = fit_policy(score_dataset('dev'), score_dataset('conformal'))
    policy[field] = value
    with pytest.raises(ValueError):
        evaluate(policy, score_dataset('test'))


def test_truncated_but_well_formed_provenance_is_rejected():
    policy = fit_policy(score_dataset('dev'), score_dataset('conformal'))
    policy['fitting_encounters'].pop()
    with pytest.raises(ValueError, match='incomplete'):
        evaluate(policy, score_dataset('test'))


def test_ensemble_continuity_is_checked_in_each_encoder_space(tmp_path):
    # ArcFace stays on the same face while AdaFace jumps to an orthogonal one: the average cosine
    # (0.5) would pass the joint 0.3 gate, but the AdaFace space alone breaks continuity.
    arc, ada = Gallery(tmp_path / 'arc.json', 'arc'), Gallery(tmp_path / 'ada.json', 'ada')
    arc.enroll('a', [[1., 0.]] * 10)
    ada.enroll('a', [[1., 0.]] * 10)
    policy = {'version': 1, 'alpha': .1, 'prefix_s': 1., 'identities': ['a'], 'coefficients': [2., 2.],
              'intercept': 0., 'gates': {'accept': .5, 'reject': .2, 'margin': 0.}, 'conformal': {'a': [.1] * 10}}
    engine = EnsembleEngine(arc, ada, policy)
    for t in (0., .2):
        engine.observe(engine.observation([1., 0.], [1., 0.]), 1., t)
    generation = engine.generation
    engine.observe(engine.observation([1., 0.], [0., 1.]), 1., .4)
    assert len(engine.evidence.samples) == 1
    assert engine.generation > generation
