"""Unit tests for fridge_backend.associate (fusion, hypothesis enumeration, and marginals)."""

from dataclasses import dataclass
import math
import pytest

from fridge_backend.associate import (
    CandidateOption,
    assign,
    compute_marginals,
    enumerate_hypotheses,
    fuse_track,
    get_candidates_for_event,
)


@dataclass(frozen=True)
class DummyConfig:
    back_ms: int = 5000
    fwd_ms: int = 2000
    sigma_ms: int = 1000
    n_eff_cap: int = 3
    null_prior: float = -2.0
    min_gap_ms: int = 1000


def test_marginals_sum_to_one():
    cfg = DummyConfig()
    # 2 events 500ms apart
    events_ts = [1000, 1500]
    c1 = [
        CandidateOption(track_id=None, person_id=None, score=-2.0),
        CandidateOption(track_id=1, person_id="p_01", score=2.5),
        CandidateOption(track_id=2, person_id="p_02", score=1.8),
    ]
    c2 = [
        CandidateOption(track_id=None, person_id=None, score=-2.0),
        CandidateOption(track_id=1, person_id="p_01", score=1.2),
        CandidateOption(track_id=2, person_id="p_02", score=2.9),
    ]
    candidates = [c1, c2]
    hypotheses = enumerate_hypotheses(events_ts, candidates, cfg.min_gap_ms)
    marginals, _, _ = compute_marginals(candidates, hypotheses)

    assert len(marginals) == 2
    for j in range(2):
        total_p = sum(marginals[j].values())
        assert total_p == pytest.approx(1.0, rel=1e-9)


def test_exclusion_constraint_under_min_gap():
    cfg = DummyConfig(min_gap_ms=1000)
    events_ts = [1000, 1500]  # 500ms apart < 1000ms
    c1 = [
        CandidateOption(track_id=None, person_id=None, score=-2.0),
        CandidateOption(track_id=1, person_id="p_01", score=1.0),
        CandidateOption(track_id=2, person_id="p_02", score=1.0),
    ]
    c2 = [
        CandidateOption(track_id=None, person_id=None, score=-2.0),
        CandidateOption(track_id=1, person_id="p_01", score=1.0),
        CandidateOption(track_id=2, person_id="p_02", score=1.0),
    ]
    hypotheses = enumerate_hypotheses(events_ts, [c1, c2], cfg.min_gap_ms)

    for h in hypotheses:
        t0, t1 = h[0].track_id, h[1].track_id
        if t0 is not None and t1 is not None:
            assert t0 != t1, f"Exclusion violated: both events assigned to track {t0}"

    # Verify (null, null) is allowed
    assert any(h[0].track_id is None and h[1].track_id is None for h in hypotheses)
    # Verify (track 1, track 2) is allowed
    assert any(h[0].track_id == 1 and h[1].track_id == 2 for h in hypotheses)
    # Verify (track 1, track 1) is NOT in hypotheses
    assert not any(h[0].track_id == 1 and h[1].track_id == 1 for h in hypotheses)


def test_sharing_allowed_beyond_min_gap():
    cfg = DummyConfig(min_gap_ms=1000)
    events_ts = [1000, 3000]  # 2000ms apart >= 1000ms
    c1 = [
        CandidateOption(track_id=None, person_id=None, score=-2.0),
        CandidateOption(track_id=1, person_id="p_01", score=1.0),
    ]
    c2 = [
        CandidateOption(track_id=None, person_id=None, score=-2.0),
        CandidateOption(track_id=1, person_id="p_01", score=1.0),
    ]
    hypotheses = enumerate_hypotheses(events_ts, [c1, c2], cfg.min_gap_ms)
    # Track 1 can handle both events because gap >= min_gap_ms
    assert any(h[0].track_id == 1 and h[1].track_id == 1 for h in hypotheses)


