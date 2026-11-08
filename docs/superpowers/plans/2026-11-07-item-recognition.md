# Item Recognition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect PUT / TAKE of fridge items from a top-mounted phone camera and publish `item.event`, then layer accuracy upgrades, each measured on/off.

**Architecture:** One Python package `fridge_item`. Pure logic (door state, door line, holding, crossing pairing, item gallery) is separated from I/O (stream reading, YOLOE detector, Kafka publish), so the logic is unit-tested with scripted tracks and the detector can be swapped per upgrade. One CLI with `record`, `calibrate`, `run`, `evaluate`.

**Tech Stack:** Python 3.11, uv, OpenCV, numpy, ultralytics (YOLOE + built-in ByteTrack), confluent-kafka, jsonschema/pytest; Phase 2+: torch, transformers (DINOv2), scipy.

**Spec:** `docs/superpowers/specs/2026-11-07-item-recognition-design.md`

## Global Constraints

- All code under `services/item/`; package `services/item/src/fridge_item/`; tests `services/item/tests/`. Never edit other folders (shared files are edited on `main` only).
- Python `>=3.11,<3.12`; add deps with `uv add` inside `services/item/`.
- Build every event with `fridge_item.events.item_event(type, item_id, item_label, confidence, ts)`; `contracts/item.event.schema.json` is not changed. `type` ∈ {`PUT`, `TAKE`}; `item_id` non-empty (`"unknown"` when no match); `confidence` in [0, 1].
- `ts` = arrival time of the frame (`fridge_item.events.now_ts()` when the frame is read), never processing-finish time.
- Clips (`*.mp4`) and weights never committed. Runtime gallery `services/item/data/gallery.json` is git-ignored.
- Run tests: `cd services/item && uv run pytest -q`. All green before every commit.
- Each phase ends with a PR from `item` into `main`.

## Review Focus

1. Hand track ID changes while the hand is inside the fridge, so `in` and `out` come from different IDs: the trip must still pair (Task 5 test `test_pairs_across_track_ids`).
2. A hand hovering on the door line must not produce extra crossings (Task 4 test `test_side_zero_within_margin`, Task 5 test `test_jitter_on_line_no_crossing`).
3. Door closes before an `out` crossing: holding `in` still yields PUT; an unpaired holding `out` yields TAKE (Task 5 test `test_close_flushes_unpaired`).
4. TAKE with an empty gallery, or after a restart: `("unknown", 0.0)` without crashing, and the gallery reloads from disk (Task 6 tests).
5. An HTTP chunk boundary splits a JPEG: the parser keeps the remainder for the next chunk (Task 1 test `test_split_keeps_partial_tail`).

---

## Phase 0: Camera and data (goal: clips that prove the camera view works)

### Task 1: Stream reading and clip recording

**Files:**
- Create: `services/item/src/fridge_item/stream.py`, `services/item/src/fridge_item/__main__.py`, `services/item/.gitignore`, `services/item/data/labels.csv`
- Test: `services/item/tests/test_stream.py`

**Interfaces:**
- Produces:
  - `split_jpegs(buf: bytes) -> tuple[list[bytes], bytes]`: complete JPEGs (`\xff\xd8` … `\xff\xd9`) and the unparsed tail.
  - `class LatestFrameReader(url: str)`: background thread reading the HTTP MJPEG stream with `requests` (`stream=True`), keeps only the newest decoded frame, reconnects after errors with a 1 s sleep; `.latest() -> tuple[np.ndarray, str] | None` returns each frame once (BGR, `ts` stamped on arrival).
  - `iter_frames(source: str) -> Iterator[tuple[np.ndarray, str]]`: `source` starting with `http` → loop on `LatestFrameReader`; otherwise a video file via `cv2.VideoCapture`.
  - CLI `uv run python -m fridge_item record <url> <out.mp4>`: writes frames with `cv2.VideoWriter` (mp4v, 15 fps) until Ctrl+C.

- [ ] **Step 1:** `uv add opencv-python numpy requests` in `services/item/`.
- [ ] **Step 2: Write failing tests**

