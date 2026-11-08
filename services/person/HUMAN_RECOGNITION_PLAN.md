# Role 1: Over-Engineered Human Recognition — Codex Implementation Brief

Research date: 2026-11-07. Owner: Role 1 (Viet in the current repository overview).
Status: researched implementation proposal; no vision models have been installed, benchmarked, or implemented by this document.

## 1. What we are building

Identify consenting, enrolled team members approaching the shared fridge, maintain their identity across short face-track interruptions, and publish `person.seen` events. A stranger, ambiguous match, or unusable face must never be forced into a registered identity.

**Recommended algorithm: a five-network, quality-aware temporal face ensemble with class-conditional conformal abstention and separately measured open-set rejection.**

The five networks are two face detectors (SCRFD and YOLO5Face), two identity encoders (ArcFace and AdaFace), and a separate MagFace quality encoder. BoT-SORT supplies motion/appearance association; robust temporal aggregation and score calibration combine their evidence. This combination is our engineering proposal, not a claim that a paper published this exact system.

There is no objectively “most complicated” recognition algorithm. This target deliberately has substantial algorithmic depth for the **Most Over-Engineered** track while keeping every layer attached to a measurable failure: missed faces, poor alignment, blur, ID switches, or false identity assignments. More networks are useful only when the recorded evaluation supports them.

### Project facts and authority

Read these alongside this brief:

- [Repository ownership and event rules](../../README.md).
- [Current English project overview](../../docs/Fridge%20Tracker%20%E2%80%93%20Project%20Overview.md).
- [Person event schema](../../contracts/person.seen.schema.json).
- [Existing event builder](src/fridge_person/events.py) and [contract tests](tests/test_contract.py).

All four existing Markdown files in the supplied folder were reviewed: the Vietnamese overview above the repository, its English copy in `docs/`, the repository README, and the dashboard README. The Vietnamese copy has older role assignments and an event example without `event_id`; follow the repository README and JSON Schemas for implementation. The dashboard README describes a Vite starter, not a completed registration interface.

At research time, `services/person/src/fridge_person/__init__.py` only prints a greeting. Runtime dependencies in its `pyproject.toml` are empty. The event helper and two schema tests exist; camera capture, enrollment, inference, tracking, calibration, and publishing do not. Other services and the dashboard are also scaffolding. Do not assume a backend registration API already exists.

### Scope and ownership

Implement inside `services/person/`, including its source, tests, dependency manifest/lockfile, and role-local documentation. Shared `contracts/`, `tools/`, `docs/`, infrastructure, the dashboard, and the backend belong to teammates. Report any required coordination without modifying those files. This brief is intentionally placed in Role 1's folder.

We own face recognition and observations. Role 2 owns items and hands; Role 3 owns person/item joining, inventory, and alerts. Recognizing someone near a fridge does not prove which visible person touched an item. The current contract cannot resolve simultaneous-person interaction; coordinate an `uncertain` result with Role 3 when multiple people are plausible. Never assign the nearest face as the taker without evidence.

## 2. Hardware decision: NVIDIA preferred; existing Mac remains viable

