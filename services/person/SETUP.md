# Person recognition: ArcFace baseline

The CLI supports model smoke checks, enrollment/removal, single-face baseline
recognition, empirical threshold calibration, and offline encounter evaluation. The event constructor and
shared contract are unchanged.

## Running the service and code layout

Run every command from this folder (`services/person/`); default paths such as
`models/det_10g.onnx` and the `../../contracts/` schema are relative to it.

```bash
uv run python -m src --help          # the console script `uv run fridge-person` is equivalent
uv run python -m src <command> --help
uv run pytest -q                     # no model weights or camera needed
```

```text
src/
  __main__.py          python -m src entry
  events.py            sole person.seen event constructor (contracts/person.seen.schema.json)
  capture.py           camera/file capture in a killable process, reconnect boundaries
  storage.py           atomic JSON writes, SHA-256 file hashes, persistent segment counter
  cli/                 argument parser (__init__.py) and one module per command:
    run.py               enroll / run / remove (capture loop, policy gating, JSONL/Kafka dispatch)
    calibrate.py         calibrate / evaluate (ArcFace baseline from encounter manifests)
    scores.py            calibrate-scores / evaluate-scores (offline ensemble score files)
    check_models.py, check_camera.py, check_encoders.py, check_detectors.py   smoke checks
  vision/              face models: arcface.py (SCRFD + ArcFace), yolo5face.py, encoders.py and
                       backbones.py (AdaFace/MagFace), detection.py (WBF fusion), boxes.py (IoU/NMS/letterbox)
  identity/            recognition.py (evidence + Baseline), gallery.py, ensemble.py (fusion, conformal,
                       EnsembleEngine), tracking.py (BoT-SORT-style tracker)
  evaluation/          dataset.py (manifests, offline observations), calibration.py (baseline threshold search)
tests/                 mirrors src/; shared fakes and the schema path live in tests/conftest.py
```

Verified development host: Apple M5 MacBook Air, 24 GB RAM, macOS 27.0.1.
Installed uv and Python 3.11.18. Phase-0 runtime versions are pinned in
pyproject.toml and uv.lock; run `uv sync` from this folder to reproduce the
environment. CPU inference passed with the official buffalo_l SCRFD and ArcFace
models and one local face image. No NVIDIA device is available.

Measured 2026-11-07: five warm detection/alignment/embedding runs after one
warm-up, p50 59.4 ms and p95 61.6 ms. This single-image smoke check establishes
neither recognition accuracy nor live camera throughput. ONNX Runtime also
reports CoreML availability; CoreML execution/parity has not been tested.
Upstream alignment emits a scikit-image deprecation warning; inference succeeds.

Obtain the official buffalo_l pack from the InsightFace model zoo:
https://github.com/deepinsight/insightface/tree/master/model_zoo
Check its pretrained-weight licensing and record the source URL and upstream
revision. Place the SCRFD detector (`det_10g.onnx`) and ArcFace recognizer
(`w600k_r50.onnx`) in ignored `models/`. The CLI never downloads weights.
Use a local image of exactly one consenting participant:

```bash
uv run python -m src check-models \
  --detector models/det_10g.onnx \
  --recognizer models/w600k_r50.onnx \
  --image models/face.jpg
```

The check runs CPU inference, validates a finite normalized 512-D vector, and
prints model hashes/file sizes and five warm latency samples after one warm-up.
It emits no face vectors or pixels. This is a smoke check, not an accuracy,
provider-parity, memory, or production latency benchmark.

Next gate: consenting enrollment/probe clips and a reachable camera for phase 1. Backend broker consumption and stale/multiple
person join policy still require coordination with Role 3. Follow the phased
acceptance criteria in HUMAN_RECOGNITION_PLAN.md before adding ensemble layers.

## Single-face baseline CLI

Implemented: bounded capture in a separate process, single-face enrollment,
atomic model-bound gallery, deliberate removal, temporal evidence, persisted
segment IDs, policy-gated JSONL and Kafka dispatch. Baseline only; this is not
the five-network target. Run commands from this service folder:

