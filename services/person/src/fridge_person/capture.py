"""Capture in a killable process: one replaceable live frame, no unbounded queue."""
from datetime import datetime, timezone, timedelta
import multiprocessing as mp
from pathlib import Path
import queue
import time


def source_value(source):
    # Only bare decimal strings select webcams; ./0 is a file path.
    return int(source) if source.isdecimal() else source


def _read(source, output, stop, replay_origin):
    import os
    # OpenCV 5 has no setLogLevel API; configure diagnostics before importing it.
    os.environ['OPENCV_LOG_LEVEL'] = 'SILENT'
    os.environ['OPENCV_FFMPEG_LOGLEVEL'] = '-8'
    import cv2
    capture = None
    try:
        value = source_value(source)
        live = isinstance(value, int) or not Path(source).is_file()
        if live and isinstance(value, str):
            capture = cv2.VideoCapture(value, cv2.CAP_FFMPEG,
                                      [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000,
                                       cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
        else:
            capture = cv2.VideoCapture(value)
        if not capture.isOpened():
            output.put(('error', 'Cannot open capture source'), timeout=1)
            return
        while not stop.is_set():
            ok, frame = capture.read()
            if not ok:
                output.put(('error', 'Live capture disconnected') if live else ('end', None), timeout=5)
                return
            received = time.monotonic()
            if live:
                timestamp = datetime.now(timezone.utc)
            else:
                timestamp = replay_origin + timedelta(milliseconds=capture.get(cv2.CAP_PROP_POS_MSEC))
            payload = ('frame', (frame, received, timestamp.isoformat(timespec='milliseconds').replace('+00:00', 'Z')))
            if live:
                try:
                    output.put_nowait(payload)
                except queue.Full:
                    try:
                        output.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        output.put_nowait(payload)
                    except queue.Full:
                        pass
            else:
                while not stop.is_set():
                    try:
                        output.put(payload, timeout=.2)
                        break
                    except queue.Full:
                        pass
    except Exception:
        # Do not expose camera URLs or embedded credentials in diagnostics.
        try:
            output.put(('error', 'Capture failed'), timeout=1)
        except queue.Full:
            pass
    finally:
        if capture is not None:
            capture.release()


class Capture:
    def __init__(self, source, replay_origin=None):
        self.source, self.replay_origin = source, replay_origin
        self.live = isinstance(source_value(source), int) or not Path(source).is_file()
        if not self.live and replay_origin is None:
            raise ValueError('Recorded video requires --replay-origin in UTC')
        self.process = None

    def _start(self):
        context = mp.get_context('spawn')
        self.output = context.Queue(maxsize=1)
        self.stop = context.Event()
        self.process = context.Process(target=_read, args=(self.source, self.output, self.stop, self.replay_origin), daemon=True)
        self.process.start()

    def _close(self):
        if self.process is None:
            return
        self.stop.set()
        self.process.join(timeout=1)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=2)
        self.output.close()

    def __enter__(self):
        self._start()
        return self

    def __iter__(self):
        reconnects = 0
        while True:
            try:
                kind, payload = self.output.get(timeout=10)
            except queue.Empty:
                kind, payload = 'error', 'Capture timed out'
            if kind == 'end':
                return
            if kind == 'error':
                if not self.live:
                    raise RuntimeError(payload)
                self._close()
                if reconnects >= 3:
                    raise RuntimeError('Capture failed after three reconnect attempts')
                # Boundary clears all evidence before a replacement capture can be used.
                yield None, time.monotonic(), None
                time.sleep(2 ** reconnects)
                reconnects += 1
                self._start()
                continue
            yield payload

    def __exit__(self, *exception):
        self._close()
