"""Track-level evidence fusion and exact JPDA / Hungarian association.

Pure functions only (no Matcher state).
"""

from __future__ import annotations

from dataclasses import dataclass
import itertools
import math
from typing import Any


@dataclass(frozen=True)
class CandidateOption:
    """A candidate association option for an item event (track or null)."""
    track_id: int | None
    person_id: str | None
    score: float


def fuse_track(
    track_id: int,
    detections: list[tuple[int, dict]],
    event_ts_ms: int,
    cfg: Any,
) -> CandidateOption:
    """Fuses detections of a single track into a CandidateOption.

    Rule 4:
    a. Track identity = confidence-weighted vote: sum of confidence per person_id
       (None = stranger is its own key); max sum wins; ties broken by person_id
       ascending with None sorting last.
    b. Identity term = mean of logit(c_i) over the detections that voted for the
       winning id, times min(n, n_eff_cap) where n is their count. logit(c) = log(c/(1-c))
       with c clamped to [0.01, 0.99].
    c. Temporal term = -0.5 * (gap / sigma_ms)**2, gap = min |t - p.ts| over all
       detections of the track in the window.
    d. score(track, event) = identity term + temporal term.
    """
    votes: dict[str | None, float] = {}
    for _, p_ev in detections:
        pid = p_ev.get("person_id")
        conf = float(p_ev["confidence"])
        votes[pid] = votes.get(pid, 0.0) + conf

    # Ties broken by person_id ascending with None sorting last.
    # To maximize vote sum with this tie-breaker:
    # Key for min: (-vote_sum, 1 if pid is None else 0, pid or "")
    winning_pid = min(
        votes.items(),
        key=lambda item: (-item[1], 1 if item[0] is None else 0, item[0] or ""),
    )[0]

    winning_detections = [p_ev for _, p_ev in detections if p_ev.get("person_id") == winning_pid]
    n = len(winning_detections)

    logits: list[float] = []
    for p_ev in winning_detections:
        c = float(p_ev["confidence"])
        c_clamped = max(0.01, min(0.99, c))
        logits.append(math.log(c_clamped / (1.0 - c_clamped)))

    mean_logit = sum(logits) / n
    identity_term = mean_logit * min(n, cfg.n_eff_cap)

    gap = min(abs(event_ts_ms - p_ts) for p_ts, _ in detections)
    temporal_term = -0.5 * ((gap / cfg.sigma_ms) ** 2)

    total_score = identity_term + temporal_term
    return CandidateOption(track_id=track_id, person_id=winning_pid, score=total_score)


def get_candidates_for_event(
    event_dict: dict,
    event_ts_ms: int,
    persons: list[tuple[int, dict]],
    cfg: Any,
) -> list[CandidateOption]:
    """Collects all candidate options (null + tracks in window) for an item event."""
    # Window: event_ts_ms - back_ms <= p.ts <= event_ts_ms + fwd_ms
    min_ts = event_ts_ms - cfg.back_ms
    max_ts = event_ts_ms + cfg.fwd_ms

    tracks_map: dict[int, list[tuple[int, dict]]] = {}
    for p_ts, p_ev in persons:
        if min_ts <= p_ts <= max_ts:
            tid = p_ev["track_id"]
            if tid not in tracks_map:
                tracks_map[tid] = []
            tracks_map[tid].append((p_ts, p_ev))

    # Sort tracks by track_id ascending for determinism
    options: list[CandidateOption] = [
        CandidateOption(track_id=None, person_id=None, score=float(cfg.null_prior))
    ]
    for tid in sorted(tracks_map.keys()):
        options.append(fuse_track(tid, tracks_map[tid], event_ts_ms, cfg))

    return options


def enumerate_hypotheses(
    events_ts_ms: list[int],
    candidates_per_event: list[list[CandidateOption]],
    min_gap_ms: int,
) -> list[tuple[CandidateOption, ...]]:
    """Enumerates all joint assignments satisfying the exclusion constraint.

    Rule 6:
    Exclusion applies ONLY to two events with |t_i - t_j| < min_gap_ms:
    they may not share the same track (null may be shared freely).
    """
    m = len(events_ts_ms)
    valid_hypotheses: list[tuple[CandidateOption, ...]] = []

    # shortcut: exhaustive product grows as (tracks+1)^events, fine for <=4 tracks and <=3 events per batch; upgrade to Murty k-best if batches grow
    for hypothesis in itertools.product(*candidates_per_event):
        is_valid = True
        for i in range(m):
            for j in range(i + 1, m):
                if abs(events_ts_ms[i] - events_ts_ms[j]) < min_gap_ms:
                    tid_i = hypothesis[i].track_id
                    tid_j = hypothesis[j].track_id
                    if tid_i is not None and tid_j is not None and tid_i == tid_j:
                        is_valid = False
                        break
            if not is_valid:
                break

        if is_valid:
            valid_hypotheses.append(hypothesis)

    return valid_hypotheses


