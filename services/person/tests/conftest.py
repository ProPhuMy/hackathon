"""Shared fakes and fixtures. Test modules import the plain helpers with `from conftest import ...`."""
import hashlib
from pathlib import Path

SCHEMA_PATH = Path(__file__).parents[3] / 'contracts' / 'person.seen.schema.json'


def fake_capture(frames):
    """Capture stand-in that replays (image, received, timestamp) frames without a camera."""
    class Capture:
        def __init__(self, *args):
            pass
        def __enter__(self):
            return iter(frames)
        def __exit__(self, *args):
            pass
    return Capture


def score_row(session, person, arc, ada):
    return {'session_id': session, 'source_sha256': hashlib.sha256(session.encode()).hexdigest(),
            'person_id': person, 'arcface': arc, 'adaface': ada}


def score_dataset(split):
    encounters = []
    for i in range(12):
        encounters.extend([
            score_row(f'{split}-a-{i}', 'a', {'a': .9, 'b': .1}, {'a': .85, 'b': .05}),
            score_row(f'{split}-b-{i}', 'b', {'a': .1, 'b': .9}, {'a': .05, 'b': .85})])
        if split != 'conformal':
            encounters.append(score_row(f'{split}-u-{i}', None, {'a': .1, 'b': .15}, {'a': .05, 'b': .1}))
    return {'binding': '0'*64, 'prefix_s': 1., 'encounters': encounters}
