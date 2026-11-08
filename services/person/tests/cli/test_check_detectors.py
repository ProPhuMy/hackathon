import json
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
from src.cli import check_detectors
import src.vision.yolo5face as yolo5face_module
from src.vision.detection import FaceDetection


def test_check_detectors_cli_errors_and_aggregate_only_output(tmp_path, monkeypatch, capsys):
    image_path = tmp_path / 'face.jpg'
    cv2.imwrite(str(image_path), np.zeros((640, 640, 3), dtype=np.uint8))

    scrfd_path = tmp_path / 'det_10g.onnx'
    scrfd_path.write_bytes(b'scrfd-weights')
    yolo_path = tmp_path / 'yolov5s-face.onnx'
    yolo_path.write_bytes(b'yolo-weights')

    # Missing file error
    missing_args = SimpleNamespace(
        command='check-detectors',
        image=tmp_path / 'nonexistent.jpg',
        scrfd=scrfd_path,
        detector=scrfd_path,
        yolo5face=yolo_path
    )
    with pytest.raises(ValueError, match='Missing local file'):
        check_detectors.execute(missing_args)

    class MockScrfd:
        def prepare(self, *args, **kwargs):
            pass

        def detect(self, image, max_num=0):
            boxes = np.array([[100.0, 100.0, 200.0, 200.0, 0.95]])
            landmarks = np.array([[[120.0, 130.0], [180.0, 130.0], [150.0, 150.0], [130.0, 180.0], [170.0, 180.0]]])
            return boxes, landmarks

    class MockYOLO5Face:
        def __init__(self, *args, **kwargs):
            pass

        def detect(self, image):
            pts = np.array([[120.0, 130.0], [180.0, 130.0], [150.0, 150.0], [130.0, 180.0], [170.0, 180.0]])
            return [FaceDetection(np.array([100.0, 100.0, 200.0, 200.0]), 0.90, pts)]

    from insightface import model_zoo
    monkeypatch.setattr(model_zoo, 'get_model', lambda *args, **kwargs: MockScrfd())
    # Monkeypatch the exact dependency boundary in both yolo5face module and main
    monkeypatch.setattr(yolo5face_module, 'YOLO5Face', MockYOLO5Face)
    monkeypatch.setattr(check_detectors, 'YOLO5Face', MockYOLO5Face, raising=False)

    valid_args = SimpleNamespace(
        command='check-detectors',
        image=image_path,
        scrfd=scrfd_path,
        detector=scrfd_path,
        yolo5face=yolo_path
    )
    check_detectors.execute(valid_args)

    output = capsys.readouterr().out
    report = json.loads(output)

    assert report['provider'] == 'CPUExecutionProvider'
    assert report['image_shape'] == [640, 640, 3]
    assert report['scrfd_count'] == 1
    assert report['yolo5face_count'] == 1
    assert report['fused_count'] == 1
    assert report['fused_two_detector_count'] == 1
    assert report['warm_samples'] == 5
    assert 'p50_total_ms' in report
    assert len(report['models']) == 2

    # Aggregate only check
    for key in report.keys():
        assert 'landmark' not in key or 'with_landmarks' in key or 'count' in key
    assert 'box' not in report and 'landmarks' not in report and 'embedding' not in report


def test_check_detectors_rejects_incompatible_scrfd_model(tmp_path, monkeypatch):
    image_path = tmp_path / 'face.jpg'
    cv2.imwrite(str(image_path), np.zeros((640, 640, 3), dtype=np.uint8))
    scrfd_path = tmp_path / 'rec_model.onnx'
    scrfd_path.write_bytes(b'dummy-rec')
    yolo_path = tmp_path / 'yolov5s-face.onnx'
    yolo_path.write_bytes(b'dummy-yolo')

    # Case 1: Model is a recognition model (taskname = 'recognition' and no detect)
    class MockRecognitionModel:
        taskname = 'recognition'

        def get_feat(self, crop):
            return np.zeros(512)

    from insightface import model_zoo
    monkeypatch.setattr(model_zoo, 'get_model', lambda *args, **kwargs: MockRecognitionModel())

    args = SimpleNamespace(
        command='check-detectors',
        image=image_path,
        scrfd=scrfd_path,
        detector=scrfd_path,
        yolo5face=yolo_path
    )
    with pytest.raises(ValueError, match='Incompatible SCRFD model'):
        check_detectors.execute(args)

    # Case 2: Model object has no detect method
    class MockModelWithoutDetect:
        pass

    monkeypatch.setattr(model_zoo, 'get_model', lambda *args, **kwargs: MockModelWithoutDetect())
    with pytest.raises(ValueError, match='Incompatible SCRFD model'):
        check_detectors.execute(args)


def test_check_detectors_with_junk_files_raises_value_error(tmp_path, monkeypatch):
    image_path = tmp_path / 'face.jpg'
    cv2.imwrite(str(image_path), np.zeros((640, 640, 3), dtype=np.uint8))
    valid_yolo = tmp_path / 'yolo.onnx'
    valid_yolo.write_bytes(b'dummy-yolo')
    junk_file = tmp_path / 'corrupt.onnx'
    junk_file.write_bytes(b'THIS_IS_NOT_A_VALID_ONNX_MODEL_FILE')

    # Junk SCRFD model fails with ValueError
    args_junk_scrfd = SimpleNamespace(
        command='check-detectors',
        image=image_path,
        scrfd=junk_file,
        detector=junk_file,
        yolo5face=valid_yolo
    )
    with pytest.raises(ValueError, match='Failed to load SCRFD model'):
        check_detectors.execute(args_junk_scrfd)

    # Junk YOLO5Face model fails with ValueError
    class MockScrfd:
        taskname = 'detection'

        def prepare(self, *args, **kwargs):
            pass

        def detect(self, *args, **kwargs):
            return np.zeros((0, 5)), np.zeros((0, 5, 2))

    from insightface import model_zoo
    monkeypatch.setattr(model_zoo, 'get_model', lambda *args, **kwargs: MockScrfd())

    args_junk_yolo = SimpleNamespace(
        command='check-detectors',
        image=image_path,
        scrfd=junk_file,
        detector=junk_file,
        yolo5face=junk_file
    )
    with pytest.raises(ValueError, match='Failed to load ONNX model'):
        check_detectors.execute(args_junk_yolo)
