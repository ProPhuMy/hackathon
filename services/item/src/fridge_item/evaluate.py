from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
import tempfile
from typing import Sequence


def score(
    expected: Sequence[tuple[str, str]], got: Sequence[tuple[str, str]]
) -> dict[str, int]:
    """Multiset match on (type, item_label) -> {"correct", "missed", "extra"}."""
    exp_counts = Counter(expected)
    got_counts = Counter(got)
    correct = sum((exp_counts & got_counts).values())
    missed = len(expected) - correct
    extra = len(got) - correct
    return {"correct": correct, "missed": missed, "extra": extra}


def load_labels(labels_path: str | Path) -> dict[str, list[tuple[str, str]]]:
    """Load labels CSV grouped by clip name.

    Rows: clip,type,item_label (one row per expected event).
    """
    labels_file = Path(labels_path)
    expected_by_clip: dict[str, list[tuple[str, str]]] = {}
    if not labels_file.is_file():
        return expected_by_clip

    with open(labels_file, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or not any(field.strip() for field in row):
                continue
            if row[0].strip().lower() == "clip" and len(row) > 1 and row[1].strip().lower() == "type":
                continue
            clip_name = row[0].strip()
            ev_type = row[1].strip()
            item_label = row[2].strip() if len(row) > 2 else ""
            if clip_name not in expected_by_clip:
                expected_by_clip[clip_name] = []
            expected_by_clip[clip_name].append((ev_type, item_label))
    return expected_by_clip


def reset_tracker(detector) -> None:
    """Reset tracker state on detector so tracks do not carry over across clips."""
    if hasattr(detector, "reset") and callable(detector.reset):
        detector.reset()
    if hasattr(detector, "model") and hasattr(detector.model, "predictor"):
        predictor = detector.model.predictor
        if predictor is not None and hasattr(predictor, "trackers"):
            predictor.trackers = []
    try:
        from ultralytics.trackers.basetrack import BaseTrack

        BaseTrack._count = 0
    except Exception:
        pass


def evaluate_command(
    labels_path: str = "data/labels.csv",
    clips_dir: str = "data/clips",
    config_path: str = "config.json",
) -> dict[str, int]:
    """Run ItemPipeline over labeled clips with a temporary gallery per clip and evaluate accuracy."""
    from fridge_item.config import load
    from fridge_item.detect import Detector
    from fridge_item.gallery import ItemGallery
    from fridge_item.pipeline import ItemPipeline
    from fridge_item.stream import iter_frames

    expected_by_clip = load_labels(labels_path)
    if not expected_by_clip:
        print("total: correct=0 missed=0 extra=0 accuracy=0.0", flush=True)
        return {"correct": 0, "missed": 0, "extra": 0}

    cfg = load(config_path)
    detector = Detector(prompts=cfg.prompts, hand_label=cfg.hand_label)

    total_correct = 0
    total_missed = 0
    total_extra = 0

    for clip_name, expected_events in expected_by_clip.items():
        clip_path = Path(clips_dir) / clip_name
        reset_tracker(detector)

        got_events: list[tuple[str, str]] = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            gallery = ItemGallery(str(Path(tmp_dir) / "gallery.json"))
            pipeline = ItemPipeline(cfg=cfg, detect=detector, gallery=gallery)

            for frame, ts in iter_frames(str(clip_path)):
                events = pipeline.process(frame, ts)
                for ev in events:
                    got_events.append((ev["type"], ev["item_label"]))

            for ev in pipeline.close():
                got_events.append((ev["type"], ev["item_label"]))

        clip_res = score(expected_events, got_events)
        c = clip_res["correct"]
        m = clip_res["missed"]
        e = clip_res["extra"]
        denom = c + m + e
        acc = c / denom if denom > 0 else 0.0
        acc_str = "0.0" if denom == 0 else f"{acc:.4f}"
        print(f"{clip_name}: correct={c} missed={m} extra={e} accuracy={acc_str}", flush=True)

        total_correct += c
        total_missed += m
        total_extra += e

    tot_denom = total_correct + total_missed + total_extra
    tot_acc = total_correct / tot_denom if tot_denom > 0 else 0.0
    tot_acc_str = "0.0" if tot_denom == 0 else f"{tot_acc:.4f}"
    print(
        f"total: correct={total_correct} missed={total_missed} extra={total_extra} accuracy={tot_acc_str}",
        flush=True,
    )

    return {"correct": total_correct, "missed": total_missed, "extra": total_extra}
