import json
from types import SimpleNamespace
import cv2
import numpy as np
from src.cli import calibrate
from src.identity.gallery import Gallery
from src.vision import arcface as vision


def test_calibrate_and_evaluate_video_manifests_end_to_end(tmp_path, monkeypatch, capsys):
    class Vision:
        signature = 'synthetic-model'
        def __init__(self, *args):
            pass
        def single_face(self, image):
            brightness = image.mean()
            vector = [1., 0.] if brightness < 100 else [0., 1.] if brightness < 200 else [-1., 0.]
            return np.array(vector), 1.
    monkeypatch.setattr(vision, 'Vision', Vision)
    gallery = Gallery(tmp_path / 'gallery.json', Vision.signature)
    gallery.enroll('a', [[1., 0.]] * 10)
    gallery.enroll('b', [[0., 1.]] * 10)
    manifests = {}
    for split, delta in [('development', 0), ('test', 10)]:
        rows = ['path,person_id,session_id,split,start_s,end_s']
        for index, (person, brightness) in enumerate([('a', 40), ('b', 140), ('', 230)]):
            path = tmp_path / f'{split}-{index}.avi'
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 5, (64, 64))
            assert writer.isOpened()
            for _ in range(5):
                writer.write(np.full((64, 64, 3), brightness + delta, dtype=np.uint8))
            writer.release()
            rows.append(f'{path.name},{person},{split}-{index},{split},0,1')
        manifest = tmp_path / f'{split}.csv'
        manifest.write_text('\n'.join(rows) + '\n')
        manifests[split] = manifest
    policy = tmp_path / 'policy.json'
    args = SimpleNamespace(command='calibrate', detector=None, recognizer=None, gallery=gallery.path,
                           manifest=manifests['development'], output=policy)
    calibrate.execute(args)
    assert json.loads(policy.read_text())['development_metrics']['known_correct'] == 2
    args.command = 'evaluate'
    args.policy = policy
    args.manifest = manifests['test']
    args.output = tmp_path / 'report.json'
    calibrate.execute(args)
    report = json.loads(args.output.read_text())
    assert report['known_correct'] == report['known_total'] == 2
    assert report['unknown_false_accepts'] == 0
    assert report['unknown_total'] == 1
