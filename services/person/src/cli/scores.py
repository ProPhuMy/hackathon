"""calibrate-scores / evaluate-scores: offline ensemble fusion and conformal calibration from score JSON."""
import json
from ..identity.ensemble import evaluate, fit_policy
from ..storage import atomic_json


def execute(args):
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