```python
def test_split_two_frames():
    a, b = b"\xff\xd8AAA\xff\xd9", b"\xff\xd8BB\xff\xd9"
    frames, rest = split_jpegs(b"junk" + a + b)
    assert frames == [a, b] and rest == b""

def test_split_keeps_partial_tail():
    frames, rest = split_jpegs(b"\xff\xd8AAA\xff\xd9\xff\xd8BB")
    assert frames == [b"\xff\xd8AAA\xff\xd9"] and rest == b"\xff\xd8BB"
```

- [ ] **Step 3:** Run `uv run pytest tests/test_stream.py -q`. Expected: FAIL (import error).
- [ ] **Step 4:** Implement `stream.py` and the `record` subcommand in `__main__.py` (argparse subparsers; later tasks add `calibrate`, `run`, `evaluate`).
- [ ] **Step 5:** Run tests. Expected: PASS.
- [ ] **Step 6:** `services/item/.gitignore` contains `data/gallery.json` and `debug/`. `data/labels.csv` header: `clip,type,item_label` (one row per expected event; a clip with a PUT then a TAKE has two rows).
- [ ] **Step 7 (manual, at the fridge):** Mount the phone (spec: Hardware). Record ≥ 10 clips into `services/item/data/clips/`: PUT, TAKE, touch-only, two different items, two identical items. Fill `labels.csv`.
- [ ] **Step 8:** Commit `feat(item): stream reader, clip recorder, labels`.

### Task 2: Calibration and config

**Files:**
- Create: `services/item/src/fridge_item/config.py`, `services/item/src/fridge_item/geometry.py` (types only in this task)
- Modify: `services/item/src/fridge_item/__main__.py` (add `calibrate`)
- Test: `services/item/tests/test_config.py`

**Interfaces:**
- Produces (`geometry.py`):
  - `Point = tuple[float, float]`
  - `@dataclass(frozen=True) class Box: x1, y1, x2, y2: float` with `.center() -> Point`, `.area() -> float`, `.intersection(other: Box) -> float`
  - `@dataclass(frozen=True) class Track: id: int; kind: Literal["hand", "item"]; box: Box; conf: float; label: str`
  - `@dataclass(frozen=True) class DoorLine: p1: Point; p2: Point; inside: Point; margin: float = 15.0`
- Produces (`config.py`):
  - `@dataclass class Config: roi: tuple[int, int, int, int]; line: DoorLine; door_on: float; door_off: float; prompts: list[str]; hand_label: str = "hand"`
  - `load(path: Path) -> Config`, `save(cfg: Config, path: Path) -> None` (JSON)
  - Default prompts: `["hand", "bottle", "milk carton", "box", "food container", "fruit", "can"]`
  - CLI `calibrate <source> [--out config.json]`: show one frame; `cv2.selectROI` for the opening region; click 2 points on the fridge front edge, then 1 point inside the fridge; press a key with the door **closed**, then **open**, to sample ROI mean brightness `c` and `o`; set `door_on = c + 0.6*(o-c)`, `door_off = c + 0.4*(o-c)`.

- [ ] **Step 1: Failing test** `test_config_roundtrip`: `save` then `load` returns an equal `Config` (including `DoorLine` and prompts).
- [ ] **Step 2:** Run, expect FAIL.
- [ ] **Step 3:** Implement `geometry.py` types, `config.py`, `calibrate`.
- [ ] **Step 4:** Run, expect PASS.
- [ ] **Step 5 (manual):** `uv run python -m fridge_item calibrate data/clips/<clip>.mp4 --out config.json`; commit `config.json` (re-run at the venue).
- [ ] **Step 6:** Commit `feat(item): calibration and config`.

### Task 3: Detector, overlay, model check (go/no-go gate)

**Files:**
- Create: `services/item/src/fridge_item/detect.py`, `services/item/src/fridge_item/draw.py`
- Modify: `__main__.py` (add `probe <clip> <out.mp4>`: detector + overlay, no logic)
- Test: `services/item/tests/test_detect.py`

**Interfaces:**
- Consumes: `Track`, `Box`, `Config.prompts`, `Config.hand_label`.
- Produces:
  - `to_tracks(xyxy: np.ndarray, ids: np.ndarray | None, conf: np.ndarray, cls: np.ndarray, names: dict[int, str], hand_label: str) -> list[Track]`: drops rows without an ID; `kind="hand"` when `names[cls] == hand_label`, else `"item"`; `label = names[cls]`.
  - `class Detector(prompts: list[str], hand_label: str = "hand", weights: str = "yoloe-11s-seg.pt")`, `__call__(frame) -> list[Track]`: `YOLOE(weights)`, `model.set_classes(prompts, model.get_text_pe(prompts))`, `model.track(frame, persist=True, verbose=False)`.
  - `overlay(frame, tracks: list[Track], line: DoorLine, door_open: bool, events: list[dict]) -> np.ndarray`: boxes with `id:label`, door line, door state text, last events.

