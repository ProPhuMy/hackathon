import threading
import time
from typing import Iterator

import cv2
import numpy as np
import requests

from fridge_item.events import now_ts


def split_jpegs(buf: bytes) -> tuple[list[bytes], bytes]:
    """Extract complete JPEG frames (from \\xff\\xd8 to \\xff\\xd9) and return unparsed tail."""
    frames = []
    cursor = 0
    while True:
        start = buf.find(b"\xff\xd8", cursor)
        if start == -1:
            tail = buf[cursor:]
            return frames, b"\xff" if tail.endswith(b"\xff") else b""
        end = buf.find(b"\xff\xd9", start + 2)
        if end == -1:
            return frames, buf[start:]
        frames.append(buf[start : end + 2])
        cursor = end + 2


class LatestFrameReader:
    """Reads HTTP MJPEG stream in background thread, keeping only the latest frame."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._stopped = False
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._latest: tuple[np.ndarray, str] | None = None
        self._new_frame = False
        self._session: requests.Session | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stopped:
            try:
                self._session = requests.Session()
                with self._session.get(self.url, stream=True, timeout=5) as resp:
                    resp.raise_for_status()
                    buf = b""
                    for chunk in resp.iter_content(chunk_size=4096):
                        if self._stopped:
                            break
                        if not chunk:
                            continue
                        buf += chunk
                        jpegs, buf = split_jpegs(buf)
                        for jpeg in jpegs:
                            arr = np.frombuffer(jpeg, dtype=np.uint8)
                            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                            if frame is not None:
                                ts = now_ts()
                                with self._lock:
                                    self._latest = (frame, ts)
                                    self._new_frame = True
            except Exception as e:
                print(e, flush=True)
            finally:
                if self._session:
                    try:
                        self._session.close()
                    except Exception:
                        pass
                    self._session = None
            if not self._stopped:
                self._stop_event.wait(1.0)

    def latest(self) -> tuple[np.ndarray, str] | None:
        """Returns the newest frame once as (frame_bgr, ts), or None if no new frame."""
        with self._lock:
            if self._new_frame:
                self._new_frame = False
                return self._latest
            return None

    def stop(self) -> None:
        self._stopped = True
        self._stop_event.set()
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass


def iter_frames(source: str) -> Iterator[tuple[np.ndarray, str]]:
    """Yields (frame, ts) from an HTTP MJPEG stream or a local video file."""
    if source.startswith("http"):
        reader = LatestFrameReader(source)
        try:
            while not reader._stopped:
                frame_data = reader.latest()
                if frame_data is not None:
                    yield frame_data
                else:
                    time.sleep(0.005)
        finally:
            reader.stop()
    else:
        cap = cv2.VideoCapture(source)
        try:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                yield frame, now_ts()
        finally:
            cap.release()
