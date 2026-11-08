import json
from types import SimpleNamespace
import cv2
import numpy as np
import torch
from src.cli import check_encoders
from src.vision import arcface as vision, encoders


def test_offline_encoder_check_reports_no_embeddings(tmp_path, monkeypatch, capsys):
    class Vision:
        def __init__(self, *args):
            pass
        def aligned_face(self, image):
            return image, .9
    class Encoders:
        hashes = ['a'*64, 'b'*64]
        adaface = torch.nn.Identity()
        magface = torch.nn.Identity()
        def __init__(self, *args):
            pass
        def encode(self, image):
            return {'adaface': np.ones(512)/np.sqrt(512), 'magface_norm': 30.}
    monkeypatch.setattr(vision, 'Vision', Vision)
    monkeypatch.setattr(encoders, 'FaceEncoders', Encoders)
    image = tmp_path/'image.png'
    cv2.imwrite(str(image), np.zeros((112,112,3), dtype=np.uint8))
    args = SimpleNamespace(image=image,detector=None,recognizer=None,adaface=image,magface=image)
    check_encoders.execute(args)
    report = json.loads(capsys.readouterr().out)
    assert report['adaface_dimension'] == 512
    assert report['magface_raw_norm'] == 30.
    assert 'adaface' not in report and 'embedding' not in report
