"""check-models: SCRFD + ArcFace smoke check on one local face image."""
import json
import platform
import time
from ..storage import file_hash


def execute(args):
    for path in (args.detector, args.recognizer, args.image):
        if not path.is_file():
            raise ValueError(f"Missing local file: {path}. See SETUP.md; weights are never downloaded automatically.")
    import cv2
    import numpy as np
    import onnxruntime as ort
    from insightface.model_zoo import get_model
    from ..vision import onnx_providers

    image = cv2.imread(str(args.image))
    if image is None:
        raise ValueError('Cannot decode the supplied image')
    providers, ctx_id = onnx_providers()
    try:
        detector = get_model(str(args.detector), providers=providers)
        recognizer = get_model(str(args.recognizer), providers=providers)
    except Exception as error:
        raise ValueError(f"Failed to load ONNX model: {error}") from error
    if detector is None or recognizer is None:
        raise ValueError('Unsupported ONNX model; supply SCRFD and ArcFace models')
    if not hasattr(detector, 'detect') or getattr(detector, 'taskname', 'detection') != 'detection':
        raise ValueError('Unsupported detector model; supply an SCRFD model')
    if not hasattr(recognizer, 'get_feat'):
        raise ValueError('Unsupported recognizer model; supply an ArcFace model')
    try:
        detector.prepare(ctx_id=ctx_id, input_size=(640, 640))
        recognizer.prepare(ctx_id=ctx_id)
    except Exception as error:
        raise ValueError(f"Failed to initialize model: {error}") from error
    latencies = []
    for iteration in range(6):
        start = time.perf_counter()
        boxes, landmarks = detector.detect(image, max_num=0)
        if len(boxes) != 1 or landmarks is None:
            raise ValueError('Smoke image must contain exactly one face with five landmarks')
        from insightface.utils.face_align import norm_crop
        crop = norm_crop(image, landmark=landmarks[0], image_size=112)
        vector = recognizer.get_feat(crop).reshape(-1)
        norm = np.linalg.norm(vector)
        if vector.shape != (512,) or not np.isfinite(vector).all() or not np.isfinite(norm) or norm <= 0:
            raise ValueError('ArcFace must produce a finite nonzero 512-D embedding')
        vector = vector / norm
        if not np.isclose(np.linalg.norm(vector), 1):
            raise ValueError('Embedding normalization failed')
        if iteration:
            latencies.append((time.perf_counter() - start) * 1000)
    artifacts = [{'file': path.name, 'bytes': path.stat().st_size, 'sha256': file_hash(path)}
                 for path in (args.detector, args.recognizer)]
    print(json.dumps({'platform': platform.platform(), 'machine': platform.machine(),
                      'provider': recognizer.session.get_providers()[0], 'available_providers': ort.get_available_providers(),
                      'warm_samples': len(latencies), 'p50_ms': float(np.percentile(latencies, 50)),
                      'p95_ms': float(np.percentile(latencies, 95)), 'models': artifacts}, indent=2))
