from typing import Literal

import cv2
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


def phrase_to_class(phrase: str, prompts: list[str]) -> int | None:
    """Map a detected phrase to a prompt index.

    Exact match (case-insensitive, stripped) first, else the longest prompt
    contained in the phrase, else None (drop detection).
    """
    clean_phrase = phrase.strip().lower()
    if not clean_phrase:
        return None

    clean_prompts = [p.strip().lower() for p in prompts]

    # Exact match first
    for i, p in enumerate(clean_prompts):
        if p and p == clean_phrase:
            return i

    # Longest prompt contained in phrase
    best_idx: int | None = None
    best_len = -1
    for i, p in enumerate(clean_prompts):
        if p and p in clean_phrase:
            if len(p) > best_len:
                best_len = len(p)
                best_idx = i

    return best_idx


def tracker_output_to_tracks(
    out: np.ndarray | None,
    names: dict[int, str],
    hand_label: str,
) -> list[Track]:
    """Convert tracker output array (N, 8) to list of Track objects."""
    if out is None or len(out) == 0:
        return []
    xyxy = out[:, :4]
    ids = out[:, 4]
    conf = out[:, 5]
    cls = out[:, 6]
    return to_tracks(
        xyxy=xyxy,
        ids=ids,
        conf=conf,
        cls=cls,
        names=names,
        hand_label=hand_label,
    )


class GDinoDetector:
    def __init__(
        self,
        prompts: list[str],
        hand_label: str = "hand",
        model_id: str = "IDEA-Research/grounding-dino-tiny",
        box_threshold: float = 0.35,
        text_threshold: float = 0.25,
        device: str | None = None,
    ) -> None:
        import boxmot
        import torch
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

        self.prompts = list(prompts)
        self.hand_label = hand_label
        self.model_id = model_id
        self.box_threshold = box_threshold
        self.text_threshold = text_threshold
        self.text_prompt = (
            (". ".join(p.lower() for p in self.prompts) + ".") if self.prompts else ""
        )

        self._torch = torch
        if device is not None:
            self.device = device
        elif torch.cuda.is_available():
            self.device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            self.device = "mps"
        else:
            self.device = "cpu"

        self.processor = AutoProcessor.from_pretrained(model_id)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(
            self.device
        )
        self.model.eval()
        self.tracker = boxmot.ByteTrack()

    def __call__(self, frame: np.ndarray) -> list[Track]:
        if frame is None or frame.size == 0 or not self.prompts:
            out = self.tracker.update(np.zeros((0, 6), dtype=np.float32))
            return tracker_output_to_tracks(
                out, {i: p for i, p in enumerate(self.prompts)}, self.hand_label
            )

        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        inputs = self.processor(
            images=rgb, text=self.text_prompt, return_tensors="pt"
        ).to(self.device)

        with self._torch.no_grad():
            outputs = self.model(**inputs)

        results = self.processor.post_process_grounded_object_detection(
            outputs=outputs,
            input_ids=inputs.input_ids,
            threshold=self.box_threshold,
            text_threshold=self.text_threshold,
            target_sizes=[(h, w)],
        )

        kept_dets: list[list[float]] = []
        if results:
            res = results[0]
            boxes = res["boxes"].detach().cpu().numpy()
            scores = res["scores"].detach().cpu().numpy()
            labels = res.get("text_labels", res.get("labels", []))
            for box, score, label in zip(boxes, scores, labels):
                cls_idx = phrase_to_class(str(label), self.prompts)
                if cls_idx is not None:
                    kept_dets.append(
                        [
                            float(box[0]),
                            float(box[1]),
                            float(box[2]),
                            float(box[3]),
                            float(score),
                            float(cls_idx),
                        ]
                    )

        if kept_dets:
            dets = np.array(kept_dets, dtype=np.float32)
        else:
            dets = np.zeros((0, 6), dtype=np.float32)

        out = self.tracker.update(dets)
        names = {i: prompt for i, prompt in enumerate(self.prompts)}
        return tracker_output_to_tracks(out, names=names, hand_label=self.hand_label)

