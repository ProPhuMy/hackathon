# Person recognition: ArcFace baseline

The CLI supports model smoke checks, enrollment/removal, single-face baseline
recognition, empirical threshold calibration, and offline encounter evaluation. The event constructor and
shared contract are unchanged.

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
uv run fridge-person check-models \
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
uv run fridge-person enroll --person-id p_01 --session-id enroll-p01-01 --source 0
uv run fridge-person remove --person-id p_01
uv run fridge-person run --source 0 --policy models/baseline-policy.json --dry-run
uv run fridge-person run --source 0 --policy models/baseline-policy.json --broker localhost:19092
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
uv run fridge-person calibrate --manifest models/development.csv --output models/baseline-policy.json
uv run fridge-person evaluate --manifest models/test.csv --policy models/baseline-policy.json --output models/metrics.json
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
.venv/bin/fridge-person check-camera --source 0 --duration 15
```

The command reports aggregate decoded/usable/stale-frame counts, reconnects and
inference timing. It never names or enrolls participants and does not retain
frames or vectors. Keep optional redirected reports under ignored `models/`.
On 2026-11-07, the CLI decoded 297 frames in 16.03 seconds (including startup and
shutdown), with 78 usable single-face frames, no stale frames or reconnects,
median inference 36.82 ms and p95 72.04 ms. These measure this scene and CPU host
only, not recognition accuracy, camera exposure-to-event latency, or performance
with the item pipeline running. All 43 automated tests passed.
