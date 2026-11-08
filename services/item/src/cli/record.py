from datetime import datetime
from pathlib import Path

import cv2

from ..draw import video_writer
from ..stream import iter_frames

# Frames buffered to measure a stream's rate before the writer (whose fps is fixed at creation) is opened.
MEASURE_FRAMES = 30


def _measured_fps(stamps: list[str]) -> float:
    """Frames per second from arrival timestamps; 15 when they span no time."""
    first, last = (datetime.fromisoformat(ts.replace("Z", "+00:00")) for ts in (stamps[0], stamps[-1]))
    span = (last - first).total_seconds()
    return (len(stamps) - 1) / span if span > 0 else 15.0


def _file_fps(path: str) -> float:
    cap = cv2.VideoCapture(path)
    try:
        return cap.get(cv2.CAP_PROP_FPS) or 15.0
    finally:
        cap.release()


def record_command(url: str, out_path: str) -> None:
    """Record an MJPEG stream or video file to MP4 at the source's real frame rate.

    The rate matters: person calibration reads video time, so a 26 fps camera saved as 15 fps would
    stretch every clip 1.7x. Streams are measured over the first frames; files keep their own rate."""
    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    # Same stream/file split as iter_frames; file frames decode faster than real time, so they cannot be timed.
    fps = None if url.startswith("http") else _file_fps(url)
    pending: list[tuple] = []
    writer: cv2.VideoWriter | None = None

    def open_writer() -> cv2.VideoWriter:
        rate = fps or _measured_fps([ts for _, ts in pending])
        opened = video_writer(out_file, pending[0][0], fps=rate)
        for buffered, _ in pending:
            opened.write(buffered)
        pending.clear()
        return opened

    try:
        for frame, ts in iter_frames(url):
            if writer is not None:
                writer.write(frame)
                continue
            pending.append((frame, ts))
            if fps is not None or len(pending) >= MEASURE_FRAMES:
                writer = open_writer()
    except KeyboardInterrupt:
        pass
    finally:
        if writer is None and pending:  # stopped before the rate was measured: save what we have
            writer = open_writer()
        if writer is not None:
            writer.release()
