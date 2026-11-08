import numpy as np
import pytest
from src.identity.recognition import unit


def test_kalman_box_tracker_prediction_and_update():
    from src.identity.tracking import KalmanBoxTracker
    tracker = KalmanBoxTracker([10., 10., 50., 50.])
    pred1 = tracker.predict(dt=0.1)
    assert len(pred1) == 4
    # Bounding box should remain close if stationary
    assert np.allclose(pred1, [10., 10., 50., 50.], atol=2.0)
    
    # Update with movement
    tracker.update([12., 12., 52., 52.])
    pred2 = tracker.predict(dt=0.1)
    # Velocity should move box slightly in positive direction
    assert pred2[0] > 11.0


def test_face_track_evidence_and_appearance_continuity():
    from src.identity.tracking import FaceTrack
    track = FaceTrack(track_id=1, initial_box=[0., 0., 100., 100.], segment_id=10)
    
    vec1 = unit([1., 0., 0.] + [0.] * 509)
    # Add 4 observations at 0.15s intervals
    for i in range(4):
        track.add_observation(
            box=[0., 0., 100., 100.],
            arc_vector=vec1,
            ada_vector=vec1,
            mag_norm=30.0,
            confidence=0.9,
            timestamp=10.0 + i * 0.15,
            low=20.0,
            high=40.0
        )
    
    # Should fuse successfully since >= 3 samples and span = 0.45s >= 0.4s
    fused = track.fuse_embeddings()
    assert fused is not None
    arc_mean, ada_mean = fused
    assert np.isclose(np.linalg.norm(arc_mean), 1.0)
    assert np.isclose(np.dot(arc_mean, vec1), 1.0)

    # Contradictory appearance (cosine < 0.3) should trigger reset
    vec_contrary = unit([0., 1., 0.] + [0.] * 509)
    track.add_observation(
        box=[0., 0., 100., 100.],
        arc_vector=vec_contrary,
        ada_vector=vec_contrary,
        mag_norm=30.0,
        confidence=0.9,
        timestamp=10.6,
        low=20.0,
        high=40.0
    )
    # Contaminated evidence cleared, cannot fuse until 3 new samples span 0.4s
    assert track.fuse_embeddings() is None
    assert len(track.arcface_samples) == 1


def test_face_tracker_multi_person_association():
    from src.identity.tracking import FaceTracker
    tracker = FaceTracker()
    
    v_alice = unit([1., 0.] + [0.] * 510)
    v_bob = unit([0., 1.] + [0.] * 510)

    # Frame 1: Alice on left, Bob on right
    det_f1 = [
        {'box': np.array([10., 10., 60., 60.]), 'confidence': 0.9, 'arc_vector': v_alice, 'ada_vector': v_alice, 'mag_norm': 30.0},
        {'box': np.array([200., 10., 250., 60.]), 'confidence': 0.9, 'arc_vector': v_bob, 'ada_vector': v_bob, 'mag_norm': 30.0},
    ]
    tracks1 = tracker.update(det_f1, timestamp=1.0)
    assert len(tracks1) == 2
    alice_id = next(t.track_id for t in tracks1 if t.last_box[0] < 100)
    bob_id = next(t.track_id for t in tracks1 if t.last_box[0] > 150)
    assert alice_id != bob_id

    # Frame 2: Slight movement
    det_f2 = [
        {'box': np.array([12., 11., 62., 61.]), 'confidence': 0.9, 'arc_vector': v_alice, 'ada_vector': v_alice, 'mag_norm': 30.0},
        {'box': np.array([202., 11., 252., 61.]), 'confidence': 0.9, 'arc_vector': v_bob, 'ada_vector': v_bob, 'mag_norm': 30.0},
    ]
    tracks2 = tracker.update(det_f2, timestamp=1.1)
    assert len(tracks2) == 2
    # Track IDs must be consistently preserved
    assert next(t.track_id for t in tracks2 if t.last_box[0] < 100) == alice_id
    assert next(t.track_id for t in tracks2 if t.last_box[0] > 150) == bob_id
