import json
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
import onnxruntime as ort
import pytest

from src.vision.detection import FaceDetection, fuse_faces
from src.vision.yolo5face import YOLO5Face, letterbox, nms
import src.vision.yolo5face as yolo5face_module
import src.main as main_module


class MockTensorInfo:
    def __init__(self, name, shape, tensor_type='tensor(float)'):
        self.name = name
        self.shape = shape
        self.type = tensor_type


class MockSessionDouble:
    def __init__(self, raw_output, input_shape=(1, 3, 640, 640), input_type='tensor(float)', output_shape=None, output_type='tensor(float)'):
        self.raw_output = raw_output
        self._inputs = [MockTensorInfo('input', list(input_shape), input_type)]
        out_shape = list(output_shape) if output_shape is not None else list(raw_output.shape)
        self._outputs = [MockTensorInfo('output', out_shape, output_type)]

    def get_inputs(self):
        return self._inputs

    def get_outputs(self):
        return self._outputs

    def run(self, output_names, input_feed):
        return [self.raw_output]


def make_detector(tmp_path, monkeypatch, raw_output, input_shape=(1, 3, 640, 640), input_type='tensor(float)',
                  output_shape=None, output_type='tensor(float)', conf_threshold=0.3, iou_threshold=0.5, input_size=None):
    model_file = tmp_path / 'yolov5s-face.onnx'
    if not model_file.exists():
        model_file.write_bytes(b'dummy-onnx-model-binary')
    mock_session = MockSessionDouble(raw_output, input_shape=input_shape, input_type=input_type,
                                    output_shape=output_shape, output_type=output_type)
    monkeypatch.setattr(ort, 'InferenceSession', lambda *args, **kwargs: mock_session)
    return YOLO5Face(model_file, conf_threshold=conf_threshold, iou_threshold=iou_threshold, input_size=input_size)


def test_metadata_validation_and_static_input_derivation(tmp_path, monkeypatch):
    dummy_file = tmp_path / 'yolov5s-face.onnx'
    dummy_file.write_bytes(b'dummy-onnx')

    # Multiple inputs rejected
    class MultiInputSession(MockSessionDouble):
        def __init__(self):
            super().__init__(np.zeros((1, 0, 16), dtype=np.float32))
            self._inputs = [MockTensorInfo('inp1', [1, 3, 640, 640]), MockTensorInfo('inp2', [1, 3, 640, 640])]

    monkeypatch.setattr(ort, 'InferenceSession', lambda *args, **kwargs: MultiInputSession())
    with pytest.raises(ValueError, match='exactly 1 model input'):
        YOLO5Face(dummy_file)

    # Multiple outputs rejected
    class MultiOutputSession(MockSessionDouble):
        def __init__(self):
            super().__init__(np.zeros((1, 0, 16), dtype=np.float32))
            self._outputs = [MockTensorInfo('out1', [1, 10, 16]), MockTensorInfo('out2', [1, 10, 16])]

    monkeypatch.setattr(ort, 'InferenceSession', lambda *args, **kwargs: MultiOutputSession())
    with pytest.raises(ValueError, match='exactly 1 model output'):
        YOLO5Face(dummy_file)

    # Non-float32 input rejected
    with pytest.raises(ValueError, match='float32'):
        make_detector(tmp_path, monkeypatch, np.zeros((1, 0, 16), dtype=np.float32), input_type='tensor(int64)')

    # Non-float32 output rejected
    with pytest.raises(ValueError, match='float32'):
        make_detector(tmp_path, monkeypatch, np.zeros((1, 0, 16), dtype=np.float32), output_type='tensor(float16)')

    with pytest.raises(ValueError, match='float32'):
        make_detector(tmp_path, monkeypatch, np.zeros((1, 0, 16), dtype=np.float32), output_type='tensor(int32)')

    # Incompatible input rank rejected
    with pytest.raises(ValueError, match='4-D NCHW'):
        make_detector(tmp_path, monkeypatch, np.zeros((1, 0, 16), dtype=np.float32), input_shape=(1, 3, 640))

    # Incompatible input channels rejected
    with pytest.raises(ValueError, match='3 input channels'):
        make_detector(tmp_path, monkeypatch, np.zeros((1, 0, 16), dtype=np.float32), input_shape=(1, 1, 640, 640))

    # Dynamic or partially dynamic spatial dimensions rejected
    with pytest.raises(ValueError, match='spatial dimensions must be fixed integers'):
        make_detector(tmp_path, monkeypatch, np.zeros((1, 0, 16), dtype=np.float32), input_shape=(1, 3, 320, 'width'))

    with pytest.raises(ValueError, match='spatial dimensions must be fixed integers'):
        make_detector(tmp_path, monkeypatch, np.zeros((1, 0, 16), dtype=np.float32), input_shape=(1, 3, 'height', 640))

    with pytest.raises(ValueError, match='spatial dimensions must be fixed integers'):
        make_detector(tmp_path, monkeypatch, np.zeros((1, 0, 16), dtype=np.float32), input_shape=(1, 3, 'height', 'width'))

    # Spatial dimensions not positive multiples of 32 rejected
    with pytest.raises(ValueError, match='Both dimensions must be positive multiples of 32'):
        make_detector(tmp_path, monkeypatch, np.zeros((1, 0, 16), dtype=np.float32), input_shape=(1, 3, 100, 100))

    with pytest.raises(ValueError, match='Both dimensions must be positive multiples of 32'):
        make_detector(tmp_path, monkeypatch, np.zeros((1, 0, 16), dtype=np.float32), input_shape=(1, 3, 0, 640))

    # Incompatible output rank rejected
    with pytest.raises(ValueError, match='rank-3'):
        make_detector(tmp_path, monkeypatch, np.zeros((1, 16), dtype=np.float32), output_shape=[1, 16])

    # Incompatible output batch rejected
    with pytest.raises(ValueError, match='output batch dimension 1'):
        make_detector(tmp_path, monkeypatch, np.zeros((2, 5, 16), dtype=np.float32), output_shape=[2, 5, 16])

    # Incompatible output columns rejected (e.g. 6 or 85 instead of 16)
    with pytest.raises(ValueError, match='schema'):
        make_detector(tmp_path, monkeypatch, np.zeros((1, 5, 6), dtype=np.float32), output_shape=[1, 5, 6])

    with pytest.raises(ValueError, match='schema'):
        make_detector(tmp_path, monkeypatch, np.zeros((1, 5, 85), dtype=np.float32), output_shape=[1, 5, 85])

    # Derives static input size from metadata
    det_static = make_detector(tmp_path, monkeypatch, np.zeros((1, 0, 16), dtype=np.float32), input_shape=(1, 3, 320, 320))
    assert det_static.input_size == (320, 320)

    # Rejects conflicting requested input_size
    with pytest.raises(ValueError, match='fixed to'):
        make_detector(tmp_path, monkeypatch, np.zeros((1, 0, 16), dtype=np.float32), input_shape=(1, 3, 320, 320), input_size=(640, 640))


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


