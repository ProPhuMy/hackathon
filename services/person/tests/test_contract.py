"""Sự kiện service này publish phải khớp schema trong contracts/. Đỏ ở đây = sẽ vỡ khi ghép."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from fridge_person.events import person_seen

SCHEMA = json.loads((Path(__file__).parents[3] / "contracts" / "person.seen.schema.json").read_text())


def test_event_matches_contract():
    Draft202012Validator(SCHEMA).validate(person_seen(track_id=7, person_id="p_02", confidence=0.93))


def test_contract_rejects_broken_event():
    bad = person_seen(track_id=7, person_id="p_02", confidence=0.93)
    del bad["ts"]
    with pytest.raises(ValidationError):
        Draft202012Validator(SCHEMA).validate(bad)
