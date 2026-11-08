import argparse
from pathlib import Path

import cv2
import numpy as np

from fridge_item.config import calibrate
from fridge_item.stream import iter_frames


def record_command(url: str, out_path: str) -> None:
    """Record MJPEG stream or video source to an MP4 video at 15 fps."""
    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer: cv2.VideoWriter | None = None
    try:
        for frame, _ in iter_frames(url):
            if writer is None:
                h, w = frame.shape[:2]
                writer = cv2.VideoWriter(str(out_file), fourcc, 15.0, (w, h))
            writer.write(frame)
    except KeyboardInterrupt:
        pass
    finally:
        if writer is not None:
            writer.release()


def calibrate_command(source: str, out_path: str) -> None:
    """Calibrate ROI, door line, and brightness thresholds."""
    calibrate(source, out_path)


def probe_command(clip: str, out_path: str, config_path: str = "config.json") -> None:
    """Run detector and overlay on clip without logic, writing MP4 at 15 fps."""
    from fridge_item.config import load
    from fridge_item.detect import Detector
    from fridge_item.draw import overlay

    cfg = load(config_path)
    detector = Detector(prompts=cfg.prompts, hand_label=cfg.hand_label)

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer: cv2.VideoWriter | None = None

    rx, ry, rw, rh = cfg.roi
    has_roi = rw > 0 and rh > 0
    door_open = True

    try:
        for frame, _ in iter_frames(clip):
            if writer is None:
                h, w = frame.shape[:2]
                writer = cv2.VideoWriter(str(out_file), fourcc, 15.0, (w, h))

            if has_roi and ry + rh <= frame.shape[0] and rx + rw <= frame.shape[1]:
                roi_crop = frame[ry : ry + rh, rx : rx + rw]
                brightness = float(np.mean(roi_crop))
                if brightness >= cfg.door_on:
                    door_open = True
                elif brightness <= cfg.door_off:
                    door_open = False

            tracks = detector(frame)
            annotated = overlay(frame, tracks, cfg.line, door_open, events=[])
            writer.write(annotated)
    except KeyboardInterrupt:
        pass
    finally:
        if writer is not None:
            writer.release()


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="fridge-item", description="Fridge Tracker item-recognition service")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    record_parser = subparsers.add_parser("record", help="Record video stream to MP4")
    record_parser.add_argument("url", help="HTTP stream URL or video path")
    record_parser.add_argument("out", help="Output MP4 file path")

    calibrate_parser = subparsers.add_parser(
        "calibrate", help="Calibrate fridge ROI, door line, and brightness thresholds"
    )
    calibrate_parser.add_argument("source", help="HTTP stream URL or video path")
    calibrate_parser.add_argument(
        "--out", default="config.json", help="Output config JSON path (default: config.json)"
    )

    probe_parser = subparsers.add_parser("probe", help="Run detector and overlay on clip")
    probe_parser.add_argument("clip", help="Input video clip path or stream URL")
    probe_parser.add_argument("out", help="Output overlay video MP4 path")
    probe_parser.add_argument(
        "--config", default="config.json", help="Path to config JSON (default: config.json)"
    )

    return parser.parse_args(args)


def main(args: list[str] | None = None) -> None:
    parsed = parse_args(args)
    if parsed.subcommand == "record":
        record_command(parsed.url, parsed.out)
    elif parsed.subcommand == "calibrate":
        calibrate_command(parsed.source, parsed.out)
    elif parsed.subcommand == "probe":
        probe_command(parsed.clip, parsed.out, parsed.config)


if __name__ == "__main__":
    main()
