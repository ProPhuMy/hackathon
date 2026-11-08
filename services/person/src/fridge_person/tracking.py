"""BoT-SORT face tracking with appearance association and quality-weighted evidence buffers."""
from collections import deque
import numpy as np
from scipy.optimize import linear_sum_assignment
from .recognition import unit
from .detection import _iou


class KalmanBoxTracker:
    """Kalman filter for tracking bounding boxes [x1, y1, x2, y2] with constant velocity."""
    def __init__(self, initial_box):
        self.state = np.zeros(8, dtype=float)
        self.state[:4] = initial_box
        self.P = np.diag([10., 10., 10., 10., 100., 100., 100., 100.])
        self.R = np.diag([1., 1., 1., 1.])
        self.last_dt = 0.1

    def predict(self, dt=0.1):
        dt = max(float(dt), 1e-3)
        self.last_dt = dt
        F = np.eye(8, dtype=float)
        F[:4, 4:] = np.eye(4) * dt
        # Process noise scaled with dt
        Q = np.diag([1., 1., 1., 1., 10., 10., 10., 10.]) * dt
        self.state = F @ self.state
        self.P = F @ self.P @ F.T + Q
        return self.state[:4].copy()

    def update(self, box):
        box = np.asarray(box, dtype=float)
        H = np.zeros((4, 8), dtype=float)
        H[:4, :4] = np.eye(4)
        y = box - H @ self.state
        S = H @ self.P @ H.T + self.R
        K = self.P @ H.T @ np.linalg.inv(S)
        self.state = self.state + K @ y
        self.P = (np.eye(8) - K @ H) @ self.P
        return self.state[:4].copy()


def _fuse_spherical(samples):
    if len(samples) < 3:
        return None
    timestamps = [t for _, _, t in samples]
    if timestamps[-1] - timestamps[0] < 0.4 - 1e-6:
        return None
    vectors = np.array([v for v, _, _ in samples])
    weights = np.array([w for _, w, _ in samples])
    resultant = (vectors * weights[:, None]).sum(axis=0)
    norm = np.linalg.norm(resultant)
    if norm <= 1e-12:
        return None
    mean = resultant / norm
    keep = vectors @ mean >= 0.5
    survivors = [s for s, k in zip(samples, keep) if k]
    if len(survivors) < 3 or (survivors[-1][2] - survivors[0][2] < 0.4 - 1e-6):
        return None
    surv_vectors = np.array([v for v, _, _ in survivors])
    surv_weights = np.array([w for _, w, _ in survivors])
    final_res = (surv_vectors * surv_weights[:, None]).sum(axis=0)
    if np.linalg.norm(final_res) <= 1e-12:
        return None
    return unit(final_res)


class FaceTrack:
    """Individual face track with motion state, appearance model, and temporal observation buffers."""
    def __init__(self, track_id, initial_box, segment_id, timestamp=0.0):
        self.track_id = int(track_id)
        self.segment_id = int(segment_id)
        self.kalman = KalmanBoxTracker(initial_box)
        self.last_box = np.asarray(initial_box, dtype=float)
        self.last_seen_time = float(timestamp)
        self.hits = 1
        self.time_since_update = 0.0
        self.state = 'tentative'
        self.smooth_appearance = None
        self.accepted_identity = None
        self.arcface_samples = deque(maxlen=20)
        self.adaface_samples = deque(maxlen=20)

    def reset_evidence(self):
        self.arcface_samples.clear()
        self.adaface_samples.clear()
        self.smooth_appearance = None
        self.accepted_identity = None
        self.segment_id += 1

    def add_observation(self, box, arc_vector, ada_vector=None, mag_norm=None, confidence=1.0, timestamp=0.0,
                        low=20.0, high=40.0):
        timestamp = float(timestamp)
        arc_vector = unit(arc_vector) if arc_vector is not None else None
        ada_vector = unit(ada_vector) if ada_vector is not None else None

        # Check appearance continuity
        if arc_vector is not None:
            if self.smooth_appearance is not None:
                sim = float(np.dot(self.smooth_appearance, arc_vector))
                if sim < 0.3:
                    # Contradiction: reset contaminated evidence
                    self.reset_evidence()
            self.smooth_appearance = arc_vector if self.smooth_appearance is None else unit(
                0.8 * self.smooth_appearance + 0.2 * arc_vector
            )

        # Calculate quality weight
        if mag_norm is not None and high > low:
            q_mag = np.clip((mag_norm - low) / (high - low), 0.0, 1.0)
        else:
            q_mag = 1.0
        weight = float(np.clip(confidence * q_mag, 1e-4, 1.0))

        if arc_vector is not None:
            self.arcface_samples.append((arc_vector, weight, timestamp))
            while self.arcface_samples and timestamp - self.arcface_samples[0][2] > 2.0:
                self.arcface_samples.popleft()

        if ada_vector is not None:
            self.adaface_samples.append((ada_vector, weight, timestamp))
            while self.adaface_samples and timestamp - self.adaface_samples[0][2] > 2.0:
                self.adaface_samples.popleft()

        self.kalman.update(box)
        self.last_box = np.asarray(box, dtype=float)
        self.last_seen_time = timestamp
        self.hits += 1
        self.time_since_update = 0.0
        if self.hits >= 2:
            self.state = 'confirmed'

    def fuse_embeddings(self):
        arc_mean = _fuse_spherical(self.arcface_samples)
        if arc_mean is None:
            return None
        if not self.adaface_samples:
            return arc_mean, None
        ada_mean = _fuse_spherical(self.adaface_samples)
        if ada_mean is None:
            return None
        return arc_mean, ada_mean