def compute_marginals(
    candidates_per_event: list[list[CandidateOption]],
    valid_hypotheses: list[tuple[CandidateOption, ...]],
) -> tuple[list[dict[CandidateOption, float]], list[float], list[float]]:
    """Computes max-subtracted normalized weights and JPDA marginals per event option.

    Returns:
        (marginals, hypothesis_scores, hypothesis_weights)
    """
    scores = [sum(opt.score for opt in h) for h in valid_hypotheses]
    max_score = max(scores)
    weights = [math.exp(s - max_score) for s in scores]
    total_weight = sum(weights)

    m = len(candidates_per_event)
    marginals: list[dict[CandidateOption, float]] = []

    for j in range(m):
        ev_marginals: dict[CandidateOption, float] = {opt: 0.0 for opt in candidates_per_event[j]}
        for h_idx, h in enumerate(valid_hypotheses):
            chosen_opt = h[j]
            ev_marginals[chosen_opt] += weights[h_idx]

        for opt in ev_marginals:
            ev_marginals[opt] /= total_weight

        marginals.append(ev_marginals)

    return marginals, scores, weights


def assign(
    events: list[tuple[int, dict]],
    persons: list[tuple[int, dict]],
    cfg: Any,
    mode: str,
) -> list[tuple[str | None, float]]:
    """Assigns actors to a batch of item events using exact JPDA or Hungarian baseline.

    Events are internally sorted by (ts_ms, event_id), and results are returned
    in that sorted order.

    Args:
        events: list of (ts_ms, event_dict) tuples.
        persons: list of (ts_ms, person_dict) tuples.
        cfg: MatcherConfig or object with tuning fields.
        mode: "jpda" or "hungarian".

    Returns:
        list of (person_id, confidence) pairs corresponding to events in (ts_ms, event_id) order.
    """
    if not events:
        return []

    if mode not in ("jpda", "hungarian"):
        raise ValueError(f"Unknown association mode: {mode}")

    sorted_events = sorted(events, key=lambda x: (x[0], x[1]["event_id"]))
    events_ts_ms = [t for t, _ in sorted_events]
    candidates_per_event = [
        get_candidates_for_event(ev_dict, t, persons, cfg)
        for t, ev_dict in sorted_events
    ]

    valid_hypotheses = enumerate_hypotheses(events_ts_ms, candidates_per_event, cfg.min_gap_ms)
    marginals, scores, _ = compute_marginals(candidates_per_event, valid_hypotheses)

    results: list[tuple[str | None, float]] = []

    if mode == "jpda":
        for j, (_, ev_dict) in enumerate(sorted_events):
            item_conf = float(ev_dict["confidence"])
            ev_marginals = marginals[j]

            # Ties: null first, then lowest track_id
            def _jpda_key(opt: CandidateOption) -> tuple[float, int, int]:
                m_val = ev_marginals[opt]
                return (
                    -m_val,
                    0 if opt.track_id is None else 1,
                    opt.track_id if opt.track_id is not None else -1,
                )

            best_opt = min(candidates_per_event[j], key=_jpda_key)
            chosen_marginal = ev_marginals[best_opt]
            conf = round(chosen_marginal * item_conf, 4)
            results.append((best_opt.person_id, conf))

    elif mode == "hungarian":
        def _hungarian_key(idx: int) -> tuple[float, tuple[int, ...]]:
            h = valid_hypotheses[idx]
            tie_tuple = tuple(-1 if opt.track_id is None else opt.track_id for opt in h)
            return (-scores[idx], tie_tuple)

        best_h_idx = min(range(len(valid_hypotheses)), key=_hungarian_key)
        best_h = valid_hypotheses[best_h_idx]

        for j, (_, ev_dict) in enumerate(sorted_events):
            item_conf = float(ev_dict["confidence"])
            chosen_opt = best_h[j]
            chosen_marginal = marginals[j][chosen_opt]
            conf = round(chosen_marginal * item_conf, 4)
            results.append((chosen_opt.person_id, conf))

    return results