- [ ] **Step 1:** `uv add ultralytics`.
- [ ] **Step 2: Failing tests** for `to_tracks`: `test_drops_rows_without_id` (ids `None` → `[]`); `test_hand_kind` (row with class `"hand"` → `kind == "hand"`, other class → `"item"`, label kept).
- [ ] **Step 3:** Run, expect FAIL. **Step 4:** Implement. **Step 5:** Run, expect PASS.
- [ ] **Step 6 (gate):** `probe` every clip into `services/item/debug/`. Watch them. Hands must be detected in most frames where they cross the line, and held items in most holding frames. **If hand recall is poor:** add `mediapipe`, produce hand `Track`s from MediaPipe Hands (assign IDs with the same ByteTrack via `boxmot`), keep `to_tracks` for items. Write the decision in the commit message.
- [ ] **Step 7:** Commit `feat(item): YOLOE detector, overlay, probe`.

**Phase 0 done when:** labeled clips exist, `config.json` is calibrated, and the probe videos show hands and items.

---

## Phase 1: PUT / TAKE main flow (goal: right events on the clips and on Redpanda)

### Task 4: Door state, line side, holding

**Files:**
- Create: `services/item/src/fridge_item/door.py`
- Modify: `services/item/src/fridge_item/geometry.py`
- Test: `services/item/tests/test_geometry.py`, `services/item/tests/test_door.py`

**Interfaces:**
- Produces:
  - `DoorLine.side(pt: Point) -> int`: `+1` on the `inside` point's side, `-1` on the other, `0` when the distance to the line is `< margin`.
  - `held_item(hand: Track, items: list[Track], min_overlap: float = 0.15) -> Track | None`: the item with the largest `intersection / item.area()` against the hand box, if ≥ `min_overlap`.
  - `class DoorDetector(roi: tuple[int, int, int, int], on: float, off: float)`, `.update(frame) -> bool`: grayscale mean in ROI; opens at `> on`, closes at `< off`, otherwise keeps state.

- [ ] **Step 1: Failing tests:** `test_side_inside_outside` (line `(0,100)-(200,100)`, inside `(100,200)`: `(100,150)` → `1`, `(100,50)` → `-1`); `test_side_zero_within_margin` (`(100,105)` → `0`); `test_held_item_picks_max_overlap`; `test_held_item_none_below_threshold`; `test_door_hysteresis` (sequence of brightness values `[10, 80, 60, 30, 10]` with on=70, off=20 → `[F, T, T, T, F]`; build frames with `np.full`).
- [ ] **Step 2:** Run, expect FAIL. **Step 3:** Implement. **Step 4:** Run, expect PASS.
- [ ] **Step 5:** Commit `feat(item): door detector, door line, holding`.

### Task 5: Door session and trip pairing

**Files:**
- Create: `services/item/src/fridge_item/session.py`
- Test: `services/item/tests/test_session.py`

**Interfaces:**
- Consumes: `Track`, `DoorLine.side`, `held_item`.
- Produces:
  - `@dataclass(frozen=True) class Crossing: direction: Literal["in", "out"]; held: Track | None; ts: str; crop: np.ndarray | None`
  - `@dataclass(frozen=True) class Trip: type: Literal["PUT", "TAKE"]; item: Track; ts: str; crop: np.ndarray | None; confidence: float`
  - `class DoorSession(line: DoorLine)`:
    - `.update(tracks: list[Track], ts: str, frame: np.ndarray | None = None) -> list[Trip]`: for each hand, remember the last **non-zero** side per track ID; a change of non-zero side is a crossing (`-1 → +1` = `in`). A hand ID seen for the first time records its side and never counts as a crossing. `held` = `held_item(hand, items)`; `crop` = the held item's box cropped from `frame` (or `None`). Pair FIFO: an `out` pairs with the oldest unpaired `in`, then apply the spec table. A trip is returned as soon as its `out` arrives. `Trip.ts` = the crossing where the item was held; `confidence = min(hand.conf, item.conf)`.
    - `.close() -> list[Trip]`: unpaired `in` holding → PUT; unpaired `out` holding → TAKE (an `out` with no pending `in` is kept unpaired until close).

