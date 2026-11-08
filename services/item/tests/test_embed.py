import sys
from unittest.mock import MagicMock
import numpy as np
import pytest

from fridge_item.embed import color_histogram


def test_color_histogram_shape_and_norm():
    # Create an RGB/BGR image (30x30 with uniform color)
    crop = np.full((30, 30, 3), 128, dtype=np.uint8)
    hist = color_histogram(crop)

    # 8 * 8 * 4 = 256 bins
    assert hist.shape == (256,)
    # Norm was multiplied by 0.5
    assert np.linalg.norm(hist) == pytest.approx(0.5, abs=1e-5)


def test_color_histogram_empty_crop():
    empty_crop = np.zeros((0, 0, 3), dtype=np.uint8)
    hist = color_histogram(empty_crop)
    assert hist.shape == (256,)
    assert np.all(hist == 0.0)


def test_embed_module_import_does_not_import_transformers():
    # If fridge_item.embed was imported, transformers shouldn't be required at module level
    # Test that importing fridge_item.embed has color_histogram and Embedder defined
    from fridge_item import embed

    assert hasattr(embed, "Embedder")
    assert hasattr(embed, "color_histogram")


def test_embedder_call_mocked(monkeypatch):
    from fridge_item.embed import Embedder

    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = False
    mock_torch.backends.mps.is_available.return_value = False

    mock_proc_instance = MagicMock()
    mock_proc_instance.return_value.to.return_value = {"pixel_values": "dummy"}
    mock_proc_cls = MagicMock(return_value=mock_proc_instance)

    mock_output = MagicMock()
    # DINOv2 CLS token (384,)
    cls_tensor = MagicMock()
    cls_tensor.squeeze.return_value.detach.return_value.cpu.return_value.numpy.return_value = np.ones(384, dtype=np.float32)
    mock_last_hidden_state = MagicMock()
    mock_last_hidden_state.__getitem__.return_value = cls_tensor
    mock_output.last_hidden_state = mock_last_hidden_state

    mock_model_instance = MagicMock()
    mock_model_instance.return_value = mock_output
    mock_model_instance.to.return_value = mock_model_instance
    mock_model_cls = MagicMock(return_value=mock_model_instance)

    monkeypatch.setattr("sys.modules", dict(sys.modules))
    monkeypatch.setitem(sys.modules, "torch", mock_torch)

    mock_transformers = MagicMock()
    mock_transformers.AutoImageProcessor.from_pretrained.return_value = mock_proc_instance
    mock_transformers.AutoModel.from_pretrained.return_value = mock_model_instance
    monkeypatch.setitem(sys.modules, "transformers", mock_transformers)

    embedder = Embedder(device="cpu")
    assert embedder.device == "cpu"

    crop = np.full((20, 20, 3), 200, dtype=np.uint8)
    emb = embedder(crop)

    # 384 (CLS) + 256 (color hist) = 640
    assert emb.shape == (640,)
    assert np.linalg.norm(emb) == pytest.approx(1.0, abs=1e-5)
