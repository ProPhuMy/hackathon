"""Model wrappers: open-vocabulary detectors, SAM segmenter, visual embedder.

Heavy libraries (torch, ultralytics, transformers) are imported only when a model is built.
"""


def pick_device(torch) -> str:
    """CUDA if available, else Apple MPS, else CPU."""
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def detector_class(name: str):
    """Detector class for `--detector`: "gdino" is Grounding DINO, anything else YOLOE."""
    if name == "gdino":
        from .gdino import GDinoDetector

        return GDinoDetector
    from .detect import Detector

    return Detector


def optional_models(embed: bool, holding: str):
    """(Embedder if embed else None, Segmenter if holding == "mask" else None)."""
    embedder = segmenter = None
    if embed:
        from .embed import Embedder

        embedder = Embedder()
    if holding == "mask":
        from .segment import Segmenter

        segmenter = Segmenter()
    return embedder, segmenter
