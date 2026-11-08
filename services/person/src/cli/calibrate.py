"""calibrate / evaluate: empirical ArcFace baseline thresholds from manifests, and held-out evaluation."""
import json
from ..evaluation.dataset import observations, read_manifest, verify_disjoint
from ..storage import atomic_json


def execute(args):
    from ..evaluation.calibration import fit_baseline, measure
    from ..identity.gallery import Gallery
    from ..vision.arcface import Vision
    vision = Vision(args.detector, args.recognizer)
    gallery = Gallery(args.gallery, vision.signature)
    if not gallery.people:
        raise ValueError('Enroll consenting participants before calibration/evaluation')
    rows = read_manifest(args.manifest, 'development' if args.command == 'calibrate' else 'test')
    for row in rows:
        if row['person_id'] is not None and row['person_id'] not in gallery.people:
            raise ValueError('Known label is not enrolled; strangers must have an empty person_id')
    verify_disjoint(rows, list(gallery.provenance.values()))
    if args.command == 'evaluate':
        policy = json.loads(args.policy.read_text())
        if policy['model'] != vision.signature or policy['gallery'] != gallery.fingerprint:
            raise ValueError('Policy incompatible with current model/gallery')
        verify_disjoint(rows, policy['development_encounters'])
    else:
        if {row['person_id'] for row in rows if row['person_id']} != set(gallery.people):
            raise ValueError('Development data must cover every enrolled identity')
    encounters = [observations(row, vision, args.rotate) for row in rows]
    if args.command == 'calibrate':
        policy, report = fit_baseline(encounters, gallery.scores)
        policy.update(model=vision.signature, gallery=gallery.fingerprint,
                      development_manifest=str(args.manifest.resolve()), development_encounters=rows,
                      scoring='arcface-single-face-baseline-v1', development_metrics=report)
        atomic_json(args.output, policy)
    else:
        report = measure(encounters, gallery.scores, policy)
        report.update(scoring='arcface-single-face-baseline-v1', test_encounters=rows,
                      limitations=['Empirical encounter metrics; no population error guarantee',
                                   'Offline decoding does not measure live throughput or broker latency'])
        atomic_json(args.output, report)
    print(json.dumps(report, indent=2))
