import json
from types import SimpleNamespace
import numpy as np
import pytest
from conftest import fake_capture
from src.cli import check_camera


def test_live_check_outputs_only_aggregate_diagnostics(monkeypatch, capsys):
    from src import capture
    from src.vision import arcface as vision
    class Vision:
        provider = 'CPUExecutionProvider'
        def __init__(self, *args):
            pass
        def single_face(self, image):
            return np.ones(512), .9
    Capture = fake_capture([(None, 100., None), ('image', 99.9, 'timestamp'), ('stale', 90., 'timestamp')])
    monkeypatch.setattr(vision, 'Vision', Vision)
    monkeypatch.setattr(capture, 'Capture', Capture)
    monkeypatch.setattr(check_camera.time, 'monotonic', lambda: 100.)
    check_camera.execute(SimpleNamespace(duration=1., source='0', rotate=0, detector=None, recognizer=None))
    report = json.loads(capsys.readouterr().out)
    assert report['decoded_frames'] == 2
    assert report['usable_single_face_frames'] == 1
    assert report['stale_frames'] == report['reconnects'] == 1
    assert 'embeddings' not in report
    assert 'images' not in report
    assert 'person_id' not in report


@pytest.mark.parametrize('duration', [0., -1., float('nan'), float('inf')])
def test_live_check_rejects_invalid_duration(duration):
    with pytest.raises(ValueError, match='duration'):
        check_camera.execute(SimpleNamespace(duration=duration))
