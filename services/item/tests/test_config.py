import json
from pathlib import Path

from src.config import Config, DEFAULT_PROMPTS, load, save
from src.core.geometry import DoorLine


def test_config_roundtrip(tmp_path: Path):
    line = DoorLine(
        p1=(12.5, 34.0),
        p2=(100.0, 45.5),
        inside=(50.0, 80.0),
        margin=15.0,
    )
    cfg = Config(
        roi=(10, 20, 200, 150),
        line=line,
        door_on=160.0,
        door_off=110.0,
        prompts=DEFAULT_PROMPTS,
        hand_label="hand",
    )
    cfg_path = tmp_path / "config.json"
    save(cfg, cfg_path)
    loaded = load(cfg_path)

    assert loaded == cfg
    assert loaded.roi == (10, 20, 200, 150)
    assert loaded.line.p1 == (12.5, 34.0)
    assert loaded.line.p2 == (100.0, 45.5)
    assert loaded.line.inside == (50.0, 80.0)
    assert loaded.line.margin == 15.0
    assert loaded.door_on == 160.0
    assert loaded.door_off == 110.0
    assert loaded.prompts == DEFAULT_PROMPTS
    assert loaded.hand_label == "hand"


def test_config_defaults():
    line = DoorLine(p1=(0.0, 0.0), p2=(10.0, 10.0), inside=(5.0, 15.0))
    cfg = Config(roi=(0, 0, 50, 50), line=line, door_on=100.0, door_off=50.0)
    assert cfg.prompts == DEFAULT_PROMPTS
    assert cfg.hand_label == "hand"
    assert cfg.line.margin == 15.0


def test_load_default_margin_and_prompts(tmp_path: Path):
    cfg_file = tmp_path / "legacy_cfg.json"
    cfg_file.write_text(
        json.dumps({
            "roi": [0, 0, 10, 10],
            "line": {"p1": [0, 0], "p2": [10, 10], "inside": [5, 5]},
            "door_on": 120.0,
            "door_off": 80.0,
        })
    )
    loaded = load(cfg_file)
    assert loaded.line.margin == 15.0
    assert loaded.prompts == DEFAULT_PROMPTS
    assert loaded.hand_label == "hand"
