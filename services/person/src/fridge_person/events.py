"""Dựng sự kiện person.seen đúng contracts/person.seen.schema.json. Mọi chỗ publish phải đi qua đây."""
import uuid
from datetime import datetime, timezone


def now_ts() -> str:
    """UTC ISO 8601 có mili giây và hậu tố Z, đúng pattern trong contracts/."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def person_seen(track_id: int, person_id: str | None, confidence: float, ts: str | None = None) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "topic": "person.seen",
        "track_id": track_id,
        "person_id": person_id,
        "ts": ts or now_ts(),
        "confidence": confidence,
    }
