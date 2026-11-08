"""Tests for deterministic offline synthetic real-Matcher replay skeleton."""

from dataclasses import asdict
import copy
import json
import math
from pathlib import Path
import pytest
import sys

from fridge_backend.eval_runner import (
    run_eval,
    run_case,
    validate_fixture,
    load_validators,
    check_no_bool_or_nonfinite,
    validate_iso_utc_timestamp,
    find_contracts_dir,
    main,
)
from fridge_backend.matcher import Matcher, MatcherConfig, MATCHER_VERSION


FIXTURE_PATH = Path(__file__).parents[1] / "synthetic_replay.json"


def test_eval_runner_synthetic_fixture_passes_with_zero_exit_code():
    report, exit_code = run_eval(FIXTURE_PATH)
    assert exit_code == 0
    assert report["summary"]["failed"] == 0
    assert report["summary"]["total_cases"] == 4
    assert report["summary"]["passed"] == 4
    assert report["dataset_type"] == "synthetic_only"
    assert report["matcher_version"] == MATCHER_VERSION
    assert "tolerance <= 1e-4" in report["comparison_definition"]

    # Assert ALL asdict(MatcherConfig()) metadata matches exactly
    expected_cfg = asdict(MatcherConfig())
    assert report["matcher_config"] == expected_cfg
    for k in (
        "back_ms", "fwd_ms", "lateness_ms", "idle_timeout_ms",
        "person_retention_ms", "threshold", "association",
        "sigma_ms", "n_eff_cap", "null_prior", "min_gap_ms",
    ):
        assert k in report["matcher_config"]


def test_eval_runner_deterministic_replay_twice():
    report1, code1 = run_eval(FIXTURE_PATH)
    report2, code2 = run_eval(FIXTURE_PATH)
    assert code1 == 0 and code2 == 0
    assert report1 == report2


def test_eval_runner_detects_missing_output(tmp_path):
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    # Add extra expected output that won't be emitted
    extra_out = copy.deepcopy(data["cases"][0]["expected_outputs"][0])
    extra_out["event_id"] = "i_missing_expected"
    data["cases"][0]["expected_outputs"].append(extra_out)

    tampered_file = tmp_path / "tampered_missing.json"
    tampered_file.write_text(json.dumps(data), encoding="utf-8")

    report, code = run_eval(tampered_file)
    assert code == 1
    assert report["summary"]["failed"] >= 1
    case_fail = next(f for f in report["failures"] if f["case_id"] == "canonical_put_take")
    assert any("Output count mismatch" in r for r in case_fail["reasons"])


def test_eval_runner_detects_extra_output(tmp_path):
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    # Remove one expected output so actual output is extra
    data["cases"][0]["expected_outputs"].pop()

    tampered_file = tmp_path / "tampered_extra.json"
    tampered_file.write_text(json.dumps(data), encoding="utf-8")

    report, code = run_eval(tampered_file)
    assert code == 1
    assert report["summary"]["failed"] >= 1
    case_fail = next(f for f in report["failures"] if f["case_id"] == "canonical_put_take")
    assert any("Output count mismatch" in r for r in case_fail["reasons"])


def test_eval_runner_detects_out_of_order_output(tmp_path):
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    # Swap expected outputs order in canonical_put_take
    outs = data["cases"][0]["expected_outputs"]
    data["cases"][0]["expected_outputs"] = [outs[1], outs[0]]

    tampered_file = tmp_path / "tampered_order.json"
    tampered_file.write_text(json.dumps(data), encoding="utf-8")

    report, code = run_eval(tampered_file)
    assert code == 1
    case_fail = next(f for f in report["failures"] if f["case_id"] == "canonical_put_take")
    assert any("mismatch" in r for r in case_fail["reasons"])


