"""Tests for ownership consistency rules (Rules 10-15) and immutability."""

import pytest
from fridge_backend import consistency


def test_rule_10_put_item_already_in():
    state = {"item_042": "p_01"}
    owner_id, status = consistency.decide(
        state=state,
        item_type="PUT",
        item_id="item_042",
        person_id="p_02",
        confidence=0.95,
        threshold=0.5,
    )
    assert owner_id == "p_01"
    assert status == "uncertain"


def test_rule_11_put_item_not_in_ok():
    state = {}
    owner_id, status = consistency.decide(
        state=state,
        item_type="PUT",
        item_id="item_042",
        person_id="p_01",
        confidence=0.90,
        threshold=0.5,
    )
    assert owner_id == "p_01"
    assert status == "ok"


def test_rule_11_put_item_not_in_uncertain_stranger():
    state = {}
    owner_id, status = consistency.decide(
        state=state,
        item_type="PUT",
        item_id="item_042",
        person_id=None,
        confidence=0.90,
        threshold=0.5,
    )
    assert owner_id is None
    assert status == "uncertain"


def test_rule_11_put_item_not_in_uncertain_low_confidence():
    state = {}
    owner_id, status = consistency.decide(
        state=state,
        item_type="PUT",
        item_id="item_042",
        person_id="p_01",
        confidence=0.45,
        threshold=0.5,
    )
    assert owner_id == "p_01"
    assert status == "uncertain"


def test_rule_12_take_item_not_in():
    state = {}
    owner_id, status = consistency.decide(
        state=state,
        item_type="TAKE",
        item_id="item_042",
        person_id="p_01",
        confidence=0.95,
        threshold=0.5,
    )
    assert owner_id is None
    assert status == "uncertain"


def test_rule_13_take_item_in_ok():
    state = {"item_042": "p_01"}
    owner_id, status = consistency.decide(
        state=state,
        item_type="TAKE",
        item_id="item_042",
        person_id="p_01",
        confidence=0.85,
        threshold=0.5,
    )
    assert owner_id == "p_01"
    assert status == "ok"


def test_rule_13_take_item_in_wrong_owner():
    state = {"item_042": "p_01"}
    owner_id, status = consistency.decide(
        state=state,
        item_type="TAKE",
        item_id="item_042",
        person_id="p_02",
        confidence=0.85,
        threshold=0.5,
    )
    assert owner_id == "p_01"
    assert status == "wrong_owner"


def test_rule_13_take_item_in_uncertain_stranger():
    state = {"item_042": "p_01"}
    owner_id, status = consistency.decide(
        state=state,
        item_type="TAKE",
        item_id="item_042",
        person_id=None,
        confidence=0.85,
        threshold=0.5,
    )
    assert owner_id == "p_01"
    assert status == "uncertain"


def test_rule_13_take_item_in_uncertain_owner_none():
    state = {"item_042": None}
    owner_id, status = consistency.decide(
        state=state,
        item_type="TAKE",
        item_id="item_042",
        person_id="p_01",
        confidence=0.85,
        threshold=0.5,
    )
    assert owner_id is None
    assert status == "uncertain"


def test_rule_13_take_item_in_uncertain_low_confidence():
    state = {"item_042": "p_01"}
    # Low confidence on wrong owner -> uncertain, not wrong_owner
    owner_id, status = consistency.decide(
        state=state,
        item_type="TAKE",
        item_id="item_042",
        person_id="p_02",
        confidence=0.40,
        threshold=0.5,
    )
    assert owner_id == "p_01"
    assert status == "uncertain"


def test_rule_14_apply_put():
    state = {}
    ev = {"type": "PUT", "item_id": "item_042", "owner_id": "p_01"}
    new_state = consistency.apply(state, ev)
    assert new_state == {"item_042": "p_01"}

    # Item already IN: state unchanged
    ev_duplicate = {"type": "PUT", "item_id": "item_042", "owner_id": "p_02"}
    dup_state = consistency.apply(new_state, ev_duplicate)
    assert dup_state == {"item_042": "p_01"}


def test_rule_15_apply_take():
    state = {"item_042": "p_01", "item_099": "p_02"}
    ev = {"type": "TAKE", "item_id": "item_042", "owner_id": "p_01"}
    new_state = consistency.apply(state, ev)
    assert new_state == {"item_099": "p_02"}

    # Item not present: safe no-op
    ev_not_in = {"type": "TAKE", "item_id": "item_unknown", "owner_id": None}
    after_not_in = consistency.apply(new_state, ev_not_in)
    assert after_not_in == {"item_099": "p_02"}


def test_apply_and_decide_never_mutate_state():
    initial = {"item_042": "p_01"}
    frozen = {"item_042": "p_01"}

    consistency.decide(initial, "PUT", "item_042", "p_02", 0.9, 0.5)
    assert initial == frozen

    consistency.decide(initial, "TAKE", "item_042", "p_02", 0.9, 0.5)
    assert initial == frozen

    consistency.apply(initial, {"type": "PUT", "item_id": "item_043", "owner_id": "p_03"})
    assert initial == frozen

    consistency.apply(initial, {"type": "TAKE", "item_id": "item_042", "owner_id": "p_01"})
    assert initial == frozen
