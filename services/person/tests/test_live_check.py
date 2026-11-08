import json
from types import SimpleNamespace
import numpy as np
import pytest
from fridge_person.main import check_camera


def test_live_check_outputs_only_aggregate_diagnostics(monkeypatch, capsys):
    from fridge_person import capture, vision, main
    class Vision:
        def __init__(self, *args):
            pass
        def single_face(self, image):
            return np.ones(512), .9
    class Capture:
        def __init__(self, *args):
            pass
        def __enter__(self):
            return iter([(None, 100., None), ('image', 99.9, 'timestamp'), ('stale', 90., 'timestamp')])
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(vision, 'Vision', Vision)
    monkeypatch.setattr(capture, 'Capture', Capture)
    monkeypatch.setattr(main.time, 'monotonic', lambda: 100.)
    check_camera(SimpleNamespace(duration=1., source='0', detector=None, recognizer=None))
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
        check_camera(SimpleNamespace(duration=duration))
