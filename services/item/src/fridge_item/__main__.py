import argparse
import json
from pathlib import Path
import time

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


def run_command(
    source: str,
    config_path: str = "config.json",
    gallery_path: str = "data/gallery.json",
    broker: str = "localhost:19092",
    dry_run: bool = False,
    debug_video: str | None = None,
) -> None:
    """Run item recognition pipeline, printing events, publishing to Kafka, and tracking latency."""
    from fridge_item.config import load
    from fridge_item.detect import Detector
    from fridge_item.draw import overlay
    from fridge_item.gallery import ItemGallery
    from fridge_item.pipeline import ItemPipeline

    cfg = load(config_path)
    gallery = ItemGallery(gallery_path)
    detector = Detector(prompts=cfg.prompts, hand_label=cfg.hand_label)

    producer = None
    if not dry_run:
        from confluent_kafka import Producer

        producer = Producer({"bootstrap.servers": broker})

    detect_times: list[float] = []
    process_times: list[float] = []

    def timed_detect(frame: np.ndarray):
        t0 = time.perf_counter()
        tracks = detector(frame)
        detect_times.append((time.perf_counter() - t0) * 1000.0)
        return tracks

    pipeline = ItemPipeline(cfg=cfg, detect=timed_detect, gallery=gallery)

    writer: cv2.VideoWriter | None = None
    recent_events: list[dict] = []
    if debug_video is not None:
        out_file = Path(debug_video)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")

    frame_idx = 0
    try:
        for frame, ts in iter_frames(source):
            frame_idx += 1
            t_start = time.perf_counter()
            events = pipeline.process(frame, ts)
            process_times.append((time.perf_counter() - t_start) * 1000.0)

            for ev in events:
                print(json.dumps(ev, ensure_ascii=False), flush=True)
                if producer is not None:
                    producer.produce(
                        "item.event",
                        key=ev["event_id"],
                        value=json.dumps(ev, ensure_ascii=False),
                    )
                    producer.poll(0)
                if debug_video is not None:
                    recent_events.append(ev)

            if debug_video is not None:
                if writer is None:
                    h, w = frame.shape[:2]
                    writer = cv2.VideoWriter(str(out_file), fourcc, 15.0, (w, h))
                annotated = overlay(
                    frame,
                    pipeline.tracks,
                    cfg.line,
                    pipeline.door_open,
                    recent_events,
                )
                writer.write(annotated)

            if frame_idx % 100 == 0:
                det_p50 = (
                    float(np.percentile(detect_times, 50))
                    if detect_times
                    else 0.0
                )
                det_p95 = (
                    float(np.percentile(detect_times, 95))
                    if detect_times
                    else 0.0
                )
                proc_p50 = (
                    float(np.percentile(process_times, 50))
                    if process_times
                    else 0.0
                )
                proc_p95 = (
                    float(np.percentile(process_times, 95))
                    if process_times
                    else 0.0
                )
                print(
                    f"Frame {frame_idx}: detector p50={det_p50:.1f}ms p95={det_p95:.1f}ms | "
                    f"process p50={proc_p50:.1f}ms p95={proc_p95:.1f}ms",
                    flush=True,
                )
    except KeyboardInterrupt:
        pass
    finally:
        flushed_events = pipeline.close()
        for ev in flushed_events:
            print(json.dumps(ev, ensure_ascii=False), flush=True)
            if producer is not None:
                producer.produce(
                    "item.event",
                    key=ev["event_id"],
                    value=json.dumps(ev, ensure_ascii=False),
                )
                producer.poll(0)
        if producer is not None:
            producer.flush()
        if writer is not None:
            writer.release()



def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fridge-item", description="Fridge Tracker item-recognition service"
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    record_parser = subparsers.add_parser("record", help="Record video stream to MP4")
    record_parser.add_argument("url", help="HTTP stream URL or video path")
    record_parser.add_argument("out", help="Output MP4 file path")

    calibrate_parser = subparsers.add_parser(
        "calibrate", help="Calibrate fridge ROI, door line, and brightness thresholds"
    )
    calibrate_parser.add_argument("source", help="HTTP stream URL or video path")
    calibrate_parser.add_argument(
        "--out",
        default="config.json",
        help="Output config JSON path (default: config.json)",
    )

    probe_parser = subparsers.add_parser(
        "probe", help="Run detector and overlay on clip"
    )
    probe_parser.add_argument("clip", help="Input video clip path or stream URL")
    probe_parser.add_argument("out", help="Output overlay video MP4 path")
    probe_parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config JSON (default: config.json)",
    )

    run_parser = subparsers.add_parser("run", help="Run item recognition pipeline")
    run_parser.add_argument(
        "--source", required=True, help="HTTP stream URL or video path"
    )
    run_parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config JSON (default: config.json)",
    )
    run_parser.add_argument(
        "--gallery",
        default="data/gallery.json",
        help="Path to gallery JSON (default: data/gallery.json)",
    )
    run_parser.add_argument(
        "--broker",
        default="localhost:19092",
        help="Kafka broker address (default: localhost:19092)",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print events only, do not publish to Kafka",
    )
    run_parser.add_argument(
        "--debug-video",
        default=None,
        help="Output overlay video MP4 path",
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
    elif parsed.subcommand == "run":
        run_command(
            source=parsed.source,
            config_path=parsed.config,
            gallery_path=parsed.gallery,
            broker=parsed.broker,
            dry_run=parsed.dry_run,
            debug_video=parsed.debug_video,
        )


if __name__ == "__main__":
    main()
