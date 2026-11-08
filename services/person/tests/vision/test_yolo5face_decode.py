import numpy as np
import pytest
from conftest import make_detector


def test_end_to_end_nonsquare_decode_and_landmark_pairing(tmp_path, monkeypatch):
    # Non-square wide image: 480 height x 640 width
    # Letterbox to (640, 640): gain=1.0, pad=(left=0, top=80)
    img_wide = np.zeros((480, 640, 3), dtype=np.uint8)

    # Ground truth coordinates in original 480x640 space
    box1 = np.array([50.0, 40.0, 150.0, 160.0])
    lm1 = np.array([[80.0, 80.0], [120.0, 80.0], [100.0, 100.0], [85.0, 130.0], [115.0, 130.0]])

    box2 = np.array([400.0, 200.0, 550.0, 380.0])
    lm2 = np.array([[440.0, 260.0], [510.0, 260.0], [475.0, 290.0], [450.0, 340.0], [500.0, 340.0]])

    # Transformed to letterbox space: y_lb = y_orig * 1.0 + 80, x_lb = x_orig * 1.0 + 0
    cx1, cy1 = 100.0, 100.0 + 80.0
    w1, h1 = 100.0, 120.0
    lm1_lb = lm1 + np.array([0.0, 80.0])

    cx2, cy2 = 475.0, 290.0 + 80.0
    w2, h2 = 150.0, 180.0
    lm2_lb = lm2 + np.array([0.0, 80.0])

    raw = np.zeros((1, 2, 16), dtype=np.float32)
    raw[0, 0, 0:4] = [cx1, cy1, w1, h1]
    raw[0, 0, 4] = 0.95
    raw[0, 0, 5:15] = lm1_lb.reshape(-1)
    raw[0, 0, 15] = 1.0

    raw[0, 1, 0:4] = [cx2, cy2, w2, h2]
    raw[0, 1, 4] = 0.90
    raw[0, 1, 5:15] = lm2_lb.reshape(-1)
    raw[0, 1, 15] = 1.0

    detector = make_detector(tmp_path, monkeypatch, raw)
    dets = detector.detect(img_wide)
    assert len(dets) == 2

    # Verify Face 1 decoded box and landmarks
    det1 = next(d for d in dets if d.box[0] < 200)
    assert np.allclose(det1.box, box1, atol=1e-4)
    assert det1.landmarks is not None
    assert np.allclose(det1.landmarks, lm1, atol=1e-4)
    assert det1.confidence == pytest.approx(0.95)

    # Verify Face 2 decoded box and landmarks
    det2 = next(d for d in dets if d.box[0] > 300)
    assert np.allclose(det2.box, box2, atol=1e-4)
    assert det2.landmarks is not None
    assert np.allclose(det2.landmarks, lm2, atol=1e-4)
    assert det2.confidence == pytest.approx(0.90)

    # Non-square tall image: 1000 height x 500 width
    # Letterbox to (640, 640): gain = 0.64, left = (640 - 320)/2 = 160, top = 0
    img_tall = np.zeros((1000, 500, 3), dtype=np.uint8)
    box_tall = np.array([100.0, 200.0, 300.0, 600.0])
    lm_tall = np.array([[160.0, 300.0], [240.0, 300.0], [200.0, 400.0], [170.0, 500.0], [230.0, 500.0]])

    gain_tall = 0.64
    pad_left = 160.0
    cx_t = 200.0 * gain_tall + pad_left
    cy_t = 400.0 * gain_tall
    w_t = 200.0 * gain_tall
    h_t = 400.0 * gain_tall
    lm_t_lb = lm_tall * gain_tall + np.array([pad_left, 0.0])

    raw_tall = np.zeros((1, 1, 16), dtype=np.float32)
    raw_tall[0, 0, 0:4] = [cx_t, cy_t, w_t, h_t]
    raw_tall[0, 0, 4] = 0.92
    raw_tall[0, 0, 5:15] = lm_t_lb.reshape(-1)
    raw_tall[0, 0, 15] = 1.0

    det_tall = make_detector(tmp_path, monkeypatch, raw_tall).detect(img_tall)
    assert len(det_tall) == 1
    assert np.allclose(det_tall[0].box, box_tall, atol=1e-4)
    assert np.allclose(det_tall[0].landmarks, lm_tall, atol=1e-4)


