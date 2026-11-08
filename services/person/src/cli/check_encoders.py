"""check-encoders: offline AdaFace/MagFace smoke check on one aligned local face."""
import json
import platform
import time


def execute(args):
    import cv2
    import numpy as np
    import resource
    from ..vision.arcface import Vision
    from ..vision.encoders import FaceEncoders
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
