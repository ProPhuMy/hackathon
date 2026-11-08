import numpy as np
from src.vision import Vision


def fixture():
    vision = Vision.__new__(Vision)
    box = np.array([[40.,30.,145.,160.,.93]])
    points = np.array([[[65.,65.],[115.,65.],[90.,90.],[70.,125.],[110.,125.]]])
    class Detector:
        def detect(self, image, max_num):
            return box, points
    class Encoder:
        calls = 0
        def get_feat(self, crop):
            self.calls += 1
            assert crop.shape == (112,112,3)
            return np.arange(512,dtype=float)[None,:]
    vision.detector = Detector()
    vision.encoder = Encoder()
    image = np.random.default_rng(0).integers(0,256,(180,180,3),dtype=np.uint8)
    return vision, image, points


def test_single_face_behavior_preserved():
    vision, image, _ = fixture()
    vector, confidence = vision.single_face(image)
    expected = np.arange(512,dtype=float)
    expected /= np.linalg.norm(expected)
    assert np.array_equal(vector, expected)
    assert confidence == .93
    assert vision.encoder.calls == 1


def test_invalid_landmarks_never_reach_encoder():
    vision, image, points = fixture()
    points[0,0,0] = np.nan
    assert vision.single_face(image) is None
    assert vision.encoder.calls == 0
