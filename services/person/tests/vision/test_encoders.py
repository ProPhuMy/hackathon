import numpy as np
import pytest
import torch
from src.vision.encoders import adaface_input, magface_input, load_checkpoint, quality_weight
from src.vision.backbones import AdaFaceIR50, MagFaceIR50


def test_checkpoint_specific_input_preprocessing_preserves_bgr():
    crop = np.zeros((112,112,3), dtype=np.uint8)
    crop[:] = [0,128,255]
    ada = adaface_input(crop)
    mag = magface_input(crop)
    assert ada.shape == mag.shape == (1,3,112,112)
    assert ada.dtype == mag.dtype == torch.float32
    assert torch.allclose(ada[0,:,0,0], torch.tensor([-1.,128/127.5-1,1.]))
    assert torch.allclose(mag[0,:,0,0], torch.tensor([0.,128/255,1.]))


@pytest.mark.parametrize('crop', [np.zeros((100,100,3),dtype=np.uint8), np.zeros((112,112,3))])
def test_invalid_aligned_crops_are_rejected(crop):
    for prepare in (adaface_input, magface_input):
        with pytest.raises(ValueError):
            prepare(crop)


def test_checkpoints_are_weights_only_tensor_dictionaries(tmp_path):
    path = tmp_path/'model.pth'
    torch.save({'state_dict': {'weight': torch.ones(2)}}, path)
    state = load_checkpoint(path)
    assert torch.equal(state['weight'], torch.ones(2))
    torch.save({'state_dict': {'weight': 'not a tensor'}}, path)
    with pytest.raises(ValueError):
        load_checkpoint(path)


def test_magface_weight_uses_raw_norm_and_valid_quantiles():
    assert quality_weight(30., .8, 10., 50.) == pytest.approx(.4)
    assert quality_weight(100., .8, 10., 50.) == pytest.approx(.8)
    assert quality_weight(1., .8, 10., 50.) == 0.
    for low, high in [(10.,10.), (20.,10.), (float('nan'),50.)]:
        with pytest.raises(ValueError):
            quality_weight(30., .8, low, high)


def test_selected_backbone_output_conventions():
    with torch.inference_mode():
        ada = AdaFaceIR50().eval()
        direction, norm = ada(torch.zeros(1,3,112,112))
        assert direction.shape == (1,512) and norm.shape == (1,1)
        assert torch.isfinite(direction).all() and torch.allclose(direction.norm(dim=1),torch.ones(1),atol=1e-5)
        del ada
        mag = MagFaceIR50().eval()
        raw = mag(torch.zeros(1,3,112,112))
        assert raw.shape == (1,512) and torch.isfinite(raw).all()


class UnsupportedMetadata:
    pass


def test_unapproved_pickle_globals_are_never_loaded(tmp_path):
    path = tmp_path/'unsupported.pth'
    torch.save({'state_dict': {'weight': torch.ones(2)}, 'extra': UnsupportedMetadata()}, path)
    with pytest.raises(ValueError, match='weights-only'):
        load_checkpoint(path)