def test_eval_runner_detects_field_and_confidence_mismatch(tmp_path):
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    # Tamper confidence by more than 1e-4
    data["cases"][0]["expected_outputs"][0]["confidence"] = 0.5000

    tampered_file = tmp_path / "tampered_conf.json"
    tampered_file.write_text(json.dumps(data), encoding="utf-8")

    report, code = run_eval(tampered_file)
    assert code == 1
    case_fail = next(f for f in report["failures"] if f["case_id"] == "canonical_put_take")
    assert any("confidence mismatch" in r for r in case_fail["reasons"])


def test_eval_runner_detects_inventory_mismatch(tmp_path):
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    # Tamper expected inventory
    data["cases"][0]["expected_inventory"] = {"item_042": "p_01"}

    tampered_file = tmp_path / "tampered_inv.json"
    tampered_file.write_text(json.dumps(data), encoding="utf-8")

    report, code = run_eval(tampered_file)
    assert code == 1
    case_fail = next(f for f in report["failures"] if f["case_id"] == "canonical_put_take")
    assert any("Inventory mismatch" in r for r in case_fail["reasons"])


def test_eval_runner_call_order_sensitivity():
    """Verifies that moving a late person input before the tick yields a different Matcher result."""
    item_ev = {
        "event_id": "i_order_1", "topic": "item.event", "type": "PUT",
        "item_id": "item_070", "item_label": "sliced bread",
        "ts": "2026-11-08T09:15:01.000Z", "confidence": 0.85
    }
    person_ev = {
        "event_id": "p_order_late", "topic": "person.seen", "track_id": 1,
        "person_id": "p_01", "ts": "2026-11-08T09:15:02.000Z", "confidence": 0.95
    }

    # Order 1: item, tick, then late person
    m1 = Matcher(MatcherConfig())
    m1.on_item(item_ev)
    outs_tick = m1.tick("2026-11-08T09:15:08.000Z")
    assert len(outs_tick) == 1
    assert outs_tick[0]["person_id"] is None
    assert outs_tick[0]["status"] == "uncertain"
    outs_late = m1.on_person(person_ev)
    assert outs_late == []

    # Order 2: item, person before tick, then tick
    m2 = Matcher(MatcherConfig())
    m2.on_item(item_ev)
    m2.on_person(person_ev)
    outs_reordered = m2.tick("2026-11-08T09:15:08.000Z")
    assert len(outs_reordered) == 1
    assert outs_reordered[0]["person_id"] == "p_01"
    assert outs_reordered[0]["status"] == "ok"


def test_eval_runner_tick_boundary_just_before_vs_at_boundary():
    """Shortened calls verifying tick just before boundary emits nothing, tick at boundary emits output."""
    m = Matcher(MatcherConfig())
    item_ev = {
        "event_id": "i_b_test", "topic": "item.event", "type": "PUT",
        "item_id": "item_b", "item_label": "Bread",
        "ts": "2026-11-08T09:15:01.000Z", "confidence": 0.85
    }
    m.on_item(item_ev)

    # Just before boundary: 7999 ms (readiness is 1000 + 7000 = 8000 ms)
    outs_before = m.tick("2026-11-08T09:15:07.999Z")
    assert outs_before == []

    # At boundary: 8000 ms
    outs_at = m.tick("2026-11-08T09:15:08.000Z")
    assert len(outs_at) == 1
    assert outs_at[0]["event_id"] == "i_b_test"


def test_eval_runner_run_case_call_order_sensitive():
    """Production run_case preserves call order; reordering late person before tick mismatches."""
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    orig_case = next(c for c in data["cases"] if c["case_id"] == "call_order_tick_before_late_person")

    # 1. Original case passes cleanly through production run_case
    assert run_case(orig_case) == []

    # 2. Reorder item, person, ticks with SAME fixed expected uncertain outputs and inventory
    item_call = orig_case["calls"][0]
    tick_before = orig_case["calls"][1]
    tick_boundary = orig_case["calls"][2]
    person_call = orig_case["calls"][3]

    reordered_case = copy.deepcopy(orig_case)
    reordered_case["calls"] = [item_call, person_call, tick_before, tick_boundary]

    # Reordering causes matcher to associate person with item, producing 'ok' status
    # instead of expected 'uncertain', so production run_case returns mismatches.
    mismatches = run_case(reordered_case)
    assert len(mismatches) > 0


