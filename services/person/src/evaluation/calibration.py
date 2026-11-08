"""Empirical ArcFace baseline tuning; no ensemble or conformal claims."""
import itertools
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
    safe = []
    # Fixed coarse search on development only; test recordings never select thresholds.
    for accept, reject, margin in itertools.product((.3, .4, .5, .6, .7, .8, .9, 1.),
                                                     (-.2, 0., .2, .4), (0., .05, .1, .2)):
        if reject > accept:
            continue
        policy = dict(accept=accept, reject=reject, margin=margin)
        report = measure(encounters, scores, policy)
        if not (report['unknown_false_accepts'] or report['wrong_known']):
            safe.append(((report['known_correct'], report['unknown_rejected']), policy, report))
    top = max((outcome for outcome, _, _ in safe), default=None)
    if top is None or top[0] == 0:
        raise ValueError('No useful development policy without false names; collect data or improve baseline')
    best = [(policy, report) for outcome, policy, report in safe if outcome == top]
    # Middle of the working accept range, not its strict edge: the edge sits just under the development
    # scores, so a known person who turns their head goes unnamed; the middle has room on both sides.
    accepts = sorted({policy['accept'] for policy, _ in best})
    middle = accepts[len(accepts) // 2]
    return max(((policy, report) for policy, report in best if policy['accept'] == middle),
               key=lambda pair: (pair[0]['margin'], -pair[0]['reject']))
