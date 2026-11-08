"""Local SCRFD/ArcFace integration; no automatic weight downloads."""
from pathlib import Path
import cv2
import numpy as np
from insightface.model_zoo import get_model
from insightface.utils.face_align import norm_crop
from ..identity.recognition import unit
from ..storage import file_hash


class Vision:
    def __init__(self, detector, recognizer):
        paths = [Path(detector), Path(recognizer)]
        for path in paths:
            if not path.is_file():
                raise ValueError(f'Missing local model: {path}')
        self.signature = ':'.join(file_hash(path) for path in paths) + ':insightface-112-bgr-v1'
        self.detector = get_model(str(paths[0]), providers=['CPUExecutionProvider'])
        self.encoder = get_model(str(paths[1]), providers=['CPUExecutionProvider'])
        self.detector.prepare(ctx_id=-1, input_size=(640, 640))
        self.encoder.prepare(ctx_id=-1)

    def aligned_face(self, image):
        boxes, landmarks = self.detector.detect(image, max_num=0)
        if len(boxes) != 1 or landmarks is None:
            return None
        box, points = boxes[0], landmarks[0]
        height, width = image.shape[:2]
        if (not np.isfinite(box).all() or not np.isfinite(points).all()
                or points.shape != (5, 2) or not 0 < box[4] <= 1
                or box[2] - box[0] < 40 or box[3] - box[1] < 40
                or np.any(points < 0) or np.any(points[:, 0] >= width)
                or np.any(points[:, 1] >= height) or points[0, 0] >= points[1, 0]
                or points[3, 0] >= points[4, 0]):
            return None
        crop = norm_crop(image, landmark=points, image_size=112)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        # Initial usability gates, not measured quality or identity thresholds.
        if cv2.Laplacian(gray, cv2.CV_64F).var() < 10 or not 15 < gray.mean() < 240:
            return None
        return crop, float(box[4])

    def single_face(self, image):
        aligned = self.aligned_face(image)
        if aligned is None:
            return None
        crop, confidence = aligned
        vector = unit(self.encoder.get_feat(crop).reshape(-1))
        if vector.shape != (512,):
            raise ValueError('Expected 512-D ArcFace output')
        return vector, confidence
