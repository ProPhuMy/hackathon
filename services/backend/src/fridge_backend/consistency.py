"""Ownership consistency rules and inventory state transitions."""


def decide(
    state: dict,
    item_type: str,
    item_id: str,
    person_id: str | None,
    confidence: float,
    threshold: float,
) -> tuple[str | None, str]:
    """Returns (owner_id, status). Pure function; never mutates state."""
    if item_type == "PUT":
        if item_id in state:
            # Rule 10: PUT, item already IN state: owner_id = state[item_id] (unchanged), status "uncertain"
            return state[item_id], "uncertain"
        else:
            # Rule 11: PUT, item not IN: owner_id = person_id; status "uncertain" if person_id is None or confidence < threshold, else "ok"
            status = "uncertain" if (person_id is None or confidence < threshold) else "ok"
            return person_id, status
    elif item_type == "TAKE":
        if item_id not in state:
            # Rule 12: TAKE, item not IN: owner_id = None, status "uncertain"
            return None, "uncertain"
        else:
            # Rule 13: TAKE, item IN: owner_id = state[item_id]; status "uncertain" if person_id is None or owner_id is None or confidence < threshold; else "wrong_owner" if person_id != owner_id; else "ok"
            owner_id = state[item_id]
            if person_id is None or owner_id is None or confidence < threshold:
                status = "uncertain"
            elif person_id != owner_id:
                status = "wrong_owner"
            else:
                status = "ok"
            return owner_id, status
    else:
        return None, "uncertain"


def apply(state: dict, fridge_event: dict) -> dict:
    """Returns the new state after one fridge.event. Pure function; never mutates state."""
    new_state = state.copy()
    ev_type = fridge_event.get("type")
    item_id = fridge_event.get("item_id")
    owner_id = fridge_event.get("owner_id")

    if ev_type == "PUT":
        # Rule 14: PUT: if item_id not in state, new state has item_id -> owner_id; if already IN, state unchanged.
        if item_id not in new_state:
            new_state[item_id] = owner_id
    elif ev_type == "TAKE":
        # Rule 15: TAKE: item_id removed if present (the item physically left even when status is uncertain).
        new_state.pop(item_id, None)

    return new_state
