# Item recognition (Role 2) – design

Owner: Dang · 11/07/2026 · Branch `item` · Code in `services/item/` only

## Intent

Detect when someone **puts an item into** or **takes an item out of** the fridge, say which item, and publish one `item.event` per action. The backend joins it with `person.seen` by time to know who did it (feature 1, 2) and whether they took someone else's item (feature 4). Over-engineering is welcome, but every layer must fix one flaw of a simpler version and get an accuracy number with it on and off.

## Hardware and data path (decided)

- **Item camera:** an Android phone lying on top of the fridge, camera end hanging 3–5 cm past the front edge, lens pointing down, tilted 15–30° inward. Streams MJPEG with the IP Webcam app. Same geometry as Samsung's AI Vision Inside camera.
- **Face camera:** the Galaxy Z Flip in front of the fridge (Role 1, not this spec).
- **Inference** runs on a rented cloud NVIDIA GPU (RTX 3090 / 4090 / 5090, A6000 or RTX PRO; CUDA 12.8). **The demo** runs on the Mac.
- **Transport (builder's call, see below):** SSH reverse tunnels from the Mac to the GPU server, so the server reads the phone at `http://localhost:8080/video` and publishes to Redpanda at `localhost:19092`. No relay code.
- **Timestamps:** `ts` = time the frame arrived on the machine running the pipeline. Person and item pipelines run on the same GPU server, so both streams share one clock.

## Algorithm

Per frame:

1. **Door open?** Mean brightness of a calibrated region of the opening, with on/off hysteresis. Closed → skip the frame. Each open→close is one **door session**.
2. **Detect + track** hands and items. v1: YOLOE (open vocabulary, text prompts) with ultralytics' built-in ByteTrack.
3. **Holding:** a hand holds the item whose box overlaps it most.
4. **Door line:** two calibrated points on the fridge's front edge plus one point known to be inside. A hand **crosses** when its center moves from one side to the other by more than a margin (no jitter on the line).
5. **Pair crossings** inside a session: each `in` crossing pairs with the next `out` crossing (FIFO), because the hand track often gets a new ID after disappearing inside the fridge.

   | in | out | result |
   |---|---|---|
   | holding | empty | PUT |
   | empty | holding | TAKE |
   | holding | holding | none (touched) |
   | empty | empty | none |

   When the door closes, an unpaired `in` while holding → PUT; an unpaired `out` while holding → TAKE.
6. **Which item:** PUT creates a new `item_id` in a gallery saved to disk. TAKE matches against items currently in the gallery (v1 by label; v2 by DINOv2 + color histogram embedding, Hungarian assignment when several items leave in one session). No match → `item_id: "unknown"`, low confidence.
7. **Publish** `item.event` (contract unchanged). `ts` is the moment the hand went **in** for both PUT and TAKE: at that moment the person still faces the face camera, while during rummaging they turn away and the backend only matches a face seen within ~3 s (`sigma_ms = 1000`, null prior −2.0). A TAKE whose `in` crossing was never seen (flushed at door close) keeps its `out` time.

## Goals

- Main flow: one item put in, later taken out → one PUT and one TAKE event with the same `item_id`.
- An accuracy number on labeled clips for every layer.
- Debug video (boxes, door line, door state, events) for the demo video.
- Per-stage latency p50/p95.

## Non-goals

- Door bins and freezer.
- Training a model from scratch. The Transformer action classifier only if ≥ 100 labeled trips exist.
- Changing `contracts/` (shared; Dang edits only on `main`).

## Upgrade layers (each measured on/off)

| Layer | Replaces | Fixes |
|---|---|---|
| DINOv2 + color + Hungarian | label match | two identical-looking items |
| SAM 2 masks for holding | box overlap | hand covering the item |
| Grounding DINO detector | YOLOE | rare items YOLOE misses |
| Shelf before/after diff (top shelf, front of shelves) | nothing | second opinion when the hand hides the item |
| HaMeR grip check | overlap | hand brushing past vs gripping (only if it runs on the GPU within the latency budget) |

## Constraints

- Python 3.11, uv, one `pyproject.toml` + `uv.lock` in `services/item/`.
- `torch` from the cu128 index on Linux; default PyPI on Mac.
- Model weights and clips never committed (`.gitignore` already blocks them).
- Freeze ~10:00 on 11/8.

## Builder's calls

- SSH reverse tunnels instead of a custom Mac thin client (zero code, same effect).
- YOLOE for hands as well as items; MediaPipe Hands is the fallback if hand recall on the recorded clips is poor.
- FIFO pairing of crossings: correct for one person at a time, which is the demo.
