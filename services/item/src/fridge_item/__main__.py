import argparse
from pathlib import Path

import cv2

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


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="fridge-item", description="Fridge Tracker item-recognition service")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    record_parser = subparsers.add_parser("record", help="Record video stream to MP4")
    record_parser.add_argument("url", help="HTTP stream URL or video path")
    record_parser.add_argument("out", help="Output MP4 file path")

    return parser.parse_args(args)


def main(args: list[str] | None = None) -> None:
    parsed = parse_args(args)
    if parsed.subcommand == "record":
        record_command(parsed.url, parsed.out)


if __name__ == "__main__":
    main()
