from typing import Literal

import numpy as np

from fridge_item.geometry import Box, Track


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
        weights: str = "yoloe-11s-seg.pt",
    ) -> None:
        # Import ultralytics inside __init__ so importing detect.py stays fast for unit tests.
        from ultralytics import YOLOE

        self.prompts = list(prompts)
        self.hand_label = hand_label
        self.weights = weights
        self.model = YOLOE(weights)
        self.model.set_classes(self.prompts, self.model.get_text_pe(self.prompts))

    def __call__(self, frame: np.ndarray) -> list[Track]:
        results = self.model.track(frame, persist=True, verbose=False)
        if not results:
            return []
        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None or getattr(boxes, "xyxy", None) is None:
            return []

        xyxy = boxes.xyxy.cpu().numpy()
        if len(xyxy) == 0:
            return []

        ids = boxes.id.cpu().numpy() if getattr(boxes, "id", None) is not None else None
        conf = (
            boxes.conf.cpu().numpy()
            if getattr(boxes, "conf", None) is not None
            else np.zeros((len(xyxy),))
        )
        cls = (
            boxes.cls.cpu().numpy()
            if getattr(boxes, "cls", None) is not None
            else np.zeros((len(xyxy),), dtype=int)
        )
        names = getattr(
            result,
            "names",
            getattr(self.model, "names", {i: p for i, p in enumerate(self.prompts)}),
        )

        return to_tracks(
            xyxy=xyxy,
            ids=ids,
            conf=conf,
            cls=cls,
            names=names,
            hand_label=self.hand_label,
        )
