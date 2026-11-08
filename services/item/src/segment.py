from __future__ import annotations

import numpy as np

from .geometry import Track


class Segmenter:
    def __init__(self, weights: str = "sam2.1_b.pt") -> None:
        from ultralytics import SAM

        self.model = SAM(weights)

    def __call__(self, frame: np.ndarray, items: list[Track]) -> dict[int, np.ndarray]:
        if not items:
            return {}
        bboxes = [[t.box.x1, t.box.y1, t.box.x2, t.box.y2] for t in items]
        results = self.model(frame, bboxes=bboxes, verbose=False)
        if not results or results[0].masks is None:
            return {}
        raw = results[0].masks.data
        if isinstance(raw, np.ndarray):
            arr = raw.astype(bool)
        elif hasattr(raw, "cpu"):
            arr = raw.cpu().numpy().astype(bool)
        else:
            arr = np.asarray(raw, dtype=bool)
        return {
            track.id: arr[i]
            for i, track in enumerate(items)
            if i < len(arr)
        }
