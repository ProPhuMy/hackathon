"""Deterministic offline synthetic real-Matcher replay skeleton and CLI."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

from jsonschema import Draft202012Validator

from fridge_backend.matcher import Matcher, MatcherConfig, MATCHER_VERSION

UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z\Z")


def find_contracts_dir() -> Path:
    """Locate contracts directory independently without importing bus/store/main."""
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        cand = parent / "contracts" / "person.seen.schema.json"
        if cand.is_file():
            return parent / "contracts"
    raise FileNotFoundError("Could not find contracts directory")


def load_validators() -> dict[str, Draft202012Validator]:
    """Load JSON Schema validators for contracts."""
    cdir = find_contracts_dir()
    return {
        "person": Draft202012Validator(json.loads((cdir / "person.seen.schema.json").read_text(encoding="utf-8"))),
        "item": Draft202012Validator(json.loads((cdir / "item.event.schema.json").read_text(encoding="utf-8"))),
        "fridge": Draft202012Validator(json.loads((cdir / "fridge.event.schema.json").read_text(encoding="utf-8"))),
    }


def validate_iso_utc_timestamp(ts: Any, field_name: str) -> str:
    """Validates real calendar dates and UTC ISO 8601 string pattern."""
    if not isinstance(ts, str) or isinstance(ts, bool):
        raise ValueError(f"Field '{field_name}' must be a string timestamp, got {type(ts).__name__}")
    if not UTC_PATTERN.fullmatch(ts):
        raise ValueError(f"Field '{field_name}' does not match ISO 8601 UTC pattern: {ts!r}")
    try:
        # Validates real calendar dates (e.g. leap years, month length)
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Field '{field_name}' has invalid calendar date {ts!r}: {exc}") from exc
    return ts


def check_no_bool_or_nonfinite(obj: Any, path: str = "root") -> None:
    """Recursively checks that numeric values are finite and not booleans."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise ValueError(f"Non-finite float at {path}: {obj}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            check_no_bool_or_nonfinite(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            check_no_bool_or_nonfinite(item, f"{path}[{idx}]")


def validate_numeric_field(val: Any, name: str, expected_types: tuple[type, ...]) -> None:
    if isinstance(val, bool):
        raise ValueError(f"Field '{name}' cannot be boolean")
    if not isinstance(val, expected_types):
        raise ValueError(f"Field '{name}' must be of type {expected_types}, got {type(val).__name__}")
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        raise ValueError(f"Field '{name}' cannot be NaN or Infinity")


def validate_fixture(raw: Any, validators: dict[str, Draft202012Validator]) -> None:
    """Validates fixture boundary shapes, schemas, and timestamps. Rejects unknown fields."""
    if not isinstance(raw, dict):
        raise ValueError(f"Fixture root must be a dict, got {type(raw).__name__}")

    allowed_root = {"schema_version", "description", "cases"}
    unknown_root = set(raw.keys()) - allowed_root
    if unknown_root:
        raise ValueError(f"Unknown root fields in fixture: {unknown_root}")

    if "schema_version" not in raw or not isinstance(raw["schema_version"], str) or isinstance(raw["schema_version"], bool) or raw["schema_version"] != "1.0":
        raise ValueError("Fixture must specify schema_version '1.0'")

    if "description" in raw and (not isinstance(raw["description"], str) or isinstance(raw["description"], bool)):
        raise ValueError("Root description must be a string")

    if "cases" not in raw or not isinstance(raw["cases"], list):
        raise ValueError("'cases' must be a list")
    if len(raw["cases"]) == 0:
        raise ValueError("'cases' list cannot be empty")

    seen_case_ids: set[str] = set()

    for idx, case in enumerate(raw["cases"]):
        c_path = f"cases[{idx}]"
        if not isinstance(case, dict):
            raise ValueError(f"{c_path} must be a dict")

        allowed_case = {"case_id", "description", "calls", "expected_outputs", "expected_inventory"}
        unknown_case = set(case.keys()) - allowed_case
        if unknown_case:
            raise ValueError(f"Unknown fields in {c_path}: {unknown_case}")

        if "description" in case and (not isinstance(case["description"], str) or isinstance(case["description"], bool)):
            raise ValueError(f"{c_path}.description must be a string")

        cid = case.get("case_id")
        if not isinstance(cid, str) or isinstance(cid, bool) or not cid.strip():
            raise ValueError(f"{c_path}.case_id must be a non-empty string")
        if cid in seen_case_ids:
            raise ValueError(f"Duplicate case_id in fixture: {cid!r}")
        seen_case_ids.add(cid)

        if "calls" not in case or not isinstance(case["calls"], list):
            raise ValueError(f"{c_path}.calls must be a list")

        for call_idx, call in enumerate(case["calls"]):
            call_path = f"{c_path}.calls[{call_idx}]"
            if not isinstance(call, dict):
                raise ValueError(f"{call_path} must be a dict")

            kind = call.get("kind")
            if kind == "tick":
                allowed_tick = {"kind", "now_ts"}
                unknown_tick = set(call.keys()) - allowed_tick
                if unknown_tick:
                    raise ValueError(f"Unknown fields in {call_path}: {unknown_tick}")
                validate_iso_utc_timestamp(call.get("now_ts"), f"{call_path}.now_ts")
            elif kind in ("person", "item"):
                allowed_ev = {"kind", "event"}
                unknown_ev = set(call.keys()) - allowed_ev
                if unknown_ev:
                    raise ValueError(f"Unknown fields in {call_path}: {unknown_ev}")
                ev = call.get("event")
                if not isinstance(ev, dict):
                    raise ValueError(f"{call_path}.event must be a dict")

                # Schema validation
                validator = validators[kind]
                validator.validate(ev)

                # Strict calendar date and non-boolean numeric checks
                validate_iso_utc_timestamp(ev.get("ts"), f"{call_path}.event.ts")
                validate_numeric_field(ev.get("confidence"), f"{call_path}.event.confidence", (int, float))
                if kind == "person":
                    validate_numeric_field(ev.get("track_id"), f"{call_path}.event.track_id", (int,))
            else:
                raise ValueError(f"Unsupported call kind in {call_path}: {kind!r}")

        # Validate expected_outputs
        if "expected_outputs" not in case or not isinstance(case["expected_outputs"], list):
            raise ValueError(f"{c_path}.expected_outputs must be a list")

        for out_idx, out in enumerate(case["expected_outputs"]):
            out_path = f"{c_path}.expected_outputs[{out_idx}]"
            if not isinstance(out, dict):
                raise ValueError(f"{out_path} must be a dict")
            validators["fridge"].validate(out)
            validate_iso_utc_timestamp(out.get("ts"), f"{out_path}.ts")
            validate_numeric_field(out.get("confidence"), f"{out_path}.confidence", (int, float))

        # Validate expected_inventory
        if "expected_inventory" not in case or not isinstance(case["expected_inventory"], dict):
            raise ValueError(f"{c_path}.expected_inventory must be a dict")
        for inv_k, inv_v in case["expected_inventory"].items():
            if not isinstance(inv_k, str) or isinstance(inv_k, bool) or (inv_v is not None and (not isinstance(inv_v, str) or isinstance(inv_v, bool))):
                raise ValueError(f"Invalid item_id or owner_id in {c_path}.expected_inventory: ({inv_k!r}: {inv_v!r})")


def run_case(case: dict) -> list[str]:
    """Runs a single test case through a fresh Matcher(MatcherConfig()) in explicit array order.
    Returns list of mismatch descriptions (empty on match).
    """
    matcher = Matcher(MatcherConfig())
    emitted: list[dict] = []

    for call in case["calls"]:
        kind = call["kind"]
        if kind == "person":
            emitted.extend(matcher.on_person(call["event"]))
        elif kind == "item":
            emitted.extend(matcher.on_item(call["event"]))
        elif kind == "tick":
            emitted.extend(matcher.tick(call["now_ts"]))

    mismatches: list[str] = []
    expected_outputs = case["expected_outputs"]

    if len(emitted) != len(expected_outputs):
        mismatches.append(
            f"Output count mismatch: emitted {len(emitted)} events, expected {len(expected_outputs)}"
        )

    for idx, (act, exp) in enumerate(zip(emitted, expected_outputs)):
        all_keys = set(act.keys()) | set(exp.keys())
        for k in sorted(all_keys):
            if k not in act:
                mismatches.append(f"Output #{idx}: missing key '{k}' in emitted event")
            elif k not in exp:
                mismatches.append(f"Output #{idx}: extra unexpected key '{k}' in emitted event")
            elif k == "confidence":
                act_conf = act[k]
                exp_conf = exp[k]
                if abs(float(act_conf) - float(exp_conf)) > 1e-4:
                    mismatches.append(
                        f"Output #{idx} confidence mismatch: emitted {act_conf} != expected {exp_conf} (diff > 1e-4)"
                    )
            else:
                if act[k] != exp[k]:
                    mismatches.append(
                        f"Output #{idx} field '{k}' mismatch: emitted {act[k]!r} != expected {exp[k]!r}"
                    )

    act_inv = matcher.inventory()
    exp_inv = case["expected_inventory"]
    if act_inv != exp_inv:
        mismatches.append(
            f"Inventory mismatch: emitted {act_inv!r} != expected {exp_inv!r}"
        )

    return mismatches


def run_eval(fixture_path: Path) -> tuple[dict, int]:
    """Evaluates synthetic replay fixture and returns (report_dict, exit_code)."""
    try:
        text = fixture_path.read_text(encoding="utf-8")
        raw = json.loads(
            text,
            parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"Non-finite float '{x}' not allowed")),
        )
        check_no_bool_or_nonfinite(raw)
        validators = load_validators()
        validate_fixture(raw, validators)
    except Exception as exc:
        report = {
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "exit_code": 2,
        }
        return report, 2

    cases = raw["cases"]
    total = len(cases)
    passed = 0
    failures = []

    for case in cases:
        cid = case["case_id"]
        mismatches = run_case(case)
        if not mismatches:
            passed += 1
        else:
            failures.append({
                "case_id": cid,
                "reasons": mismatches,
            })

    cfg = MatcherConfig()
    report = {
        "dataset_type": "synthetic_only",
        "disclaimer": "SYNTHETIC REPLAY ONLY: No real clip data or Role 4 ground truth agreement.",
        "matcher_version": MATCHER_VERSION,
        "matcher_config": asdict(cfg),
        "comparison_definition": "Whole output array order and all fields, confidence absolute tolerance <= 1e-4, final inventory exact.",
        "summary": {
            "total_cases": total,
            "passed": passed,
            "failed": len(failures),
        },
        "failures": failures,
    }

    exit_code = 0 if len(failures) == 0 else 1
    return report, exit_code


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for fridge_backend.eval_runner."""
    parser = argparse.ArgumentParser(
        prog="python -m fridge_backend.eval_runner",
        description="Deterministic offline synthetic replay runner for Fridge Tracker Matcher",
    )
    parser.add_argument("fixture", help="Path to synthetic replay fixture JSON")
    args = parser.parse_args(argv)

    fpath = Path(args.fixture)
    if not fpath.is_file():
        err_report = {
            "status": "error",
            "error": f"Fixture file not found: {args.fixture}",
            "exit_code": 2,
        }
        print(json.dumps(err_report, indent=2))
        sys.exit(2)

    report, exit_code = run_eval(fpath)
    print(json.dumps(report, indent=2))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
