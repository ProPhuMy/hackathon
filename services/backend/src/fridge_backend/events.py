"""Builds fridge.event events matching contracts/fridge.event.schema.json. Every publish must go through here."""


def fridge_event(item: dict, person_id: str | None, owner_id: str | None, confidence: float, status: str) -> dict:
    """item is a received item.event; its event_id is kept as the idempotency key."""
    return {
        "event_id": item["event_id"],
        "topic": "fridge.event",
        "type": item["type"],
        "item_id": item["item_id"],
        "item_label": item["item_label"],
        "person_id": person_id,
        "owner_id": owner_id,
        "ts": item["ts"],
        "confidence": confidence,
        "status": status,
    }