**Use an already accessible NVIDIA GPU for the ambitious full stack.** CUDA is the more natural fit for the upstream research environments. PyTorch documents separate CUDA and macOS acceleration paths; NVIDIA CUDA is not the execution backend for Apple Silicon. See [PyTorch installation](https://pytorch.org/get-started/locally/) and [MPS documentation](https://docs.pytorch.org/docs/stable/notes/mps.html).

The actual available NVIDIA machine, Mac chip, RAM, GPU VRAM, and operating system are unconfirmed. Do not infer them from the development computer or spend money on this proposal. The existing project explicitly plans a Mac and excludes the Jetson located in Vietnam.

| Deployment | Recommended use | First execution path | What must be verified |
| --- | --- | --- | --- |
| NVIDIA machine already available locally | Preferred full ensemble and possible research extensions | PyTorch CUDA; compatible ONNX Runtime CUDA provider for InsightFace | GPU/driver/runtime compatibility, VRAM with the item pipeline also running, camera connectivity |
| Existing Apple Silicon Mac | Baseline, integration, and full ensemble if profiling permits | InsightFace ONNX on CPU first; PyTorch CPU correctness first, then tested MPS | MPS operators, CPU fallback cost, total unified-memory pressure, live latency |
| Mac with ONNX CoreML provider | An optimization to try after correctness | Query installed providers and compare CoreML + CPU with CPU alone | Actual operator coverage, output parity, compilation/warm-up, measured speed |

Do not install `onnxruntime-gpu` expecting CUDA acceleration on macOS, treat ONNX as automatically using MPS, or assume CoreML accelerates every graph. [ONNX Runtime CoreML documentation](https://onnxruntime.ai/docs/execution-providers/CoreML-ExecutionProvider.html) describes a separate provider with supported-operator constraints.

On Mac, run inference directly on macOS as the project specifies. Keep Redpanda/Postgres in Docker. If inference moves to another machine, `localhost:19092` no longer refers to the Mac's broker: coordinate a reachable advertised broker address and camera URL with the infrastructure owner. Do not silently rewrite compose or introduce cloud deployment.

**No Mac FPS or RAM claim is established by the research.** Record checkpoint file bytes, parameter count where available, process peak resident memory, GPU peak allocation on CUDA, and warm p50/p95 latency on the actual host. File size is not inference memory. Published NVIDIA benchmark times are not Mac estimates.

## 3. Approaches researched and our selection

| Approach | Strength | Cost / limitation | Decision |
| --- | --- | --- | --- |
| SCRFD + ArcFace + cosine threshold | Fastest path to a real event and a useful baseline | Frame noise, temporal instability, and open-set errors need work | Build first and retain as the measured baseline |
| SCRFD + YOLO5Face, ArcFace + AdaFace, MagFace quality, BoT-SORT, temporal fusion, calibrated rejection + conformal sets | Five networks plus geometric, temporal, and statistical reasoning; clear ablations | More model loading, checkpoint integration, compute, and calibration data | **Selected target** |
| KP-RPE Vision Transformer or CAFace learned aggregation | More elaborate research-level representation or video fusion | Model-specific inputs/backbones, extra memory, unverified device compatibility | Research extensions only after the selected target works; see section 11 |

### Exact model starting points

| Component | Initial artifact | Primary evidence | Integration decision |
| --- | --- | --- | --- |
| Primary detector | InsightFace `buffalo_l` SCRFD-10GF | [Official model zoo](https://github.com/deepinsight/insightface/blob/master/model_zoo/README.md), [SCRFD paper](https://arxiv.org/abs/2105.04714) | Load detection and recognition only; omit age/gender and unused landmark models |
| Second detector | `deepcam-cn/yolov5-face`, pretrained `yolov5s` face checkpoint | [Authors' code and checkpoint links](https://github.com/deepcam-cn/yolov5-face), [YOLO5Face paper](https://arxiv.org/abs/2105.12931) | This is a face-specific model with five landmarks, not a generic Ultralytics object model |
| Box ensemble | Weighted Boxes Fusion (WBF) | [Paper](https://arxiv.org/abs/1910.13302), [authors' implementation](https://github.com/ZFTurbo/Weighted-Boxes-Fusion) | Use `ensemble-boxes` if compatible; preserve source detections for landmark ownership |
| Identity encoder A | ArcFace ResNet50 from `buffalo_l` | [ArcFace paper](https://arxiv.org/abs/1801.07698), official model zoo above | Use normalized 512-D identity vectors and cosine comparison |
| Identity encoder B | Official AdaFace IR-50 `adaface_ir50_ms1mv2.ckpt` | [Official repository](https://github.com/mk-minchul/AdaFace), [inference example](https://github.com/mk-minchul/AdaFace/blob/master/inference.py), [paper](https://arxiv.org/abs/2204.00964) | Preserve this checkpoint's preprocessing and separate embedding space |
| Quality encoder | Official MagFace iResNet50 MS1MV2 checkpoint | [Official code/model zoo](https://github.com/IrvingMeng/MagFace), [paper](https://arxiv.org/abs/2103.06627) | Use its raw feature magnitude for quality; do not substitute ArcFace's vector norm |
| Tracker | BoxMOT BoT-SORT using supplied ArcFace appearance vectors | [BoT-SORT paper/code](https://github.com/NirAharon/BoT-SORT), [BoxMOT tracker documentation](https://mikel-brostrom.github.io/boxmot/reference/boxmot/trackers/botsort/tracker/) | Adapt to pinned BoxMOT API; no person-body ReID model |

Checkpoint links exist in the cited repositories, but downloads, hashes, compatibility, and results have not been verified here. Record upstream revision, download origin, SHA-256, input convention, and license in a local model manifest. Code licenses and weight/dataset licenses can differ; InsightFace's public pretrained weights are described as non-commercial research models in its [official license notes](https://github.com/deepinsight/insightface#license). Check hackathon and later reuse eligibility rather than assuming the code license covers the weights.

## 4. Pipeline and invariants

```text
Galaxy Z Flip MJPEG / webcam / recorded clip
    -> timestamped latest-frame capture
    -> SCRFD + YOLO5Face on the SAME frame
    -> WBF boxes + validated source-owned five-point landmarks
    -> 112 x 112 similarity-aligned face crops
    -> ArcFace vectors | AdaFace vectors | MagFace raw magnitude
    -> BoT-SORT association using motion + ArcFace appearance
    -> isolated, bounded observation window for EACH track
    -> quality-weighted robust temporal template per identity encoder
    -> comparison with enrolled per-person templates
    -> fitted score fusion + open-set absolute/margin gates
    -> class-conditional conformal candidate set
    -> conservative identity state / abstention
    -> existing person_seen(...) builder -> schema validation
    -> Redpanda topic person.seen
```

Invariants:

1. Every crop, vector, landmark, score, and timestamp stays attached to its source frame and detection. Detection array order is not a track ID.
2. Track buffers never share observations. A tracker association error must not permanently attach one person's name to another.
3. ArcFace and AdaFace galleries remain separate. They are independently trained coordinate systems, even though both output 512 values.
4. No named event without recent usable observed face evidence and a passed rejection policy. Predicted boxes alone are not observations.
5. The pipeline cannot grow an unbounded frame queue. Stale inference is worse than dropping a frame.
6. Events contain no pixels, landmarks, embeddings, detector boxes, or private diagnostic fields.

## 5. Algorithms to implement

### 5.1 Capture and event time

Read the phone's MJPEG stream through OpenCV. Also support a local webcam and a video file for reproducible evaluation. Use a capture worker with one replaceable latest-frame slot and a processing loop; do not enqueue every camera frame. Close capture, windows, writers, and the producer on shutdown. A blocking network read needs a tested timeout/reconnect path, not just a stop flag that it never checks.

Attach a UTC receipt timestamp and a monotonic timestamp immediately after decode. Preserve the UTC timestamp through inference and publication; monotonic time governs durations, expiry, and reconnect backoff. MJPEG commonly lacks trustworthy synchronized capture timestamps: call this **Mac/host receipt time**, not camera exposure time. Ask Role 3 to account for independently measured phone/network delay. A hybrid logical clock does not synchronize physical clocks or recover missing capture timestamps.

Recorded clips use video presentation time; replay maps all related person/item recordings to one agreed UTC origin. Do not stamp an old frame with current wall time after inference. A reconnect clears old track evidence and allocates new service-level track IDs.

### 5.2 Detection ensemble and five-point alignment

Start with SCRFD at an initial 640 x 640 detector input. Later run YOLO5Face on the same sampled frame. Undo each detector's resize/letterbox before combining outputs. Apply each detector's own duplicate suppression, reject non-finite/invalid boxes, and clip coordinates to the image.

WBF clusters sufficiently overlapping face boxes. Its coordinate fusion has the form:

```text
b_fused = sum_j(weight_model[j] * score[j] * box[j])
          / sum_j(weight_model[j] * score[j])
```

Use the published implementation's complete scoring behavior, not just this simplified coordinate expression. Initial ensemble model weights are equal; initial WBF IoU is 0.55. Those are development starting points, not measured optimums. Convert to normalized `[0,1]` coordinates for the library and back afterward. Preserve valid single-detector faces and measure their false-positive cost; requiring both detectors to agree defeats the recall objective.

WBF does not fuse landmarks. Keep the five points from the highest-scoring valid source face in that box's cluster, preferring SCRFD on a tie. Preserve cluster/source association explicitly or conservatively rematch by IoU with one-to-one constraints. Never attach another nearby face's points. If landmark ownership is ambiguous, withhold that recognition observation.

Estimate a 2-D similarity transform into the checkpoint's 112 x 112 canonical face template using eyes, nose, and mouth corners. Check landmark order, geometry, finite transform, and image boundaries. Extreme profile detections with unreliable points can be tracked geometrically without contributing identity evidence. Do not stretch an arbitrary rectangular crop and call it aligned.

### 5.3 Separate embeddings and a real quality model

Run all encoders in evaluation/inference mode. For encoder `m`, normalize finite nonzero output `f_m` into `e_m = f_m / ||f_m||`. Invalid/zero vectors contribute no evidence and must not reach cosine calculations.

Use each model's exact channel order, normalization, and alignment reference. The original AdaFace implementation expects BGR, while InsightFace's recognition preprocessing handles RGB internally; passing the same preprocessed tensor to both is incorrect. The [official AdaFace inference code](https://github.com/mk-minchul/AdaFace/blob/master/inference.py) is the reference for that checkpoint. Test a fixed aligned image against the upstream implementation before device optimization.

MagFace quality is `r = ||f_mag||` **before L2 normalization from a MagFace-trained network**. Its [official quality instructions](https://github.com/IrvingMeng/MagFace#quality-assessment) explicitly use feature magnitude. Normalized ArcFace vectors have norm approximately one and cannot implement this quality method. AdaFace's own feature-norm proxy is another method; label it accurately if used in the early version.

Proposed system-level weighting rule, to fit on development data:

```text
q_mag = clip((r - r_low) / (r_high - r_low), 0, 1)
q = detector_confidence * q_mag * alignment_validity
```

Here `r_low`/`r_high` are frozen development-set quantiles with a checked positive denominator. `alignment_validity` is a binary geometry gate, not an invented probability. Reject unusably small, badly blurred, saturated, or invalidly aligned crops using development-selected gates before fusion. Store their reasons in diagnostics. Do not copy MagFace magnitude thresholds between checkpoints without measurement.

### 5.4 BoT-SORT and identity contamination control

Use its Kalman motion prediction, association, and camera-motion compensation, supplying face-specific ArcFace appearance vectors. This adapts a tracker studied on pedestrians to faces; published pedestrian tracking results are not proof of face performance. Tune on our face clips.

Pin a BoxMOT version compatible with Python 3.11 and inspect that version's public inputs/outputs. The documented tracker accepts appearance embeddings, but API versions differ. Disable automatic body-ReID loading. A six-column detection array and the index of its corresponding embedding must remain aligned, including low-confidence detections. Supply no fabricated unit vectors for invalid faces; use the library's supported geometry-only path for those observations.

Keep a per-track rolling window of at most 20 usable observations from the last two seconds, initially sampling identity evidence at no more than 5 Hz per track. Use elapsed time for service-level expiry; tracker “lost frames” settings count tracker updates and must be reconciled with actual sampling. Empty frames still advance tracker/expiry state. For variable frame gaps, use the pinned implementation's supported delta-time interface, or reset after a large gap rather than pretending updates arrived at fixed FPS.

Require at least three usable observations spanning at least 0.4 seconds before accepting a name. These are proposed initial settings. A large appearance discontinuity or contradictory high-quality identity evidence invalidates the accepted identity immediately and clears contaminated evidence. If the tracker exposes no safe public split operation, retire the service-level identity segment and start a fresh one; do not mutate tracker internals.

On evidence expiry, stream reconnect, appearance contradiction, or revocation of a previously accepted name, clear the whole identity buffer and retire its service-level segment ID. Reacceptance requires three new usable observations spanning 0.4 seconds after that boundary; retained pre-boundary observations never count. A short geometric prediction within the freshness limit may support association, but cannot itself refresh evidence or certify a returning face.

This is face tracking, not body ReID. Once the face disappears, stop publishing fresh evidence; a short internal prediction can support reacquisition only until the expiry limit. Do not claim recognition when a person turns their back for an entire interaction.

### 5.5 Robust quality-weighted temporal fusion

For each track and EACH encoder separately:

```text
u_m = sum_i(q_i * e_mi)
mu_m = u_m / ||u_m||
R_m = ||u_m|| / sum_i(q_i)
```

`R_m` is directional agreement in `[0,1]`, not a correctness probability. Guard empty windows, all-zero weights, and a near-zero resultant. This is a weighted hyperspherical mean; it is not a trained uncertainty network or a full probabilistic face embedding.

Before MagFace is added, the runnable temporal baseline uses `q_i = detector_confidence * alignment_validity` after the same basic crop-validity gates. Label that as detector-weighted fusion. The MagFace experiment replaces this weight with the section 5.3 formula; it does not retroactively turn the baseline into MagFace weighting.

To reduce contamination, recompute once after dropping angular outliers relative to the initial template using a development-fixed cosine cutoff. Do not repeatedly prune until a desired identity wins. A rejected high-quality contradiction triggers the identity reset rule instead of silently hiding the contradiction. Keep the surviving-evidence count and span checks after pruning.

### 5.6 Enrollment and per-person multi-pose templates

Enroll only people who explicitly participate. Assign stable IDs matching the team's chosen convention, initially `p_01` through `p_04`. Take roughly 10–20 accepted crops across front, left, and right views, preferably from more than one short capture. Reject enrollment frames containing zero or multiple faces and validate IDs before using them in file paths.

Build up to three normalized pose-bin templates per person per encoder. Use landmark geometry as a pose proxy; do not claim metric 3-D head pose from five points. A bin without enough evidence is absent. Score a person with the best cosine over available templates:

```text
s_m(k) = max_j dot(mu_m, gallery_m[k, j])
```

This is our inference-time gallery design, not “sub-center ArcFace training.” More templates can raise impostor match scores; calibrate with this exact gallery rule. Save arrays plus model/preprocessing hashes, person IDs, template counts, and a gallery version. Use non-pickle array storage and atomic replacement. Do not overwrite an existing identity's enrollment silently. Provide a deliberate local remove operation; removal invalidates its templates, cached track identity, and affected calibration.

Keep runtime biometric data under the service's `models/` directory, already excluded by the repository's `models/` ignore rule; verify with `git check-ignore`. Retain no raw enrollment images by default. Debug images/video require explicit opt-in and stay in ignored storage. Never log embeddings. Re-enrollment or model/preprocessing changes invalidate fitted artifacts; do not reuse incompatible calibration.

Dashboard registration is a teammate integration dependency. Provide a working local enrollment CLI first and document its inputs/outputs for Roles 3/4. Do not invent their HTTP routes or change their code.

### 5.7 Fitted score fusion and open-set gates

Never average ArcFace and AdaFace vectors directly. Fuse **scores for the same candidate identity** instead. Fit a small L2-regularized logistic regressor on development tracks using `[s_arc(k), s_ada(k)]`, with target “candidate k is the correct enrolled identity.” Include candidates for non-enrolled people as negatives. Use scikit-learn's implementation for fitting; store the fitted coefficients and use the direct sigmoid for inference.

```text
F_k = sigmoid(b + w_arc * s_arc(k) + w_ada * s_ada(k))
k_best = argmax_k F_k
margin = F_best - F_second
```

The regressor is a small score calibrator, not face-model fine-tuning. Its output is a fitted compatibility score; candidate sampling and unknown-person prevalence affect probability interpretation. Do not describe it as an established deployment posterior. Store training sampling policy and assess reliability on held-out data. With one enrolled identity, use a separately validated one-class threshold; do not invent a runner-up score.

Require absolute compatibility, runner-up margin, valid temporal evidence, and the conformal condition below. Select thresholds using the development set, including strangers, before inspecting the final test set. Conservative gates can abstain on many known people; report that cost. Before calibration exists, run the explicit baseline with a development-selected ArcFace cosine threshold and report it as the baseline, not the completed ensemble. Missing/incompatible target artifacts prevent target-mode named events.

Baseline naming uses `s_arc(best)` with separately development-selected cosine acceptance, rejection, and runner-up-margin thresholds. Its event confidence is `clip((s_arc(best) + 1) / 2, 0, 1)`, explicitly an uncalibrated similarity score. Before tracking exists, use a short bounded single-face window to enforce the minimum evidence requirement and reset it whenever no face or multiple faces are visible; allocate a new segment rather than guessing association. Phase 2 replaces this restriction with tested tracking. Phase 3 can run the additional networks in dry-run diagnostics while baseline publication continues; only phase 4 switches named publication to fitted ensemble scores. Report the active scoring policy in startup logs and to Role 3, without adding event fields.

### 5.8 Class-conditional split conformal candidate sets

Use frozen fusion scores. For calibration track `i` with known true identity `y_i`, let `a_i = 1 - F_yi`. For candidate `k`, compute:

```text
p_k = (1 + count_{i:y_i=k}(a_i >= 1 - F_k)) / (n_k + 1)
C = {k : p_k > alpha}
```

Use `alpha = 0.10` initially. Accept only when `C` is a singleton containing `k_best` AND the separate gates pass; empty or multiple-label sets abstain. A p-value is compatibility, not identity probability or event confidence. See the [conformal prediction tutorial](https://arxiv.org/abs/2107.07511).

Class-conditional coverage needs exchangeable calibration/test units within each known class and a fixed scoring rule. It does **not** establish rejection of unseen identities, accuracy among accepted singletons, or continuous-video guarantees after repeated decisions. Measure unknown false accepts separately. The extra gates may reduce final acceptance without preserving coverage.

Use one predetermined observation prefix per independent calibration encounter, following the same prefix/window policy as inference. Adjacent video frames are not independent calibration examples. At least nine calibration encounters per class are needed even to attain p-value 0.10; that is merely resolution, not strong evidence. If data are insufficient, report empirical rejection and omit the conformal guarantee. New gallery members or changed scoring require recalibration.

Concretely, require at least nine valid calibration encounters for **every** enrolled class before enabling the conformal target. Zero/missing-class data is a calibration error, not p-value one. If the requirement is unmet, do not silently bypass the singleton gate: keep the explicitly selected, development-validated calibrated-ensemble version without conformal, mark the conformal layer incomplete, and report only empirical rejection. A launch requesting the full conformal target fails clearly when its artifacts/data are missing. More data or a documented lower phase is the remedy; deleting the guarantee sentence alone does not fix an always-multiple candidate set.

### 5.9 Conservative state and emitted confidence

Maintain internal states `pending`, `known`, `unknown`, `ambiguous`, and `lost`. Only `known` carries a name. Start pending; accept after the evidence requirements and all gates pass. Failed gates clear the name; expired evidence becomes lost. Reacceptance follows the complete buffer-reset rule in section 5.4. Local states/reasons stay in diagnostics because the shared schema has no status field.

For a known ensemble event, use `confidence = F_best`, clearly documented as the fitted recognition compatibility score; the earlier baseline uses the explicitly defined rescaled cosine. Do not emit the conformal p-value, a detector score, or a made-up certainty.

Preserve the authoritative schema's `null = stranger` semantics. An `unknown` decision requires sufficient valid temporal evidence and `F_best < tau_reject`, with `tau_reject <= tau_accept` fixed on development strangers; when conformal is active, also require an empty candidate set. Emit `person_id=null, confidence=0.0` only for that operational open-set rejection, expressing zero support for an enrolled identity. Use the analogous cosine rejection threshold in the baseline. This remains an algorithmic classification, not proof of stranger status.

Other failures, including low quality, near-tied identities, multiple conformal candidates, and a failed margin with a plausible known candidate, are `ambiguous`; emit nothing. `pending` and `lost` also emit nothing. Do not repurpose null to mean every kind of abstention without a teammate-approved contract change. A previously published named observation cannot be retracted through this schema: Roles 1/3 must verify evidence-age limits and ambiguous/multiple-person joining before live alerts. Role 3 should treat absent/stale matches and null identity conservatively as `uncertain`; that integration is required and not implemented by this brief.

## 6. Preserve the exact event contract

Build every observation through existing `fridge_person.events.person_seen(...)`. Pass the evidence frame's preserved UTC `ts`; omitting it would stamp publication time. The example below is illustrative, not measured output:

```json
{
  "event_id": "c8cd6ec8-7168-4d83-8c6d-fb0888758eac",
  "topic": "person.seen",
  "track_id": 7,
  "person_id": "p_02",
  "ts": "2026-11-08T09:15:02.120Z",
  "confidence": 0.93
}
```

The schema has `additionalProperties: false`. No new fields, topics, state enums, or separate recognition API are required. Validate using the existing JSON Schema before publishing; the helper currently constructs a dict without validating arguments. Invalid internal output must be rejected visibly, not coerced into a named event.

Publish at first stable decision, decision change, and at most every 500 ms while a newly observed face supports the current decision. Track the evidence timestamp already published; never repeatedly publish the same old frame with a fresh timestamp. Require evidence age no greater than one second at dispatch. Role 3 must agree on a join window and stale-evidence limit; suggested heartbeat/age values are initial integration settings.

Use `confluent-kafka`, matching the shared fake publisher. Host-local default is `localhost:19092`, topic `person.seen`; key by `event_id` as the shared fake publisher does. Allocate an event once and preserve its ID/payload through transport retries. Do not call the builder again for a retry. Enable producer idempotence and handle delivery callbacks, polling, queue-full errors, and shutdown flush failure. This does not promise exactly-once application behavior across restarts.

Use a small bounded pending-event queue. A broker outage must not accumulate unbounded memory or block capture. When full, drop expired pending observations, record the loss, and report unhealthy publication; do not silently discard events or pretend delivery succeeded. Late delivered observations retain their original timestamps for Role 3's watermark policy. Video replay can write validated JSONL without a broker for deterministic tests.

Service-level `track_id` values must not collide on tracker resets/reconnects. Use a monotonically allocated local segment ID and persist its next value atomically across normal restarts; backend identity is `person_id`, never `track_id`. A process restart clears temporal evidence even if its counter persists.

## 7. Implementation structure and dependencies

Keep the existing `fridge-person = fridge_person:main` entry point. Turn `__init__.py:main` into a thin delegation to the CLI. Preserve `events.py` as the sole event constructor. A fitting module split is:

```text
services/person/
  HUMAN_RECOGNITION_PLAN.md
  pyproject.toml                 # service-local dependencies only
  src/fridge_person/
    __init__.py                 # existing entry point
    events.py                   # existing event contract owner
    main.py                     # CLI, capture lifecycle, orchestration
    vision.py                   # concrete detector/encoder integration + alignment
    recognition.py              # track windows, gallery matching, rejection state
    gallery.py                  # enrollment, versioned local persistence
    calibration.py              # fit/load score fusion + conformal artifacts
    publisher.py                # bounded delivery, validation, output modes
  tests/                        # existing contract tests plus focused new cases
  models/                       # ignored weights/gallery/calibration/local clips
```

This describes responsibilities, not a requirement to create empty modules. Combine small tightly related functions when clearer. No model-provider framework, plugin system, vector database, extra microservices, or custom training framework.

Add only dependencies needed for the phase being implemented: NumPy, OpenCV, InsightFace, the correct ONNX Runtime package for the host, and then PyTorch/torchvision as required by the chosen checkpoints; BoxMOT for tracking; `ensemble-boxes` for WBF; scikit-learn for calibration; `confluent-kafka` for transport; `jsonschema` as a runtime dependency once runtime validation uses it. Pin compatible versions in the service lockfile after a smoke run. Reuse transitive dependencies carefully instead of installing several incompatible OpenCV/ONNX variants.

Use the upstream inference code needed by a checkpoint with attribution/license; do not vendor an entire training repository or install its historical CUDA training environment into this service. Avoid unpinned remote executable loading. A normal launch must not unexpectedly download weights. Provide explicit model setup instructions with source URLs and fail with a useful missing-model message.

### Intended CLI acceptance interface

Codex should implement these commands; they do not exist yet. Paths are relative to `services/person/`:

```bash
uv run fridge-person enroll --person-id p_01 --source 0
uv run fridge-person run --source "$PERSON_CAMERA_URL" --broker localhost:19092
uv run fridge-person run --source models/clips/probe.mp4 --dry-run
uv run fridge-person calibrate --manifest models/data/development.csv --conformal-manifest models/data/conformal.csv
uv run fridge-person evaluate --manifest models/data/test.csv --output models/reports/metrics.json
uv run pytest
```

Treat `PERSON_CAMERA_URL` as local input, never log embedded credentials. Support numeric webcam index and URL/file source without guessing from a numeric-looking filename alone; document the parsing rule. Enrollment/removal/calibration/target-vs-baseline selection can use the smallest clear CLI needed; no dashboard implementation is included here.

## 8. Delivery phases and stop conditions

| Phase | Implement | Proof before continuing |
| --- | --- | --- |
| 0. Host/model feasibility | Identify actual host, pin compatible Python 3.11 packages, load SCRFD + ArcFace, test one image, record latency/memory | Finite normalized embeddings; documented provider; no fabricated benchmark |
| 1. Baseline end to end | Phone capture, aligned ArcFace, four-person enrollment, conservative cosine threshold, valid JSONL and Redpanda output | Known-person and stranger examples; schema tests pass; Role 3 consumes events |
| 2. Temporal identity | BoT-SORT with face embeddings, per-track buffers, robust weighted temporal fusion, expiry/reset | Crossing/occlusion/reconnect clips do not leak accepted identity across tracks |
| 3. Full neural ensemble | Add AdaFace, separate MagFace quality, YOLO5Face + WBF; ablate each layer | Output parity checks; measured error/latency tradeoffs; no vector-space averaging |
| 4. Statistical rejection | Fit score fusion on development; freeze; calibrate conformal sets on independent known encounters; evaluate unseen identities | Unknown acceptance and known abstention reported separately; no unsupported statistical guarantee |
| 5. Demo evidence | Overlay detector boxes, track ID, pose/quality, model scores, fused score, candidate set, rejection reason, timing | Real recorded scenes and actual ablation table; no unimplemented layers in pitch |

Finish the full five-network target if it meets the measured budget. If a model cannot run within the available hardware/time, preserve the last working phase and identify the exact omitted layer in the handoff and video. Do not quietly call an ArcFace-only result the full ensemble. The project proposes code freeze around 10:00 and submission at 13:00 on 2026-11-08; confirm the venue timezone with the team rather than inferring it from timestamp examples.

## 9. Data, tests, and evaluation

Keep enrollment, development, conformal calibration, and final test recordings disjoint by capture/encounter, not by individual frames. Development fits quality gates, fusion, and thresholds. Conformal calibration only ranks frozen known-identity scores. The final test set is touched after configuration is frozen. Reserve different stranger identities for development and final testing where possible. Four enrolled teammates alone cannot establish unknown-person rejection.

Use a Role 1 local manifest, for example `path,person_id,session_id,split,start_s,end_s`; empty `person_id` denotes an unregistered participant. Keep paths relative to the manifest or document one fixed base. Do not edit Role 4's existing `eval/labels.csv`, which labels whole item interactions and cannot express all person-track cases. Exchange results with Role 4 so person accuracy and full PUT/TAKE accuracy remain separate.

Record normal, side-view, dark/backlit, blur/motion, small-face, two-person crossing, short occlusion, face disappearance, stranger, and stream-disconnect cases. Retain consent and allow deletion. A print/phone replay can document the known lack of spoof protection, not serve as proof of liveness.

### Focused automated proof

- Existing positive and negative contract tests stay green. Add null identity, confidence bounds/non-finite values, forbidden extra fields, preserved `ts`, and reused event IDs on retries.
- Synthetic boxes exercise WBF coordinate conversion, single-detector faces, nearby distinct faces, and source-landmark ownership.
- Synthetic vectors exercise separate encoder spaces, zero vectors/weights, normalization, outlier handling, count/span requirements, expiry, and two-track isolation.
- Tracker integration exercises detection-to-embedding correspondence, variable frame gaps, reconnect/reset IDs, and high-quality identity contradiction.
- Tiny fixed score arrays exercise logistic artifact compatibility, conformal finite-sample ranking/ties, empty/multiple/singleton sets, one-person galleries, and insufficient calibration.
- Fake capture/producer and a controlled clock exercise stale-frame dropping, broker backpressure, callbacks/retries, failure visibility, and shutdown. No camera, GPU, broker, or network is needed for these unit tests.
- A separate opt-in smoke run with actual local weights proves shape/preprocessing parity, provider execution, phone capture, real broker consumption, and measured performance. Unit tests are not this hardware proof.

### Metrics and experiment design

Report numerator/denominator, not just a percentage:

| Metric | Definition |
| --- | --- |
| Known correct identification rate | Known encounters correctly named / all known encounters, including abstentions in the denominator |
| Precision of accepted names | Correct names / all emitted/encounter-level accepted names; report wrong-known and unknown false names separately |
| Unknown false-accept rate | Stranger encounters assigned any enrolled identity / all stranger encounters |
| Known abstention rate | Known encounters left unassigned / all known encounters |
| Conformal diagnostics | Pre-extra-gate coverage on known encounters, empty/singleton/multiple set rates, sample count per identity |
| Tracking stability | Identity switches and false identity carryovers per annotated sequence; IDF1 only if frame-level track ground truth exists |
| Live behavior | Time to first correct stable identity, p50/p95 host-receipt-to-dispatch latency, throughput, dropped/stale frames, peak memory |

For video, “accepted anywhere during the encounter” catches brief false identifications; also score one predetermined decision prefix per encounter for conformal analysis. Do not score only the clean last frame. Report all output events when measuring transient false names.

Proposed demo targets, not measured results: at least 90% correct known-encounter identification, no stranger false accepts in the collected test encounters, median stable identity within one second, and p95 receipt-to-dispatch latency within one second under shared host load. Zero observed errors in a small sample does not establish zero population error. If the data/budget cannot support those targets, report the measured tradeoff and abstain more conservatively.

Use matched ablations on identical held-out clips: ArcFace alone; +tracking/temporal fusion; +AdaFace; +MagFace weighting; +detector ensemble; +calibrated rejection; +conformal abstention. Freeze each variant on development/calibration data, not the test set. Refit fusion/recalibrate when its input models or gallery change. Include simple averaging versus quality-weighted robust averaging. Record actual changes, including regressions and slower variants; leave results cells blank until measured.

## 10. What we deliberately do not implement

- Body ReID, gait recognition, cross-camera identity association, cloud inference, model training from scratch, or item/hand recognition.
- Face images/embeddings on Redpanda, dashboard, MCP, or third-party face APIs.
- Qdrant, Ray Serve, Kubernetes-per-model, or another event schema for four enrolled people.
- Depth Anything + rPPG liveness in the primary plan. Monocular estimated depth is not a validated photo-spoof detector; replayed video may contain pulse-like signals. The project leaves liveness undecided. Treat spoofing as an explicit limitation until a dedicated PAD method and appropriate attack evaluation are agreed.

Recognition here is a consenting-team hackathon prototype, not access control or proof of identity. It must not infer ethnicity, health, emotion, intent, or other sensitive attributes.

## 11. Research ceiling: more complicated algorithms considered

These are real research alternatives, not hidden commitments or an implementation shopping list. Do not build them before the selected target and backup demo are complete.

### KP-RPE Vision Transformer

[KeyPoint Relative Position Encoding](https://arxiv.org/abs/2403.14852) injects facial landmark structure into attention. The authors' [CVLface pretrained-model table](https://github.com/mk-minchul/CVLface/blob/main/cvlface/pretrained_models/README.md) links `minchul/cvlface_adaface_vit_base_kprpe_webface4m`. This is a stronger research candidate when alignment errors dominate, rather than simply adding a larger CNN.

If the full system is stable and an NVIDIA host has measured headroom, compare it as a **replacement** for the AdaFace IR-50 branch. Match the published landmark/crop convention, enroll a new compatible gallery, and refit fusion/calibration. It cannot reuse the IR-50 embeddings. Mac execution and memory remain unverified. Avoid adding a third identity encoder merely for the model count.

### CAFace learned cluster-and-aggregate video fusion

[CAFace](https://arxiv.org/abs/2210.10864) uses learned clustering and aggregation to summarize video features. Its [official repository](https://github.com/mk-minchul/caface) supplies a pretrained AdaFace/WebFace4M system and precomputed class centers. It is a compelling advanced demonstration if long, low-quality probe sequences are the actual bottleneck.

Use the matching backbone and all checkpoint-required intermediate features/centers; it is not a plug-in weighted average for arbitrary ArcFace or AdaFace IR-50 vectors. Benchmark a self-contained upstream inference example before considering integration. Its training data, camera regime, CUDA assumptions, and sequence latency need verification. A later adoption replaces the compatible branch's aggregation; do not stack a second unrelated aggregator onto it.

### Probabilistic Face Embeddings (PFE)

[PFE](https://arxiv.org/abs/1904.09658) represents image embeddings as distributions rather than single points, enabling uncertainty-sensitive matching and fusion. It is mathematically richer than our directional-average diagnostic. It needs an appropriately trained uncertainty estimator; inventing variance as `1 / MagFace_quality` does not reproduce the paper. With no verified matching uncertainty checkpoint in this repository, omit it from the committed target.

## 12. Paste this instruction into the next Codex session

> Implement Role 1 from `services/person/HUMAN_RECOGNITION_PLAN.md`. First read the repository README, current overview, existing person service, and person event schema. Work only inside `services/person/`. Preserve the existing entry point, `person_seen` constructor, and exact event contract. Inspect the actual available hardware; use NVIDIA/CUDA if already available, otherwise the documented Mac path. Do not purchase hardware, introduce cloud services, change shared files, or assume missing model weights/APIs exist. Start with the real camera-to-event ArcFace baseline, then implement the selected five-network ensemble, per-track robust temporal fusion, measured open-set gates, and correctly scoped conformal abstention in the documented phases. Keep a runnable baseline throughout. Fit and evaluate on disjoint encounter-level recordings. Run focused unit/contract tests and separate real-weight/device/broker smoke checks. Report actual metrics, incomplete layers, and integration dependencies honestly. Do not implement the section 11 research extensions without a further request. Stop when the selected target's acceptance checks pass or report a concrete hardware/data blocker with the last working phase preserved.

Suggested judges' explanation once implemented: “Two detectors find the face, two independent recognition models identify it, a fifth model measures frame quality, motion tracking connects observations, temporal geometry suppresses noisy frames, and calibrated rejection lets the system refuse to guess.” Show only layers that actually run and accompany the explanation with measured ablations.
