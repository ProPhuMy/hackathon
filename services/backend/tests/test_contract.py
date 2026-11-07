"""Sự kiện service này publish phải khớp schema trong contracts/. Đỏ ở đây = sẽ vỡ khi ghép."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from fridge_backend.events import fridge_event
ITEM = {"event_id": "e1", "topic": "item.event", "type": "TAKE", "item_id": "item_042", "item_label": "hộp sữa", "ts": "2026-11-08T09:15:03.480Z", "confidence": 0.88}

SCHEMA = json.loads((Path(__file__).parents[3] / "contracts" / "fridge.event.schema.json").read_text())


def test_event_matches_contract():
    Draft202012Validator(SCHEMA).validate(fridge_event(ITEM, person_id="p_03", owner_id="p_02", confidence=0.85, status="wrong_owner"))


def test_contract_rejects_broken_event():
    bad = fridge_event(ITEM, person_id="p_03", owner_id="p_02", confidence=0.85, status="wrong_owner")
    del bad["status"]
    with pytest.raises(ValidationError):
        Draft202012Validator(SCHEMA).validate(bad)
