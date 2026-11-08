import json
from pathlib import Path
import time

import cv2
import numpy as np

from ..config import load
from ..core.gallery import ItemGallery
from ..core.pipeline import ItemPipeline
from ..draw import overlay, video_writer
from ..stream import iter_frames
from ..vision import detector_class, optional_models


def _percentile(values: list[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else 0.0


def run_command(
    source: str,
    config_path: str = "config.json",
    gallery_path: str = "data/gallery.json",
    broker: str = "localhost:19092",
    dry_run: bool = False,
    debug_video: str | None = None,
    embed: bool = False,
    holding: str = "box",
    detector: str = "yoloe",
    shelf_check: bool = False,
) -> None:
    """Run item recognition pipeline, printing events, publishing to Kafka, and tracking latency."""
    cfg = load(config_path)
    gallery = ItemGallery(gallery_path)
    detector_model = detector_class(detector)(prompts=cfg.prompts, hand_label=cfg.hand_label)
    embedder, segmenter = optional_models(embed, holding)

    producer = None
    if not dry_run:
        from confluent_kafka import Producer

        producer = Producer({"bootstrap.servers": broker})

    detect_times: list[float] = []
    process_times: list[float] = []

    def timed_detect(frame: np.ndarray):
        t0 = time.perf_counter()
        tracks = detector_model(frame)
        detect_times.append((time.perf_counter() - t0) * 1000.0)
        return tracks

    pipeline = ItemPipeline(
        cfg=cfg,
        detect=timed_detect,
        gallery=gallery,
        embed=embedder,
        segment=segmenter,
        shelf_check=shelf_check,
    )

    writer: cv2.VideoWriter | None = None
    recent_events: list[dict] = []
    if debug_video is not None:
        out_file = Path(debug_video)
        out_file.parent.mkdir(parents=True, exist_ok=True)

    def on_delivery(err, _msg=None):
        if err:
            print(f"kafka delivery failed: {err}", flush=True)

    def publish(ev: dict) -> None:
        print(json.dumps(ev, ensure_ascii=False), flush=True)
        if producer is not None:
            producer.produce(
                "item.event",
                key=ev["event_id"],
                value=json.dumps(ev, ensure_ascii=False),
                on_delivery=on_delivery,
            )
            producer.poll(0)

    frame_idx = 0
    try:
        for frame, ts in iter_frames(source):
            frame_idx += 1
            t_start = time.perf_counter()
            events = pipeline.process(frame, ts)
            process_times.append((time.perf_counter() - t_start) * 1000.0)

            for ev in events:
                publish(ev)
                if debug_video is not None:
                    recent_events.append(ev)

            if debug_video is not None:
                if writer is None:
                    writer = video_writer(out_file, frame)
                annotated = overlay(
                    frame,
                    pipeline.tracks,
                    cfg.line,
                    pipeline.door_open,
                    recent_events,
                )
                writer.write(annotated)

            if frame_idx % 100 == 0:
                print(
                    f"Frame {frame_idx}: detector p50={_percentile(detect_times, 50):.1f}ms "
                    f"p95={_percentile(detect_times, 95):.1f}ms | "
                    f"process p50={_percentile(process_times, 50):.1f}ms "
                    f"p95={_percentile(process_times, 95):.1f}ms",
                    flush=True,
                )
    except KeyboardInterrupt:
        pass
    finally:
        try:
            for ev in pipeline.close():
                publish(ev)
        finally:
            try:
                if writer is not None:
                    writer.release()
            finally:
                if producer is not None:
                    remaining = producer.flush(10)
                    if remaining:
                        print(
                            f"warning: kafka producer flush timed out with {remaining} messages remaining",
                            flush=True,
                        )
