"""Face models: SCRFD/ArcFace, YOLO5Face, AdaFace/MagFace, and detector box fusion."""


def onnx_providers():
    """(ONNX Runtime providers, insightface ctx_id): CUDA when the GPU build is installed, else CPU.

    CPU stays listed after CUDA so a host without a usable NVIDIA GPU still runs (ORT falls back)."""
    import onnxruntime as ort
    if 'CUDAExecutionProvider' not in ort.get_available_providers():
        return ['CPUExecutionProvider'], -1
    ort.preload_dlls()  # load the pip-installed CUDA/cuDNN libraries before the first session
    return ['CUDAExecutionProvider', 'CPUExecutionProvider'], 0