- [ ] **Step 1: Failing tests** (helpers build tracks at given centers):
  - `test_put`: hand holding item crosses in, hand empty crosses out → `[Trip(type="PUT", item.label == "bottle")]`.
  - `test_take`: empty in, holding out → TAKE.
  - `test_touch_no_event`: holding in, holding out → `[]`.
  - `test_pairs_across_track_ids`: in by hand id 1, out by hand id 7 → PUT.
  - `test_jitter_on_line_no_crossing`: hand oscillates between `(100,98)` and `(100,103)` (inside the margin) for 10 frames → no crossings, `close() == []`.
  - `test_close_flushes_unpaired`: holding in, door closes → `close()` returns one PUT; separate session with only holding out → one TAKE.
  - `test_ts_is_held_crossing`: PUT trip `ts` equals the `in` frame's `ts`.
- [ ] **Step 2:** Run, expect FAIL. **Step 3:** Implement. **Step 4:** Run, expect PASS.
- [ ] **Step 5:** Commit `feat(item): door session and PUT/TAKE pairing`.

### Task 6: Item gallery (label matching)

**Files:**
- Create: `services/item/src/fridge_item/gallery.py`
- Test: `services/item/tests/test_gallery.py`

**Interfaces:**
- Produces: `class ItemGallery(path: Path)`, loads the JSON file if it exists:
  - `.add(label: str, embedding: np.ndarray | None = None) -> str`: new id `"item_" + uuid4().hex[:8]`, saves file.
  - `.take(label: str, embedding: np.ndarray | None = None) -> tuple[str, float]`: v1: oldest item with the same label → `(id, 1.0)`; else oldest item of any label → `(id, 0.3)`; empty → `("unknown", 0.0)`. Removes the matched item, saves file.
  - `.items() -> dict[str, dict]` (`{"label": str, "embedding": list[float] | None}`)

- [ ] **Step 1: Failing tests:** `test_add_then_take_same_label`; `test_take_empty_returns_unknown` (`("unknown", 0.0)`); `test_take_other_label_low_score` (`score == 0.3`); `test_persists_across_instances` (add, new `ItemGallery(same path)`, take returns that id).
- [ ] **Step 2:** Run, expect FAIL. **Step 3:** Implement. **Step 4:** Run, expect PASS.
- [ ] **Step 5:** Commit `feat(item): persistent item gallery`.

### Task 7: Pipeline, `run` CLI, publish