```bash
uv run python -m src enroll --person-id p_01 --session-id enroll-p01-01 --source 0
uv run python -m src remove --person-id p_01
uv run python -m src run --source 0 --policy models/baseline-policy.json --dry-run
uv run python -m src run --source 0 --policy models/baseline-policy.json --broker localhost:19092
```

Bare decimal sources are webcams; prefix numeric file names with `./`.
Recorded clips additionally require `--replay-origin 2026-11-08T09:00:00Z`.
Live events use host receipt time; recorded events preserve presentation time.
Do not feed historical replay events into live alerts. Enrollment collects 20
usable observations, stores one normalized averaged template,
and retains no images. Live capture retries up to three times per invocation
with 1/2/4-second backoff, a new queue, fresh evidence, and a new segment ID.
Recorded-file failures exit without reconnecting. Network capture has OpenCV
timeouts and a killable process; exhausted retries exit with an error.

## Calibrate and evaluate on independent recordings

Keep local manifests and recordings inside ignored `models/`. A CSV row is one
independent encounter (not an individual video frame):

```csv
path,person_id,session_id,split,start_s,end_s
clips/p01-dev.avi,p_01,p01-dev-01,development,0,5
clips/stranger-dev.avi,,stranger-dev-01,development,0,5
```

Paths resolve relative to the manifest. Empty person_id labels a stranger; a
nonempty label must already be enrolled. Development must cover every enrolled
person plus strangers. Use separate recordings and unique encounter/session IDs
for enrollment, development and test; different frames of one encounter are not
independent. Do not relabel one continuous capture as different sessions.
The tool rejects overlapping paths, file hashes and session IDs across supplied
splits and recorded enrollment provenance. It cannot detect copied/re-encoded
encounters with dishonest metadata. Live enrollment records the supplied session
ID; include the same ID for all recordings belonging to that encounter.

```bash
uv run python -m src calibrate --manifest models/development.csv --output models/baseline-policy.json
uv run python -m src evaluate --manifest models/test.csv --policy models/baseline-policy.json --output models/metrics.json
```

Test rows use `split=test`. Calibration searches a fixed coarse threshold grid
using only development encounters. It requires zero false names on that data
and at least one correctly named known encounter, then maximizes correct known
encounters and operational stranger rejection. Failure to find a useful policy
is an explicit error. This is empirical threshold selection, **not** learned
ensemble fusion or conformal calibration, and zero observed false names does not
guarantee zero deployment error. Test evaluation never retunes the policy.
Reports include known/unknown totals, correct known encounters, wrong-known and
unknown false accepts, abstentions, and accepted-observation precision counts.
A wrong name anywhere in a scored encounter counts as a failure. Offline
recording evaluation does not benchmark live camera/broker latency.

Both commands use the same temporal/reset engine as live inference. Every
enrollment change creates a new gallery revision and invalidates policies.
Active runs detect gallery changes and exit; restart after recalibration.
Do not hand-author thresholds as a substitute for collecting development data.

Remaining acceptance blockers: four-person enrollment, development/test/stranger
recordings, phone camera connectivity, real broker consumption, and agreed
backend stale/multiple-person handling. The single face photo only proves model
inference, not these acceptance conditions. BoT-SORT, AdaFace, MagFace, YOLO5Face,
pose-bin templates, fitted score fusion, conformal calibration, annotated metrics,
and demo overlays remain unimplemented. Do not claim ensemble accuracy or spoof
protection. Kafka uses bounded synchronous dispatch with idempotent producer
retries; it stops visibly on delivery failure rather than accumulating events.

## Verification handoff (2026-11-07)

- 33 automated tests passed on Python 3.11.18. These cover temporal decisions,
  replay timing/shutdown, safe enrollment, gallery revisions and stable hashes,
  policy invalidation, schema bounds, failed Kafka callbacks, manifest separation,
  and synthetic-video calibration/evaluation through the concrete OpenCV decoder.
- Real SCRFD/ArcFace inference passed again with the supplied local photo.
- Source compilation and `git diff --check` passed.
- No real enrollment or known/stranger encounter accuracy is claimed. Camera
  source and participant identity/consent remain needed for local enrollment.
- Docker is not installed on this host; real Redpanda publication/consumption
  has not been tested. Use an already reachable broker or coordinate local
  infrastructure setup with its owner.


