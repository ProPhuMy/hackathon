"""Interactive calibration: pick the opening ROI, the door line, and sample closed/open brightness."""
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..config import DEFAULT_PROMPTS, Config, save
from ..core.door import measure_brightness
from ..core.geometry import DoorLine, Point
from ..stream import iter_frames


def calibrate_command(source: str, out_path: Path | str = "config.json") -> Config:
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

        def show(frame: np.ndarray) -> None:
            disp = frame.copy()
            cv2.rectangle(disp, (rx, ry), (rx + rw, ry + rh), (0, 255, 255), 2)
            cv2.putText(disp, prompt_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.imshow(window_sample, disp)

        try:
            for frame, _ in frames:
                last_frame = frame
                show(frame)
                if cv2.waitKey(30) != -1:
                    break
            else:
                # Source ran out (a video file): sample its last frame once a key is pressed.
                if last_frame is None:
                    raise ValueError(f"Frame source exhausted before sampling: {prompt_text}")
                show(last_frame)
                cv2.waitKey(0)
        finally:
            cv2.destroyWindow(window_sample)

        return measure_brightness(last_frame, roi)

    try:
        c = sample_brightness("Door CLOSED - press any key to sample", initial_frame=first_frame)
        o = sample_brightness("Door OPEN - press any key to sample", initial_frame=None)
    finally:
        cv2.destroyAllWindows()

    # Opening may brighten the ROI (fridge light) or darken it (door shelves over the floor); either works.
    if abs(o - c) < 10:
        raise ValueError(
            f"Door brightness barely changed when opened (closed={c:.1f}, open={o:.1f}, |diff|={abs(o - c):.1f} < 10);"
            " draw the region where opening the door changes the picture most"
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
