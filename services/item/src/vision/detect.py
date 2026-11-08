"""YOLOE open-vocabulary detector with ultralytics ByteTrack, and the array-to-Track converter both detectors share."""
from typing import Literal

import numpy as np

from ..core.geometry import Box, Track


def to_tracks(
    xyxy: np.ndarray,
    ids: np.ndarray | None,
    conf: np.ndarray,
    cls: np.ndarray,
    names: dict[int, str],
    hand_label: str,
) -> list[Track]:
    """Convert raw detector/tracker arrays to Track instances.

    Drops rows where ID is None or missing/NaN.
    """
    if ids is None:
        return []

    tracks: list[Track] = []
    n = min(len(xyxy), len(ids), len(conf), len(cls))
    for i in range(n):
        raw_id = ids[i]
        if raw_id is None:
            continue
        if isinstance(raw_id, (float, np.floating)) and np.isnan(raw_id):
            continue

        track_id = int(raw_id)
        class_idx = int(cls[i])
        label = names.get(class_idx, str(class_idx))
        kind: Literal["hand", "item"] = "hand" if label == hand_label else "item"
        box = Box(
            x1=float(xyxy[i, 0]),
            y1=float(xyxy[i, 1]),
            x2=float(xyxy[i, 2]),
            y2=float(xyxy[i, 3]),
        )
        tracks.append(
            Track(
                id=track_id,
                kind=kind,
                box=box,
                conf=float(conf[i]),
                label=label,
            )
        )
    return tracks


class Detector:
    def __init__(
        self,
        prompts: list[str],
        hand_label: str = "hand",
        # YOLOE-26l: on our iPhone top-down clips it was the only size that found a small grape bunch,
        # and it caught bottles/hands 2-4x more often than YOLOE-11s (see RESULTS.md, 2026-11-08).
        weights: str = "models/yoloe-26l-seg.pt",
    ) -> None:
        # Import ultralytics inside __init__ so importing detect.py stays fast for unit tests.
        from ultralytics import YOLOE

        self.prompts = list(prompts)
        self.hand_label = hand_label
        self.weights = weights
        self.model = YOLOE(weights)
        self.model.set_classes(self.prompts, self.model.get_text_pe(self.prompts))

    def __call__(self, frame: np.ndarray) -> list[Track]:
        results = self.model.track(
            frame, persist=True, verbose=False, tracker="bytetrack.yaml"
        )
        if not results:
            return []
        result = results[0]
        boxes = result.boxes
        return to_tracks(
            xyxy=boxes.xyxy.cpu().numpy(),
            # ByteTrack leaves id None until it has confirmed tracks.
            ids=boxes.id.cpu().numpy() if boxes.id is not None else None,
            conf=boxes.conf.cpu().numpy(),
            cls=boxes.cls.cpu().numpy(),
            names=result.names,
            hand_label=self.hand_label,
        )