## Follow-up verification

38 tests pass, including disconnect/reconnect boundaries, bounded retries,
model-independent enrollment removal, and duplicate-recording rejection within
a manifest. Webcam 0 was attempted without saving images; macOS denied camera
access. Live capture could not be verified. Grant camera access to the host app
in System Settings > Privacy & Security > Camera, or provide a reachable phone
MJPEG URL. No camera permission settings were changed by the service.


## Live camera/model check

Run from a camera-authorized Terminal (the agent's subprocess may have separate
macOS camera permissions):

```bash
.venv/bin/python -m src check-camera --source 0 --duration 15
```

The command reports aggregate decoded/usable/stale-frame counts, reconnects and
inference timing. It never names or enrolls participants and does not retain
frames or vectors. Keep optional redirected reports under ignored `models/`.
On 2026-11-07, the CLI decoded 297 frames in 16.03 seconds (including startup and
shutdown), with 78 usable single-face frames, no stale frames or reconnects,
median inference 36.82 ms and p95 72.04 ms. These measure this scene and CPU host
only, not recognition accuracy, camera exposure-to-event latency, or performance
with the item pipeline running. All 43 automated tests passed.

## Enrollment and data-collection outcome

After explicit participant consent, local webcam enrollment completed for one
participant. The gallery's normalized 512-D template and private file permissions
were verified; the gallery remains ignored by Git. No enrollment images were
retained. This supersedes the earlier note that no real enrollment had run.

With explicit permission to retain evaluation video, two development-capture
attempts were made. The first was rejected when multiple faces were detected;
its partial clip was discarded. The second timed out waiting for an empty-view
boundary followed by a single-person return. No completed development clip was
retained, and no recognition threshold or accuracy result was fabricated.

Next physical test: keep the camera view empty for two seconds, then let only
the enrolled participant enter and remain visible for eight seconds. Independent
development and test encounters plus a different consenting stranger are still
needed. Camera processes have exited after these attempts.

## Improved-framing development encounter

A subsequent camera check found a fully visible face in 60/60 single-face
frames, with median width 354.6 pixels, compared with 41–59 pixels in the earlier
poorly framed clip. The existing enrollment was retained: clean live samples
had cosine similarity 0.770–0.828 to it. Repeated-frame inference was deterministic
and matched InsightFace's own `get` path (cosine >0.99999); the weak earlier
results did not justify changing recognition thresholds.

After the participant moved locations, a new eight-second development encounter
was captured following a countdown. All 37 decoded observations were usable;
similarity to the enrollment ranged 0.780–0.828 (median 0.806). These are similarity
diagnostics, not recognition accuracy or calibrated acceptance probabilities.
The local development manifest uses this clip and excludes the poor-framing
clip. Raw videos and per-frame host receipt timestamps remain under ignored
`models/data/`; AVI presentation is nominally 5 FPS, not original camera PTS.

43 automated tests passed again. Calibration still requires independent stranger
encounters, and final accuracy requires untouched test encounters. No thresholds
were fitted from this one known-person clip. Capture processes have exited.

## Initial baseline calibration and held-out attempt

A consenting unenrolled participant's development clip was collected (40 decoded
frames). The frozen baseline was fitted on one known and one stranger encounter:
1/1 known encounter correctly named, 1/1 stranger encounter operationally rejected,
with zero observed false names. These two development encounters cannot establish
deployment accuracy or unknown-person error rates.

Concrete CLI replay produced 12 schema-valid named events for the known clip and
one schema-valid null-identity event for the stranger clip. Original replay UTC
timestamps were preserved; concurrently running replays had no segment/event ID
collisions. Runtime policy and biometric clips remain ignored local artifacts.

A subsequent clip labelled as a known-person held-out test contained 41 usable
observations but emitted no accepted names. Its raw cosine similarities were
0.089–0.222, substantially below the clean known development encounter. Participant
identity for that clip needs user confirmation; preserve its supplied label and
provisional abstention result until confirmed. Do not lower thresholds or relabel
it to manufacture a passing test. The stranger held-out capture was rejected for
multiple detected faces and its partial clip was discarded. No complete held-out
known/stranger accuracy result is available. All camera processes have exited.

