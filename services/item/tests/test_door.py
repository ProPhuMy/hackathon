import numpy as np
import pytest
from src.door import DoorDetector


def test_door_hysteresis():
    roi = (10, 10, 20, 20)
    detector = DoorDetector(roi=roi, on=70.0, off=20.0)

    brightnesses = [10, 80, 60, 30, 10]
    expected = [False, True, True, True, False]
    actual = []

    for b in brightnesses:
        frame = np.full((100, 100, 3), b, dtype=np.uint8)
        state = detector.update(frame)
        actual.append(state)

    assert actual == expected


def test_door_roi_region():
    # Verify that only the ROI affects the door detection
    roi = (10, 10, 20, 20)
    detector = DoorDetector(roi=roi, on=70.0, off=20.0)

    # Frame with background 255 but ROI 0
    frame = np.full((100, 100, 3), 255, dtype=np.uint8)
    frame[10:30, 10:30] = 0
    assert detector.update(frame) is False

    # Frame with background 0 but ROI 255
    frame2 = np.zeros((100, 100, 3), dtype=np.uint8)
    frame2[10:30, 10:30] = 255
    assert detector.update(frame2) is True


def test_door_2d_grayscale_and_threshold_edges():
    roi = (0, 0, 10, 10)
    detector = DoorDetector(roi=roi, on=50.0, off=25.0)

    # 2D frame
    frame = np.full((20, 20), 50, dtype=np.uint8)  # Exactly equal to on -> does not open (> on required)
    assert detector.update(frame) is False

    frame_open = np.full((20, 20), 51, dtype=np.uint8)  # > on -> opens
    assert detector.update(frame_open) is True

    frame_mid = np.full((20, 20), 25, dtype=np.uint8)  # Exactly equal to off -> does not close (< off required)
    assert detector.update(frame_mid) is True

    frame_closed = np.full((20, 20), 24, dtype=np.uint8)  # < off -> closes
    assert detector.update(frame_closed) is False


def test_measure_brightness_helper_matches_door_detector_colored_frame():
    from src.door import measure_brightness

    roi = (10, 10, 20, 20)
    # Colored frame: B=200, G=50, R=20
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[10:30, 10:30] = [200, 50, 20]

    val = measure_brightness(frame, roi)

    # Naive BGR mean is (200 + 50 + 20) / 3 = 90.0, which differs from grayscale mean (~58.1)
    bgr_mean = float(np.mean(frame[10:30, 10:30]))
    assert abs(bgr_mean - val) > 10.0

    # DoorDetector with on threshold just below and just above val
    det_below = DoorDetector(roi=roi, on=val - 0.5, off=0.0)
    assert det_below.update(frame) is True

    det_above = DoorDetector(roi=roi, on=val + 0.5, off=0.0)
    assert det_above.update(frame) is False
