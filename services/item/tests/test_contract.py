"""Sự kiện service này publish phải khớp schema trong contracts/. Đỏ ở đây = sẽ vỡ khi ghép."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from fridge_item.events import item_event

SCHEMA = json.loads((Path(__file__).parents[3] / "contracts" / "item.event.schema.json").read_text())


def test_event_matches_contract():
    Draft202012Validator(SCHEMA).validate(item_event("TAKE", "item_042", "hộp sữa", 0.88))


def test_contract_rejects_broken_event():
    bad = item_event("TAKE", "item_042", "hộp sữa", 0.88)
    del bad["type"]
    with pytest.raises(ValidationError):
        Draft202012Validator(SCHEMA).validate(bad)