## Offline ensemble tools (no additional recording required)

The existing ArcFace `run`, `calibrate`, and `evaluate` commands are unchanged.
New score-only commands implement the selected ensemble's statistical layer:

```bash
uv run python -m src calibrate-scores --development models/scores/development.json --conformal models/scores/conformal.json --output models/ensemble-policy.json
uv run python -m src evaluate-scores --scores models/scores/test.json --policy models/ensemble-policy.json --output models/ensemble-metrics.json
```

Each input JSON has `binding`, `prefix_s`, and `encounters`. `binding` is a 64-digit
lowercase SHA-256 fingerprint of the producer's exact model/preprocessing/gallery
configuration, identical across the three splits. The tool checks equality; it
does not load or attest to the models that produced scores. `prefix_s` must be
1.0: one predetermined one-second observation prefix per independent encounter,
using the same usable-observation and temporal gates in every split.

Each encounter contains:

- `session_id`: unique independent encounter ID.
- `source_sha256`: original recording file hash, unique within and across splits.
- `person_id`: an enrolled ID, or null for an unregistered participant.
- `arcface` and `adaface`: separate dictionaries mapping every enrolled ID to
  that encoder's finite cosine score in [-1,1]. Both must have identical keys.

Development must include every enrolled identity and strangers. L2 logistic
regression fits candidate-level fusion, with every enrolled candidate included
for every encounter. Absolute acceptance/rejection and runner-up gates are fitted
on development before reading conformal scores. One-person galleries use a
separately development-fitted absolute threshold and no invented runner-up.
Conformal input uses known identities only and at least nine independently
recorded encounters for EVERY enrolled class. Missing classes/counts fail clearly.
Candidate p-values use the finite-sample greater-or-equal ranking and strict
`p > 0.10` membership. Only an accepted singleton names a person; multiple/empty
sets abstain unless low support and an empty set justify operational stranger
rejection. Confidence is the logistic compatibility score, never a p-value.

Tests use synthetic score arrays. This is not proof that real neural scores are
calibrated, encounters are exchangeable, unknown identities are rejected, or
continuous-video decisions have conformal coverage. The tool cannot establish
physical recording independence from metadata. Evaluation reports raw counts
and denominators, including known coverage BEFORE extra rejection gates. Do not
create live policies from synthetic scores. The new artifact is intentionally
separate from the runnable ArcFace baseline policy.

`fuse_faces` (`src/vision/detection.py`) also implements published Weighted Boxes Fusion for SCRFD
and YOLO5Face boxes. It preserves single-detector faces, clips coordinates, keeps
five-point landmarks from one valid source (SCRFD wins score ties), and withholds
landmarks if source ownership is ambiguous. Invalid landmarks do not prevent
geometry-only output. This utility is tested with synthetic boxes; the second
neural detector is not yet integrated. AdaFace, MagFace, YOLO5Face and BoT-SORT
model/runtime integration remains incomplete; no full ensemble run is claimed.

Offline-layer verification: 65 automated tests passed, including statistical
ranking/ties, class-count failures, independent split checks, malformed/truncated
policy provenance, artifact round-trips, source-landmark ownership, and all prior
baseline checks. An independent read-only code review found an artifact-validation
gap; its reproduced failures were fixed and the fix re-reviewed. Existing-clip
baseline replay still produced 12 schema-valid named observations without opening
a camera. Source compilation and source-distribution/wheel builds passed. No new
camera sessions were used for this work. Runtime neural ensemble integration and
real-world accuracy remain unverified.

## Real AdaFace and MagFace encoder components

`check-encoders` loads local official AdaFace IR-50 MS1MV2 and MagFace iResNet50
checkpoints on CPU, using the same validated SCRFD five-point crop as ArcFace:

```bash
uv run python -m src check-encoders --image models/face.jpg
```

Explicit checkpoint overrides are `--adaface` and `--magface`. Missing or
incompatible weights fail clearly; launches never download them. Official sources:

- AdaFace: https://drive.google.com/file/d/1eUaSHG4pGlIZK7hBkqjyp2fc2epKoBvI/view
  Local name `models/adaface_ir50_ms1mv2.ckpt`, SHA-256
  `234da6ce931f821e0a8e920063dc2091d8122ea46285c159d2f25d3f762fecb3`.
