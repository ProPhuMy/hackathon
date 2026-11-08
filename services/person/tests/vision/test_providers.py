import sys
from types import SimpleNamespace
from src.vision import onnx_providers


def fake_ort(monkeypatch, available):
    calls = []
    monkeypatch.setitem(sys.modules, 'onnxruntime', SimpleNamespace(
        get_available_providers=lambda: available, preload_dlls=lambda: calls.append('preload')))
    return calls


def test_cuda_build_uses_the_gpu_with_cpu_fallback(monkeypatch):
    calls = fake_ort(monkeypatch, ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider'])
    assert onnx_providers() == (['CUDAExecutionProvider', 'CPUExecutionProvider'], 0)
    assert calls == ['preload']


def test_cpu_build_stays_on_cpu(monkeypatch):
    calls = fake_ort(monkeypatch, ['CoreMLExecutionProvider', 'CPUExecutionProvider'])
    assert onnx_providers() == (['CPUExecutionProvider'], -1)
    assert calls == []
