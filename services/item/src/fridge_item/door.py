import cv2
import numpy as np


class DoorDetector:
    def __init__(self, roi: tuple[int, int, int, int], on: float, off: float) -> None:
        self.roi = roi
        self.on = float(on)
        self.off = float(off)
        self.is_open: bool = False

    def update(self, frame: np.ndarray) -> bool:
        if frame.ndim == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame
        x, y, w, h = int(self.roi[0]), int(self.roi[1]), int(self.roi[2]), int(self.roi[3])
        crop = gray[y : y + h, x : x + w]
        mean_val = float(np.mean(crop)) if crop.size > 0 else 0.0
        if mean_val > self.on:
            self.is_open = True
        elif mean_val < self.off:
            self.is_open = False
        return self.is_open
