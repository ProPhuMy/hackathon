"""Dựng sự kiện fridge.event đúng contracts/fridge.event.schema.json. Mọi chỗ publish phải đi qua đây."""


def fridge_event(item: dict, person_id: str | None, owner_id: str | None, confidence: float, status: str) -> dict:
    """item là một item.event đã nhận; giữ event_id của nó làm idempotency key."""
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
