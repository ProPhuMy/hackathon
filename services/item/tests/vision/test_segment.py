from unittest.mock import MagicMock

import numpy as np

from src.core.geometry import Box, Track


def test_segmenter_empty_items_no_model_call(monkeypatch):
    from src.vision.segment import Segmenter

    mock_sam_cls = MagicMock()
    mock_sam_instance = MagicMock()
    mock_sam_cls.return_value = mock_sam_instance
    monkeypatch.setattr("ultralytics.SAM", mock_sam_cls)

    seg = Segmenter(weights="test_weights.pt")
    mock_sam_cls.assert_called_once_with("test_weights.pt")

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    res = seg(frame, [])
    assert res == {}
    mock_sam_instance.assert_not_called()


def test_segmenter_calls_sam_with_bboxes_and_returns_masks(monkeypatch):
    from src.vision.segment import Segmenter

    item1 = Track(10, "item", Box(10.0, 20.0, 30.0, 40.0), 0.9, "bottle")
    item2 = Track(20, "item", Box(50.0, 60.0, 70.0, 80.0), 0.8, "can")

    mock_masks_data = np.zeros((2, 100, 100), dtype=np.uint8)
    mock_masks_data[0, 20:40, 10:30] = 1
    mock_masks_data[1, 60:80, 50:70] = 1

    mock_result = MagicMock()
    mock_result.masks.data = mock_masks_data

    mock_sam_instance = MagicMock(return_value=[mock_result])
    mock_sam_cls = MagicMock(return_value=mock_sam_instance)
    monkeypatch.setattr("ultralytics.SAM", mock_sam_cls)

    seg = Segmenter()
    mock_sam_cls.assert_called_once_with("models/sam2.1_b.pt")

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    masks = seg(frame, [item1, item2])

    assert 10 in masks
    assert 20 in masks
    assert masks[10].dtype == bool
    assert masks[20].dtype == bool
    assert masks[10].shape == (100, 100)
    assert masks[20].shape == (100, 100)
    assert np.all(masks[10][20:40, 10:30] == True)
    assert np.all(masks[20][60:80, 50:70] == True)

    mock_sam_instance.assert_called_once()
    call_args, call_kwargs = mock_sam_instance.call_args
    assert np.array_equal(call_args[0], frame)
    assert call_kwargs["bboxes"] == [
        [10.0, 20.0, 30.0, 40.0],
        [50.0, 60.0, 70.0, 80.0],
    ]


def test_segmenter_handles_none_masks(monkeypatch):
    from src.vision.segment import Segmenter

    mock_result = MagicMock()
    mock_result.masks = None
    mock_sam_instance = MagicMock(return_value=[mock_result])
    monkeypatch.setattr("ultralytics.SAM", MagicMock(return_value=mock_sam_instance))

    seg = Segmenter()
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    item = Track(1, "item", Box(0, 0, 10, 10), 0.9, "apple")
    assert seg(frame, [item]) == {}
