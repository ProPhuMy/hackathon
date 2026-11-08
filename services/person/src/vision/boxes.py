"""Box geometry shared by the detectors, WBF fusion and the tracker: IoU, landmark checks, letterbox and NMS."""
import cv2
import numpy as np


def iou(left, right):
    intersection = np.maximum(0, np.minimum(left[2:], right[2:]) - np.maximum(left[:2], right[:2])).prod()
    union = np.prod(left[2:] - left[:2]) + np.prod(right[2:] - right[:2]) - intersection
    return float(intersection / union) if union > 0 else 0.


def valid_points(points, box):
    if points is None:
        return None
    points = np.asarray(points, dtype=float)
    if (points.shape != (5, 2) or not np.isfinite(points).all()
            or np.any(points < box[:2]) or np.any(points > box[2:])
            or points[0, 0] >= points[1, 0] or points[3, 0] >= points[4, 0]):
        return None
    return points.copy()


def letterbox(image, target_size=(640, 640), color=(114, 114, 114)):
    """Resize image and pad to target_size maintaining aspect ratio.

    Returns:
        padded: np.ndarray of shape (target_size[0], target_size[1], 3)
        gain: float scale factor
        pad: (left, top) integer pixel offsets of resized image inside padded canvas
    """
    h, w = image.shape[:2]
    target_h, target_w = target_size
    gain = min(target_h / h, target_w / w)
    new_unpad = (int(round(w * gain)), int(round(h * gain)))
    pad_w = (target_w - new_unpad[0]) / 2.0
    pad_h = (target_h - new_unpad[1]) / 2.0

    if (w, h) != new_unpad:
        resized = cv2.resize(image, new_unpad, interpolation=cv2.INTER_LINEAR)
    else:
        resized = image

    top = int(round(pad_h - 0.1))
    bottom = int(round(pad_h + 0.1))
    left = int(round(pad_w - 0.1))
    right = int(round(pad_w + 0.1))

    padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return padded, gain, (left, top)


def nms(boxes, scores, iou_threshold):
    """Run OpenCV NMSBoxes on candidate boxes and scores.

    Args:
        boxes: np.ndarray of shape (N, 4) in [x1, y1, x2, y2] format
        scores: np.ndarray of shape (N,)
        iou_threshold: float in [0, 1]
    Returns:
        keep: np.ndarray of integer indices into original candidates
    """
    if len(boxes) == 0:
        return np.array([], dtype=int)
    xywh = np.zeros_like(boxes)
    xywh[:, 0] = boxes[:, 0]
    xywh[:, 1] = boxes[:, 1]
    xywh[:, 2] = boxes[:, 2] - boxes[:, 0]
    xywh[:, 3] = boxes[:, 3] - boxes[:, 1]
    indices = cv2.dnn.NMSBoxes(
        xywh.tolist(),
        [float(s) for s in scores],
        score_threshold=0.0,
        nms_threshold=float(iou_threshold)
    )
    if indices is None or len(indices) == 0:
        return np.array([], dtype=int)
    return np.asarray(indices, dtype=int).reshape(-1)
