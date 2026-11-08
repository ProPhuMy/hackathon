"""Calibrated two-encoder score fusion with conservative conformal abstention.

Inputs are one fixed one-second prefix per independent encounter, not video frames.
This module neither runs neural models nor certifies rejection of unseen identities.
"""
import itertools
import re
import numpy as np
from sklearn.linear_model import LogisticRegression


def _scores(arcface, adaface, identities):
    if not isinstance(arcface, dict) or not isinstance(adaface, dict):
        raise ValueError('Encoder scores must be mappings of enrolled identities')
    if set(arcface) != set(identities) or set(adaface) != set(identities):
        raise ValueError('Both encoder scores must cover exactly the same identities')
    raw = [[arcface[k], adaface[k]] for k in identities]
    if any(isinstance(v, bool) or not isinstance(v, (int, float, np.integer, np.floating)) for pair in raw for v in pair):
        raise ValueError('Encoder scores must be finite numeric cosines')
    values = np.array(raw, dtype=float)
    if not np.isfinite(values).all() or np.any(np.abs(values) > 1.000001):
        raise ValueError('Encoder cosine scores must be finite and in [-1,1]')
    return values


def _validate_sources(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError('Fitting/encounter provenance must be a nonempty list')
    sessions, sources = set(), set()
    for row in rows:
        if not isinstance(row, dict) or not {'session_id', 'source_sha256'} <= row.keys():
            raise ValueError('Missing encounter provenance')
        session, source = row['session_id'], row['source_sha256']
        if not isinstance(session, str) or not session or not isinstance(source, str) or not re.fullmatch(r'[0-9a-f]{64}', source):
            raise ValueError('Encounter needs a session ID and recording SHA-256')
        if session in sessions or source in sources:
            raise ValueError('Recording/session overlap within scored encounters')
        sessions.add(session)
        sources.add(source)


def _validate(data):
    if not isinstance(data, dict) or not {'binding', 'prefix_s', 'encounters'} <= data.keys():
        raise ValueError('Scored dataset needs binding, prefix_s and encounters')
    if not isinstance(data['binding'], str) or not re.fullmatch(r'[0-9a-f]{64}', data['binding']):
        raise ValueError('Pipeline binding must be a SHA-256 of models, preprocessing and galleries')
    if isinstance(data['prefix_s'], bool) or data['prefix_s'] != 1.:
        raise ValueError('Scoring requires the fixed one-second encounter prefix')
    rows = data['encounters']
    if not isinstance(rows, list) or not rows:
        raise ValueError('No scored encounters')
    for row in rows:
        if not isinstance(row, dict) or not {'session_id', 'source_sha256', 'person_id', 'arcface', 'adaface'} <= row.keys() or not isinstance(row['arcface'], dict):
            raise ValueError('Malformed scored encounter')
    identities = sorted(rows[0]['arcface'])
    if not identities or any(not isinstance(k, str) or not k for k in identities):
        raise ValueError('Invalid enrolled identities')
    _validate_sources(rows)
    for row in rows:
        if row['person_id'] is not None and row['person_id'] not in identities:
            raise ValueError('Known encounter label is not among enrolled identities')
        _scores(row['arcface'], row['adaface'], identities)
    return identities


def _disjoint(rows, previous):
    for key in ('session_id', 'source_sha256'):
        if {r[key] for r in rows} & {r[key] for r in previous}:
            raise ValueError('Encounter overlap between development, conformal or test data')


def fused_scores(policy, arcface, adaface):
    values = _scores(arcface, adaface, policy['identities'])
    coefficients = np.asarray(policy['coefficients'], dtype=float)
    intercept = float(policy['intercept'])
    if coefficients.shape != (2,) or not np.isfinite(coefficients).all() or not np.isfinite(intercept):
        raise ValueError('Invalid fusion coefficients')
    logits = values @ coefficients + intercept
    probabilities = np.exp(-np.logaddexp(0., -logits))
    return dict(zip(policy['identities'], map(float, probabilities)))


def candidate_set(scores, calibration):
    if set(scores) != set(calibration) or not scores:
        raise ValueError('Conformal calibration must cover every identity')
    pvalues = {}
    for person, score in scores.items():
        values = np.asarray(calibration[person], dtype=float)
        if values.ndim != 1 or len(values) < 9:
            raise ValueError('At least nine independent calibration encounters per identity are required')
        if not np.isfinite(values).all() or np.any((values < 0) | (values > 1)) or not np.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Invalid conformal scores')
        pvalues[person] = float((1 + np.count_nonzero(values >= 1 - score)) / (len(values) + 1))
    return {person for person, value in pvalues.items() if value > .1}, pvalues


def _decision(scores, gates, candidates=None):
    accept, reject, margin = (gates[k] for k in ('accept', 'reject', 'margin'))
    if not 0 <= reject <= accept <= 1 or not 0 <= margin <= 1:
        raise ValueError('Invalid ensemble rejection gates')
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best, confidence = ranked[0]
    result = dict(state='ambiguous', person_id=None, confidence=None)
    if confidence < reject and (candidates is None or not candidates):
        result.update(state='unknown', confidence=0.)
    elif (confidence >= accept and (len(ranked) == 1 or confidence - ranked[1][1] >= margin)
          and (candidates is None or candidates == {best})):
        result.update(state='known', person_id=best, confidence=confidence)
    return result


def predict(policy, arcface, adaface):
    if policy['version'] != 1 or policy['alpha'] != .1 or isinstance(policy['prefix_s'], bool) or policy['prefix_s'] != 1.:
        raise ValueError('Unsupported ensemble policy version/alpha')
    scores = fused_scores(policy, arcface, adaface)
    candidates, pvalues = candidate_set(scores, policy['conformal'])
    result = _decision(scores, policy['gates'], candidates)
    result.update(candidates=sorted(candidates), pvalues=pvalues)
    return result


def fit_policy(development, conformal):
    identities = _validate(development)
    conformal_identities = _validate(conformal)
    if development['binding'] != conformal['binding']:
        raise ValueError('Model/gallery pipeline binding mismatch')
    _disjoint(development['encounters'], conformal['encounters'])
    if identities != conformal_identities:
        raise ValueError('Calibration identities mismatch')
    rows = development['encounters']
    if {r['person_id'] for r in rows if r['person_id'] is not None} != set(identities) or not any(r['person_id'] is None for r in rows):
        raise ValueError('Development needs every enrolled identity and strangers')
    features, labels = [], []
    for row in rows:
        features.extend(_scores(row['arcface'], row['adaface'], identities))
        labels.extend([int(person == row['person_id']) for person in identities])
    # Every encounter contributes one candidate per enrolled identity, with equal weight.
    regression = LogisticRegression(C=1., max_iter=1000, random_state=0)
    regression.fit(features, labels)
    policy = dict(version=1, alpha=.1, binding=development['binding'], prefix_s=1.,
                  identities=identities, coefficients=regression.coef_[0].tolist(),
                  intercept=float(regression.intercept_[0]), sampling='all enrolled candidates per encounter')
    scores = [fused_scores(policy, row['arcface'], row['adaface']) for row in rows]
    best = None
    # Gates are frozen on development BEFORE any conformal observations are used.
    for accept, reject, margin in itertools.product(np.linspace(0, 1, 21), np.linspace(0, 1, 21), (0., .05, .1, .2)):
        if reject > accept:
            continue
        gates = dict(accept=float(accept), reject=float(reject), margin=margin)
        decisions = [_decision(value, gates) for value in scores]
        if any(d['state'] == 'known' and d['person_id'] != row['person_id'] for d, row in zip(decisions, rows)):
            continue
        correct = sum(d['state'] == 'known' and d['person_id'] == row['person_id'] for d, row in zip(decisions, rows))
        rejected = sum(d['state'] == 'unknown' and row['person_id'] is None for d, row in zip(decisions, rows))
        rank = correct, rejected, accept, margin, -reject
        if best is None or rank > best[0]:
            best = rank, gates
    if best is None or best[0][0] == 0:
        raise ValueError('Development cannot support a useful ensemble policy without false names')
    policy['gates'] = best[1]
    calibration = {person: [] for person in identities}
    for row in conformal['encounters']:
        if row['person_id'] is None:
            raise ValueError('Conformal calibration uses known encounters only')
        values = fused_scores(policy, row['arcface'], row['adaface'])
        calibration[row['person_id']].append(1 - values[row['person_id']])
    candidate_set({k: .5 for k in identities}, calibration)  # Check class counts before saving.
    policy['conformal'] = calibration
    policy['development_count'] = len(rows)
    policy['fitting_encounters'] = [{k: row[k] for k in ('session_id', 'source_sha256')}
                                  for row in rows + conformal['encounters']]
    return policy


def evaluate(policy, data):
    required = {'version', 'alpha', 'prefix_s', 'binding', 'identities', 'coefficients',
                'intercept', 'gates', 'conformal', 'development_count', 'fitting_encounters'}
    if not isinstance(policy, dict) or not required <= policy.keys():
        raise ValueError('Incomplete ensemble policy')
    if policy['version'] != 1 or policy['alpha'] != .1 or isinstance(policy['prefix_s'], bool) or policy['prefix_s'] != 1.:
        raise ValueError('Unsupported policy version, prefix or alpha')
    _validate_sources(policy['fitting_encounters'])
    count = policy['development_count']
    if (type(count) is not int or count < len(policy['identities']) + 1
            or len(policy['fitting_encounters']) != count + sum(len(v) for v in policy['conformal'].values())):
        raise ValueError('Fitting provenance is incomplete or inconsistent with calibration counts')
    if data['binding'] != policy['binding']:
        raise ValueError('Model/gallery pipeline binding mismatch')
    if _validate(data) != policy['identities']:
        raise ValueError('Evaluation identities mismatch')
    _disjoint(data['encounters'], policy['fitting_encounters'])
    report = dict(known_total=0, known_correct=0, known_abstained=0, wrong_known=0,
                  unknown_total=0, unknown_false_accepts=0, unknown_rejected=0,
                  conformal_known_covered=0, conformal_empty=0, conformal_singleton=0, conformal_multiple=0)
    for row in data['encounters']:
        result = predict(policy, row['arcface'], row['adaface'])
        truth = row['person_id']
        size = len(result['candidates'])
        report['conformal_empty' if size == 0 else 'conformal_singleton' if size == 1 else 'conformal_multiple'] += 1
        if truth is None:
            report['unknown_total'] += 1
            report['unknown_false_accepts'] += result['state'] == 'known'
            report['unknown_rejected'] += result['state'] == 'unknown'
        else:
            report['known_total'] += 1
            report['conformal_known_covered'] += truth in result['candidates']
            report['known_correct'] += result['state'] == 'known' and result['person_id'] == truth
            report['wrong_known'] += result['state'] == 'known' and result['person_id'] != truth
            report['known_abstained'] += result['state'] != 'known'
    return report


def execute(args):
    import json
    from ..storage import atomic_json
    if args.command == 'calibrate-scores':
        development = json.loads(args.development.read_text())
        conformal = json.loads(args.conformal.read_text())
        policy = fit_policy(development, conformal)
        atomic_json(args.output, policy)
        report = dict(enrolled_classes=len(policy['identities']),
                      development_encounters=len(development['encounters']),
                      conformal_counts={k: len(v) for k, v in policy['conformal'].items()})
    else:
        policy = json.loads(args.policy.read_text())
        report = evaluate(policy, json.loads(args.scores.read_text()))
        atomic_json(args.output, report)
    print(json.dumps(report, indent=2))
