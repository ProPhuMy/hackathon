"""Single-face baseline; multiple faces must reset evidence rather than guess association."""
from collections import deque
import numpy as np


def unit(vector):
    vector = np.asarray(vector, dtype=float)
    norm = np.linalg.norm(vector)
    if vector.ndim != 1 or not np.isfinite(vector).all() or not np.isfinite(norm) or norm <= 1e-12:
        raise ValueError('Invalid embedding')
    return vector / norm


class Evidence:
    def __init__(self):
        self.samples = deque(maxlen=20)

    def clear(self):
        self.samples.clear()

    def observe(self, vector, weight, now):
        vector = unit(vector)
        if not np.isfinite(weight) or not 0 < weight <= 1 or not np.isfinite(now):
            raise ValueError('Invalid observation weight or time')
        if self.samples:
            previous, _, timestamp = self.samples[-1]
            if now < timestamp or now - timestamp > 1 or np.dot(previous, vector) < .3:
                self.clear()
        self.samples.append((vector, weight, now))
        while self.samples and now - self.samples[0][2] > 2:
            self.samples.popleft()
        vectors = np.array([v for v, _, _ in self.samples])
        weights = np.array([w for _, w, _ in self.samples])
        resultant = (vectors * weights[:, None]).sum(axis=0)
        if np.linalg.norm(resultant) <= 1e-12:
            self.clear()
            return None
        mean = unit(resultant)
        keep = vectors @ mean >= .5
        survivors = [sample for sample, valid in zip(self.samples, keep) if valid]
        if len(survivors) < 3 or survivors[-1][2] - survivors[0][2] < .4 - 1e-6:
            return None
        return unit(sum(v * w for v, w, _ in survivors))


def decision(scores, accept, reject, margin):
    if not -1 <= reject <= accept <= 1 or not 0 <= margin <= 2:
        raise ValueError('Invalid baseline thresholds')
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked or any(not np.isfinite(s) or not -1.000001 <= s <= 1.000001 for _, s in ranked):
        raise ValueError('Empty or invalid gallery scores')
    person, best = ranked[0]
    if best < reject:
        return None, 0.
    if best >= accept and (len(ranked) == 1 or best - ranked[1][1] >= margin):
        return person, float(np.clip((best + 1) / 2, 0, 1))
    return None


class Baseline:
    """Same evidence/reset policy for live inference and encounter evaluation."""
    def __init__(self, scores, policy):
        self.scores = scores
        self.thresholds = tuple(policy[key] for key in ('accept', 'reject', 'margin'))
        decision({'validation': 0.}, *self.thresholds)
        self.evidence = Evidence()
        self.accepted = None
        self.generation = 0

    def reset(self):
        self.evidence.clear()
        self.accepted = None
        self.generation += 1

    def decide(self, vector):
        return decision(self.scores(vector), *self.thresholds)

    def observe(self, vector, weight, now):
        instantaneous = self.decide(vector)
        if self.accepted is not None and (instantaneous is None or instantaneous[0] != self.accepted):
            self.reset()
        previous_count = len(self.evidence.samples)
        mean = self.evidence.observe(vector, weight, now)
        if previous_count and len(self.evidence.samples) == 1:
            self.accepted = None
            self.generation += 1
        if mean is None:
            return None
        result = self.decide(mean)
        if result is None:
            self.reset()
        else:
            self.accepted = result[0]
        return result