def test_rgb_channel_scaling_in_preprocess(tmp_path, monkeypatch):
    detector = make_detector(tmp_path, monkeypatch, np.zeros((1, 0, 16), dtype=np.float32))
    img = np.zeros((640, 640, 3), dtype=np.uint8)
    # Set distinctive colors in OpenCV BGR
    img[10, 10] = [255, 0, 0]  # Pure Blue
    img[10, 11] = [0, 255, 0]  # Pure Green
    img[10, 12] = [0, 0, 255]  # Pure Red

    tensor, gain, pad = detector.preprocess(img)
    assert tensor.shape == (1, 3, 640, 640)
    assert tensor.dtype == np.float32
    assert 0.0 <= tensor.min() <= tensor.max() <= 1.0

    left, top = pad
    # Blue in BGR is channel 2 in RGB, scaled to 1.0
    assert tensor[0, 2, top + 10, left + 10] == pytest.approx(1.0)
    assert tensor[0, 0, top + 10, left + 10] == pytest.approx(0.0)

    # Green in BGR is channel 1 in RGB
    assert tensor[0, 1, top + 10, left + 11] == pytest.approx(1.0)
    assert tensor[0, 0, top + 10, left + 11] == pytest.approx(0.0)

    # Red in BGR is channel 0 in RGB
    assert tensor[0, 0, top + 10, left + 12] == pytest.approx(1.0)
    assert tensor[0, 2, top + 10, left + 12] == pytest.approx(0.0)


def test_confidence_math_validates_each_probability_independently(tmp_path, monkeypatch):
    raw = np.zeros((1, 4, 16), dtype=np.float32)

    # Candidate 0: obj_conf=-0.9 and cls_conf=-0.8 (product is +0.72, but probabilities are invalid!)
    raw[0, 0, 0:4] = [320, 320, 100, 100]
    raw[0, 0, 4] = -0.9
    raw[0, 0, 15] = -0.8

    # Candidate 1: obj_conf=1.2 (>1.0) and cls_conf=0.5
    raw[0, 1, 0:4] = [200, 200, 80, 80]
    raw[0, 1, 4] = 1.2
    raw[0, 1, 15] = 0.5

    # Candidate 2: obj_conf=0.9 and cls_conf=0.2 (product is 0.18, below threshold 0.3)
    raw[0, 2, 0:4] = [100, 100, 50, 50]
    raw[0, 2, 4] = 0.9
    raw[0, 2, 15] = 0.2

    # Candidate 3: obj_conf=0.9 and cls_conf=0.8 (product 0.72, valid and above threshold)
    raw[0, 3, 0:4] = [400, 400, 90, 90]
    raw[0, 3, 4] = 0.9
    raw[0, 3, 15] = 0.8

    detector = make_detector(tmp_path, monkeypatch, raw, conf_threshold=0.3)
    dets = detector.detect(np.zeros((640, 640, 3), dtype=np.uint8))
    assert len(dets) == 1
    assert dets[0].confidence == pytest.approx(0.72)


def test_empty_detections_returns_empty_list(tmp_path, monkeypatch):
    img = np.zeros((480, 640, 3), dtype=np.uint8)

    detector = make_detector(tmp_path, monkeypatch, np.zeros((1, 0, 16), dtype=np.float32))
    assert detector.detect(img) == []

    raw = np.zeros((1, 5, 16), dtype=np.float32)
    raw[0, :, 4] = 0.1
    raw[0, :, 15] = 0.2
    detector_low = make_detector(tmp_path, monkeypatch, raw, conf_threshold=0.3)
    assert detector_low.detect(img) == []


def test_invalid_outputs_and_inputs_raise_errors(tmp_path, monkeypatch):
    img = np.zeros((640, 640, 3), dtype=np.uint8)

    # Non-finite values
    raw = np.zeros((1, 5, 16), dtype=np.float32)
    raw[0, 0, 0] = float('nan')
    detector = make_detector(tmp_path, monkeypatch, raw)
    with pytest.raises(ValueError, match='non-finite'):
        detector.detect(img)

    # Non-floating output array
    raw_int = np.zeros((1, 5, 16), dtype=np.int32)
    detector_int = make_detector(tmp_path, monkeypatch, raw_int)
    with pytest.raises(ValueError, match='floating point'):
        detector_int.detect(img)

    # Invalid input images
    valid_detector = make_detector(tmp_path, monkeypatch, np.zeros((1, 0, 16), dtype=np.float32))
    for bad_input in [None, np.zeros((100, 100)), np.zeros((100, 100, 4), dtype=np.uint8), np.zeros((100, 100, 3), dtype=float)]:
        with pytest.raises(ValueError, match='Invalid input image'):
            valid_detector.detect(bad_input)
