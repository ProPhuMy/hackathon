"""check-camera: live inference smoke check; reports counts and timing only."""
import json
import time


def execute(args):
    """Live inference smoke check: report counts/timing without retaining biometric data."""
    import math
    if not math.isfinite(args.duration) or args.duration <= 0:
        raise ValueError('Camera check duration must be finite and positive')
    import numpy as np
    from ..capture import Capture
    from ..vision.arcface import Vision
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
