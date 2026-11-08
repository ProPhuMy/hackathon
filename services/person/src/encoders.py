"""Strict local checkpoint inference for the selected AdaFace and MagFace models."""
import pickle
from pathlib import Path
import numpy as np
import torch
from .backbones import AdaFaceIR50, MagFaceIR50
from .recognition import unit
from .storage import file_hash


class _LegacyCheckpointMetadata:
    """Inert replacement for an obsolete Lightning callback used as a metadata key."""


def load_checkpoint(path):
    try:
        # Never import/execute the training callback and never enable unrestricted pickle.
        with torch.serialization.safe_globals([(_LegacyCheckpointMetadata,
                'pytorch_lightning.callbacks.model_checkpoint.ModelCheckpoint')]):
            checkpoint = torch.load(path, map_location='cpu', weights_only=True)
    except (pickle.UnpicklingError, RuntimeError, EOFError) as error:
        raise ValueError('Checkpoint cannot be loaded safely in weights-only mode') from error
    if not isinstance(checkpoint, dict) or not isinstance(checkpoint.get('state_dict'), dict):
        raise ValueError('Checkpoint must contain a state_dict')
    state = checkpoint['state_dict']
    if not state or any(not isinstance(key, str) or not isinstance(value, torch.Tensor) for key, value in state.items()):
        raise ValueError('Checkpoint state_dict must contain named tensors only')
    return state


def _crop(crop):
    if not isinstance(crop, np.ndarray) or crop.shape != (112,112,3) or crop.dtype != np.uint8:
        raise ValueError('Expected a uint8 BGR, five-point-aligned 112x112 crop')
    return crop


def adaface_input(crop):
    # Official inference.py converts BGR in float64 before casting the tensor to float32.
    array = ((_crop(crop) / 255.) - .5) / .5
    return torch.from_numpy(array.transpose(2,0,1).copy()).unsqueeze(0).float()


def magface_input(crop):
    # Official gen_feat.py uses OpenCV BGR + ToTensor, Normalize(mean=0,std=1).
    return torch.from_numpy(_crop(crop).transpose(2,0,1).copy()).unsqueeze(0).float().div(255.)


def quality_weight(raw_norm, confidence, low, high):
    if (not np.isfinite([raw_norm, confidence, low, high]).all() or raw_norm <= 0
            or not 0 <= confidence <= 1 or not 0 <= low < high):
        raise ValueError('Invalid MagFace norm, detector confidence or quality quantiles')
    return float(confidence * np.clip((raw_norm - low) / (high - low), 0, 1))


class FaceEncoders:
    def __init__(self, adaface_path, magface_path):
        paths = [Path(adaface_path), Path(magface_path)]
        for path in paths:
            if not path.is_file():
                raise ValueError(f'Missing local encoder checkpoint: {path}')
        self.adaface = AdaFaceIR50()
        state = load_checkpoint(paths[0])
        state = {key.removeprefix('model.'): value for key,value in state.items() if key.startswith('model.')}
        try:
            self.adaface.load_state_dict(state, strict=True)
        except RuntimeError as error:
            raise ValueError('AdaFace checkpoint is incompatible with the selected IR-50 architecture') from error
        del state
        self.adaface.eval()
        self.magface = MagFaceIR50()
        state = load_checkpoint(paths[1])
        cleaned = {}
        for key,value in state.items():
            for prefix in ('features.module.', 'module.features.'):
                if key.startswith(prefix):
                    cleaned[key.removeprefix(prefix)] = value
        try:
            self.magface.load_state_dict(cleaned, strict=True)
        except RuntimeError as error:
            raise ValueError('MagFace checkpoint is incompatible with the selected iResNet50 architecture') from error
        self.magface.eval()
        self.hashes = [file_hash(path) for path in paths]
        self.signature = ':'.join(self.hashes) + ':ada-bgr-neg1-mag-bgr-zero1-v1'

    def encode(self, aligned_bgr):
        with torch.inference_mode():
            direction, norm = self.adaface(adaface_input(aligned_bgr))
            raw = self.magface(magface_input(aligned_bgr))
        ada = unit(direction[0].numpy())
        raw = raw[0].numpy()
        magnitude = float(np.linalg.norm(raw))
        if (ada.shape != (512,) or raw.shape != (512,) or not np.isfinite(raw).all()
                or not np.isfinite(magnitude) or magnitude <= 0 or not torch.isfinite(norm).all() or norm.item() <= 0):
            raise ValueError('Invalid encoder evidence; refusing recognition')
        return {'adaface': ada, 'magface_norm': magnitude}