**Files:**
- Create: `services/item/src/fridge_item/pipeline.py`
- Modify: `__main__.py` (add `run`)
- Test: `services/item/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `DoorDetector`, `DoorSession`, `ItemGallery`, `Detector` (or any `Callable[[np.ndarray], list[Track]]`), `item_event`.
- Produces:
  - `class ItemPipeline(cfg: Config, detect: Callable[[np.ndarray], list[Track]], gallery: ItemGallery, embed: Callable[[np.ndarray], np.ndarray] | None = None)`:
    - `.process(frame: np.ndarray, ts: str) -> list[dict]`: door closed → if a session is open, `close()` it and emit its trips; door open → start a session if none, call the detector, `session.update`. PUT → `item_id = gallery.add(label, emb)`; TAKE → `item_id, score = gallery.take(label, emb)`, `confidence *= score` (for `"unknown"` use `confidence = 0.1`). `emb = embed(trip.crop)` when both exist.
    - `.tracks`, `.door_open` (last frame, for the overlay).
  - CLI `run --source <url|file> [--config config.json] [--gallery data/gallery.json] [--broker localhost:19092 | --dry-run] [--debug-video debug/out.mp4]`: prints every event as JSON; publishes to topic `item.event` with key `event_id` (same producer code as `tools/fake_events.py`); prints p50/p95 of detector ms and whole-frame ms every 100 frames (`time.perf_counter`).

- [ ] **Step 1:** `uv add confluent-kafka`.
- [ ] **Step 2: Failing test** `test_put_then_take_events`: a fake detector scripted per frame index plus frames whose ROI brightness opens and closes the door twice. Session 1 = PUT of `"bottle"`, session 2 = TAKE. Assert two events, `type` PUT then TAKE, the same `item_id`, and each validates against `contracts/item.event.schema.json` (load as in `tests/test_contract.py`).
- [ ] **Step 3:** Run, expect FAIL. **Step 4:** Implement. **Step 5:** Run, expect PASS.
- [ ] **Step 6 (manual):** `uv run python -m fridge_item run --source data/clips/<put_take>.mp4 --dry-run --debug-video debug/put_take.mp4`. Events printed, the overlay shows them.
- [ ] **Step 7 (manual):** with `docker compose -f infra/docker-compose.yml up -d` from the repo root, run without `--dry-run`; `rpk topic consume item.event` shows the events.
- [ ] **Step 8:** Commit `feat(item): pipeline and run CLI`.

### Task 8: Evaluation and baseline number

**Files:**
- Create: `services/item/src/fridge_item/evaluate.py`, `services/item/RESULTS.md`
- Modify: `__main__.py` (add `evaluate`)
- Test: `services/item/tests/test_evaluate.py`

**Interfaces:**
- Produces:
  - `score(expected: list[tuple[str, str]], got: list[tuple[str, str]]) -> dict[str, int]`: multiset match on `(type, item_label)` → `{"correct", "missed", "extra"}`.
  - CLI `evaluate [--labels data/labels.csv] [--clips data/clips] [--config config.json]`: runs `ItemPipeline` with a fresh temporary gallery per clip, sums `score` over clips, and prints totals plus `accuracy = correct / (correct + missed + extra)`.

- [ ] **Step 1: Failing tests:** `test_score_exact` (`correct=2, missed=0, extra=0`); `test_score_missed_and_extra`.
- [ ] **Step 2:** Run, expect FAIL. **Step 3:** Implement. **Step 4:** Run, expect PASS.
- [ ] **Step 5:** Run `evaluate`; write the baseline row in `RESULTS.md` (`| layer | correct | missed | extra | accuracy |`).
- [ ] **Step 6:** Commit `feat(item): evaluation, baseline result`; push; open a PR `item → main`.

**Phase 1 done when:** the PUT→TAKE clip produces the right two events on Redpanda and `RESULTS.md` has a baseline.

---

## Phase 2: Item identity (goal: identical-looking items are told apart)

### Task 9: Embeddings and Hungarian matching

**Files:**
- Create: `services/item/src/fridge_item/embed.py`
- Modify: `gallery.py` (embedding match), `session.py` (best crop), `pipeline.py` (pass `embed`), `pyproject.toml`
- Test: `services/item/tests/test_gallery.py`, `services/item/tests/test_session.py`

**Interfaces:**
- Produces:
  - `class Embedder(device: str | None = None)`, `__call__(crop: np.ndarray) -> np.ndarray`: L2-normalized concat of the DINOv2 `facebook/dinov2-small` CLS vector (via `transformers.AutoModel`) and an HSV histogram (8×8×4 bins, L2-normalized, weight 0.5).
  - `ItemGallery.take(label, embedding)`: with an embedding, score = cosine against the stored embeddings, best item. Label only breaks ties.
  - `ItemGallery.take_many(queries: list[tuple[str, np.ndarray]]) -> list[tuple[str, float]]`: one assignment for several TAKEs in the same session via `scipy.optimize.linear_sum_assignment` on `1 - cosine`; extra queries → `("unknown", 0.0)`.
  - `DoorSession`: `Trip.crop` = the largest-area crop of the held item seen while that hand held it, not only the crossing frame.
  - `run` and `evaluate` get a `--embed` flag: when set, the pipeline is built with `embed=Embedder()`; without it, behavior stays label-only (the on/off switch for `RESULTS.md`).
- [ ] **Step 1:** In `pyproject.toml` add the cu128 index for Linux, then `uv add "torch>=2.8,<2.11" transformers scipy`:

```toml
[[tool.uv.index]]
name = "pytorch-cu128"
url = "https://download.pytorch.org/whl/cu128"
explicit = true

