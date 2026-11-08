"""Empirical ArcFace baseline tuning; no ensemble or conformal claims."""
import itertools
import numpy as np
from ..identity.recognition import Baseline


def measure(encounters, scores, policy):
    report = dict(known_total=0, known_correct=0, known_abstained=0, wrong_known=0,
                  unknown_total=0, unknown_false_accepts=0, unknown_rejected=0,
                  accepted_observations=0, correct_accepted_observations=0)
    for encounter in encounters:
        truth = encounter['person_id']
        engine = Baseline(scores, policy)
        names = set()
        rejected = False
        for timestamp, vector, weight in encounter['observations']:
            if vector is None:
                engine.reset()
                continue
            result = engine.observe(vector, weight, timestamp)
            if result is None:
                continue
            person, _ = result
            if person is None:
                rejected = True
            else:
                names.add(person)
                report['accepted_observations'] += 1
                report['correct_accepted_observations'] += int(person == truth)
        if truth is None:
            report['unknown_total'] += 1
            report['unknown_false_accepts'] += bool(names)
            report['unknown_rejected'] += rejected and not names
        else:
            report['known_total'] += 1
            report['known_correct'] += names == {truth}
            report['known_abstained'] += not names
            report['wrong_known'] += bool(names - {truth})
    return report


def fit_baseline(encounters, scores):
    if not any(e['person_id'] is None for e in encounters) or not any(e['person_id'] is not None for e in encounters):
        raise ValueError('Calibration requires independent known and stranger encounters')
    best = None
    # Fixed coarse search on development only; test recordings never select thresholds.
    for accept, reject, margin in itertools.product((.3, .4, .5, .6, .7, .8, .9, 1.),
                                                     (-.2, 0., .2, .4), (0., .05, .1, .2)):
        if reject > accept:
            continue
        policy = dict(accept=accept, reject=reject, margin=margin)
        report = measure(encounters, scores, policy)
        if report['unknown_false_accepts'] or report['wrong_known']:
            continue
        rank = (report['known_correct'], report['unknown_rejected'], accept, margin, -reject)
        if best is None or rank > best[0]:
            best = rank, policy, report
    if best is None or best[2]['known_correct'] == 0:
        raise ValueError('No useful development policy without false names; collect data or improve baseline')
    return best[1], best[2]
