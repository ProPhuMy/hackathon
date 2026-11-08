from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .core.door import measure_brightness
from .core.geometry import DoorLine, Point
from .stream import iter_frames

DEFAULT_PROMPTS: list[str] = [
    "hand",
    "bottle",
    "milk carton",
    "box",
    "food container",
    "fruit",
    "can",
]


@dataclass
class Config:
    roi: tuple[int, int, int, int]
    line: DoorLine
    door_on: float
    door_off: float
    prompts: list[str] = field(default_factory=lambda: list(DEFAULT_PROMPTS))
    hand_label: str = "hand"


def save(cfg: Config, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "roi": list(cfg.roi),
        "line": {
            "p1": [cfg.line.p1[0], cfg.line.p1[1]],
            "p2": [cfg.line.p2[0], cfg.line.p2[1]],
            "inside": [cfg.line.inside[0], cfg.line.inside[1]],
            "margin": cfg.line.margin,
        },
        "door_on": cfg.door_on,
        "door_off": cfg.door_off,
        "prompts": cfg.prompts,
        "hand_label": cfg.hand_label,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load(path: Path | str) -> Config:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    roi_raw = data["roi"]
    roi = (int(roi_raw[0]), int(roi_raw[1]), int(roi_raw[2]), int(roi_raw[3]))
    line_raw = data["line"]
    line = DoorLine(
        p1=(float(line_raw["p1"][0]), float(line_raw["p1"][1])),
        p2=(float(line_raw["p2"][0]), float(line_raw["p2"][1])),
        inside=(float(line_raw["inside"][0]), float(line_raw["inside"][1])),
        margin=float(line_raw.get("margin", 15.0)),
    )
    door_on = float(data["door_on"])
    door_off = float(data["door_off"])
    prompts = list(data.get("prompts", DEFAULT_PROMPTS))
    hand_label = str(data.get("hand_label", "hand"))
    return Config(
        roi=roi,
        line=line,
        door_on=door_on,
        door_off=door_off,
        prompts=prompts,
        hand_label=hand_label,
    )


def calibrate(source: str, out_path: Path | str = "config.json") -> Config:
    frames = iter_frames(source)
    try:
        first_frame, _ = next(frames)
    except StopIteration:
        raise ValueError(f"No frames available from source: {source}")

    roi_raw = cv2.selectROI(
        "Select Opening Region", first_frame, fromCenter=False, showCrosshair=True
    )
    cv2.destroyWindow("Select Opening Region")
    roi = (int(roi_raw[0]), int(roi_raw[1]), int(roi_raw[2]), int(roi_raw[3]))
    if roi[2] <= 0 or roi[3] <= 0:
        raise ValueError(f"Invalid ROI {roi}: width and height must be positive")

    points: list[Point] = []
    window_edge = "Click 2 front-edge points, then 1 inside point"
    cv2.namedWindow(window_edge)
    display = first_frame.copy()

    def on_mouse(event: int, x: int, y: int, flags: int, param: Any) -> None:
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 3:
            pt = (float(x), float(y))
            points.append(pt)
            cv2.circle(display, (x, y), 4, (0, 0, 255), -1)
            if len(points) == 2:
                p1_int = (int(points[0][0]), int(points[0][1]))
                p2_int = (int(points[1][0]), int(points[1][1]))
                cv2.line(display, p1_int, p2_int, (0, 255, 0), 2)
            cv2.imshow(window_edge, display)

    cv2.setMouseCallback(window_edge, on_mouse)
    cv2.imshow(window_edge, display)
    while len(points) < 3:
        key = cv2.waitKey(20)
        if key == 27:  # ESC
            break
    cv2.destroyWindow(window_edge)

    if len(points) < 3:
        raise RuntimeError("Calibration aborted: 3 points required.")

    line = DoorLine(p1=points[0], p2=points[1], inside=points[2])

    rx, ry, rw, rh = roi

    def sample_brightness(prompt_text: str, initial_frame: np.ndarray | None = None) -> float:
        window_sample = "Sample Brightness"
        cv2.namedWindow(window_sample)
        last_frame = initial_frame
        try:
            for frame, _ in frames:
                last_frame = frame
                disp = frame.copy()
                cv2.rectangle(disp, (rx, ry), (rx + rw, ry + rh), (0, 255, 255), 2)
                cv2.putText(
                    disp,
                    prompt_text,
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2,
                )
                cv2.imshow(window_sample, disp)
                k = cv2.waitKey(30)
                if k != -1:
                    break
            else:
                if last_frame is None:
                    raise ValueError(f"Frame source exhausted before sampling: {prompt_text}")
                disp = last_frame.copy()
                cv2.rectangle(disp, (rx, ry), (rx + rw, ry + rh), (0, 255, 255), 2)
                cv2.putText(
                    disp,
                    prompt_text,
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2,
                )
                cv2.imshow(window_sample, disp)
                cv2.waitKey(0)
        finally:
            cv2.destroyWindow(window_sample)

        if last_frame is None:
            raise ValueError(f"Frame source exhausted before sampling: {prompt_text}")

        return measure_brightness(last_frame, roi)

    try:
        c = sample_brightness("Door CLOSED - press any key to sample", initial_frame=first_frame)
        o = sample_brightness("Door OPEN - press any key to sample", initial_frame=None)
    finally:
        cv2.destroyAllWindows()

    if (o - c) < 10:
        raise ValueError(
            f"Door did not get brighter when opened (closed={c:.1f}, open={o:.1f}, diff={o - c:.1f} < 10)"
        )

    door_on = c + 0.6 * (o - c)
    door_off = c + 0.4 * (o - c)

    cfg = Config(
        roi=roi,
        line=line,
        door_on=door_on,
        door_off=door_off,
        prompts=list(DEFAULT_PROMPTS),
        hand_label="hand",
    )
    save(cfg, out_path)
    return cfg
