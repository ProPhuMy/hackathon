"""Encounter manifests and offline baseline evaluation; paths are manifest-relative."""
import csv
import math
from pathlib import Path
import cv2
from .storage import atomic_json, file_hash


def read_manifest(path, split):
    path = Path(path).resolve()
    with path.open(newline='') as stream:
        reader = csv.DictReader(stream)
        required = {'path', 'person_id', 'session_id', 'split', 'start_s', 'end_s'}
        if not required <= set(reader.fieldnames or []):
            raise ValueError('Manifest needs path,person_id,session_id,split,start_s,end_s')
        rows = []
        sessions = set()
        recordings = set()
        for row in reader:
            if row['split'] != split:
                raise ValueError(f'Manifest split must be {split}')
            if not row['session_id'] or row['session_id'] in sessions:
                raise ValueError('Each row must be one independent encounter with a unique session_id')
            sessions.add(row['session_id'])
            start, end = float(row['start_s']), float(row['end_s'])
            if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end:
                raise ValueError('Invalid encounter time range')
            source = (path.parent / row['path']).resolve()
            digest = file_hash(source)
            if digest in recordings:
                raise ValueError('Duplicate recording; each encounter needs an independent capture')
            recordings.add(digest)
            rows.append(dict(path=str(source), person_id=row['person_id'] or None,
                             session_id=row['session_id'], sha256=digest,
                             start_s=start, end_s=end))
    if not rows:
        raise ValueError('Manifest is empty')
    return rows


def verify_disjoint(rows, previous):
    for key in ('path', 'session_id', 'sha256'):
        old = {row[key] for row in previous if row.get(key)}
        if any(row.get(key) in old for row in rows if row.get(key)):
            raise ValueError(f'Recording overlap by {key}; use independent encounters')


def observations(row, vision):
    capture = cv2.VideoCapture(row['path'])
    if not capture.isOpened():
        raise ValueError('Cannot open manifest video')
    samples = []
    previous = -float('inf')
    try:
        while True:
            ok, image = capture.read()
            if not ok:
                break
            timestamp = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if timestamp < row['start_s']:
                continue
            if timestamp >= row['end_s']:
                break
            if timestamp - previous < .2 - 1e-6:
                continue
            previous = timestamp
            result = vision.single_face(image)
            vector, weight = result if result is not None else (None, 0.)
            samples.append((timestamp, vector, weight))
    finally:
        capture.release()
    return {'person_id': row['person_id'], 'observations': samples}


def execute(args):
    import json
    from .calibration import fit_baseline, measure
    from .gallery import Gallery
    from .vision import Vision
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
    encounters = [observations(row, vision) for row in rows]
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
