import hashlib
import pytest
from src.identity.ensemble import fit_policy, evaluate, predict, candidate_set


def row(session, person, arc, ada):
    return {'session_id': session, 'source_sha256': hashlib.sha256(session.encode()).hexdigest(),
            'person_id': person, 'arcface': arc, 'adaface': ada}


def dataset(split):
    encounters = []
    for i in range(12):
        encounters.extend([
            row(f'{split}-a-{i}', 'a', {'a': .9, 'b': .1}, {'a': .85, 'b': .05}),
            row(f'{split}-b-{i}', 'b', {'a': .1, 'b': .9}, {'a': .05, 'b': .85})])
        if split != 'conformal':
            encounters.append(row(f'{split}-u-{i}', None, {'a': .1, 'b': .15}, {'a': .05, 'b': .1}))
    return {'binding': '0'*64, 'prefix_s': 1., 'encounters': encounters}


def test_fitted_fusion_conformal_and_independent_evaluation():
    policy = fit_policy(dataset('dev'), dataset('conformal'))
    assert len(policy['coefficients']) == 2
    report = evaluate(policy, dataset('test'))
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
    calibration = dataset('conformal')
    calibration['encounters'] = calibration['encounters'][:16]
    with pytest.raises(ValueError, match='nine'):
        fit_policy(dataset('dev'), calibration)


def test_overlapping_recordings_and_bindings_fail():
    with pytest.raises(ValueError, match='overlap'):
        fit_policy(dataset('dev'), dataset('dev'))
    conformal = dataset('conformal')
    conformal['binding'] = '1'*64
    with pytest.raises(ValueError, match='binding'):
        fit_policy(dataset('dev'), conformal)


def test_invalid_or_mismatched_encoder_scores_are_rejected():
    development = dataset('dev')
    development['encounters'][0]['adaface'] = {'different': .5}
    with pytest.raises(ValueError, match='identities'):
        fit_policy(development, dataset('conformal'))
    development = dataset('dev')
    development['encounters'][0]['arcface']['a'] = float('nan')
    with pytest.raises(ValueError, match='finite'):
        fit_policy(development, dataset('conformal'))


def test_multiple_candidates_abstain_even_with_high_best_score():
    policy = fit_policy(dataset('dev'), dataset('conformal'))
    decision = predict(policy, {'a': .9, 'b': .9}, {'a': .9, 'b': .9})
    assert decision['state'] == 'ambiguous'
    assert decision['person_id'] is None


def test_evaluation_cannot_reuse_development_or_conformal_encounters():
    policy = fit_policy(dataset('dev'), dataset('conformal'))
    with pytest.raises(ValueError, match='overlap'):
        evaluate(policy, dataset('dev'))


def test_one_person_gallery_needs_no_fabricated_runner_up():
    development, calibration, test = dataset('dev'), dataset('conformal'), dataset('test')
    for data in (development, calibration, test):
        data['encounters'] = [r for r in data['encounters'] if r['person_id'] != 'b']
        for r in data['encounters']:
            del r['arcface']['b']
            del r['adaface']['b']
    report = evaluate(fit_policy(development, calibration), test)
    assert report['known_correct'] == 12
    assert report['unknown_false_accepts'] == 0


def test_json_artifacts_roundtrip_through_cli_handler(tmp_path, capsys):
    import json
    from types import SimpleNamespace
    from src.identity.ensemble import execute
    paths = {}
    for split in ('dev', 'conformal', 'test'):
        path = tmp_path / f'{split}.json'
        path.write_text(json.dumps(dataset(split)))
        paths[split] = path
    policy = tmp_path / 'policy.json'
    execute(SimpleNamespace(command='calibrate-scores', development=paths['dev'], conformal=paths['conformal'], output=policy))
    output = tmp_path / 'report.json'
    execute(SimpleNamespace(command='evaluate-scores', scores=paths['test'], policy=policy, output=output))
    assert json.loads(output.read_text())['known_correct'] == 24


@pytest.mark.parametrize('invalid', [None, {}, {'binding': None, 'prefix_s': 1., 'encounters': []}])
def test_malformed_datasets_fail_clearly(invalid):
    with pytest.raises(ValueError):
        fit_policy(invalid, dataset('conformal'))


@pytest.mark.parametrize('field,value', [('prefix_s', 60.), ('fitting_encounters', []),
                                        ('fitting_encounters', [{'session_id': 'x', 'source_sha256': 'bad'}])])
def test_loaded_policy_cannot_disable_prefix_or_leakage_validation(field, value):
    policy = fit_policy(dataset('dev'), dataset('conformal'))
    policy[field] = value
    with pytest.raises(ValueError):
        evaluate(policy, dataset('test'))


def test_truncated_but_well_formed_provenance_is_rejected():
    policy = fit_policy(dataset('dev'), dataset('conformal'))
    policy['fitting_encounters'].pop()
    with pytest.raises(ValueError, match='incomplete'):
        evaluate(policy, dataset('test'))
