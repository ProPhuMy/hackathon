# Fridge Tracker: Item Recognition Service

## 1. What This Service Does
The Fridge Tracker item recognition service monitors refrigerator access in real time using computer vision and visual embeddings to detect items being placed into (PUT) or taken out of (TAKE) the fridge.
It publishes structured event payloads to the `item.event` Kafka topic, including the action type, item identifier, item label, confidence score, and capture timestamp.

## 2. Setup at the Fridge
Mount the phone on top of the fridge, camera end 3-5 cm past the front edge, lens down, tilted 15-30 degrees inward; IP Webcam app; lock exposure and focus.

## 3. Commands
Run commands with `uv run python -m src <cmd>`:

- **record**:
  ```bash
  uv run python -m src record http://192.168.1.50:8080/video data/clips/sample.mp4
  ```
- **calibrate**:
  ```bash
  uv run python -m src calibrate http://192.168.1.50:8080/video --out config.json
  ```
- **probe**:
  ```bash
  uv run python -m src probe data/clips/sample.mp4 debug/probe.mp4 --config config.json
  ```
- **run**:
  ```bash
  uv run python -m src run --source http://localhost:8080/video --config config.json --gallery data/gallery.json --broker localhost:19092 --dry-run --debug-video debug/live.mp4 --embed
  ```
- **evaluate**:
  ```bash
  uv run python -m src evaluate --labels data/labels.csv --clips data/clips --config config.json --embed
  ```

Tests: `uv run pytest -q` (no models are loaded or downloaded).

Model weights: YOLOE and SAM 2 weights default to `models/` (git-ignored) and are downloaded there on first use; Grounding DINO and DINOv2 come from the Hugging Face cache.

## 4. Code Layout
```
src/                 package `src`, run as `python -m src`
  __main__.py        entry point -> cli.main
  config.py          Config dataclass, JSON load/save
  events.py          item.event payloads (contracts/item.event.schema.json)
  stream.py          MJPEG/video frame source
  draw.py            debug-video overlay and writer
  cli/               one module per command: record, calibrate, probe, run, evaluate
  core/              door, geometry, session (hand crossings), shelf diff, gallery, pipeline
  vision/            YOLOE detector, Grounding DINO detector, SAM segmenter, DINOv2 embedder
tests/               mirrors src/ (core/, vision/, cli/); shared fakes in conftest.py
```

## 5. Labels Format
`data/labels.csv: clip,type,item_label; one row per expected event`.
Example:
```csv
clip,type,item_label
clip_01.mp4,PUT,coke
clip_01.mp4,TAKE,apple
clip_02.mp4,PUT,milk
```

## 6. Running on the Cloud GPU
- **Step 1:** On the GPU server: clone, `cd services/item && uv sync`. Check `uv run python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_arch_list())"` prints `True` and includes the GPU's `sm_` (e.g. `sm_120` on a 5090).
- **Step 2:** From the Mac (phone and Mac on the same Wi-Fi/hotspot, Redpanda running on the Mac): `ssh -N -R 8080:<phone-ip>:8080 -R 19092:localhost:19092 <user>@<gpu-host>`.
- **Step 3:** On the GPU: `uv run python -m src run --source http://localhost:8080/video --broker localhost:19092 --debug-video debug/live.mp4`. On the Mac: `docker compose -f infra/docker-compose.yml exec redpanda rpk topic consume item.event` shows a live PUT and TAKE.
- **Step 4:** Record the printed p50/p95 in `RESULTS.md`. Optional speed-up if detector p95 > 30 ms: export YOLOE to TensorRT FP16 (`model.export(format="engine", half=True)` after `set_classes`, built on the GPU server) and load the `.engine`; record the new numbers.

## 7. Known Limitation
Crossings are paired in order, so the logic assumes one person at the fridge at a time.
