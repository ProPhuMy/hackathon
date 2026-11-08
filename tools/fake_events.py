# /// script
# requires-python = ">=3.11"
# dependencies = ["confluent-kafka", "jsonschema"]
# ///
"""Publish fake events matching contracts/ to Redpanda so nobody has to wait on anyone.

Demo scenario: p_01 puts a milk carton in, then p_02 takes it by mistake.
    uv run tools/fake_events.py            # run once
    uv run tools/fake_events.py --loop     # loop forever, 5s between scenarios
    uv run tools/fake_events.py --dry-run  # print only, no Redpanda needed
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
    yield item("PUT", "item_042", "milk carton", 0.90)
    yield person(2, "p_02", 0.91)
    yield item("TAKE", "item_042", "milk carton", 0.87)


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
            VALIDATORS[ev["topic"]].validate(ev)  # fake events must match the contract too
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
