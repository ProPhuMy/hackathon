"""Exercise orchestration with deterministic observations; no hardware required."""
import json
from types import SimpleNamespace
import numpy as np
import pytest
from conftest import SCHEMA_PATH, fake_capture
from src.cli import run as runtime
from src.identity.gallery import Gallery


def setup_runtime(tmp_path, monkeypatch, frames, command='run'):
    class Vision:
        signature = 'test-model'
        def __init__(self, *args):
            pass
        def single_face(self, image):
            return image
    Capture = fake_capture(frames)
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
                           schema=SCHEMA_PATH)


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


def test_remove_does_not_need_model_weights_or_camera(tmp_path, monkeypatch):
    args = setup_runtime(tmp_path, monkeypatch, [], command='remove')
    args.person_id = 'a'
    def unavailable(*args):
        raise AssertionError('Removal must not load face models')
    monkeypatch.setattr(runtime, 'Vision', unavailable)
    runtime.execute(args)
    assert Gallery(args.gallery, 'test-model').people == {}


def test_reconnect_boundary_requires_fresh_evidence_and_segment(tmp_path, monkeypatch, capsys):
    frames = [frame(t) for t in (0., .2, .4)]
    frames += [(None, 100., None)]
    frames += [frame(t) for t in (.6, .8, 1.)]
    args = setup_runtime(tmp_path, monkeypatch, frames)
    runtime.execute(args)
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(events) == 2
    assert events[1]['track_id'] != events[0]['track_id']
    assert events[1]['ts'].endswith('01.000Z')


def setup_ensemble(tmp_path, monkeypatch, ada_live=(0., 1.), ada_enrolled=(0., 1.), ada_model='test-ada', frames=None):
    """ArcFace and AdaFace live in different spaces: ArcFace sees [1, 0], AdaFace sees ada_live."""
    class Vision:
        signature = 'test-model'
        def __init__(self, *args):
            pass
        def single_face(self, image):
            return image  # lets the pre-fix code reach scoring, so these tests fail for the right reason
        def aligned_face(self, image):
            return image  # (crop, confidence); the fake crop is the ArcFace vector
        def encode(self, crop):
            return crop
    class FaceEncoders:
        signature = 'test-ada'
        def __init__(self, *args):
            pass
        def encode(self, crop):
            return {'adaface': np.array(ada_live), 'magface_norm': 20.}
    Capture = fake_capture(frames if frames is not None else [
        ((np.array([1., 0.]), 1.), 100., f'2026-01-01T00:00:0{i:05.3f}Z')
        for i in range(6)
    ])
    monkeypatch.setattr(runtime, 'Vision', Vision)
    monkeypatch.setattr(runtime, 'Capture', Capture)
    monkeypatch.setattr('src.vision.encoders.FaceEncoders', FaceEncoders)
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: 100.)

    g_arc = Gallery(tmp_path / 'gallery.json', Vision.signature)
    g_arc.enroll('a', [[1., 0.]] * 10)
    g_ada = Gallery(tmp_path / 'gallery_adaface.json', ada_model)
    g_ada.enroll('a', [list(ada_enrolled)] * 10)

    policy = {
        'version': 1, 'alpha': 0.1, 'prefix_s': 1.0, 'binding': '0' * 64,
        'identities': ['a'], 'coefficients': [2.0, 2.0], 'intercept': 0.0,
        'gates': {'accept': 0.5, 'reject': 0.2, 'margin': 0.0},
        'conformal': {'a': [0.1] * 10}, 'development_manifest': 'dev.csv',
        'gallery': g_arc.fingerprint, 'model': Vision.signature,
        'ada_gallery': g_ada.fingerprint, 'ada_model': FaceEncoders.signature,
    }
    policy_path = tmp_path / 'ensemble_policy.json'
    policy_path.write_text(json.dumps(policy))
    args = SimpleNamespace(
        command='run', detector=None, recognizer=None, gallery=g_arc.path, ada_gallery=g_ada.path,
        adaface=None, magface=None, person_id=None, source='fake',
        replay_origin='2026-01-01T00:00:00Z', broker=None, policy=policy_path, schema=SCHEMA_PATH)
    return args, policy, policy_path


def test_ensemble_runtime_conformal_decision_and_dispatch(tmp_path, monkeypatch, capsys):
    # AdaFace vectors differ from ArcFace ones. Scoring the AdaFace gallery with the ArcFace vector
    # (the old bug) gives cosine 0 there, fused 0.88, no conformal candidate, and no event.
    args, _, _ = setup_ensemble(tmp_path, monkeypatch)
    runtime.execute(args)
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(events) >= 1
    assert events[0]['person_id'] == 'a'
    assert events[0]['confidence'] > 0.5


def test_ensemble_requires_an_adaface_gallery(tmp_path, monkeypatch):
    args, _, _ = setup_ensemble(tmp_path, monkeypatch)
    args.ada_gallery.unlink()
    with pytest.raises(ValueError, match='needs an AdaFace gallery'):
        runtime.execute(args)


def test_ensemble_rejects_adaface_gallery_from_another_model(tmp_path, monkeypatch):
    args, _, _ = setup_ensemble(tmp_path, monkeypatch, ada_model='other-ada-model')
    with pytest.raises(ValueError, match='model/preprocessing mismatch'):
        runtime.execute(args)


@pytest.mark.parametrize('key', ['ada_gallery', 'ada_model'])
def test_ensemble_policy_must_bind_the_adaface_gallery(tmp_path, monkeypatch, key):
    args, policy, policy_path = setup_ensemble(tmp_path, monkeypatch)
    policy[key] = 'stale'
    policy_path.write_text(json.dumps(policy))
    with pytest.raises(ValueError, match='AdaFace gallery/model'):
        runtime.execute(args)


def test_ensemble_policy_identities_must_match_both_galleries(tmp_path, monkeypatch):
    args, policy, policy_path = setup_ensemble(tmp_path, monkeypatch)
    policy['identities'] = ['a', 'b']
    policy['conformal']['b'] = [0.1] * 10
    policy_path.write_text(json.dumps(policy))
    with pytest.raises(ValueError, match='identities must match'):
        runtime.execute(args)


def test_adaface_gallery_change_stops_active_run(tmp_path, monkeypatch):
    def frames():
        yield frame(0.)
        Gallery(tmp_path / 'gallery_adaface.json', 'test-ada').remove('a')
        yield frame(.2)
    args, _, _ = setup_ensemble(tmp_path, monkeypatch, frames=frames())
    with pytest.raises(ValueError, match='Gallery changed'):
        runtime.execute(args)
