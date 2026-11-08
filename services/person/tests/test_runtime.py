"""Exercise orchestration with deterministic observations; no hardware required."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import numpy as np
import pytest
from fridge_person import runtime
from fridge_person.gallery import Gallery


def setup_runtime(tmp_path, monkeypatch, frames, command='run'):
    class Vision:
        signature = 'test-model'
        def __init__(self, *args):
            pass
        def single_face(self, image):
            return image
    class Capture:
        def __init__(self, *args):
            pass
        def __enter__(self):
            return iter(frames)
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(runtime, 'Vision', Vision)
    monkeypatch.setattr(runtime, 'Capture', Capture)
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: 100.)
    gallery = Gallery(tmp_path / 'gallery.json', Vision.signature)
    gallery.enroll('a', [[1., 0.]] * 10)
    policy = tmp_path / 'policy.json'
    policy.write_text(json.dumps(dict(model=Vision.signature, gallery=gallery.fingerprint,
                                     development_manifest='dev.csv', accept=.8, reject=.2, margin=.1)))
    return SimpleNamespace(command=command, detector=None, recognizer=None, gallery=gallery.path,
                           person_id='b', source='fake', replay_origin='2026-01-01T00:00:00Z',
                           broker=None, policy=policy,
                           schema=runtime.Path('../../contracts/person.seen.schema.json'))


def frame(t, vector=(1., 0.)):
    return ((np.array(vector), 1.), 100., f'2026-01-01T00:00:{t:06.3f}Z')


def test_replay_heartbeat_uses_video_time(tmp_path, monkeypatch, capsys):
    args = setup_runtime(tmp_path, monkeypatch, [frame(t) for t in (0., .2, .4, .6, .8, 1., 1.2)])
    runtime.execute(args)
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(events) == 2
    assert events[0]['ts'].endswith('00.400Z')
    assert events[1]['ts'].endswith('01.000Z')


def test_enrollment_cannot_combine_different_people(tmp_path, monkeypatch):
    frames = [frame(i * .2) for i in range(10)] + [frame(2. + i * .2, (-1., 0.)) for i in range(10)]
    args = setup_runtime(tmp_path, monkeypatch, frames, command='enroll')
    with pytest.raises(ValueError, match='Enrollment incomplete'):
        runtime.execute(args)
    assert 'b' not in Gallery(args.gallery, 'test-model').people


def test_gallery_revocation_stops_active_run(tmp_path, monkeypatch):
    def frames():
        yield frame(0.)
        Gallery(args.gallery, 'test-model').remove('a')
        yield frame(.2)
    args = setup_runtime(tmp_path, monkeypatch, frames())
    with pytest.raises(ValueError, match='Gallery changed'):
        runtime.execute(args)


def test_confidence_changes_do_not_bypass_heartbeat_limit(tmp_path, monkeypatch, capsys):
    frames = [frame(t, (1., .01 * i)) for i, t in enumerate((0., .2, .4, .6, .8, 1., 1.2))]
    args = setup_runtime(tmp_path, monkeypatch, frames)
    runtime.execute(args)
    assert len(capsys.readouterr().out.splitlines()) == 2


def test_successful_enrollment_retains_no_images(tmp_path, monkeypatch, capsys):
    args = setup_runtime(tmp_path, monkeypatch, [frame(i * .2) for i in range(20)], command='enroll')
    args.session_id = 'enrollment-test'
    runtime.execute(args)
    gallery = Gallery(args.gallery, 'test-model')
    assert 'b' in gallery.people
    assert gallery.provenance['b']['session_id'] == 'enrollment-test'
    assert not list(tmp_path.glob('*.jpg'))


def test_failed_broker_callback_is_not_reported_as_success(tmp_path, monkeypatch):
    import confluent_kafka
    class Producer:
        def __init__(self, config):
            assert config['enable.idempotence'] is True
            self.payload = None
        def produce(self, topic, key, value, on_delivery):
            self.payload = json.loads(value)
            assert key == self.payload['event_id']
            on_delivery('broker unavailable', None)
        def flush(self, timeout):
            return 0
    monkeypatch.setattr(confluent_kafka, 'Producer', Producer)
    args = setup_runtime(tmp_path, monkeypatch, [frame(t) for t in (0., .2, .4)])
    args.broker = 'fake-broker'
    with pytest.raises(RuntimeError, match='delivery failed'):
        runtime.execute(args)
