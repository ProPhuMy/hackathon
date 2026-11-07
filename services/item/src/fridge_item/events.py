"""Dựng sự kiện item.event đúng contracts/item.event.schema.json. Mọi chỗ publish phải đi qua đây."""
import uuid
from datetime import datetime, timezone


def now_ts() -> str:
    """UTC ISO 8601 có mili giây và hậu tố Z, đúng pattern trong contracts/."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def item_event(type: str, item_id: str, item_label: str, confidence: float, ts: str | None = None) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "topic": "item.event",
        "type": type,
        "item_id": item_id,
        "item_label": item_label,
        "ts": ts or now_ts(),
        "confidence": confidence,
    }
