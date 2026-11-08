"""Events this service publishes must match the schema in contracts/. Red here = breaks at integration."""
import pytest
from jsonschema import Draft202012Validator, ValidationError

from conftest import SCHEMA
from src.events import item_event


def test_event_matches_contract():
    Draft202012Validator(SCHEMA).validate(item_event("TAKE", "item_042", "milk carton", 0.88))


def test_contract_rejects_broken_event():
    bad = item_event("TAKE", "item_042", "milk carton", 0.88)
    del bad["type"]
    with pytest.raises(ValidationError):
        Draft202012Validator(SCHEMA).validate(bad)
