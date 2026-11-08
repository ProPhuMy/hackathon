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
    # CPU is the documented Mac correctness baseline, independent of CoreML availability.
    detector = get_model(str(args.detector), providers=['CPUExecutionProvider'])
    recognizer = get_model(str(args.recognizer), providers=['CPUExecutionProvider'])
    if detector is None or recognizer is None:
        raise ValueError('Unsupported ONNX model; supply SCRFD and ArcFace models')
    detector.prepare(ctx_id=-1, input_size=(640, 640))
    recognizer.prepare(ctx_id=-1)
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
    args = parser.parse_args()
    try:
        if args.command == 'check-models':
            check_models(args)
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
