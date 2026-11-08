from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.core.geometry import Box
from src.vision.detect import Detector, to_tracks


def test_drops_rows_without_id():
    xyxy = np.array([[10.0, 20.0, 30.0, 40.0], [50.0, 60.0, 70.0, 80.0]])
    conf = np.array([0.9, 0.8])
    cls = np.array([0, 1])
    names = {0: "hand", 1: "bottle"}

    # Case 1: ids is None
    tracks_none = to_tracks(
        xyxy=xyxy,
        ids=None,
        conf=conf,
        cls=cls,
        names=names,
        hand_label="hand",
    )
    assert tracks_none == []

    # Case 2: ids contains a NaN / missing ID
    ids_with_nan = np.array([np.nan, 3.0])
    tracks_filtered = to_tracks(
        xyxy=xyxy,
        ids=ids_with_nan,
        conf=conf,
        cls=cls,
        names=names,
        hand_label="hand",
    )
    assert len(tracks_filtered) == 1
    assert tracks_filtered[0].id == 3
    assert tracks_filtered[0].label == "bottle"


def test_hand_kind():
    xyxy = np.array(
        [
            [10.0, 20.0, 30.0, 40.0],
            [50.0, 60.0, 70.0, 80.0],
            [15.0, 25.0, 35.0, 45.0],
        ]
    )
    ids = np.array([1, 2, 5])
    conf = np.array([0.95, 0.82, 0.75])
    cls = np.array([0, 1, 2])
    names = {0: "hand", 1: "milk carton", 2: "can"}

    tracks = to_tracks(
        xyxy=xyxy,
        ids=ids,
        conf=conf,
        cls=cls,
        names=names,
        hand_label="hand",
    )
    assert len(tracks) == 3

    # Row 0: class is "hand" -> kind == "hand"
    assert tracks[0].id == 1
    assert tracks[0].kind == "hand"
    assert tracks[0].label == "hand"
    assert tracks[0].conf == 0.95
    assert tracks[0].box == Box(10.0, 20.0, 30.0, 40.0)

    # Row 1: class is "milk carton" -> kind == "item"
    assert tracks[1].id == 2
    assert tracks[1].kind == "item"
    assert tracks[1].label == "milk carton"
    assert tracks[1].conf == 0.82
    assert tracks[1].box == Box(50.0, 60.0, 70.0, 80.0)

    # Row 2: class is "can" -> kind == "item"
    assert tracks[2].id == 5
    assert tracks[2].kind == "item"
    assert tracks[2].label == "can"
    assert tracks[2].conf == 0.75
    assert tracks[2].box == Box(15.0, 25.0, 35.0, 45.0)


def test_custom_hand_label():
    xyxy = np.array([[1.0, 2.0, 3.0, 4.0]])
    ids = np.array([10])
    conf = np.array([0.9])
    cls = np.array([0])
    names = {0: "user_hand"}

    tracks = to_tracks(
        xyxy=xyxy,
        ids=ids,
        conf=conf,
        cls=cls,
        names=names,
        hand_label="user_hand",
    )
    assert len(tracks) == 1
    assert tracks[0].kind == "hand"
    assert tracks[0].label == "user_hand"


def test_empty_detections():
    xyxy = np.empty((0, 4))
    ids = np.empty((0,))
    conf = np.empty((0,))
    cls = np.empty((0,))
    names = {0: "hand"}

    tracks = to_tracks(
        xyxy=xyxy,
        ids=ids,
        conf=conf,
        cls=cls,
        names=names,
        hand_label="hand",
    )
    assert tracks == []


def test_detector_mocked():
    with patch("ultralytics.YOLOE") as mock_yoloe_cls:
        mock_model = MagicMock()
        mock_yoloe_cls.return_value = mock_model
        mock_model.get_text_pe.return_value = "dummy_embeddings"
        mock_model.names = {0: "hand", 1: "bottle"}

        detector = Detector(prompts=["hand", "bottle"], hand_label="hand", weights="test.pt")
        mock_yoloe_cls.assert_called_once_with("test.pt")
        mock_model.get_text_pe.assert_called_once_with(["hand", "bottle"])
        mock_model.set_classes.assert_called_once_with(["hand", "bottle"], "dummy_embeddings")

        # Mock results returned by track
        mock_box = MagicMock()
        import torch

        mock_box.xyxy = torch.tensor([[10.0, 20.0, 30.0, 40.0]])
        mock_box.id = torch.tensor([1.0])
        mock_box.conf = torch.tensor([0.91])
        mock_box.cls = torch.tensor([0.0])

        mock_result = MagicMock()
        mock_result.boxes = mock_box
        mock_result.names = {0: "hand", 1: "bottle"}
        mock_model.track.return_value = [mock_result]

        dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        tracks = detector(dummy_frame)

        mock_model.track.assert_called_once_with(
            dummy_frame, persist=True, verbose=False, tracker="bytetrack.yaml"
        )
        assert len(tracks) == 1
        assert tracks[0].id == 1
        assert tracks[0].kind == "hand"
        assert tracks[0].label == "hand"
        assert pytest.approx(tracks[0].conf, 0.01) == 0.91


def test_arm_counts_as_a_hand():
    # Seen from above, the forearm is detected far more often than the hand itself.
    tracks = to_tracks(
        xyxy=np.array([[0, 0, 10, 10], [5, 5, 15, 15]], dtype=float),
        ids=np.array([1, 2]),
        conf=np.array([0.5, 0.8]),
        cls=np.array([0, 1]),
        names={0: "arm", 1: "bottle"},
        hand_label="hand",
    )
    assert [t.kind for t in tracks] == ["hand", "item"]
