"""Role 1 CLI. Model loading always uses explicit local files."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time


def check_models(args):
    for path in (args.detector, args.recognizer, args.image):
        if not path.is_file():
            raise ValueError(f"Missing local file: {path}. See SETUP.md; weights are never downloaded automatically.")
    import cv2
    import numpy as np
    import onnxruntime as ort
    from insightface.model_zoo import get_model

    image = cv2.imread(str(args.image))
    if image is None:
        raise ValueError('Cannot decode the supplied image')
    try:
        detector = get_model(str(args.detector), providers=['CPUExecutionProvider'])
        recognizer = get_model(str(args.recognizer), providers=['CPUExecutionProvider'])
    except Exception as error:
        raise ValueError(f"Failed to load ONNX model: {error}") from error
    if detector is None or recognizer is None:
        raise ValueError('Unsupported ONNX model; supply SCRFD and ArcFace models')
    if not hasattr(detector, 'detect') or getattr(detector, 'taskname', 'detection') != 'detection':
        raise ValueError('Unsupported detector model; supply an SCRFD model')
    if not hasattr(recognizer, 'get_feat'):
        raise ValueError('Unsupported recognizer model; supply an ArcFace model')
    try:
        detector.prepare(ctx_id=-1, input_size=(640, 640))
        recognizer.prepare(ctx_id=-1)
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
    artifacts = []
    for path in (args.detector, args.recognizer):
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        artifacts.append({'file': path.name, 'bytes': path.stat().st_size, 'sha256': digest})
    print(json.dumps({'platform': platform.platform(), 'machine': platform.machine(),
                      'provider': 'CPUExecutionProvider', 'available_providers': ort.get_available_providers(),
                      'warm_samples': len(latencies), 'p50_ms': float(np.percentile(latencies, 50)),
                      'p95_ms': float(np.percentile(latencies, 95)), 'models': artifacts}, indent=2))


def check_camera(args):
    """Live inference smoke check: report counts/timing without retaining biometric data."""
    import math
    if not math.isfinite(args.duration) or args.duration <= 0:
        raise ValueError('Camera check duration must be finite and positive')
    import numpy as np
    from .capture import Capture
    from .vision import Vision
    vision = Vision(args.detector, args.recognizer)
    report = dict(decoded_frames=0, usable_single_face_frames=0, stale_frames=0, reconnects=0)
    timings = []
    started = time.monotonic()
    with Capture(args.source) as capture:
        for image, received, timestamp in capture:
            if time.monotonic() - started >= args.duration:
                break
            if image is None:
                report['reconnects'] += 1
                continue
            report['decoded_frames'] += 1
            if time.monotonic() - received > 1:
                report['stale_frames'] += 1
                continue
            begin = time.monotonic()
            face = vision.single_face(image)
            timings.append((time.monotonic() - begin) * 1000)
            report['usable_single_face_frames'] += int(face is not None)
    report['elapsed_s'] = round(time.monotonic() - started, 2)
    report['inference_samples'] = len(timings)
    if timings:
        report['median_inference_ms'] = round(float(np.percentile(timings, 50)), 2)
        report['p95_inference_ms'] = round(float(np.percentile(timings, 95)), 2)
    print(json.dumps(report, indent=2))
    if not report['decoded_frames']:
        raise ValueError('Camera check decoded no frames')


def check_encoders(args):
    import cv2
    import numpy as np
    import resource
    from .vision import Vision
    from .encoders import FaceEncoders
    if not args.image.is_file():
        raise ValueError('Missing local test image')
    image = cv2.imread(str(args.image))
    if image is None:
        raise ValueError('Cannot decode the test image')
    vision = Vision(args.detector, args.recognizer)
    aligned = vision.aligned_face(image)
    if aligned is None:
        raise ValueError('Image must contain exactly one usable, aligned face')
    crop, _ = aligned
    encoders = FaceEncoders(args.adaface, args.magface)
    timings = []
    for iteration in range(6):
        started = time.perf_counter()
        evidence = encoders.encode(crop)
        elapsed = (time.perf_counter() - started) * 1000
        if iteration:
            timings.append(elapsed)
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report = dict(provider='PyTorch CPU', warm_samples=len(timings),
                  adaface_dimension=len(evidence['adaface']),
                  adaface_vector_norm=float(np.linalg.norm(evidence['adaface'])),
                  magface_raw_norm=evidence['magface_norm'], quality_weight_calibrated=False,
                  p50_encoder_ms=float(np.percentile(timings,50)),
                  p95_encoder_ms=float(np.percentile(timings,95)),
                  peak_process_rss_bytes=peak_rss if platform.system() == 'Darwin' else peak_rss * 1024,
                  models=[dict(file=path.name, sha256=digest, bytes=path.stat().st_size,
                               parameters=sum(p.numel() for p in model.parameters()))
                          for path,digest,model in zip((args.adaface,args.magface),encoders.hashes,
                                                     (encoders.adaface,encoders.magface))])
    print(json.dumps(report,indent=2))


def check_detectors(args):
    import cv2
    import numpy as np
    import onnxruntime as ort
    from insightface.model_zoo import get_model
    from .detection import FaceDetection, _iou, fuse_faces, _valid_points
    from .yolo5face import YOLO5Face

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

    artifacts = []
    for path in (scrfd_path, args.yolo5face):
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        artifacts.append({'file': path.name, 'bytes': path.stat().st_size, 'sha256': digest})

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


def main():
    parser = argparse.ArgumentParser(description='Fridge person recognition: model feasibility')
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('check-models', help='Test local SCRFD + ArcFace on one consenting face image')
    for name in ('detector', 'recognizer', 'image'):
        check.add_argument(f'--{name}', type=Path, required=True)
    for command in ('enroll', 'run', 'remove'):
        sub = commands.add_parser(command)
        sub.add_argument('--detector', type=Path, default=Path('models/det_10g.onnx'))
        sub.add_argument('--recognizer', type=Path, default=Path('models/w600k_r50.onnx'))
        sub.add_argument('--gallery', type=Path, default=Path('models/gallery.json'))
        if command in ('enroll', 'remove'):
            sub.add_argument('--person-id', required=True)
            if command == 'enroll':
                sub.add_argument('--session-id', required=True, help='Unique enrollment encounter ID')
        if command != 'remove':
            sub.add_argument('--source', required=True)
            sub.add_argument('--replay-origin', help='UTC origin required for recorded clips')
        if command == 'run':
            output = sub.add_mutually_exclusive_group(required=True)
            output.add_argument('--dry-run', action='store_true', help='Validated JSONL on stdout')
            output.add_argument('--broker')
            sub.add_argument('--policy', type=Path, required=True, help='Development-selected baseline policy JSON')
            sub.add_argument('--schema', type=Path, default=Path('../../contracts/person.seen.schema.json'))
    for command in ('calibrate', 'evaluate'):
        sub = commands.add_parser(command, help='Empirical single-face ArcFace baseline')
        sub.add_argument('--manifest', type=Path, required=True)
        sub.add_argument('--output', type=Path, required=True)
        sub.add_argument('--detector', type=Path, default=Path('models/det_10g.onnx'))
        sub.add_argument('--recognizer', type=Path, default=Path('models/w600k_r50.onnx'))
        sub.add_argument('--gallery', type=Path, default=Path('models/gallery.json'))
        if command == 'evaluate':
            sub.add_argument('--policy', type=Path, required=True)
    live = commands.add_parser('check-camera', help='Live model smoke check; no enrollment or retained frames')
    live.add_argument('--source', default='0')
    live.add_argument('--duration', type=float, default=15.)
    live.add_argument('--detector', type=Path, default=Path('models/det_10g.onnx'))
    live.add_argument('--recognizer', type=Path, default=Path('models/w600k_r50.onnx'))
    for command in ('calibrate-scores', 'evaluate-scores'):
        sub = commands.add_parser(command, help='Offline ensemble score calibration; no model inference')
        sub.add_argument('--output', type=Path, required=True)
        if command == 'calibrate-scores':
            sub.add_argument('--development', type=Path, required=True)
            sub.add_argument('--conformal', type=Path, required=True)
        else:
            sub.add_argument('--scores', type=Path, required=True)
            sub.add_argument('--policy', type=Path, required=True)
    encoders = commands.add_parser('check-encoders', help='Offline AdaFace/MagFace smoke check; no enrollment')
    encoders.add_argument('--image', type=Path, required=True)
    encoders.add_argument('--detector', type=Path, default=Path('models/det_10g.onnx'))
    encoders.add_argument('--recognizer', type=Path, default=Path('models/w600k_r50.onnx'))
    encoders.add_argument('--adaface', type=Path, default=Path('models/adaface_ir50_ms1mv2.ckpt'))
    encoders.add_argument('--magface', type=Path, default=Path('models/magface_iresnet50.pth'))
    detectors = commands.add_parser('check-detectors', help='Offline SCRFD + YOLO5Face detection and WBF fusion check')
    detectors.add_argument('--image', type=Path, required=True)
    detectors.add_argument('--scrfd', type=Path, default=None)
    detectors.add_argument('--detector', type=Path, default=Path('models/det_10g.onnx'))
    detectors.add_argument('--yolo5face', type=Path, default=Path('models/yolov5s-face.onnx'))
    args = parser.parse_args()
    try:
        if args.command == 'check-models':
            check_models(args)
        elif args.command == 'check-encoders':
            check_encoders(args)
        elif args.command == 'check-detectors':
            check_detectors(args)
        elif args.command in ('calibrate-scores', 'evaluate-scores'):
            from .ensemble import execute
            execute(args)
        elif args.command == 'check-camera':
            check_camera(args)
        elif args.command in ('calibrate', 'evaluate'):
            from .dataset import execute
            execute(args)
        else:
            from .runtime import execute
            execute(args)
    except (ValueError, ImportError, OSError, RuntimeError, KeyError) as error:
        print(f'Person service failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
