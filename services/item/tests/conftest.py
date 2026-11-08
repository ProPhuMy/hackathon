"""Shared fakes and fixtures. Test modules import the plain helpers with `from conftest import ...`."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from src.config import Config, save
from src.core.geometry import Box, DoorLine, Track
from src.core.pipeline import ItemPipeline

SCHEMA = json.loads(
    (Path(__file__).parents[3] / "contracts" / "item.event.schema.json").read_text()
)


def hand(id: int, cx: float, cy: float, conf: float = 0.9) -> Track:
    return Track(
        id=id,
        kind="hand",
        box=Box(cx - 10.0, cy - 10.0, cx + 10.0, cy + 10.0),
        conf=conf,
        label="hand",
    )


def item(id: int, cx: float, cy: float, label: str = "bottle", conf: float = 0.85) -> Track:
    return Track(
        id=id,
        kind="item",
        box=Box(cx - 10.0, cy - 10.0, cx + 10.0, cy + 10.0),
        conf=conf,
        label=label,
    )


class ScriptedDetector:
    """Returns script[i] on the i-th call, then []; counts calls."""

    def __init__(self, script: list[list[Track]]) -> None:
        self.script = script
        self.call_count = 0

    def __call__(self, frame: np.ndarray) -> list[Track]:
        idx = self.call_count
        self.call_count += 1
        if idx < len(self.script):
            return self.script[idx]
        return []


@pytest.fixture(autouse=True)
def guard_no_yoloe(monkeypatch):
    """Ensure tests never load or download real models."""
    monkeypatch.setattr("ultralytics.YOLOE", MagicMock())


@pytest.fixture
def line() -> DoorLine:
    # y = 100 line. Inside is y = 200. Margin is 15.
    # y < 85 is outside (-1), y > 115 is inside (+1), 85 <= y <= 115 is margin (0).
    return DoorLine(p1=(0.0, 100.0), p2=(200.0, 100.0), inside=(100.0, 200.0))


@pytest.fixture
def cfg(line) -> Config:
    return Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)


@pytest.fixture
def cfg_file(tmp_path: Path, cfg: Config) -> Path:
    path = tmp_path / "cfg.json"
    save(cfg, path)
    return path


@pytest.fixture
def pipelines_built(monkeypatch) -> list[ItemPipeline]:
    """Every ItemPipeline constructed during the test, in order."""
    built = []
    original_init = ItemPipeline.__init__

    def spy_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        built.append(self)

    monkeypatch.setattr("src.core.pipeline.ItemPipeline.__init__", spy_init)
    return built
