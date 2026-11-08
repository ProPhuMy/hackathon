"""Events this service publishes must match the schema in contracts/. Red here = breaks at integration."""
import json

import pytest
from jsonschema import Draft202012Validator, ValidationError

from conftest import SCHEMA_PATH
from src.events import person_seen

SCHEMA = json.loads(SCHEMA_PATH.read_text())


def test_event_matches_contract():
    Draft202012Validator(SCHEMA).validate(person_seen(track_id=7, person_id="p_02", confidence=0.93))


def test_contract_rejects_broken_event():
    bad = person_seen(track_id=7, person_id="p_02", confidence=0.93)
    del bad["ts"]
    with pytest.raises(ValidationError):
        Draft202012Validator(SCHEMA).validate(bad)


def test_null_identity_and_preserved_evidence_timestamp():
    ts = '2026-11-08T09:15:02.120Z'
    event = person_seen(0, None, 0., ts=ts)
    Draft202012Validator(SCHEMA).validate(event)
    assert event['ts'] == ts
    assert set(event) == set(SCHEMA['required'])


@pytest.mark.parametrize('confidence', [-.1, 1.1, float('inf'), -float('inf')])
def test_contract_rejects_invalid_confidence(confidence):
    with pytest.raises(ValidationError):
        Draft202012Validator(SCHEMA).validate(person_seen(0, 'a', confidence))
