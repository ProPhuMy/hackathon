# Person recognition and tracking: research and recommended stack

Researched 11/07/2026 for Role 1 (Viet). Goal: the most advanced techniques that still run in real time on one NVIDIA GPU, so the demo can show **both accuracy and latency**.

Nothing here has been run on our hardware yet. Numbers marked *est* are scaled from other GPUs; benchmark first (see [First hour](#first-hour-on-the-gpu-server)).

## The one structural change: track bodies, attach faces

The current plan tracks faces. When someone turns their back to open the fridge, the face disappears, the track dies and the identity is lost exactly when we need it.

Instead: detect **people** (YOLO), track the **body box** with BoT-SORT, detect faces **inside** each body box, and accumulate identity on the body track. The identity learned while the person walked up survives the back-turned period. This covers most of what body re-ID would give, for free.

Measure: share of back-turned frames that still carry the right `person_id`, face-track vs body-track.

## Pipeline

```
phone MJPEG ──► latest-frame slot ──► GPU decode/resize
                                         │
                       YOLO person (TRT) ─┤ every frame
                    BoT-SORT + CMC ───────┤ every frame
       face detect inside body boxes ─────┤ every frame (SCRFD ⊕ YOLO-face, WBF)
                                         │
             track identity confident? ──┤ no → recognition ensemble on batched crops
                                         │       (AdaFace + LVFace, quality, liveness)
                                         │ yes → re-check every N frames only
                                         ▼
          SPRT commit → conformal stranger test → publish person.seen
```

Heavy models run only on tracks that are not yet identified. Per-frame cost stays roughly flat no matter how many layers we add: complex where it matters, cheap everywhere else.

## Layers

Each layer replaces a simpler approach, fixes one flaw, and is measured on/off.

| Layer | Baseline | Advanced | Flaw fixed | Measure |
|---|---|---|---|---|
| Tracking | ByteTrack | **BoT-SORT with camera motion compensation** (`boxmot`, `use_cmc: true`, `cmc_method: sof`, downscale 2) | ID lost when the phone shakes or someone is occluded | ID switches / fragments on a labelled shaky clip |
| Face detection | SCRFD-10G | **SCRFD-10G_KPS + YOLO-face, boxes fused with Weighted Boxes Fusion**; landmarks from SCRFD | Missed profile and small faces | Face recall, WBF on vs off |
| Recognition | ArcFace R50 (buffalo_l) | **AdaFace IR101 (CNN) + LVFace-B (ViT, ICCV 2025)**, per-model Platt/isotonic calibration then fusion | Two ResNet + margin-loss models make the same mistakes; CNN + ViT disagree usefully | Track-level top-1 accuracy |
| Frame quality | none | **AdaFace feature norm** (free), optionally **eDifFIQA**. Drop MagFace: it needs a third R100 just for a score | Blurry/dark frames pull identity off | Quality-weighted vs plain mean |
| Set fusion | mean embedding | **CAFace** (requires the AdaFace IR101 **WebFace4M** backbone, so use that one) | Bad frames dilute good ones | mean vs quality-weighted vs CAFace |
| Identity decision | per-frame argmax | **SPRT over quality-weighted log-likelihoods + switching penalty** (HMM-style hysteresis) | `person_id` flickers frame to frame | ID flips per track, frames-to-correct-ID |
| Known vs stranger | fixed cosine 0.4 | **Split conformal on the track-level score**. Calibrate the stranger side with thousands of LFW/CelebA identities scored against our gallery; calibrate per track, not per frame | Fixed threshold has an unknown error rate | Target vs observed stranger acceptance at several α |
| Liveness (if time) | none | **insightface 2.x liveness addon + MiniFASNet (via `uniface`)**, averaged over the track | Holding up a photo or a phone screen | Attack rejection + false reject on ~20 clips each: real / print / screen |
| Re-entry (if time) | none | boxmot ReID only for a lost track that returns within N s; never assigns identity | Person leaves and returns back-turned | Re-entry ID accuracy |

Conformal notes: with n calibration samples the smallest reachable α is 1/(n+1), so per-person (Mondrian) thresholds are impossible with 4–10 people; pool them. Threshold = the ⌈(n+1)(1−α)⌉-th order statistic. Optional ablation: Extreme Value Machine (`pip install evm`).

## Latency

Advertise p50/p95 per stage next to the accuracy table.

### Techniques, ranked by payoff

1. **Latest-frame slot.** Own reader thread for MJPEG that overwrites one slot; never use OpenCV's buffer (`CAP_PROP_BUFFERSIZE` is ignored for HTTP). Prevents hundreds of ms to seconds of queueing. ~30 min. Even faster: read with `requests` and split on JPEG markers `\xff\xd8` / `\xff\xd9`.
2. **TensorRT FP16** for every model. ~2–4× faster. 1–2 h.
3. **Adaptive computation.** Recognition ensemble + liveness only until the track's identity is committed, then re-check every N frames. Cuts face-model compute ~90%. ~1 h.
4. **Face detection inside person boxes** instead of the full frame.
5. **Batch all face crops** of a frame into one call.
6. **GPU preprocessing** (torch resize/normalize on CUDA). Saves 2–5 ms of CPU.
7. **CUDA graphs** (`trt_cuda_graph_enable`). ~0.5–1 ms per model.
8. CUDA streams / async stages: helps throughput, not single-frame latency. Low priority.

### Per-model latency, TensorRT FP16, batch 1

| Model | 3090 / A6000 (est) | 5090 (est) | Source |
|---|---|---|---|
| YOLO26 n / s / m @640 | 1.0 / 1.5 / 2.5 ms | 0.6 / 0.8 / 1.2 ms | T4 measured 1.7 / 2.5 / 4.7 ms |
| SCRFD-10G @640 | 2–3 ms | ~1 ms | 4.9 ms on unnamed hardware |
| ResNet100 @112 | 1.5 ms (batch 3 ≈ 2 ms) | 0.6 ms | 2080 Ti measured 2.37 ms |
| ViT-B face @112 | 2–3 ms | ~1 ms | none found |
| MiniFASNet @80 | <0.5 ms | <0.3 ms | none found |
| JPEG decode 720p | CPU 3–6 ms, nvJPEG 1–2 ms | | none found |

**Worst case (3090, everything serial, TensorRT FP16): ~15–25 ms per frame, 40+ fps.** The same ensemble in FP32 without TensorRT is ~50–80 ms and misses real time. No single model misses real time on a 3090.

### End-to-end budget (est)

Phone capture 30–60 ms + JPEG encode 5–15 ms + Wi-Fi 10–40 ms + decode 3–5 ms + inference 10–25 ms ≈ **80–150 ms glass-to-event** on good Wi-Fi with a local GPU.

With the GPU in the cloud, add the Mac → cloud → Mac round trip: roughly 20–80 ms depending on region and venue internet (est), plus upload time for each JPEG. Send already-encoded JPEG bytes (don't decode and re-encode on the Mac), keep one persistent connection open, and lower the stream resolution if upload is slow.

**Honest measurement:** point the phone at the server's own monitor showing a millisecond clock. Latency = event time − the clock value visible in the frame; both come from the server clock, so no clock-sync error. Also log per-stage `perf_counter_ns` (synchronize CUDA or use CUDA events) and report p50/p95.

## Deployment

### One stack for every candidate GPU

RTX 3090 / A6000 (sm_86), RTX 4090 / 6000 Ada (sm_89), RTX 5090 / RTX PRO 6000 (sm_120).

| Component | Version | Pitfalls |
|---|---|---|
| CUDA / driver | CUDA **12.8**, driver ≥ 570 (unverified) | 12.8 is the first CUDA that builds sm_120 and still covers sm_86/89. Never mix CUDA 12 and 13 libraries in one process |
| PyTorch | 2.8–2.10 from `--index-url https://download.pytorch.org/whl/cu128` | From 2.11 plain `pip install torch` pulls CUDA 13: pin. cu124/cu126 builds fail on sm_120 with "no kernel image is available". Check `torch.cuda.get_arch_list()` contains `sm_120` |
| onnxruntime-gpu | 1.22.x, or ≥ 1.23.2 | **1.23.0 fails on the 5090** ("no kernel image"). ≥ 1.27 defaults to CUDA 13: pin. Uninstall CPU `onnxruntime` or the GPU provider breaks |
| TensorRT | `tensorrt-cu12` 10.9.x (match the ORT build) | **Engines only run on the GPU + TensorRT version they were built on**: build on the demo machine; delete the engine cache when the GPU, model or TRT version changes |
| Ultralytics | `export(format="engine", half=True)` | Build on the target GPU; check mAP after export |
| boxmot | pure Python/NumPy | ECC motion compensation is slow at full resolution: use `sof` with downscale 2 |
| insightface | 2.0 / 2.1 (no compiler needed anymore) | Picks the CUDA provider itself; the TensorRT provider is unverified |

Skip FP8/FP4: FP16 works on every candidate GPU. Check FP16 vs FP32 cosine similarity on ~50 face pairs (expect > 0.999).

### Serving: one Python process

**onnxruntime-gpu with the TensorRT execution provider** (`trt_fp16_enable`, `trt_engine_cache_enable`, `trt_timing_cache_enable`) plus Ultralytics `.engine` files, all in one process, with the CUDA provider as fallback. 1–2 h, best latency per hour of work.

Rejected for latency: Triton (4–8 h, its batching helps throughput, not one stream), Ray Serve (no latency gain), DeepStream (days), native trtexec engines (≤ 10–20% faster than the above for 2–4 h of work).

Export AdaFace IR101 with a dynamic batch dimension. LVFace ships an official ONNX; export with opset ≥ 17 so LayerNorm stays one op. TensorRT conversion of LVFace is unverified.

### Network and stream

The demo runs on the Mac and only inference runs on a rented cloud GPU, so the phone can't reach the GPU server directly:

```
phone ──Wi-Fi/hotspot──► Mac thin client ──Tailscale / SSH tunnel──► cloud GPU (inference)
                              ▲                                            │
                              └──────────── tracks + identities ◄──────────┘
                              │
                              └──► publish person.seen to Redpanda on the Mac
```

- The Mac client reads `http://<phone>:8080/video` with the latest-frame slot and forwards the raw JPEG bytes over one persistent connection.
- The GPU server runs the whole pipeline (detection, tracking, recognition) and returns results; the Mac publishes `person.seen`. Redpanda never has to be reachable from the cloud.
- Pick the GPU region closest to the venue and measure the round trip on the first hour.
- Lower resolution / JPEG quality in the IP Webcam app if upload is the bottleneck.
- Docker with the NVIDIA Container Toolkit (`--gpus all`, `nvidia/cuda:12.8.x-cudnn-runtime`) works on the Linux server.

### Input-format trap

AdaFace expects **BGR** normalized with mean 0.5 / std 0.5; insightface models expect RGB. Getting this wrong silently ruins accuracy.

### Mac fallback

`uniface[cpu]` bundles SCRFD, YOLOv8-face, AdaFace, ArcFace and eDifFIQA as ONNX. Use plain `onnxruntime` (`onnxruntime-silicon` is deprecated). Benchmark the CoreML provider before trusting it (one report found it 3× slower than CPU); give SCRFD a fixed 640×640 input. boxmot on `mps` is unverified; use CPU.

## First hour on the GPU server

1. `nvidia-smi` → note GPU and driver. Ping the server from the Mac and note the round trip.
2. Install the pinned stack; check `torch.cuda.get_arch_list()` and that one ORT TensorRT session runs.
3. Benchmark the main flow: buffalo_l + YOLO person + BoT-SORT, per-stage ms.
4. Then add layers in this order, measuring each:
   - **Main flow (~2 h):** buffalo_l + YOLO person + BoT-SORT, face-to-body association, mean embedding, fixed threshold, publish `person.seen`.
   - **Accuracy layers (~4 h):** AdaFace + LVFace with calibration, quality weighting, SPRT, conformal, SCRFD + YOLO-face WBF, TensorRT FP16, adaptive computation.
   - **If time is left:** CAFace, liveness, re-entry ReID.

## Contract note

Publish `person.seen` only once the identity is committed. Then `person_id: null` keeps meaning "stranger" and the shared contract does not change.

## Researched and rejected

| Option | Why not |
|---|---|
| MOTIP, CAMELTrack, SAM 2 / SAMURAI trackers | Heavier and slower; their leaderboard gains come from crowded scenes, not 1–3 people at a fridge |
| rPPG liveness (pyVHR, rPPG-Toolbox) | Needs ~10 s of still face; MJPEG compression destroys the signal; a replayed video still shows a pulse |
| FLIP anti-spoofing | 4–5 h of research-code setup, non-commercial weights |
| Depth Anything V2 liveness | Monocular depth can "invent" a face shape on a flat photo; only try if tested on a real print first |
| MagFace | Needs its own R100 only for a quality score; AdaFace norm + eDifFIQA cover it |
| TopoFR R200 | Best IJB-C (97.84) but PyTorch-only, no license stated. Optional third model |
| Triton / Ray Serve / DeepStream | See [Serving](#serving-one-python-process) |

## Licenses

insightface, LVFace, QMagFace and FRoundation weights are non-commercial; YOLO-face is GPL-3.0. Fine for a hackathon, not for a product.

## Sources

Detection / recognition / quality: [insightface model zoo](https://github.com/deepinsight/insightface/tree/master/model_zoo) · [SCRFD](https://github.com/deepinsight/insightface/tree/master/detection/scrfd) · [YOLO-face](https://github.com/akanametov/yolo-face) · [uniface](https://github.com/yakhyo/uniface) · [AdaFace](https://github.com/mk-minchul/AdaFace) · [AdaFace ONNX](https://huggingface.co/datnt114/adaface-onnx) · [LVFace](https://github.com/bytedance/LVFace) · [TopoFR](https://github.com/DanJun6737/TopoFR) · [TransFace](https://github.com/DanJun6737/TransFace) · [PETALface](https://github.com/Kartik-3004/PETALface) · [MagFace](https://github.com/IrvingMeng/MagFace) · [eDifFIQA](https://github.com/LSIbabnikz/eDifFIQA) · [CR-FIQA](https://github.com/fdbtrs/cr-fiqa) · [CAFace](https://github.com/mk-minchul/caface) · [QMagFace](https://github.com/pterhoer/QMagFace)

Tracking / open set: [boxmot](https://github.com/mikel-brostrom/boxmot) · [BoT-SORT config](https://raw.githubusercontent.com/mikel-brostrom/boxmot/master/boxmot/configs/trackers/botsort.yaml) · [OccluBoost](https://mikel-brostrom.github.io/boxmot/trackers/occluboost/) · [CAMELTrack](https://github.com/TrackingLaboratory/CAMELTrack) · [MOTIP (CVPR 2025)](https://openaccess.thecvf.com/content/CVPR2025/papers/Gao_Multiple_Object_Tracking_as_ID_Prediction_CVPR_2025_paper.pdf) · [EdgeTAM](https://arxiv.org/html/2501.07256v1) · [Extreme Value Machine](https://github.com/Vastlab/ExtremeValueMachine) · [CGTC](https://www.alphaxiv.org/overview/2510.13037) · [Conformal prediction for face recognition](https://proceedings.mlr.press/v60/eliades17a.html)

Liveness: [insightface liveness / changelog](https://raw.githubusercontent.com/deepinsight/insightface/HEAD/python-package/CHANGELOG.md) · [face-antispoof-onnx](https://github.com/suriAI/face-antispoof-onnx) · [Depth Anything V2](https://github.com/DepthAnything/Depth-Anything-V2) · [rPPG-Toolbox](https://github.com/ubicomplab/rPPG-Toolbox) · [pyVHR](https://github.com/phuselab/pyVHR) · [FLIP](https://github.com/koushiksrivats/FLIP)

GPU / latency: [PyTorch 2.7 Blackwell](https://pytorch.org/blog/pytorch-2-7/) · [sm_120 thread](https://discuss.pytorch.org/t/when-will-sm120-support-be-available/223621) · [ORT CUDA EP](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html) · [ORT TensorRT EP](https://onnxruntime.ai/docs/execution-providers/TensorRT-ExecutionProvider.html) · [ORT CoreML EP](https://onnxruntime.ai/docs/execution-providers/CoreML-ExecutionProvider.html) · [TensorRT support matrix](https://docs.nvidia.com/deeplearning/tensorrt/latest/getting-started/support-matrix.html) · [Blackwell migration guide](https://forums.developer.nvidia.com/t/software-migration-guide-for-nvidia-blackwell-rtx-gpus-a-guide-to-cuda-12-8-pytorch-tensorrt-and-llama-cpp/321330) · [YOLO26](https://docs.ultralytics.com/models/yolo26) · [TensorRT accuracy](https://docs.nvidia.com/deeplearning/tensorrt/10.x.x/inference-library/accuracy-considerations.html) · [MagFace TRT timing](https://www.github.com/tonhathuy/tensorrt-triton-magface) · [glass-to-glass latency](https://thomedw.github.io/blog/subsecond-glass-to-glass-latency) · [CoreML vs CPU](https://rapidai.github.io/RapidOCRDocs/main/blog/posts/inference_engine/compare_coreml_cpu_provider_perf.md)

**Unverified:** every latency number on our GPUs, anti-spoof accuracy on print/screen attacks, LVFace → TensorRT conversion, insightface with the TensorRT provider, boxmot on MPS, which ORT 1.23.x release carries the sm_120 fix, and the exact driver requirement.