def test_correlated_frames_vs_raw_logit_sum():
    cfg = DummyConfig(n_eff_cap=3, sigma_ms=1000)
    # Track 1: 20 frames at 0.6 confidence
    c1 = 0.6
    logit1 = math.log(c1 / (1.0 - c1))
    raw_sum_track1 = 20 * logit1

    # Track 2: 2 frames at 0.95 confidence
    c2 = 0.95
    logit2 = math.log(c2 / (1.0 - c2))
    raw_sum_track2 = 2 * logit2

    # Verify that raw sum would favor Track 1
    assert raw_sum_track1 > raw_sum_track2

    # Under fusion with n_eff_cap = 3:
    event_ts = 1000
    dets_t1 = [(1000, {"person_id": "p_01", "confidence": 0.6})] * 20
    dets_t2 = [(1000, {"person_id": "p_02", "confidence": 0.95})] * 2

    opt1 = fuse_track(1, dets_t1, event_ts, cfg)
    opt2 = fuse_track(2, dets_t2, event_ts, cfg)

    assert opt1.score < opt2.score
    assert opt1.person_id == "p_01"
    assert opt2.person_id == "p_02"


def test_fuse_track_voting_tie_breakers():
    cfg = DummyConfig()
    event_ts = 1000

    # Case 1: Equal votes between "p_01" and "p_02" -> "p_01" wins (person_id ascending)
    dets_equal = [
        (1000, {"person_id": "p_02", "confidence": 0.9}),
        (1000, {"person_id": "p_01", "confidence": 0.9}),
    ]
    opt_a = fuse_track(1, dets_equal, event_ts, cfg)
    assert opt_a.person_id == "p_01"

    # Case 2: Equal votes between "p_01" and None -> "p_01" wins (None sorts last)
    dets_stranger_tie = [
        (1000, {"person_id": None, "confidence": 0.9}),
        (1000, {"person_id": "p_01", "confidence": 0.9}),
    ]
    opt_b = fuse_track(1, dets_stranger_tie, event_ts, cfg)
    assert opt_b.person_id == "p_01"

    # Case 3: Stranger has higher votes -> None wins
    dets_stranger_wins = [
        (1000, {"person_id": None, "confidence": 0.95}),
        (1000, {"person_id": "p_01", "confidence": 0.5}),
    ]
    opt_c = fuse_track(1, dets_stranger_wins, event_ts, cfg)
    assert opt_c.person_id is None


def test_stranger_track_and_null_assignment():
    cfg = DummyConfig()
    ev = (1000, {"event_id": "i1", "confidence": 0.9})

    # Only stranger track present
    p_stranger = (
        1000,
        {"event_id": "p1", "track_id": 1, "person_id": None, "confidence": 0.9},
    )
    cands = get_candidates_for_event(ev[1], ev[0], [p_stranger], cfg)
    assert any(c.track_id == 1 and c.person_id is None for c in cands)

    res_jpda = assign([ev], [p_stranger], cfg, mode="jpda")
    assert len(res_jpda) == 1
    pid, conf = res_jpda[0]
    assert pid is None
    assert conf > 0.0

    # No candidate present -> only null hypothesis
    cands_empty = get_candidates_for_event(ev[1], ev[0], [], cfg)
    assert len(cands_empty) == 1
    assert cands_empty[0].track_id is None

    res_null = assign([ev], [], cfg, mode="jpda")
    assert len(res_null) == 1
    pid_null, conf_null = res_null[0]
    assert pid_null is None
    assert conf_null == 0.9  # null marginal is 1.0, 1.0 * 0.9 = 0.9


def test_tie_breaking_jpda_null_first_then_lowest_track():
    cfg = DummyConfig(null_prior=0.0)
    # Event where null and track 1 have identical score 0.0
    # Track 1 has score 0.0: identity 0.0 (c=0.5 -> logit 0.0), gap 0
    p1 = (1000, {"event_id": "p1", "track_id": 1, "person_id": "p_01", "confidence": 0.5})
    ev = (1000, {"event_id": "i1", "confidence": 0.9})

    cands = get_candidates_for_event(ev[1], ev[0], [p1], cfg)
    assert any(c.track_id == 1 for c in cands)

    # Marginal will be 0.5 for null and 0.5 for track 1
    # Tied marginal -> null wins (null first)
    res = assign([ev], [p1], cfg, mode="jpda")
    assert res[0][0] is None


def test_tie_breaking_hungarian_lexicographic():
    cfg = DummyConfig(null_prior=-10.0)
    # Tie two tracks (score 0.0 each), with null_prior=-10.0 so null is out of the tie
    p1 = (1000, {"event_id": "p1", "track_id": 1, "person_id": "p_01", "confidence": 0.5})
    p2 = (1000, {"event_id": "p2", "track_id": 2, "person_id": "p_02", "confidence": 0.5})
    ev = (1000, {"event_id": "i1", "confidence": 0.9})

    cands = get_candidates_for_event(ev[1], ev[0], [p1, p2], cfg)
    assert any(c.track_id == 1 for c in cands)
    assert any(c.track_id == 2 for c in cands)

    res = assign([ev], [p1, p2], cfg, mode="hungarian")
    # Lexicographical tuple: track 1 is (1,), track 2 is (2,) -> track 1 (lowest track_id) wins
    assert res[0][0] == "p_01"


