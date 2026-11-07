# /// script
# requires-python = ">=3.11"
# dependencies = ["confluent-kafka", "jsonschema"]
# ///
"""Bắn sự kiện giả đúng contracts/ vào Redpanda để không ai phải chờ ai.

Kịch bản demo: p_01 đặt hộp sữa, rồi p_02 lấy nhầm.
    uv run tools/fake_events.py            # chạy 1 lần
    uv run tools/fake_events.py --loop     # lặp mãi, mỗi kịch bản cách nhau 5s
    uv run tools/fake_events.py --dry-run  # chỉ in ra, không cần Redpanda
"""
import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
VALIDATORS = {
    p.name.removesuffix(".schema.json"): Draft202012Validator(json.loads(p.read_text()))
    for p in CONTRACTS.glob("*.schema.json")
}


def now_ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def person(track_id, person_id, confidence):
    return {"event_id": str(uuid.uuid4()), "topic": "person.seen", "track_id": track_id,
            "person_id": person_id, "ts": now_ts(), "confidence": confidence}


def item(type, item_id, label, confidence):
    return {"event_id": str(uuid.uuid4()), "topic": "item.event", "type": type,
            "item_id": item_id, "item_label": label, "ts": now_ts(), "confidence": confidence}


def scenario():
    yield person(1, "p_01", 0.94)
    yield item("PUT", "item_042", "hộp sữa", 0.90)
    yield person(2, "p_02", 0.91)
    yield item("TAKE", "item_042", "hộp sữa", 0.87)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="localhost:19092")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    producer = None
    if not args.dry_run:
        from confluent_kafka import Producer
        producer = Producer({"bootstrap.servers": args.broker})

    while True:
        for ev in scenario():
            VALIDATORS[ev["topic"]].validate(ev)  # sự kiện giả cũng phải đúng contract
            print(json.dumps(ev, ensure_ascii=False))
            if producer:
                producer.produce(ev["topic"], key=ev["event_id"], value=json.dumps(ev, ensure_ascii=False))
                producer.flush()
            time.sleep(1)
        if not args.loop:
            break
        time.sleep(5)


if __name__ == "__main__":
    main()
