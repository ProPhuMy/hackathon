from __future__ import annotations

import cv2
import numpy as np


def color_histogram(crop: np.ndarray) -> np.ndarray:
    """HSV histogram with bins [8, 8, 4] and ranges [0,180,0,256,0,256], flattened, L2-normalized, multiplied by 0.5."""
    if crop is None or crop.size == 0:
        return np.zeros(8 * 8 * 4, dtype=np.float32)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 8, 4], [0, 180, 0, 256, 0, 256])
    hist = hist.flatten().astype(np.float32)
    norm = float(np.linalg.norm(hist))
    if norm > 0:
        hist = hist / norm
    return hist * 0.5


class Embedder:
    """Visual embedder using DINOv2-small CLS token concatenated with an HSV color histogram."""

    def __init__(self, device: str | None = None) -> None:
        import torch
        from transformers import AutoImageProcessor, AutoModel

        if device is None:
            if torch.cuda.is_available():
                device = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"
        self.device = device
        self._torch = torch
        self.processor = AutoImageProcessor.from_pretrained("facebook/dinov2-small")
        self.model = AutoModel.from_pretrained("facebook/dinov2-small").to(self.device)
        self.model.eval()

    def __call__(self, crop: np.ndarray) -> np.ndarray:
        hist = color_histogram(crop)
        if crop is None or crop.size == 0:
            cls_token = np.zeros(384, dtype=np.float32)
        else:
            rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            inputs = self.processor(images=rgb, return_tensors="pt").to(self.device)
            with self._torch.no_grad():
                outputs = self.model(**inputs)
                cls_tensor = outputs.last_hidden_state[:, 0].squeeze(0).detach().cpu().numpy()
                cls_token = cls_tensor.astype(np.float32)

        cls_norm = float(np.linalg.norm(cls_token))
        if cls_norm > 0:
            cls_token = cls_token / cls_norm

        combined = np.concatenate([cls_token, hist])
        comb_norm = float(np.linalg.norm(combined))
        if comb_norm > 0:
            combined = combined / comb_norm
        return combined