- MagFace: https://drive.google.com/file/d/1QPNOviu_A8YDk9Rxe8hgMIXvDKzh6JMG/view
  Local name `models/magface_iresnet50.pth`, SHA-256
  `4e0611e0267a157bd9f6c4d034b424271515a8cac49e5f3cb98d3daf558403e7`.

Code uses inference-only adaptations with pinned upstream attribution/licenses.
The AdaFace legacy Lightning callback metadata maps to an inert placeholder;
weights-only loading remains enabled. Arbitrary pickle globals, partial weights,
and incompatible state dictionaries are rejected. No training framework is
installed. License files/notices are included in package metadata; code licensing
does not establish pretrained-weight/dataset eligibility for later reuse.

AdaFace uses aligned BGR pixels scaled to [-1,1], and returns a normalized 512-D
identity vector. The selected MagFace official `inference/gen_feat.py` uses BGR
ToTensor [0,1] with no mean subtraction; its RAW output magnitude supplies quality.
Do not reuse either preprocessing tensor for ArcFace, which handles its own RGB
conversion. Do not mix ArcFace and AdaFace vector spaces. `quality_weight` implements
the detector-confidence times clipped MagFace-quantile weighting rule; its low/high
quantiles must be fitted on development data. No quality quantiles are fabricated.

Real checkpoint smoke test on the existing local image: normalized 512-D AdaFace
output and MagFace raw norm 29.5905. Same-crop CPU outputs matched pinned official
networks: max AdaFace element error 6.26e-9, max MagFace element error zero. The
canonical five-point reference agrees within 3.82e-6 pixels; this is not a claim
that different detectors produce identical crops. Encoder-only warm timing over
five samples after warm-up: p50 39.67 ms, p95 47.13 ms. Peak process RSS (including
model loading and existing ONNX models) was 1,801,879,552 bytes. Checkpoint files are
700,286,703 and 393,032,658 bytes; parameter counts are 43,585,600 and 43,590,848.
These single-image measurements are not full-pipeline throughput or accuracy.

The existing baseline's `single_face` result, model signature, gallery and policy
are preserved. The encoder diagnostic prints aggregate metadata/norms/timing, never
images or embedding arrays. Local model origins, hashes and preprocessing are
recorded in ignored `models/encoder-manifest.json`. No new recordings were used.
The full five-network runtime still needs YOLO5Face, BoT-SORT, separate AdaFace
gallery enrollment, temporal integration, quality calibration, and compatible
ensemble score artifacts before it can publish named ensemble events.

## Offline dual-detector diagnostic CLI (SCRFD + YOLO5Face + WBF)

`check-detectors` runs SCRFD and YOLO5Face on the same local image, fuses their candidate
boxes using `fuse_faces` (`src/vision/detection.py`), and reports aggregate detection counts, source
attributions, and timing diagnostics without printing or storing pixels, landmarks, or
embeddings:

```bash
uv run python -m src check-detectors \
  --image models/face.jpg \
  --scrfd models/det_10g.onnx \
  --yolo5face models/yolov5s-face.onnx
```

Arguments:
- `--image`: local face image file (required).
- `--scrfd` (or `--detector`): local SCRFD ONNX checkpoint (default `models/det_10g.onnx`).
- `--yolo5face`: local YOLO5Face ONNX checkpoint (default `models/yolov5s-face.onnx`).

### YOLO5Face export specification and verified recipe

Upstream repository: `https://github.com/deepcam-cn/yolov5-face`, pinned commit
`152c688d551aefb973b7b589fb0691c93dab3564` (GPL-3.0).

Export command:
```bash
python export.py --weights weights/yolov5s-face.pt --img_size 640 --batch_size 1
```

