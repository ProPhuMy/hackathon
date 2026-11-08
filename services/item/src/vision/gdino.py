"""Grounding DINO detector with boxmot ByteTrack, the `--detector gdino` alternative to YOLOE."""
import cv2
import numpy as np

from ..core.geometry import Track
from . import pick_device
from .detect import to_tracks


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
        self.names = dict(enumerate(self.prompts))
        self.hand_label = hand_label
        self.model_id = model_id
        self.box_threshold = box_threshold
        self.text_threshold = text_threshold
        self.text_prompt = (
            (". ".join(p.lower() for p in self.prompts) + ".") if self.prompts else ""
        )

        self._torch = torch
        self.device = device if device is not None else pick_device(torch)

        self.processor = AutoProcessor.from_pretrained(model_id)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(
            self.device
        )
        self.model.eval()
        bt_config = boxmot.ByteTrackConfig(
            min_conf=self.box_threshold,
            track_thresh=self.box_threshold,
        )
        self.tracker = boxmot.ByteTrack(bt_config)

    def __call__(self, frame: np.ndarray) -> list[Track]:
        if frame is None or frame.size == 0 or not self.prompts:
            out = self.tracker.update(np.zeros((0, 6), dtype=np.float32))
            return tracker_output_to_tracks(out, self.names, self.hand_label)

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
        return tracker_output_to_tracks(out, names=self.names, hand_label=self.hand_label)
