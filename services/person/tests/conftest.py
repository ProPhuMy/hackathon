"""Shared fakes and fixtures. Test modules import the plain helpers with `from conftest import ...`."""
import hashlib
from pathlib import Path
import onnxruntime as ort
from src.vision.yolo5face import YOLO5Face

SCHEMA_PATH = Path(__file__).parents[3] / 'contracts' / 'person.seen.schema.json'


def fake_capture(frames):
    """Capture stand-in that replays (image, received, timestamp) frames without a camera."""
    class Capture:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return iter(frames)
        def __exit__(self, *args):
            pass
    return Capture


def score_row(session, person, arc, ada):
    return {'session_id': session, 'source_sha256': hashlib.sha256(session.encode()).hexdigest(),
            'person_id': person, 'arcface': arc, 'adaface': ada}


def score_dataset(split):
    encounters = []
    for i in range(12):
        encounters.extend([
            score_row(f'{split}-a-{i}', 'a', {'a': .9, 'b': .1}, {'a': .85, 'b': .05}),
            score_row(f'{split}-b-{i}', 'b', {'a': .1, 'b': .9}, {'a': .05, 'b': .85})])
        if split != 'conformal':
            encounters.append(score_row(f'{split}-u-{i}', None, {'a': .1, 'b': .15}, {'a': .05, 'b': .1}))
    return {'binding': '0'*64, 'prefix_s': 1., 'encounters': encounters}


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


def left_lit_clip(path, frames=5):
    """64x32 (w x h) MJPG clip, left half white: a 90-degree clockwise turn moves the white to the top."""
    import cv2
    import numpy as np
    image = np.zeros((32, 64, 3), dtype=np.uint8)
    image[:, :32] = 255
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 5, (64, 32))
    for _ in range(frames):
        writer.write(image)
    writer.release()
    return path


def is_turned_clockwise(image):
    return image.shape == (64, 32, 3) and image[:32].mean() > 200 > 50 > image[32:].mean()
