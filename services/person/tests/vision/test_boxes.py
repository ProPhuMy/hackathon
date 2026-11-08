import numpy as np
from src.vision.boxes import letterbox, nms


def test_nms_at_zero_iou_threshold_does_not_suppress_nonoverlapping():
    # Disjoint boxes: IoU is 0.0
    boxes = np.array([[10.0, 10.0, 50.0, 50.0], [100.0, 100.0, 150.0, 150.0]], dtype=float)
    scores = np.array([0.9, 0.85])

    # At iou_threshold=0.0, non-overlapping boxes must NOT be suppressed
    keep = nms(boxes, scores, iou_threshold=0.0)
    assert len(keep) == 2
    assert set(keep.tolist()) == {0, 1}

    # Partially overlapping boxes: IoU > 0.0, so at iou_threshold=0.0, lower confidence is suppressed
    overlapping = np.array([[10.0, 10.0, 50.0, 50.0], [20.0, 20.0, 60.0, 60.0]], dtype=float)
    keep_overlap = nms(overlapping, scores, iou_threshold=0.0)
    assert len(keep_overlap) == 1 and keep_overlap[0] == 0


def test_letterbox_roundtrip_square_and_nonsquare():
    test_shapes = [(640, 640), (480, 640), (720, 1280), (1000, 500), (200, 600)]
    for h, w in test_shapes:
        img = np.zeros((h, w, 3), dtype=np.uint8)
        padded, gain, pad = letterbox(img, (640, 640))
        assert padded.shape == (640, 640, 3)
        left, top = pad
        assert 0 <= left <= 640 and 0 <= top <= 640

        pts_orig = np.array([[0.0, 0.0], [w / 2.0, h / 2.0], [float(w - 1), float(h - 1)]])
        pts_letterbox = pts_orig * gain + np.array([left, top])
        pts_recovered = (pts_letterbox - np.array([left, top])) / gain
        assert np.allclose(pts_orig, pts_recovered, atol=1e-5)
