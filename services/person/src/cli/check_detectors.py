"""check-detectors: SCRFD + YOLO5Face on one local image, fused with WBF; aggregate diagnostics only."""
import json
import time
from ..storage import file_hash


def execute(args):
    import cv2
    import numpy as np
    import onnxruntime as ort
    from insightface.model_zoo import get_model
    from ..vision.detection import FaceDetection, _iou, fuse_faces, _valid_points
    from ..vision.yolo5face import YOLO5Face

    scrfd_path = args.scrfd or args.detector
    for path, name in ((args.image, 'image'), (scrfd_path, 'SCRFD model'), (args.yolo5face, 'YOLO5Face model')):
        if not path.is_file():
            raise ValueError(f"Missing local file: {path}. See SETUP.md; weights are never downloaded automatically.")

    image = cv2.imread(str(args.image))
    if image is None:
        raise ValueError('Cannot decode the supplied image')

    try:
        scrfd = get_model(str(scrfd_path), providers=['CPUExecutionProvider'])
    except Exception as error:
        raise ValueError(f"Failed to load SCRFD model from {scrfd_path}: {error}") from error
    if scrfd is None or not hasattr(scrfd, 'detect') or getattr(scrfd, 'taskname', 'detection') != 'detection':
        raise ValueError(f"Incompatible SCRFD model: {scrfd_path} is not a face detection model. Provide an SCRFD checkpoint.")
    try:
        scrfd.prepare(ctx_id=-1, input_size=(640, 640))
    except Exception as error:
        raise ValueError(f"Failed to initialize SCRFD model: {error}") from error

    try:
        yolo = YOLO5Face(model_path=args.yolo5face)
    except Exception as error:
        if isinstance(error, ValueError):
            raise
        raise ValueError(f"Failed to load YOLO5Face model from {args.yolo5face}: {error}") from error

    scrfd_ms, yolo_ms, fusion_ms, total_ms = [], [], [], []
    scrfd_faces, yolo_faces, fused_faces = [], [], []

    for iteration in range(6):
        t0 = time.perf_counter()
        t_scrfd_start = time.perf_counter()
        boxes, landmarks = scrfd.detect(image, max_num=0)
        t_scrfd = (time.perf_counter() - t_scrfd_start) * 1000.0

        current_scrfd = []
        if boxes is not None and len(boxes) > 0:
            for idx, b in enumerate(boxes):
                if len(b) >= 5 and np.isfinite(b[:5]).all():
                    pts = _valid_points(landmarks[idx], b[:4]) if landmarks is not None and len(landmarks) > idx else None
                    current_scrfd.append(FaceDetection(box=np.asarray(b[:4], dtype=float), confidence=float(b[4]), landmarks=pts))

        t_yolo_start = time.perf_counter()
        current_yolo = yolo.detect(image)
        t_yolo = (time.perf_counter() - t_yolo_start) * 1000.0

        t_fusion_start = time.perf_counter()
        current_fused = fuse_faces(current_scrfd, current_yolo, image.shape)
        t_fusion = (time.perf_counter() - t_fusion_start) * 1000.0

        t_total = (time.perf_counter() - t0) * 1000.0

        if iteration:
            scrfd_ms.append(t_scrfd)
            yolo_ms.append(t_yolo)
            fusion_ms.append(t_fusion)
            total_ms.append(t_total)
        scrfd_faces = current_scrfd
        yolo_faces = current_yolo
        fused_faces = current_fused

    two_detector = 0
    scrfd_only = 0
    yolo_only = 0
    for f in fused_faces:
        in_scrfd = any(_iou(s.box, f.box) >= 0.55 for s in scrfd_faces)
        in_yolo = any(_iou(y.box, f.box) >= 0.55 for y in yolo_faces)
        if in_scrfd and in_yolo:
            two_detector += 1
        elif in_scrfd:
            scrfd_only += 1
        elif in_yolo:
            yolo_only += 1

    artifacts = [{'file': path.name, 'bytes': path.stat().st_size, 'sha256': file_hash(path)}
                 for path in (scrfd_path, args.yolo5face)]

    report = {
        'provider': 'CPUExecutionProvider',
        'available_providers': ort.get_available_providers(),
        'image_shape': list(image.shape),
        'warm_samples': len(total_ms),
        'scrfd_count': len(scrfd_faces),
        'scrfd_with_landmarks': sum(1 for d in scrfd_faces if d.landmarks is not None),
        'yolo5face_count': len(yolo_faces),
        'yolo5face_with_landmarks': sum(1 for d in yolo_faces if d.landmarks is not None),
        'fused_count': len(fused_faces),
        'fused_with_landmarks': sum(1 for d in fused_faces if d.landmarks is not None),
        'fused_two_detector_count': two_detector,
        'fused_scrfd_only_count': scrfd_only,
        'fused_yolo5face_only_count': yolo_only,
        'p50_scrfd_ms': float(np.percentile(scrfd_ms, 50)),
        'p95_scrfd_ms': float(np.percentile(scrfd_ms, 95)),
        'p50_yolo5face_ms': float(np.percentile(yolo_ms, 50)),
        'p95_yolo5face_ms': float(np.percentile(yolo_ms, 95)),
        'p50_fusion_ms': float(np.percentile(fusion_ms, 50)),
        'p95_fusion_ms': float(np.percentile(fusion_ms, 95)),
        'p50_total_ms': float(np.percentile(total_ms, 50)),
        'p95_total_ms': float(np.percentile(total_ms, 95)),
        'models': artifacts
    }
    print(json.dumps(report, indent=2))