def test_determinism_input_order_invariance():
    cfg = DummyConfig(min_gap_ms=1000)
    # 2 events within min_gap_ms and 2 tracks
    ev1 = (1000, {"event_id": "i1", "confidence": 0.90})
    ev2 = (1400, {"event_id": "i2", "confidence": 0.85})  # gap 400ms < 1000ms

    p1 = (1000, {"event_id": "p1", "track_id": 1, "person_id": "p_01", "confidence": 0.92})
    p2 = (1400, {"event_id": "p2", "track_id": 2, "person_id": "p_02", "confidence": 0.88})

    cands_ev1 = get_candidates_for_event(ev1[1], ev1[0], [p1, p2], cfg)
    cands_ev2 = get_candidates_for_event(ev2[1], ev2[0], [p1, p2], cfg)
    assert any(c.track_id == 1 for c in cands_ev1) and any(c.track_id == 2 for c in cands_ev1)
    assert any(c.track_id == 1 for c in cands_ev2) and any(c.track_id == 2 for c in cands_ev2)

    res_normal = assign([ev1, ev2], [p1, p2], cfg, mode="jpda")
    # Assert non-null actor for both events
    assert res_normal[0][0] is not None
    assert res_normal[1][0] is not None
    assert res_normal[0][0] == "p_01"
    assert res_normal[1][0] == "p_02"

    # Shuffled persons list
    res_shuffled_persons = assign([ev1, ev2], [p2, p1], cfg, mode="jpda")
    assert res_shuffled_persons == res_normal

    # Shuffled events list (assign sorts events by (ts_ms, event_id) and returns in that order)
    res_shuffled_events = assign([ev2, ev1], [p1, p2], cfg, mode="jpda")
    assert res_shuffled_events == res_normal

    # Shuffled both events and persons
    res_shuffled_both = assign([ev2, ev1], [p2, p1], cfg, mode="jpda")
    assert res_shuffled_both == res_normal

    # Hungarian mode order invariance
    res_hung = assign([ev1, ev2], [p1, p2], cfg, mode="hungarian")
    assert res_hung[0][0] is not None and res_hung[1][0] is not None
    assert assign([ev2, ev1], [p2, p1], cfg, mode="hungarian") == res_hung


def test_acceptance_a_fragmented_person_jpda():
    """Acceptance (a): Person p_01 split into two tracks loses individually to p_02,
    but wins under JPDA group marginal with confidence >= 0.5.
    """
    cfg = DummyConfig()
    item_conf = 0.95
    ev = (1000, {"event_id": "i1", "confidence": item_conf})

    p1 = (1000, {"event_id": "p1", "track_id": 1, "person_id": "p_01", "confidence": 0.60})
    p2 = (1000, {"event_id": "p2", "track_id": 2, "person_id": "p_01", "confidence": 0.60})
    p3 = (1000, {"event_id": "p3", "track_id": 3, "person_id": "p_02", "confidence": 0.70})
    persons = [p1, p2, p3]

    candidates = [get_candidates_for_event(ev[1], ev[0], persons, cfg)]
    hypotheses = enumerate_hypotheses([ev[0]], candidates, cfg.min_gap_ms)
    marginals, _, _ = compute_marginals(candidates, hypotheses)

    ev_marginals = marginals[0]
    opt_t1 = next(opt for opt in candidates[0] if opt.track_id == 1)
    opt_t2 = next(opt for opt in candidates[0] if opt.track_id == 2)
    opt_t3 = next(opt for opt in candidates[0] if opt.track_id == 3)

    m1 = ev_marginals[opt_t1]
    m2 = ev_marginals[opt_t2]
    m3 = ev_marginals[opt_t3]

    # Under old per-track rule: Track 3 (p_02) beats both p_01 tracks,
    # and either p_01 track's individual confidence product is < 0.5
    assert m3 > m1 and m3 > m2
    assert m1 * item_conf < 0.5
    assert m2 * item_conf < 0.5

    # Summed group marginal of p_01 times item confidence is >= 0.5
    group_p01 = m1 + m2
    expected_conf = round(group_p01 * item_conf, 4)
    assert expected_conf >= 0.5

    # Run assign in "jpda" mode
    res = assign([ev], persons, cfg, mode="jpda")
    assert len(res) == 1
    assert res[0] == ("p_01", expected_conf)
    assert res[0][1] >= 0.5