[tool.uv.sources]
torch = [{ index = "pytorch-cu128", marker = "sys_platform == 'linux'" }]
torchvision = [{ index = "pytorch-cu128", marker = "sys_platform == 'linux'" }]
```

- [ ] **Step 2: Failing tests:** `test_take_by_embedding_picks_nearest` (two `"bottle"` items with orthogonal vectors; a query near the second → second id); `test_take_many_assigns_one_to_one` (2 items, 2 queries, swapped order → correct ids); `test_take_many_extra_query_unknown`; `test_trip_crop_is_largest_held` (session where the held item's box grows then shrinks → crop shape equals the largest box).
- [ ] **Step 3:** Run, expect FAIL. **Step 4:** Implement (`take_many` is used by the pipeline when ≥ 2 TAKEs close in one session). **Step 5:** Run, expect PASS.
- [ ] **Step 6:** Record clips with two identical-looking items; `evaluate` with and without `--embed`; add both rows to `RESULTS.md`.
- [ ] **Step 7:** Commit `feat(item): DINOv2 + color embeddings, Hungarian matching`; PR to `main`.

---

## Phase 3: Live on the cloud GPU (goal: real-time demo, latency numbers)

### Task 10: GPU deployment and latency

**Files:**
- Modify: `services/item/README.md` (create): run instructions below
- No new code unless a step fails.

- [ ] **Step 1:** On the GPU server: clone, `cd services/item && uv sync`. Check `uv run python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_arch_list())"` prints `True` and includes the GPU's `sm_` (e.g. `sm_120` on a 5090).
- [ ] **Step 2:** From the Mac (phone and Mac on the same Wi-Fi/hotspot, Redpanda running on the Mac): `ssh -N -R 8080:<phone-ip>:8080 -R 19092:localhost:19092 <user>@<gpu-host>`.
- [ ] **Step 3:** On the GPU: `uv run python -m fridge_item run --source http://localhost:8080/video --broker localhost:19092 --debug-video debug/live.mp4`. On the Mac: `docker compose -f infra/docker-compose.yml exec redpanda rpk topic consume item.event` shows a live PUT and TAKE.
- [ ] **Step 4:** Record the printed p50/p95 in `RESULTS.md`. Optional speed-up if detector p95 > 30 ms: export YOLOE to TensorRT FP16 (`model.export(format="engine", half=True)` after `set_classes`, built on the GPU server) and load the `.engine`; record the new numbers.
- [ ] **Step 5:** Commit `docs(item): GPU run instructions and latency`; PR to `main`.

**Phase 3 done when:** a live PUT/TAKE shows up on the Mac's Redpanda from the cloud GPU, with latency recorded. **Record the backup demo video here.**

---

## Phase 4: Accuracy upgrades (each: add, `evaluate` on/off, add a row to `RESULTS.md`, commit)

### Task 11: SAM 2 masks for holding
- `held_item` gets `masks: dict[int, np.ndarray] | None`: overlap = hand box ∩ item mask pixels / mask pixels. Masks from ultralytics `SAM("sam2.1_b.pt")` prompted with the item boxes, only on door-open frames.
- CLI flag `--holding box|mask`. Test `test_held_item_mask_overlap` with synthetic masks.
- Fixes: the hand covering the item.

### Task 12: Grounding DINO detector
- `class GDinoDetector(prompts, hand_label)` with the same `__call__` contract as `Detector`, using `transformers` `IDEA-Research/grounding-dino-tiny` for boxes and `boxmot.ByteTrack` for IDs (`uv add boxmot`). Reuse `to_tracks` on its output.
- CLI flag `--detector yoloe|gdino`. Fixes: rare items YOLOE misses.

### Task 13: Shelf before/after second opinion
- `shelf_diff(before: np.ndarray, after: np.ndarray, detect) -> tuple[list[Track], list[Track]]` (added, removed) on the first and last door-open frames with no hand in the ROI.
- In `ItemPipeline`, on session close: agreeing evidence multiplies trip confidence by 1.0, contradicting evidence by 0.5. A diff with no trip emits nothing (log only). Test with scripted tracks.
- Fixes: the hand hides the item at the crossing.

### Task 14: HaMeR grip check (spike, 30 min time-box)
- Go only if HaMeR runs on the GPU server at ≤ 30 ms per hand crop. Otherwise write "no-go: <reason>" in `RESULTS.md` and stop.

**Out of plan:** the Transformer action classifier (needs ≥ 100 labeled trips; revisit only if they exist).
