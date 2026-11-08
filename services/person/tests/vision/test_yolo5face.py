import numpy as np
import onnxruntime as ort
import pytest
from conftest import MockSessionDouble, MockTensorInfo, make_detector
from src.vision.yolo5face import YOLO5Face


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


def test_junk_onnx_file_raises_value_error(tmp_path):
    junk_file = tmp_path / 'corrupt.onnx'
    junk_file.write_bytes(b'THIS_IS_NOT_A_VALID_ONNX_MODEL_FILE')
    # Real ONNX Runtime loading without mocking to prove InvalidProtobuf/etc. is converted to ValueError
    with pytest.raises(ValueError, match='Failed to load ONNX model'):
        YOLO5Face(junk_file)