def test_acceptance_b_fragmented_person_hungarian():
    """Acceptance (b): Hungarian picks best hypothesis person_id, but confidence is group marginal."""
    cfg = DummyConfig()
    item_conf = 0.95
    ev = (1000, {"event_id": "i1", "confidence": item_conf})

    p1 = (1000, {"event_id": "p1", "track_id": 1, "person_id": "p_01", "confidence": 0.60})
    p2 = (1000, {"event_id": "p2", "track_id": 2, "person_id": "p_01", "confidence": 0.60})
    p3 = (1000, {"event_id": "p3", "track_id": 3, "person_id": "p_02", "confidence": 0.70})
    persons = [p1, p2, p3]

    candidates = [get_candidates_for_event(ev[1], ev[0], persons, cfg)]
    hypotheses = enumerate_hypotheses([ev[0]], candidates, cfg.min_gap_ms)
    marginals, scores, _ = compute_marginals(candidates, hypotheses)

    # Independent computation of best hypothesis
    best_h_idx = max(range(len(hypotheses)), key=lambda idx: scores[idx])
    best_pid = hypotheses[best_h_idx][0].person_id
    assert best_pid == "p_02"

    group_best = sum(
        m for opt, m in marginals[0].items() if opt.person_id == best_pid
    )
    expected_conf = round(group_best * item_conf, 4)

    res = assign([ev], persons, cfg, mode="hungarian")
    assert len(res) == 1
    assert res[0] == (best_pid, expected_conf)


def test_acceptance_c_none_group_stranger_and_null():
    """Acceptance (c): Stranger track (person_id None) groups with null option into key None."""
    cfg = DummyConfig()
    item_conf = 0.80
    ev = (1000, {"event_id": "i1", "confidence": item_conf})

    p_stranger = (1000, {"event_id": "ps", "track_id": 1, "person_id": None, "confidence": 0.70})
    persons = [p_stranger]

    candidates = [get_candidates_for_event(ev[1], ev[0], persons, cfg)]
    hypotheses = enumerate_hypotheses([ev[0]], candidates, cfg.min_gap_ms)
    marginals, _, _ = compute_marginals(candidates, hypotheses)

    opt_null = next(opt for opt in candidates[0] if opt.track_id is None)
    opt_stranger = next(opt for opt in candidates[0] if opt.track_id == 1)

    null_marginal = marginals[0][opt_null]
    stranger_marginal = marginals[0][opt_stranger]
    expected_conf = round((null_marginal + stranger_marginal) * item_conf, 4)

    res = assign([ev], persons, cfg, mode="jpda")
    assert len(res) == 1
    assert res[0] == (None, expected_conf)


def test_acceptance_d_tie_breaking_group_marginals():
    """Acceptance (d): Equal group marginals break ties by person_id ascending; None wins against named."""
    # 1. Symmetric p_01 and p_02 tracks: lower person_id wins ("p_01" < "p_02")
    cfg = DummyConfig()
    ev = (1000, {"event_id": "i1", "confidence": 0.90})
    p1 = (1000, {"event_id": "p1", "track_id": 1, "person_id": "p_01", "confidence": 0.80})
    p2 = (1000, {"event_id": "p2", "track_id": 2, "person_id": "p_02", "confidence": 0.80})

    res_symmetric = assign([ev], [p1, p2], cfg, mode="jpda")
    assert res_symmetric[0][0] == "p_01"

    # 2. None wins a tie against a named person
    cfg_tie_null = DummyConfig(null_prior=0.0)
    # p1 at c=0.5 -> logit 0.0 -> score 0.0, matching null_prior 0.0
    p_named = (1000, {"event_id": "pn", "track_id": 1, "person_id": "p_01", "confidence": 0.50})
    res_none_tie = assign([ev], [p_named], cfg_tie_null, mode="jpda")
    assert res_none_tie[0][0] is None