def test_empty_detections_returns_empty_list(tmp_path, monkeypatch):
    img = np.zeros((480, 640, 3), dtype=np.uint8)

    session = MockSessionDouble(np.zeros((1, 0, 16), dtype=np.float32))
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


def test_junk_onnx_file_raises_value_error(tmp_path):
    junk_file = tmp_path / 'corrupt.onnx'
    junk_file.write_bytes(b'THIS_IS_NOT_A_VALID_ONNX_MODEL_FILE')
    # Real ONNX Runtime loading without mocking to prove InvalidProtobuf/etc. is converted to ValueError
    with pytest.raises(ValueError, match='Failed to load ONNX model'):
        YOLO5Face(junk_file)


def test_wbf_single_and_two_detector_faces():
    pts_scrfd = np.array([[20.0, 20.0], [40.0, 20.0], [30.0, 30.0], [22.0, 40.0], [38.0, 40.0]], dtype=float)
    pts_yolo = pts_scrfd + 0.5
    scrfd_face = FaceDetection(np.array([10.0, 10.0, 50.0, 50.0]), 0.9, pts_scrfd)
    yolo_face = FaceDetection(np.array([12.0, 12.0, 52.0, 52.0]), 0.85, pts_yolo)

    fused = fuse_faces([scrfd_face], [yolo_face], (100, 100))
    assert len(fused) == 1
    assert np.array_equal(fused[0].landmarks, pts_scrfd)

    yolo_only = FaceDetection(np.array([60.0, 10.0, 95.0, 50.0]), 0.8, pts_yolo)
    fused_single = fuse_faces([], [yolo_only], (100, 100))
    assert len(fused_single) == 1
    assert np.allclose(fused_single[0].box, [60.0, 10.0, 95.0, 50.0])

    assert fuse_faces([], [], (100, 100)) == []


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
        main_module.check_detectors(missing_args)

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
    monkeypatch.setattr(main_module, 'YOLO5Face', MockYOLO5Face, raising=False)

    valid_args = SimpleNamespace(
        command='check-detectors',
        image=image_path,
        scrfd=scrfd_path,
        detector=scrfd_path,
        yolo5face=yolo_path
    )
    main_module.check_detectors(valid_args)

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
        main_module.check_detectors(args)

    # Case 2: Model object has no detect method
    class MockModelWithoutDetect:
        pass

    monkeypatch.setattr(model_zoo, 'get_model', lambda *args, **kwargs: MockModelWithoutDetect())
    with pytest.raises(ValueError, match='Incompatible SCRFD model'):
        main_module.check_detectors(args)


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
        main_module.check_detectors(args_junk_scrfd)

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
        main_module.check_detectors(args_junk_yolo)
