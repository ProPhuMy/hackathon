"""Builds item.event events matching contracts/item.event.schema.json. Every publish must go through here."""
import uuid
from datetime import datetime, timezone


def now_ts() -> str:
    """UTC ISO 8601 with milliseconds and a Z suffix, matching the pattern in contracts/."""
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
