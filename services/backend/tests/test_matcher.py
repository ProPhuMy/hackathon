"""Tests for Matcher: join logic, dedup, watermarks, idle timeout, JPDA/Hungarian association, and contract conformance."""

from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from jsonschema import Draft202012Validator
import pytest

from fridge_backend.matcher import Matcher, MatcherConfig

SCHEMA = json.loads((Path(__file__).parents[3] / "contracts" / "fridge.event.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)

T_BASE = datetime(2026, 11, 8, 9, 15, 0, 0, tzinfo=timezone.utc)


def ts(seconds: float) -> str:
    """Helper returning ISO UTC string at T_BASE + seconds."""
    dt = T_BASE + timedelta(seconds=seconds)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_person(event_id: str, person_id: str | None, seconds: float, confidence: float = 0.9, track_id: int = 1) -> dict:
    return {
        "event_id": event_id,
        "topic": "person.seen",
        "track_id": track_id,
        "person_id": person_id,
        "ts": ts(seconds),
        "confidence": confidence,
    }


def make_item(event_id: str, item_type: str, item_id: str, seconds: float, confidence: float = 0.9, label: str = "milk carton") -> dict:
    return {
        "event_id": event_id,
        "topic": "item.event",
        "type": item_type,
        "item_id": item_id,
        "item_label": label,
        "ts": ts(seconds),
        "confidence": confidence,
    }


def test_acceptance_a_demo_scenario():
    """Demo scenario with split tick(T+8s) and tick(T+20s) to inspect intermediate inventory."""
    m = Matcher(MatcherConfig(association="nearest"))

    # 1. p_01 seen at T
    p1 = make_person("p1", "p_01", 0.0, confidence=0.94, track_id=1)
    assert m.on_person(p1) == []

    # 2. PUT item_042 at T+1s
    i1 = make_item("i1", "PUT", "item_042", 1.0, confidence=0.90)
    assert m.on_item(i1) == []

    # 3. p_02 seen at T+2s
    p2 = make_person("p2", "p_02", 2.0, confidence=0.91, track_id=2)
    assert m.on_person(p2) == []

    # 4. TAKE item_042 at T+3s
    i2 = make_item("i2", "TAKE", "item_042", 3.0, confidence=0.87)
    assert m.on_item(i2) == []

    # At T+8s, PUT is ready (1s + 2s + 2s + 3s = 8s), but TAKE is not ready until T+10s (3s + 2s + 2s + 3s)
    out_8s = m.tick(ts(8.0))
    assert len(out_8s) == 1
    put_out = out_8s[0]
    VALIDATOR.validate(put_out)
    assert put_out["type"] == "PUT"
    assert put_out["item_id"] == "item_042"
    assert put_out["person_id"] == "p_01"
    assert put_out["owner_id"] == "p_01"
    assert put_out["status"] == "ok"
    assert put_out["confidence"] == 0.846
    assert m.inventory() == {"item_042": "p_01"}

    # At T+20s, TAKE is ready
    out_20s = m.tick(ts(20.0))
    assert len(out_20s) == 1
    take_out = out_20s[0]
    VALIDATOR.validate(take_out)
    assert take_out["type"] == "TAKE"
    assert take_out["item_id"] == "item_042"
    assert take_out["person_id"] == "p_02"
    assert take_out["owner_id"] == "p_01"
    assert take_out["status"] == "wrong_owner"
    assert take_out["confidence"] == 0.7917
    assert m.inventory() == {}


def test_acceptance_b_duplicate_input():
    """Duplicate input (same event_id twice for both person and item) returns [] and causes no changes."""
    m = Matcher(MatcherConfig(association="nearest"))
    p1 = make_person("p1", "p_01", 0.0)
    assert m.on_person(p1) == []
    assert m.on_person(p1) == []  # duplicate person

    i1 = make_item("i1", "PUT", "item_001", 1.0)
    assert m.on_item(i1) == []
    assert m.on_item(i1) == []  # duplicate item

    # Duplicate after finalization is also ignored
    out = m.tick(ts(10.0))
    assert len(out) == 1
    VALIDATOR.validate(out[0])
    assert m.on_item(i1) == []
    assert m.on_person(p1) == []


def test_acceptance_c_out_of_order_within_lateness():
    """Person arrives after item but with timestamp before it; still chosen as actor."""
    m = Matcher(MatcherConfig(association="nearest"))
    # Item arrives first with ts = T+1.0s
    i1 = make_item("i1", "PUT", "item_001", 1.0, confidence=0.9)
    assert m.on_item(i1) == []

    # Person arrives second with ts = T+0.5s (before item, within lateness_ms=2000)
    p1 = make_person("p1", "p_01", 0.5, confidence=0.9)
    assert m.on_person(p1) == []

    # Finalize via tick
    out = m.tick(ts(10.0))
    assert len(out) == 1
    VALIDATOR.validate(out[0])
    assert out[0]["person_id"] == "p_01"
    assert out[0]["status"] == "ok"


def test_acceptance_d_late_beyond_lateness():
    """Late beyond lateness_ms is dropped, records event_id, does not run finalize, does not become actor."""
    m = Matcher(MatcherConfig(association="nearest"))
    # Person at T+10s sets person_wm = T+10s
    p_lead = make_person("p_lead", "p_leader", 10.0)
    assert m.on_person(p_lead) == []

    # Person at T+5s is late (10.0s - 2.0s = 8.0s cutoff > 5.0s) -> dropped
    p_late = make_person("p_late", "p_late_guy", 5.0)
    assert m.on_person(p_late) == []

    # Duplicate of dropped event is also dropped immediately
    assert m.on_person(p_late) == []

    # Item at T+5s arrives (item_wm starts at 5.0s, so not late for item stream)
    i1 = make_item("i1", "PUT", "item_001", 5.0)
    # Note: person_wm is 10.0s >= 5s + 2s + 2s = 9s, so item finalizes immediately on on_item
    out = m.on_item(i1)
    assert len(out) == 1
    VALIDATOR.validate(out[0])
    # The late person was dropped, so p_late_guy is NOT chosen. p_lead at 10s is outside [5s - 5s, 5s + 2s].
    # So actor is None!
    assert out[0]["person_id"] is None
    assert out[0]["confidence"] == 0.0
    assert out[0]["status"] == "uncertain"


def test_acceptance_e_idle_timeout():
    """Item with no later persons is emitted only by tick once now >= t + fwd + lateness + idle_timeout."""
    m = Matcher(MatcherConfig(association="nearest"))
    # Item at T+1s. fwd=2s, lateness=2s, idle_timeout=3s -> ready at T + 1s + 7s = T + 8.0s
    i1 = make_item("i1", "PUT", "item_001", 1.0)
    assert m.on_item(i1) == []

    # Before T+8.0s -> not ready
    assert m.tick(ts(7.999)) == []

    # At T+8.0s -> ready and finalized
    out = m.tick(ts(8.0))
    assert len(out) == 1
    VALIDATOR.validate(out[0])
    assert out[0]["item_id"] == "item_001"


def test_acceptance_f_unknown_person_and_stranger():
    """Item with no person in window -> person_id None, status uncertain; stranger -> uncertain."""
    # Sub-case 1: No person in window
    m1 = Matcher(MatcherConfig(association="nearest"))
    i1 = make_item("i1", "PUT", "item_001", 1.0, confidence=0.8)
    m1.on_item(i1)
    out1 = m1.tick(ts(10.0))
    assert len(out1) == 1
    VALIDATOR.validate(out1[0])
    assert out1[0]["person_id"] is None
    assert out1[0]["owner_id"] is None
    assert out1[0]["confidence"] == 0.0
    assert out1[0]["status"] == "uncertain"

    # Sub-case 2: Stranger (person_id is None / null)
    m2 = Matcher(MatcherConfig(association="nearest"))
    p_stranger = make_person("p_stranger", None, 1.0, confidence=0.8)
    m2.on_person(p_stranger)
    i2 = make_item("i2", "PUT", "item_002", 1.0, confidence=0.9)
    m2.on_item(i2)
    out2 = m2.tick(ts(10.0))
    assert len(out2) == 1
    VALIDATOR.validate(out2[0])
    assert out2[0]["person_id"] is None
    assert out2[0]["owner_id"] is None
    assert out2[0]["confidence"] == 0.72  # round(0.8 * 0.9, 4)
    assert out2[0]["status"] == "uncertain"


def test_acceptance_g_one_person_two_items():
    """Same person PUTs two items 1s apart; both outputs have that person."""
    m = Matcher(MatcherConfig(association="nearest"))
    p1 = make_person("p1", "p_01", 1.0, confidence=0.95)
    m.on_person(p1)

    i1 = make_item("i1", "PUT", "item_001", 1.0, confidence=0.9)
    i2 = make_item("i2", "PUT", "item_002", 2.0, confidence=0.9)
    m.on_item(i1)
    m.on_item(i2)

    # Idle timeout tick at T+10s finalizes both
    out = m.tick(ts(10.0))
    assert len(out) == 2
    for ev in out:
        VALIDATOR.validate(ev)
        assert ev["person_id"] == "p_01"
        assert ev["owner_id"] == "p_01"
        assert ev["status"] == "ok"

    assert m.inventory() == {"item_001": "p_01", "item_002": "p_01"}


def test_acceptance_h_determinism():
    """Run the same call sequence on two fresh Matchers; outputs identical."""
    seq = [
        ("person", make_person("p1", "p_01", 0.0, confidence=0.95)),
        ("item", make_item("i1", "PUT", "item_042", 1.0, confidence=0.90)),
        ("person", make_person("p2", "p_02", 2.0, confidence=0.92)),
        ("item", make_item("i2", "TAKE", "item_042", 3.0, confidence=0.88)),
        ("tick", ts(8.0)),
        ("tick", ts(20.0)),
    ]

    def run_seq():
        m = Matcher(MatcherConfig(association="nearest"))
        all_outputs = []
        for kind, arg in seq:
            if kind == "person":
                all_outputs.extend(m.on_person(arg))
            elif kind == "item":
                all_outputs.extend(m.on_item(arg))
            elif kind == "tick":
                all_outputs.extend(m.tick(arg))
        return all_outputs, m.inventory()

    out1, inv1 = run_seq()
    out2, inv2 = run_seq()

    assert out1 == out2
    assert inv1 == inv2


def test_acceptance_i_low_confidence_gives_uncertain_not_wrong_owner():
    """Product below threshold -> uncertain, not wrong_owner."""
    m = Matcher(MatcherConfig(threshold=0.5, association="nearest"))

    # Seed inventory with item_042 owned by p_01
    m.on_person(make_person("p1", "p_01", 0.0, confidence=1.0))
    m.on_item(make_item("i1", "PUT", "item_042", 1.0, confidence=1.0))
    m.tick(ts(8.0))
    assert m.inventory() == {"item_042": "p_01"}

    # Person p_02 with confidence 0.6 TAKEs item_042 with confidence 0.7 (0.6 * 0.7 = 0.42 < 0.5)
    m.on_person(make_person("p2", "p_02", 9.0, confidence=0.6))
    m.on_item(make_item("i2", "TAKE", "item_042", 9.5, confidence=0.7))
    out = m.tick(ts(20.0))

    assert len(out) == 1
    take_out = out[0]
    VALIDATOR.validate(take_out)
    assert take_out["person_id"] == "p_02"
    assert take_out["owner_id"] == "p_01"
    assert take_out["confidence"] == 0.42
    assert take_out["status"] == "uncertain"
    # Even though uncertain, the item was taken, so inventory is empty
    assert m.inventory() == {}


def test_item_late_beyond_lateness_dropped():
    """Item arriving with ts < item_wm - lateness_ms is dropped and never appears in output or inventory."""
    m = Matcher(MatcherConfig(association="nearest"))
    i_a = make_item("ia", "PUT", "item_A", 10.0)
    assert m.on_item(i_a) == []

    # item_B at T+5s arrives late (item_wm=10s, 5s < 10s - 2s = 8s) -> dropped
    i_b = make_item("ib", "PUT", "item_B", 5.0)
    assert m.on_item(i_b) == []

    out = m.tick(ts(30.0))
    assert len(out) == 1
    VALIDATOR.validate(out[0])
    assert out[0]["item_id"] == "item_A"
    assert "item_B" not in [ev["item_id"] for ev in out]
    assert m.inventory() == {"item_A": None}


def test_tie_break_backward_window():
    """Two persons at identical ts in backward window: lowest event_id wins ('pa' over 'pb')."""
    m = Matcher(MatcherConfig(association="nearest"))
    # 'pb' fed first, then 'pa'
    pb = make_person("pb", "p_B", 0.5)
    pa = make_person("pa", "p_A", 0.5)
    assert m.on_person(pb) == []
    assert m.on_person(pa) == []

    i1 = make_item("i1", "PUT", "item_001", 1.0)
    assert m.on_item(i1) == []

    out = m.tick(ts(10.0))
    assert len(out) == 1
    VALIDATOR.validate(out[0])
    assert out[0]["person_id"] == "p_A"


def test_tie_break_forward_window():
    """Two persons at identical ts in forward window: lowest event_id wins ('pa' over 'pb')."""
    m = Matcher(MatcherConfig(association="nearest"))
    i1 = make_item("i1", "PUT", "item_001", 1.0)
    assert m.on_item(i1) == []

    # No person before the item; two persons at T+1.5s ('pb' fed first, then 'pa')
    pb = make_person("pb", "p_B", 1.5)
    pa = make_person("pa", "p_A", 1.5)
    assert m.on_person(pb) == []
    assert m.on_person(pa) == []

    out = m.tick(ts(10.0))
    assert len(out) == 1
    VALIDATOR.validate(out[0])
    assert out[0]["person_id"] == "p_A"


# ==============================================================================
# Stage 3 Tests: JPDA, Hungarian, Track Fusion, Mutual Exclusion, and Mode Switch
# ==============================================================================


@pytest.mark.parametrize("mode", ["nearest", "hungarian", "jpda"])
def test_demo_scenario_modes(mode: str):
    """Rule 9: Demo scenario must give PUT -> p_01 (ok) and TAKE -> p_02 (wrong_owner) in all 3 modes."""
    m = Matcher(MatcherConfig(association=mode))

    p1 = make_person("p1", "p_01", 0.0, confidence=0.94, track_id=1)
    assert m.on_person(p1) == []

    i1 = make_item("i1", "PUT", "item_042", 1.0, confidence=0.90)
    assert m.on_item(i1) == []

    p2 = make_person("p2", "p_02", 2.0, confidence=0.91, track_id=2)
    assert m.on_person(p2) == []

    i2 = make_item("i2", "TAKE", "item_042", 3.0, confidence=0.87)
    assert m.on_item(i2) == []

    # At T+8s, PUT item_042 is finalized (1s + 2s + 2s + 3s = 8s)
    out_8s = m.tick(ts(8.0))
    assert len(out_8s) == 1
    put_out = out_8s[0]
    VALIDATOR.validate(put_out)
    assert put_out["type"] == "PUT"
    assert put_out["item_id"] == "item_042"
    assert put_out["person_id"] == "p_01"
    assert put_out["owner_id"] == "p_01"
    assert put_out["status"] == "ok"
    if mode == "nearest":
        assert put_out["confidence"] == 0.846
    else:
        assert put_out["confidence"] == 0.5423
    assert m.inventory() == {"item_042": "p_01"}

    # At T+20s, TAKE item_042 is finalized
    out_20s = m.tick(ts(20.0))
    assert len(out_20s) == 1
    take_out = out_20s[0]
    VALIDATOR.validate(take_out)
    assert take_out["type"] == "TAKE"
    assert take_out["item_id"] == "item_042"
    assert take_out["person_id"] == "p_02"
    assert take_out["owner_id"] == "p_01"
    assert take_out["status"] == "wrong_owner"
    if mode == "nearest":
        assert take_out["confidence"] == 0.7917
    else:
        assert take_out["confidence"] == 0.8282
    assert m.inventory() == {}


def test_two_people_at_fridge():
    """Two people visible, A PUTs X at 1.0s, B TAKEs Y at 1.5s (0.5s later).

    Nearest provably fails on item X (assigns B), while JPDA and Hungarian correctly assign X->A, Y->B.
    """
    def run_with_mode(mode: str) -> list[dict]:
        m = Matcher(MatcherConfig(association=mode))
        # Person A (track 1): visible at 0.6s and 1.01s (immediately after item X)
        # Person B (track 2): visible at 0.99s (immediately before item X) and 1.51s (immediately after item Y)
        # For item X at 1.0s:
        # - backward window [-4.0s, 1.0s] contains:
        #   p_A1 at 0.6s
        #   p_B1 at 0.99s
        # Nearest selects p_B1 (Person B, wrong!) because 0.99s > 0.6s in backward window.
        p_A1 = make_person("p_A1", "p_01", 0.6, confidence=0.95, track_id=1)
        p_B1 = make_person("p_B1", "p_02", 0.99, confidence=0.95, track_id=2)
        p_A2 = make_person("p_A2", "p_01", 1.01, confidence=0.95, track_id=1)
        p_B2 = make_person("p_B2", "p_02", 1.51, confidence=0.95, track_id=2)

        m.on_person(p_A1)
        m.on_person(p_B1)
        m.on_person(p_A2)
        m.on_person(p_B2)

        # Item X (PUT) at 1.0s, Item Y (TAKE) at 1.5s (0.5s apart < min_gap_ms 1000ms)
        i_X = make_item("i_X", "PUT", "item_X", 1.0, confidence=0.90)
        i_Y = make_item("i_Y", "TAKE", "item_Y", 1.5, confidence=0.90)

        m.on_item(i_X)
        m.on_item(i_Y)

        # Advance tick beyond both observation windows
        return m.tick(ts(15.0))

    # 1. Nearest mode: provably fails for item X (picks p_02 instead of p_01)
    outs_nearest = run_with_mode("nearest")
    assert len(outs_nearest) == 2
    for ev in outs_nearest:
        VALIDATOR.validate(ev)
    ev_X_nearest = next(ev for ev in outs_nearest if ev["item_id"] == "item_X")
    assert ev_X_nearest["person_id"] == "p_02", "Nearest should have picked p_02 (wrong actor) due to backward timestamp"

    # 2. JPDA mode: correctly assigns X -> p_01 and Y -> p_02
    outs_jpda = run_with_mode("jpda")
    assert len(outs_jpda) == 2
    for ev in outs_jpda:
        VALIDATOR.validate(ev)
    ev_X_jpda = next(ev for ev in outs_jpda if ev["item_id"] == "item_X")
    ev_Y_jpda = next(ev for ev in outs_jpda if ev["item_id"] == "item_Y")
    assert ev_X_jpda["person_id"] == "p_01"
    assert ev_Y_jpda["person_id"] == "p_02"

    # 3. Hungarian mode: correctly assigns X -> p_01 and Y -> p_02
    outs_hungarian = run_with_mode("hungarian")
    assert len(outs_hungarian) == 2
    for ev in outs_hungarian:
        VALIDATOR.validate(ev)
    ev_X_hungarian = next(ev for ev in outs_hungarian if ev["item_id"] == "item_X")
    ev_Y_hungarian = next(ev for ev in outs_hungarian if ev["item_id"] == "item_Y")
    assert ev_X_hungarian["person_id"] == "p_01"
    assert ev_Y_hungarian["person_id"] == "p_02"


@pytest.mark.parametrize("mode", ["nearest", "hungarian", "jpda"])
def test_one_person_two_items_separated(mode: str):
    """One person, two items more than min_gap_ms apart: both assigned to that person in all modes."""
    m = Matcher(MatcherConfig(association=mode, min_gap_ms=1000))

    p1 = make_person("p1", "p_01", 1.0, confidence=0.95, track_id=1)
    m.on_person(p1)

    i1 = make_item("i1", "PUT", "item_001", 1.0, confidence=0.90)
    i2 = make_item("i2", "PUT", "item_002", 3.0, confidence=0.90)  # 2.0s apart > min_gap_ms

    m.on_item(i1)
    m.on_item(i2)

    outs = m.tick(ts(15.0))
    assert len(outs) == 2
    for ev in outs:
        VALIDATOR.validate(ev)
        assert ev["person_id"] == "p_01"
        assert ev["owner_id"] == "p_01"
        assert ev["status"] == "ok"

    assert m.inventory() == {"item_001": "p_01", "item_002": "p_01"}


@pytest.mark.parametrize("mode", ["hungarian", "jpda"])
def test_correlated_frames_cap(mode: str):
    """Track with 20 frames at 0.6 confidence loses to Track with 2 frames at 0.95 under capped fusion."""
    # Verify raw sum would have chosen Track 1
    raw_sum_t1 = 20 * math.log(0.6 / 0.4)
    raw_sum_t2 = 2 * math.log(0.95 / 0.05)
    assert raw_sum_t1 > raw_sum_t2

    m = Matcher(MatcherConfig(association=mode, n_eff_cap=3, sigma_ms=1000))

    # Track 1 has 20 detections around T+1s with confidence 0.6
    for k in range(20):
        p = make_person(f"p1_{k}", "p_01", 0.9 + k * 0.01, confidence=0.6, track_id=1)
        m.on_person(p)

    # Track 2 has 2 detections around T+1s with confidence 0.95
    for k in range(2):
        p = make_person(f"p2_{k}", "p_02", 0.99 + k * 0.02, confidence=0.95, track_id=2)
        m.on_person(p)

    i1 = make_item("i1", "PUT", "item_001", 1.0, confidence=0.90)
    m.on_item(i1)

    outs = m.tick(ts(15.0))
    assert len(outs) == 1
    VALIDATOR.validate(outs[0])
    # Track 2 (p_02) must win
    assert outs[0]["person_id"] == "p_02"
    assert outs[0]["status"] == "ok"


@pytest.mark.parametrize("mode", ["hungarian", "jpda"])
def test_stranger_only_and_no_candidate(mode: str):
    """Stranger only or no candidate -> person_id None, status 'uncertain' in jpda and hungarian."""
    # Case 1: Stranger only
    m1 = Matcher(MatcherConfig(association=mode))
    p_stranger = make_person("p_s", None, 1.0, confidence=0.9, track_id=1)
    m1.on_person(p_stranger)
    i1 = make_item("i1", "PUT", "item_001", 1.0, confidence=0.9)
    m1.on_item(i1)
    outs1 = m1.tick(ts(10.0))
    assert len(outs1) == 1
    VALIDATOR.validate(outs1[0])
    assert outs1[0]["person_id"] is None
    assert outs1[0]["owner_id"] is None
    assert outs1[0]["status"] == "uncertain"

    # Case 2: No person candidates at all
    m2 = Matcher(MatcherConfig(association=mode))
    i2 = make_item("i2", "PUT", "item_002", 1.0, confidence=0.9)
    m2.on_item(i2)
    outs2 = m2.tick(ts(10.0))
    assert len(outs2) == 1
    VALIDATOR.validate(outs2[0])
    assert outs2[0]["person_id"] is None
    assert outs2[0]["owner_id"] is None
    assert outs2[0]["status"] == "uncertain"


def test_mode_switch_and_validation():
    """Mode switch: all 3 modes run, invalid mode raises ValueError, 'nearest' matches stage-1 confidences."""
    for mode in ["nearest", "hungarian", "jpda"]:
        m = Matcher(MatcherConfig(association=mode))
        assert m.cfg.association == mode

    with pytest.raises(ValueError, match="Unknown association mode"):
        Matcher(MatcherConfig(association="invalid_mode"))


@pytest.mark.parametrize("mode", ["nearest", "hungarian", "jpda"])
def test_determinism_all_modes(mode: str):
    """Determinism: the same call sequence twice gives identical outputs and inventory in every mode."""
    seq = [
        ("person", make_person("p1", "p_01", 0.0, confidence=0.94, track_id=1)),
        ("item", make_item("i1", "PUT", "item_042", 1.0, confidence=0.90)),
        ("person", make_person("p2", "p_02", 2.0, confidence=0.91, track_id=2)),
        ("item", make_item("i2", "TAKE", "item_042", 3.0, confidence=0.87)),
        ("tick", ts(8.0)),
        ("tick", ts(20.0)),
    ]

    def run_seq():
        m = Matcher(MatcherConfig(association=mode))
        all_outputs = []
        for kind, arg in seq:
            if kind == "person":
                all_outputs.extend(m.on_person(arg))
            elif kind == "item":
                all_outputs.extend(m.on_item(arg))
            elif kind == "tick":
                all_outputs.extend(m.tick(arg))
        return all_outputs, m.inventory()

    out1, inv1 = run_seq()
    out2, inv2 = run_seq()

    assert out1 == out2
    assert inv1 == inv2