Supported ONNX graph layout:
- Requires `model.model[-1].export_cat = True` (as set by official `export.py`).
- Input: exactly 1 float32 NCHW tensor `(batch, 3, height, width)`, default `(1, 3, 640, 640)` float32 in `[0.0, 1.0]`. Spatial dimensions must be fixed positive integers (multiples of 32); dynamic or partially dynamic spatial dimensions are rejected because the pinned upstream exporter only makes batch dynamic.
- Output: exactly 1 float32 rank-3 decoded tensor `(batch, num_candidates, 16)`. The 16 channels per candidate are:
  - `[0:2]`: box center coordinates `(cx, cy)` in letterbox pixels.
  - `[2:4]`: box dimensions `(w, h)` in letterbox pixels.
  - `[4]`: objectness confidence (sigmoid applied).
  - `[5:15]`: 5 facial landmarks `(x1, y1), (x2, y2), (x3, y3), (x4, y4), (x5, y5)`
    in letterbox coordinates, corresponding to left eye, right eye, nose, left mouth,
    and right mouth.
  - `[15]`: face class probability (sigmoid applied, `nc=1`).
- Incompatible ONNX layouts (e.g. generic Ultralytics 6-channel or 85-channel outputs)
  are rejected helpfully with an explicit error.
- Preprocessing recipe: input BGR uint8 is resized with aspect-ratio letterboxing to
  `(640, 640)` with padding color `(114, 114, 114)`. The canvas is converted from BGR
  to RGB following the verified official training/dataset loader (`utils/datasets.py`),
  noting that `detect_face.py` contained an extraneous BGR2RGB flip on already RGB data.
  Values are normalized to `[0.0, 1.0]` by dividing by 255.0.
- Postprocessing: candidate confidence is `conf = obj_conf * cls_conf`. Bounding boxes
  and five landmarks are inverse-projected from letterbox coordinates to original image
  space, clipped to original dimensions, and filtered by greedy IoU NMS (default 0.5)
  and confidence threshold (default 0.3).
- Weighted Boxes Fusion: `fuse_faces` (`src/vision/detection.py`) blends overlapping boxes (`iou_thr=0.55`)
  with equal detector weights, while conservatively preserving source-owned landmarks from
  the highest-scoring detection (SCRFD preferred on ties). Single-detector faces survive.

### Limitations and incomplete checks

- No official pre-exported YOLO5Face ONNX artifact was committed to this repository.
  Launches never download weights. Explicit local model files missing or incompatible fail
  visibly.
- Testing is performed using comprehensive synthetic model outputs and session doubles
  exercising letterbox round-trips (including non-square inputs), empty detections, NMS,
  confidence math, landmark-box pairing, invalid layouts, and WBF fusion.
- No real-weight smoke test is claimed for YOLO5Face until a verified exported artifact is
  provided locally.
- Five-network components are implemented and unit-tested, but **not wired into `run`**. The live `run` command uses the SCRFD + ArcFace baseline (`Vision.single_face`, `models/baseline-policy.json`); do not present its output as the full ensemble. Components available for integration:
  - `DualGallery` ensures strictly separate template stores and independent coordinate spaces for ArcFace and AdaFace without vector-space averaging.
  - `FaceTracker` and `FaceTrack` implement BoT-SORT-style motion and appearance tracking using Kalman filters, IoU distance, and ArcFace appearance association, enforcing appearance continuity (rejecting cosine < 0.3) and per-track temporal evidence windows.
  - MagFace raw norm quantiles provide quality weighting for robust spherical temporal aggregation with angular outlier rejection.
  - `src/cli/run.py` has an ensemble branch for conformal policies. Each aligned face crop is encoded by both ArcFace and AdaFace (`--adaface`/`--magface` checkpoints), and each gallery is scored only with its own encoder's vector. It requires a separate AdaFace gallery (`--ada-gallery`, default `gallery_adaface.json` next to `--gallery`) whose `model` field equals the full `FaceEncoders` signature (AdaFace hash, MagFace hash and preprocessing tag; no command enrolls such a gallery yet), and the policy must bind it with `ada_gallery` (gallery fingerprint) and `ada_model` (that signature) next to `gallery`/`model`; its identities must match both galleries. Evidence is averaged per encoder space and the 0.3 continuity gate is checked in each space, so one encoder seeing a different face restarts the evidence. MagFace is loaded (it is part of the signature) but its quality norm is not used for weighting yet. A `calibrate-scores` policy still lacks these binding keys, so the branch is only reachable with a policy completed by hand.
