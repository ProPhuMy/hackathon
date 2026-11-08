import numpy as np
from src.detection import FaceDetection, fuse_faces


def face(box, confidence=.9, points=None):
    return FaceDetection(np.array(box, dtype=float), confidence, points)


def test_single_detector_face_survives_with_its_landmarks():
    points = np.array([[20, 20], [40, 20], [30, 30], [22, 40], [38, 40]], dtype=float)
    result = fuse_faces([face([10, 10, 50, 50], points=points)], [], (100, 100))
    assert len(result) == 1
    assert np.allclose(result[0].box, [10, 10, 50, 50])
    assert np.array_equal(result[0].landmarks, points)


def test_box_coordinates_fuse_but_landmarks_keep_source_ownership():
    a = np.array([[20, 20], [40, 20], [30, 30], [22, 40], [38, 40]], dtype=float)
    b = a + 1
    result = fuse_faces([face([10, 10, 50, 50], .9, a)], [face([12, 12, 52, 52], .8, b)], (100, 100))
    assert len(result) == 1
    assert np.allclose(result[0].box, (np.array([10, 10, 50, 50])*.9 + np.array([12, 12, 52, 52])*.8)/1.7)
    assert np.array_equal(result[0].landmarks, a)


def test_distinct_faces_do_not_exchange_landmarks():
    a = np.array([[20, 20], [40, 20], [30, 30], [22, 40], [38, 40]], dtype=float)
    b = a + [50, 0]
    result = fuse_faces([face([10, 10, 50, 50], .9, a), face([60, 10, 100, 50], .8, b)], [], (100, 120))
    assert len(result) == 2
    for detection in result:
        assert np.array_equal(detection.landmarks, a if detection.box[0] < 50 else b)


def test_invalid_detections_and_landmarks_cannot_contribute_identity():
    result = fuse_faces([face([0, 0, float('nan'), 10]), face([10, 10, 5, 5]),
                         face([-10, -10, 30, 30], points=np.full((5, 2), float('nan')))], [], (100, 100))
    assert len(result) == 1
    assert np.allclose(result[0].box, [0, 0, 30, 30])
    assert result[0].landmarks is None


def test_ties_prefer_scrfd_and_empty_frames_are_valid():
    a = np.array([[20, 20], [40, 20], [30, 30], [22, 40], [38, 40]], dtype=float)
    result = fuse_faces([face([10, 10, 50, 50], .9, a)], [face([10, 10, 50, 50], .9, a+1)], (100, 100))
    assert np.array_equal(result[0].landmarks, a)
    assert fuse_faces([], [], (100, 100)) == []


def test_ambiguous_source_landmarks_are_withheld(monkeypatch):
    from src import detection
    monkeypatch.setattr(detection, 'weighted_boxes_fusion', lambda *args, **kwargs:
                        (np.array([[.1, .1, .6, .6], [.2, .1, .7, .6]]), [.9, .9], [0, 0]))
    points = np.array([[25, 20], [45, 20], [35, 30], [27, 40], [43, 40]], dtype=float)
    result = fuse_faces([face([15, 10, 65, 60], points=points)], [], (100, 100))
    assert len(result) == 2
    assert all(face.landmarks is None for face in result)