class FaceTracker:
    """Multi-face tracker combining motion Kalman prediction and ArcFace appearance association."""
    def __init__(self, iou_weight=0.5, appearance_weight=0.5, max_staleness=2.0):
        self.iou_weight = iou_weight
        self.appearance_weight = appearance_weight
        self.max_staleness = max_staleness
        self.tracks = []
        self._next_track_id = 1
        self._last_timestamp = None

    def update(self, detections, timestamp):
        timestamp = float(timestamp)
        dt = (timestamp - self._last_timestamp) if self._last_timestamp is not None else 0.1
        self._last_timestamp = timestamp

        # Predict positions
        for track in self.tracks:
            track.kalman.predict(dt)
            track.time_since_update += dt

        # Associate
        unmatched_dets = list(range(len(detections)))
        if self.tracks and detections:
            cost_matrix = np.full((len(self.tracks), len(detections)), 1000.0)
            for t_idx, track in enumerate(self.tracks):
                for d_idx, det in enumerate(detections):
                    iou_val = _iou(track.last_box, det['box'])
                    arc_vec = det.get('arc_vector')
                    if track.smooth_appearance is not None and arc_vec is not None:
                        cos_sim = float(np.dot(track.smooth_appearance, arc_vec))
                        if iou_val < 0.1 and cos_sim < 0.2:
                            continue
                        cost = self.iou_weight * (1.0 - iou_val) + self.appearance_weight * (1.0 - max(cos_sim, 0.0))
                    else:
                        if iou_val < 0.1:
                            continue
                        cost = 1.0 - iou_val
                    cost_matrix[t_idx, d_idx] = cost

            row_ind, col_ind = linear_sum_assignment(cost_matrix)
            matched_dets = set()
            for r, c in zip(row_ind, col_ind):
                if cost_matrix[r, c] < 0.8:
                    track = self.tracks[r]
                    det = detections[c]
                    track.add_observation(
                        box=det['box'],
                        arc_vector=det.get('arc_vector'),
                        ada_vector=det.get('ada_vector'),
                        mag_norm=det.get('mag_norm'),
                        confidence=det.get('confidence', 1.0),
                        timestamp=timestamp
                    )
                    matched_dets.add(c)
            unmatched_dets = [i for i in range(len(detections)) if i not in matched_dets]

        # Initialize new tracks for unmatched detections
        for d_idx in unmatched_dets:
            det = detections[d_idx]
            new_track = FaceTrack(
                track_id=self._next_track_id,
                initial_box=det['box'],
                segment_id=self._next_track_id * 1000,
                timestamp=timestamp
            )
            self._next_track_id += 1
            new_track.add_observation(
                box=det['box'],
                arc_vector=det.get('arc_vector'),
                ada_vector=det.get('ada_vector'),
                mag_norm=det.get('mag_norm'),
                confidence=det.get('confidence', 1.0),
                timestamp=timestamp
            )
            self.tracks.append(new_track)

        # Prune stale tracks
        alive_tracks = []
        for track in self.tracks:
            if track.time_since_update > self.max_staleness:
                track.state = 'deleted'
            else:
                alive_tracks.append(track)
        self.tracks = alive_tracks

        return [t for t in self.tracks if t.time_since_update < 0.05 or t.state == 'confirmed']