def test_eval_runner_run_case_tick_boundary():
    """Production run_case tests tick boundary and proves no hidden final tick."""
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    orig_case = next(c for c in data["cases"] if c["case_id"] == "call_order_tick_before_late_person")

    item_call = orig_case["calls"][0]
    tick_before = orig_case["calls"][1]
    tick_boundary = orig_case["calls"][2]

    # Sub-case A: calls=[item, just-before-tick], expected_outputs=[], expected_inventory={}
    # Must emit nothing before boundary
    case_before = {
        "case_id": "call_order_just_before_tick",
        "calls": [copy.deepcopy(item_call), copy.deepcopy(tick_before)],
        "expected_outputs": [],
        "expected_inventory": {},
    }
    assert run_case(case_before) == []

    # Sub-case B: at-boundary case with original fixed expected output must pass
    case_at = {
        "case_id": "call_order_at_boundary_tick",
        "calls": [copy.deepcopy(item_call), copy.deepcopy(tick_boundary)],
        "expected_outputs": copy.deepcopy(orig_case["expected_outputs"]),
        "expected_inventory": copy.deepcopy(orig_case["expected_inventory"]),
    }
    assert run_case(case_at) == []


@pytest.mark.parametrize("malformed_modifier, expected_err", [
    (lambda d: d.update({"unknown_root_key": True}), "Unknown root fields"),
    (lambda d: d["cases"][0].update({"unknown_case_field": "bad"}), "Unknown fields in cases[0]"),
    (lambda d: d["cases"][0]["calls"][0].update({"unknown_call_field": "bad"}), "Unknown fields in cases[0].calls[0]"),
    (lambda d: d["cases"][0]["calls"][0].update({"kind": "unsupported_kind"}), "Unsupported call kind"),
    (lambda d: d.update({"cases": []}), "'cases' list cannot be empty"),
    (lambda d: d.pop("cases"), "'cases' must be a list"),
    (lambda d: d["cases"].append(copy.deepcopy(d["cases"][0])), "Duplicate case_id"),
    (lambda d: d["cases"][0]["calls"][0]["event"].update({"track_id": True}), "is not of type 'integer'"),
    (lambda d: d["cases"][0]["calls"][0]["event"].update({"confidence": False}), "is not of type 'number'"),
    (lambda d: d["cases"][0]["calls"][0]["event"].update({"ts": "2026-02-29T09:15:00.000Z"}), "invalid calendar date"),
    (lambda d: d["cases"][0]["calls"][0]["event"].update({"ts": "2026-13-01T09:15:00.000Z"}), "invalid calendar date"),
    (lambda d: d["cases"][0]["calls"][0]["event"].update({"ts": "2026-11-08T09:15:00.000Z\n"}), "does not match ISO 8601 UTC pattern"),
    (lambda d: d.update({"schema_version": "2.0"}), "schema_version '1.0'"),
    (lambda d: d.pop("schema_version"), "schema_version '1.0'"),
    (lambda d: d.update({"description": 123}), "Root description must be a string"),
    (lambda d: d["cases"][0].update({"description": True}), "description must be a string"),
    (lambda d: d["cases"][0].update({"expected_inventory": 42}), "expected_inventory must be a dict"),
    (lambda d: d["cases"][0].update({"expected_inventory": {"item_bad": True}}), "Invalid item_id or owner_id"),
    (lambda d: d["cases"][0]["expected_outputs"][0].pop("status"), "is a required property"),
])
def test_eval_runner_malformed_fixture_rejection(tmp_path, malformed_modifier, expected_err):
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    malformed_modifier(data)

    bad_file = tmp_path / "bad_fixture.json"
    bad_file.write_text(json.dumps(data), encoding="utf-8")

    report, code = run_eval(bad_file)
    assert code == 2
    assert report["status"] == "error"
    assert report["exit_code"] == 2
    assert expected_err in report["error"]


