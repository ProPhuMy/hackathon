"""Published WBF box fusion with conservative, source-owned five-point landmarks."""
from dataclasses import dataclass
import numpy as np
from ensemble_boxes import weighted_boxes_fusion


@dataclass
class FaceDetection:
    box: np.ndarray
    confidence: float
    landmarks: np.ndarray | None = None


def _iou(left, right):
    intersection = np.maximum(0, np.minimum(left[2:], right[2:]) - np.maximum(left[:2], right[:2])).prod()
    union = np.prod(left[2:] - left[:2]) + np.prod(right[2:] - right[:2]) - intersection
    return float(intersection / union) if union > 0 else 0.


def _valid_points(points, box):
    if points is None:
        return None
    points = np.asarray(points, dtype=float)
    if (points.shape != (5, 2) or not np.isfinite(points).all()
            or np.any(points < box[:2]) or np.any(points > box[2:])
            or points[0, 0] >= points[1, 0] or points[3, 0] >= points[4, 0]):
        return None
    return points.copy()


def fuse_faces(scrfd, yolo5face, image_shape):
    height, width = image_shape[:2]
    if not np.isfinite([height, width]).all() or height <= 0 or width <= 0:
        raise ValueError('Invalid image dimensions')
    scale = np.array([width, height, width, height], dtype=float)
    boxes, scores, labels, sources = [[], []], [[], []], [[], []], []
    for model, detections in enumerate((scrfd, yolo5face)):
        for detection in detections:
            box = np.asarray(detection.box, dtype=float)
            confidence = detection.confidence
            if (box.shape != (4,) or not np.isfinite(box).all()
                    or not np.isfinite(confidence) or not 0 < confidence <= 1):
                continue
            box = np.clip(box, 0, scale)
            if np.any(box[2:] <= box[:2]):
                continue
            boxes[model].append((box / scale).tolist())
            scores[model].append(float(confidence))
            labels[model].append(0)
            sources.append((box, float(confidence), model, _valid_points(detection.landmarks, box)))
    if not sources:
        return []
    fused, fused_scores, _ = weighted_boxes_fusion(boxes, scores, labels, weights=[1, 1], iou_thr=.55,
                                                skip_box_thr=0., conf_type='avg')
    fused = np.asarray(fused) * scale
    matches = np.array([[_iou(source[0], box) >= .55 for box in fused] for source in sources])
    result = []
    for index, (box, confidence) in enumerate(zip(fused, fused_scores)):
        owners = [source for source, matching in zip(sources, matches)
                  if matching[index] and matching.sum() == 1 and source[3] is not None]
        # A source matching multiple fused faces is unsafe for recognition, even if its score wins.
        owner = min(owners, key=lambda source: (-source[1], source[2])) if owners else None
        result.append(FaceDetection(box.copy(), float(confidence), owner[3].copy() if owner else None))
    return result
