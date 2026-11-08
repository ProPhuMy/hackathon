from pathlib import Path

import cv2

from ..config import load
from ..core.door import DoorDetector
from ..draw import overlay, video_writer
from ..stream import iter_frames
from ..vision import detector_class


def probe_command(
    clip: str,
    out_path: str,
    config_path: str = "config.json",
    detector: str = "yoloe",
) -> None:
    """Run detector and overlay on clip without logic, writing MP4 at 15 fps."""
    cfg = load(config_path)
    detector_model = detector_class(detector)(prompts=cfg.prompts, hand_label=cfg.hand_label)

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    writer: cv2.VideoWriter | None = None

    door_detector = DoorDetector(roi=cfg.roi, on=cfg.door_on, off=cfg.door_off)

    try:
        for frame, _ in iter_frames(clip):
            if writer is None:
                writer = video_writer(out_file, frame)

            door_open = door_detector.update(frame)

            tracks = detector_model(frame)
            annotated = overlay(frame, tracks, cfg.line, door_open, events=[])
            writer.write(annotated)
    except KeyboardInterrupt:
        pass
    finally:
        if writer is not None:
            writer.release()
