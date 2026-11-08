from pathlib import Path

import cv2

from ..draw import video_writer
from ..stream import iter_frames


def record_command(url: str, out_path: str) -> None:
    """Record MJPEG stream or video source to an MP4 video at 15 fps."""
    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    writer: cv2.VideoWriter | None = None
    try:
        for frame, _ in iter_frames(url):
            if writer is None:
                writer = video_writer(out_file, frame)
            writer.write(frame)
    except KeyboardInterrupt:
        pass
    finally:
        if writer is not None:
            writer.release()