def test_eval_runner_rejects_nan_and_infinity_and_overflow(tmp_path):
    bad_nan_text = '{"schema_version": "1.0", "description": "test", "cases": [{"case_id": "c1", "calls": [], "expected_outputs": [], "expected_inventory": {}}], "val": NaN}'
    bad_nan_file = tmp_path / "bad_nan.json"
    bad_nan_file.write_text(bad_nan_text, encoding="utf-8")

    report, code = run_eval(bad_nan_file)
    assert code == 2
    assert "Non-finite float" in report["error"]

    bad_inf_text = '{"schema_version": "1.0", "description": "test", "cases": [{"case_id": "c1", "calls": [], "expected_outputs": [], "expected_inventory": {}}], "val": Infinity}'
    bad_inf_file = tmp_path / "bad_inf.json"
    bad_inf_file.write_text(bad_inf_text, encoding="utf-8")

    report2, code2 = run_eval(bad_inf_file)
    assert code2 == 2
    assert "Non-finite float" in report2["error"]

    bad_overflow_text = '{"schema_version": "1.0", "description": "test", "cases": [{"case_id": "c1", "calls": [], "expected_outputs": [], "expected_inventory": {}}], "val": 1e999}'
    bad_overflow_file = tmp_path / "bad_overflow.json"
    bad_overflow_file.write_text(bad_overflow_text, encoding="utf-8")

    report3, code3 = run_eval(bad_overflow_file)
    assert code3 == 2
    assert "Non-finite float" in report3["error"]


def test_eval_runner_rejects_invalid_json(tmp_path):
    bad_json_file = tmp_path / "malformed.json"
    bad_json_file.write_text("{ unclosed json", encoding="utf-8")

    report, code = run_eval(bad_json_file)
    assert code == 2
    assert report["status"] == "error"


def test_eval_runner_cli_exit_code_1_on_mismatch(capsys, tmp_path):
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    data["cases"][0]["expected_outputs"][0]["confidence"] = 0.1234
    tampered_file = tmp_path / "tampered_cli.json"
    tampered_file.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main([str(tampered_file)])
    assert exc.value.code == 1

    out = capsys.readouterr().out
    report = json.loads(out)
    assert report["summary"]["failed"] >= 1


def test_eval_runner_cli_exit_codes(capsys, tmp_path):
    # Success -> exit 0
    with pytest.raises(SystemExit) as exc:
        main([str(FIXTURE_PATH)])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["summary"]["failed"] == 0

    # Nonexistent file -> exit 2
    with pytest.raises(SystemExit) as exc2:
        main([str(tmp_path / "non_existent.json")])
    assert exc2.value.code == 2

    # Malformed file -> exit 2
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as exc3:
        main([str(bad_file)])
    assert exc3.value.code == 2


def test_eval_runner_runtime_isolation(monkeypatch):
    """Verifies that eval_runner runs completely offline with no network, DB, or forbidden imports."""
    import socket

    # Guard against socket creation
    def forbidden_socket(*args, **kwargs):
        raise RuntimeError("Network socket access forbidden in eval_runner")

    monkeypatch.setattr(socket, "socket", forbidden_socket)

    # Guard against forbidden module imports at runtime
    forbidden_modules = {
        "psycopg",
        "confluent_kafka",
        "fridge_backend.bus",
        "fridge_backend.store",
        "fridge_backend.main",
    }

    orig_import = __import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        for forb in forbidden_modules:
            if name == forb or name.startswith(forb + "."):
                raise ImportError(f"Forbidden module {name} imported during eval_runner")
        return orig_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", guarded_import)

    report, code = run_eval(FIXTURE_PATH)
    assert code == 0
    assert report["summary"]["failed"] == 0
