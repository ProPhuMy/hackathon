"""Per-fridge config (ROI, door line, brightness thresholds, prompts) and its JSON load/save."""
from dataclasses import dataclass, field
import json
from pathlib import Path

from .core.geometry import DoorLine

DEFAULT_PROMPTS: list[str] = [
    "hand",
    "arm",
    "bottle",
    "milk carton",
    "box",
    "food container",
    "fruit",
    "can",
]


@dataclass
class Config:
    roi: tuple[int, int, int, int]
    line: DoorLine
    door_on: float
    door_off: float
    prompts: list[str] = field(default_factory=lambda: list(DEFAULT_PROMPTS))
    hand_label: str = "hand"
    # "crossing": hands crossing the door line, gated by door brightness (camera sees the opening).
    # "edge": items vanishing past / appearing at the line, no door gating (camera on top, looking down the front).
    mode: str = "crossing"


def save(cfg: Config, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "roi": list(cfg.roi),
        "line": {
            "p1": [cfg.line.p1[0], cfg.line.p1[1]],
            "p2": [cfg.line.p2[0], cfg.line.p2[1]],
            "inside": [cfg.line.inside[0], cfg.line.inside[1]],
            "margin": cfg.line.margin,
        },
        "door_on": cfg.door_on,
        "door_off": cfg.door_off,
        "prompts": cfg.prompts,
        "hand_label": cfg.hand_label,
        "mode": cfg.mode,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load(path: Path | str) -> Config:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    roi_raw = data["roi"]
    roi = (int(roi_raw[0]), int(roi_raw[1]), int(roi_raw[2]), int(roi_raw[3]))
    line_raw = data["line"]
    line = DoorLine(
        p1=(float(line_raw["p1"][0]), float(line_raw["p1"][1])),
        p2=(float(line_raw["p2"][0]), float(line_raw["p2"][1])),
        inside=(float(line_raw["inside"][0]), float(line_raw["inside"][1])),
        margin=float(line_raw.get("margin", 15.0)),
    )
    door_on = float(data["door_on"])
    door_off = float(data["door_off"])
    prompts = list(data.get("prompts", DEFAULT_PROMPTS))
    hand_label = str(data.get("hand_label", "hand"))
    mode = str(data.get("mode", "crossing"))
    if mode not in ("crossing", "edge"):
        raise ValueError(f"Unknown mode {mode!r}: use 'crossing' or 'edge'")
    return Config(
        roi=roi,
        line=line,
        door_on=door_on,
        door_off=door_off,
        prompts=prompts,
        hand_label=hand_label,
        mode=mode,
    )
