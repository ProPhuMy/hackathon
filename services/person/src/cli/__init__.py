"""Role 1 CLI. Model loading always uses explicit local files."""
import argparse
from importlib import import_module
from pathlib import Path
import sys

# Command modules load lazily, so --help and model-free commands never import model runtimes.
HANDLERS = {
    'check-models': 'check_models', 'check-camera': 'check_camera',
    'check-encoders': 'check_encoders', 'check-detectors': 'check_detectors',
    'enroll': 'run', 'run': 'run', 'remove': 'run',
    'calibrate': 'calibrate', 'evaluate': 'calibrate',
    'calibrate-scores': 'scores', 'evaluate-scores': 'scores',
}


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
        sub.add_argument('--ada-gallery', type=Path, default=None, help='Separate AdaFace gallery for ensemble')
        if command in ('enroll', 'remove'):
            sub.add_argument('--person-id', required=True)
            if command == 'enroll':
                sub.add_argument('--session-id', required=True, help='Unique enrollment encounter ID')
        if command != 'remove':
            sub.add_argument('--source', required=True)
            sub.add_argument('--replay-origin', help='UTC origin required for recorded clips')
            sub.add_argument('--rotate', type=int, choices=(0, 90, 180, 270), default=0, help='Turn frames clockwise; 90 or 270 for a phone mounted in portrait that streams landscape')
        if command == 'run':
            output = sub.add_mutually_exclusive_group(required=True)
            output.add_argument('--dry-run', action='store_true', help='Validated JSONL on stdout')
            output.add_argument('--broker')
            sub.add_argument('--policy', type=Path, required=True, help='Development-selected baseline policy JSON')
            sub.add_argument('--adaface', type=Path, default=Path('models/adaface_ir50_ms1mv2.ckpt'),
                             help='AdaFace checkpoint, used only with an ensemble (conformal) policy')
            sub.add_argument('--magface', type=Path, default=Path('models/magface_iresnet50.pth'),
                             help='MagFace checkpoint, loaded with AdaFace for an ensemble policy')
            sub.add_argument('--schema', type=Path, default=Path('../../contracts/person.seen.schema.json'))
    for command in ('calibrate', 'evaluate'):
        sub = commands.add_parser(command, help='Empirical single-face ArcFace baseline')
        sub.add_argument('--manifest', type=Path, required=True)
        sub.add_argument('--output', type=Path, required=True)
        sub.add_argument('--detector', type=Path, default=Path('models/det_10g.onnx'))
        sub.add_argument('--recognizer', type=Path, default=Path('models/w600k_r50.onnx'))
        sub.add_argument('--gallery', type=Path, default=Path('models/gallery.json'))
        sub.add_argument('--rotate', type=int, choices=(0, 90, 180, 270), default=0, help='Turn frames clockwise; 90 or 270 for a phone mounted in portrait that streams landscape')
        if command == 'evaluate':
            sub.add_argument('--policy', type=Path, required=True)
    live = commands.add_parser('check-camera', help='Live model smoke check; no enrollment or retained frames')
    live.add_argument('--source', default='0')
    live.add_argument('--duration', type=float, default=15.)
    live.add_argument('--rotate', type=int, choices=(0, 90, 180, 270), default=0, help='Turn frames clockwise; 90 or 270 for a phone mounted in portrait that streams landscape')
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
        import_module(f'{__name__}.{HANDLERS[args.command]}').execute(args)
    except (ValueError, ImportError, OSError, RuntimeError, KeyError) as error:
        print(f'Person service failed: {error}', file=sys.stderr)
        return 1
    return 0
