# **Fridge Tracker – Project Overview**

Updated 11/07/2026 · Dang  
**One sentence:** a shared-fridge management system that knows who put what in, who took what out, and who took someone else's food. Every technique we add must make this sentence more accurate, or help access the data behind it.

## **Problem and goals**

A shared-fridge tracker: know who put each item in, who took each item out, and raise an alert when the taker is not the item's owner. Everything is managed through a web dashboard.  
Entering the **Most Over-Engineered** track. Principle: algorithms may be complex, but every layer must serve a concrete goal, mainly improving person-recognition accuracy.  
Pitch setting (proposed, team has not decided): a shared fridge in a dorm, shared house or office pantry.

## **Locked scope**

The project has exactly the 6 features below. Anything not in this table is not built, unless the whole team agrees to replace an existing row.

| \# | Feature | What it does | Done when (proposed) |
| :---- | :---- | :---- | :---- |
| 1 | Record who puts items in | Know who just put which item into the fridge | Every put produces a PUT event with person, item, time |
| 2 | Record who takes items out | Know who just took which item out | Every take produces a similar TAKE event |
| 3 | Current inventory | List of items currently in the fridge and the owner of each | The list matches reality after every door close |
| 4 | Matching and alerts | Compare the taker with the item's owner, alert when they differ | Taking someone else's item shows an alert on the dashboard; low confidence is flagged "uncertain" |
| 5 | Web dashboard | Manage users, inventory, event history, alerts | All 4 are viewable and new people can be registered |
| 6 | High-accuracy face recognition and tracking | Identify the right person for features 1 and 2 | Has an accuracy number on the team's test set |

The algorithm layers in the Architecture section (tracking, embedding fusion, open-set, liveness) are **how feature 6 is built**, not new features. The complexity for the over-engineered track lives inside feature 6, not in adding features.  
The **MCP server** is an access layer, not a new feature: it lets other Claude instances read inventory, history, alerts and trends from the same data as the dashboard. Read-only; never returns face images or embeddings. Planned tools: get\_inventory, get\_history, get\_alerts, get\_trends.

## **Technical architecture**

People and items are recognized in parallel, then combined for matching. An event is created and sent to matching only when both pipelines have a result.  
**Person recognition pipeline (feature 6\)**

> 1. Galaxy Z Flip camera: streams video to the Mac, which forwards frames to the cloud GPU server  
> 2. Face detection and alignment: SCRFD \+ YOLO-face ensemble (WBF)  
> 3. Face embedding: ArcFace \+ AdaFace ensemble, with calibration  
> 4. Tracking and temporal fusion: BoT-SORT; fusion weighted by MagFace quality score  
> 5. Liveness (not decided): anti photo-spoofing; only if time allows  
> 6. Who is this? Conformal prediction: known person or stranger

**Item recognition pipeline**

> 1. Door open (not decided): the item camera detects the fridge light turning on  
> 2. Hand \+ object: Grounding DINO \+ SAM 2; 3D hand via HaMeR  
> 3. In or out, grab or touch: 3D plane at the door \+ Transformer action classifier  
> 4. Which item, whose: DINOv2 \+ color \+ position, matched with the Hungarian algorithm

**Combining the two pipelines**

> 1. PUT / TAKE event: person \+ item \+ time \+ confidence (features 1, 2\)  
> 2. Matching \+ alerts (feature 4): alert on wrong taker; flag "uncertain" on low confidence  
> 3. Web dashboard (features 3, 5): inventory, event history, alerts, person registration

## **Over-engineered techniques per problem**

Each technique replaces a simple approach and fixes exactly one flaw of that approach. The "What it fixes" column is the justification for the judges, and each layer should have an accuracy number with it on and off.  
**Note:** these techniques are suggestions, not final choices. Each member researches their own area and may swap in a better technique, as long as it still fixes the flaw in the last column. When researching, check 4 things:

> * Is there code and a pretrained model available  
> * Does it run on the cloud NVIDIA GPU server (CUDA 12.8, RTX 3090 through 5090), and how much VRAM does it use  
> * Per-frame processing speed  
> * Integration difficulty within hackathon time

### **Person recognition**

| Problem | Instead of | Use | What it fixes |
| :---- | :---- | :---- | :---- |
| Face detection | SCRFD | SCRFD \+ YOLO-face ensemble, merged with Weighted Boxes Fusion | Missed profile faces and small distant faces |
| Face recognition | ArcFace | ArcFace \+ AdaFace ensemble, scores merged via calibration; MagFace norm as frame quality score | Blurry or dark frames giving the wrong identity |
| Strangers | A fixed threshold | Conformal prediction: a threshold with a guaranteed error rate | Strangers wrongly labeled as known people |
| Tracking | ByteTrack | BoT-SORT with camera motion compensation | Lost IDs under occlusion or phone shake |
| Back turned to the fridge | Not handled | Not doing it: team dropped body re-ID | Identity lost right when interacting with the fridge |
| Photo spoofing | Not handled | Depth Anything V2 (flat photos have no depth) \+ rPPG heart rate from skin color | Spoofing with a photo or video on a phone |

### **Hand \+ object**

| Problem | Instead of | Use | What it fixes |
| :---- | :---- | :---- | :---- |
| Door open | On/off switch | Item camera detects the fridge light \+ optical flow on the door (proposed) | Wasted processing when nobody opens the fridge |
| Object detection | YOLO with fixed classes | Grounding DINO (open-vocabulary) \+ SAM 2 tracking masks across video | Unknown items not in the class list; items occluded by the hand |
| Hand | MediaPipe Hands 2D | HaMeR 3D hand mesh | Can't tell whether the hand actually grips the item |
| Whose hand | Not handled | Full-body pose (ViTPose), linking skeleton wrists to hands | Two people near the fridge at once |
| In or out | Before/after image diff | Depth Anything V2 builds a 3D plane at the fridge door; object trajectory via Kalman filter | Can't tell PUT from TAKE |
| Action type | if/else rules | Transformer over hand keypoint sequences \+ object mask, classifying PUT / TAKE / touch only | Touching and leaving an item counted as taking |
| Which item, whose | QR sticker | DINOv2 \+ color histogram \+ shelf position, matched with the Hungarian algorithm | Two identical items |
| Consistency | Trusting each event alone | Factor graph over the event sequence, e.g. you can't take an item that isn't in the fridge | Contradictory events |

### **Infrastructure**

| Problem | Instead of | Use | What it fixes |
| :---- | :---- | :---- | :---- |
| Orchestration | One Python script | Kubernetes (k3d on Mac), one microservice per model | One slow model drags down the whole system |
| Data transport | Direct function calls | Redpanda (Kafka-compatible) as the event bus | Dropped frames when a model can't keep up |
| State storage | One inventory table | Event sourcing \+ CQRS: inventory is a projection of the event log | Losing the history that trends and MCP need |
| Model serving | Loading the model in every service | Ray Serve with dynamic batching | Processing single frames, wasting hardware |
| Autoscaling | Fixed number of workers | KEDA scaling workers on consumer lag | Many fridges, many people at once |
| Face gallery | In-memory list | Qdrant (vector DB) | Slow search with many people |
| Trends | Querying the log directly | TimescaleDB | Time-series trend queries |
| Security | No internal encryption | Linkerd service mesh, mTLS between services | Face data crossing the internal network unencrypted |
| Observability | print logging | OpenTelemetry tracing \+ Prometheus/Grafana | Not knowing which step slows an event down |
| Deployment | kubectl apply by hand | GitOps with Argo CD | Pure over-engineering; say so plainly in the pitch |

### **Distributed system design**

The Infrastructure table above is the tooling; this table is the distributed-systems algorithms running on that tooling. Each row still fixes a real flaw of a system with two cameras and many services.

| Problem | Instead of | Use | What it fixes |
| :---- | :---- | :---- | :---- |
| Joining people with items | Comparing timestamps directly | Event-time window join with watermarks (Quix Streams or Bytewax), handling late events | Network delay makes events arrive out of order and join the wrong person |
| Two camera clocks | Trusting the phone's time | Hybrid logical clock attached to each frame, estimating clock skew at startup | Two phones drifting a few hundred milliseconds apart |
| Duplicates | Writing directly | Idempotency key per event \+ Kafka transactions (exactly-once) | One take counted twice when a service restarts |
| DB write and publish | Two separate commands | Transactional outbox | DB and event bus diverge after a mid-way crash |
| Per-fridge ordering | One shared topic | Partition by fridge\_id, consistent hashing to assign fridges to workers | Events for the same fridge processed out of order when scaling |
| Model can't keep up | Waiting | Back-pressure: priority queue by frame quality score, dropping poor frames first (load shedding) | Queue grows and latency increases forever |
| Model failure | Whole pipeline stalls | Circuit breaker \+ graceful degradation: if SAM 2 fails, fall back to YOLO | One failing model takes down the whole system |
| Model upgrades | Swapping directly | Not doing it: use a script that measures accuracy on the test clip set | Not knowing if the new model is better; also the source of on/off accuracy numbers |
| Event bus | One broker | 3-node Redpanda cluster, each partition replicated with Raft | One dead broker loses events |
| Event contracts | Free-form JSON | Redpanda schema registry \+ Protobuf | One person changing the format breaks someone else's service |
| Resilience | Hoping it runs | Chaos engineering: randomly kill a pod or broker while running | Proves the system self-heals |
| MCP server | Unlimited calls | Token bucket rate limiting | Another AI hammering it slows the dashboard |

Decided: do the watermark join, skip shadow deployment. The 3-node Redpanda cluster with chaos testing is also in, after the main flow runs on 1 node; all 3 nodes run on the same Mac, so it is a simulated distributed system, and the video must say so clearly.  
Pitch story: the heavy models (SAM 2, HaMeR, ensembles) make the system slow, so it needs an event bus, Kubernetes and autoscaling. The infrastructure complexity is justified by the algorithm complexity itself.  
Real risk: we don't know yet which NVIDIA GPU we get (RTX 3090 / 4090 / 5090, A6000 or RTX PRO). Use one CUDA 12.8 stack that covers all of them, and build TensorRT engines on the actual machine; see [research/person-recognition.md](research/person-recognition.md#deployment). The Mac stays as a fallback, where RAM is the limit.

## **Priority order**

Work in this order; each step starts only after the previous one runs.

> 1. Main flow end to end: one person, one item, put in then taken out, shown on the dashboard.  
> 2. Accuracy layers for person recognition and hand \+ object (the first two tables above).  
> 3. MCP server.  
> 4. Cluster infrastructure (Infrastructure table).

If time runs out, cut infrastructure first: it makes the system look bigger, not more correct.

## **Work split**

Four roles in parallel, connected by a shared event format locked in the first 30 minutes.

| Role | Person | Owns | Hands off |
| :---- | :---- | :---- | :---- |
| 1\. Person recognition | Viet | Face camera, detection ensemble, ArcFace \+ AdaFace, BoT-SORT, open-set | person.seen events |
| 2\. Item recognition | Dang | Item camera, door-open detection, Grounding DINO \+ SAM 2, HaMeR, PUT/TAKE classification, DINOv2 \+ Hungarian | item.event events |
| 3\. Backend and matching | Phong | Event bus, event sourcing \+ CQRS, time-based join of people with item events, matching \+ alerts, MCP server | API for the dashboard and MCP |
| 4\. Dashboard, infra and video | Khang | Web dashboard, Kubernetes \+ autoscaling, Grafana, recording and editing the demo video | Video submitted at 13:00 |

The two recognition pipelines don't know about each other; the backend joins them by time window into fridge.event. The current format is defined in `contracts/*.schema.json`; examples:  
`{ "event_id": "…", "topic": "person.seen", "track_id": 7, "person_id": "p_02", "ts": "2026-11-08T09:15:02.120Z", "confidence": 0.93 }`  
`{ "event_id": "…", "topic": "item.event", "type": "TAKE", "item_id": "item_042", "item_label": "milk carton", "ts": "2026-11-08T09:15:03.480Z", "confidence": 0.88 }`  
Milestones:

> 1. First 30 minutes: lock the event format. Everyone uses fake data in that format so nobody waits on anyone.  
> 2. Main flow end to end with the simplest models.  
> 3. Gradually swap in the over-engineered techniques, measuring accuracy before and after each swap.  
> 4. Around 10:00 AM on 11/8: code freeze, whole team moves to recording and editing the video.  
> 5. 13:00: submit.

While working, everyone saves debug videos of their part (bounding boxes, masks, track IDs, hand meshes). Those are ready-made footage for the algorithm section.

## **Implementation**

Start with docker-compose and fake data so all 4 people can work in parallel right away. Kubernetes comes in only after the main flow runs.

### **Stack**

| Layer | Tool |
| :---- | :---- |
| Language | Python 3.11 \+ uv for all vision and backend services |
| Phone video | Android: IP Webcam app streaming MJPEG over Wi-Fi, read with OpenCV; iPhone: Continuity Camera with the Mac |
| Person recognition | insightface (SCRFD, ArcFace), boxmot (BoT-SORT) |
| Item recognition | ultralytics YOLO and MediaPipe Hands for the first version; transformers (Grounding DINO, DINOv2) and SAM 2 when upgrading |
| Event bus | Redpanda in Docker |
| Backend | FastAPI, Postgres as the event store, SSE pushing updates to the dashboard |
| MCP server | Python MCP SDK (FastMCP), read-only |
| Dashboard | React (Vite) |
| Infrastructure | docker-compose first; then k3d \+ KEDA \+ Prometheus/Grafana |

### **Repo layout**

See the repo root `README.md` for folder ownership and the Git workflow.

`contracts/              # event format (JSON Schema), locked first`  
`tools/fake_events.py    # publishes fake events so nobody waits on anyone`  
`services/person/        # Role 1`  
`services/item/          # Role 2`  
`services/backend/       # Role 3: event join, matching, API, MCP`  
`dashboard/              # Role 4`  
`eval/                   # labeled test clips + accuracy script`  
`infra/                  # docker-compose.yml, k8s/`  
`docs/                   # this document`

### **Two notes before starting**

> 1. The demo runs on the Mac; only model inference runs on a rented cloud NVIDIA GPU server (natively or in Docker with the NVIDIA Container Toolkit). The phones can't reach the cloud over local Wi-Fi, so a thin client on the Mac reads each phone stream, sends frames to the GPU server, gets results back and publishes events to Redpanda on the Mac. Connect the Mac and the GPU server with Tailscale or an SSH tunnel, and pick a GPU region close to the hackathon: every round trip adds to latency. The Mac's GPU can't be used from inside Docker or k3d, so on the Mac k3d only holds the backend, dashboard and lightweight workers; the autoscaling demo uses those workers.  
> 2. Hackathon Wi-Fi often blocks devices from talking to each other. If the phones can't stream to the Mac, turn on a hotspot from one phone and put the Mac and both camera phones on it.

### **First tasks per role**

**Role 1, person recognition (Viet)**

> 1. Read the stream from the Z Flip, run SCRFD \+ ArcFace, register a gallery for the 4 team members.  
> 2. Add BoT-SORT, fuse embeddings per track, publish person.seen.  
> 3. Once the main flow runs: add AdaFace, MagFace quality score, conformal threshold.

**Role 2, item recognition (Dang)**

> 1. Read the stream from the second phone; detect door open by brightness.  
> 2. YOLO \+ MediaPipe Hands; decide PUT/TAKE by the direction an item crosses a line at the fridge door; publish item.event.  
> 3. Add DINOv2 \+ Hungarian to tell items apart, then Grounding DINO \+ SAM 2\. HaMeR depends heavily on NVIDIA GPUs, so run it on the GPU server; if it doesn't fit the latency budget, keep MediaPipe.

**Role 3, backend and matching (Phong)**

> 1. Repo, contracts/, fake\_events.py and docker-compose (Redpanda, Postgres) are already set up by Dang; start from fake events on the bus.  
> 2. Join each item.event with the nearest person.seen via an event-time window join with watermarks, write fridge.event, build inventory from the log.  
> 3. Matching \+ alerts, API \+ SSE, then the MCP server.

**Role 4, dashboard, infra and video (Khang)**

> 1. Dashboard running on fake data from Role 3's API.  
> 2. Record about 20–30 labeled put/take clips early (who, which item, PUT or TAKE) as the test set, and write the accuracy script. This is the source of numbers for the final scene of the video.  
> 3. As soon as the main flow runs, record a backup video. Then move Redpanda to a 3-node cluster and try killing a node, then set up k3d \+ KEDA \+ Grafana.

## **Demo video script**

About 3 minutes long. The first minute shows the product actually working; the remaining two introduce the algorithms and infrastructure for the over-engineered track.

| Time | Scene | On screen | Narration |
| :---- | :---- | :---- | :---- |
| 0:00–0:15 | Opening | Someone opens the fridge; their lunch box is gone | "Who took my lunch?" then read the project's one sentence |
| 0:15–0:45 | Putting an item | Person A puts a milk carton in the fridge; dashboard adds the item, owner A | Buy it, put it straight in the fridge: no tags, no app |
| 0:45–1:10 | Wrong taker | Person B takes the milk carton; dashboard shows an alert | The system knows B just took A's item |
| 1:10–1:50 | Person recognition | Split screen: face boxes from two detectors, track IDs, recognition scores; a stranger is flagged "unknown" | Each layer fixes one flaw: profile faces, blurry frames, strangers |
| 1:50–2:30 | Hand \+ object | SAM 2 masks, HaMeR hand mesh, 3D plane at the fridge door; two identical items still told apart | Why 3D and the Hungarian algorithm are needed |
| 2:30–2:50 | Infrastructure | Architecture diagram; simulated many fridges, pod count rising, traces on Grafana; kill a broker and the system keeps running | Heavy models need an event bus and autoscaling |
| 2:50–3:05 | MCP | Ask Claude: "Who took A's food the most this week?" | Other AIs can read the fridge data too |
| 3:05–3:15 | Closing | Accuracy table with each layer on and off | Over-engineered, but every layer has a reason |

Scenes 1:10–2:50 include only techniques that actually work; anything cut is left out of the video. Record each scene separately and edit them together; narrate in English if the judges speak English.

## **Hardware**

Only equipment the team already has; the Jetson is in Vietnam, so it is not part of the plan.

| Device | Role |
| :---- | :---- |
| Galaxy Z Flip (folded in Flex mode) | Camera facing people, streams video to the Mac |
| The team's second phone | Films items and hands at the fridge shelves |
| Cloud NVIDIA GPU server (RTX 3090 / 4090 / 5090, A6000 or RTX PRO; Linux) | Runs model inference only, with TensorRT FP16 |
| Mac | Runs the demo: reads the phone streams and forwards frames to the GPU server, plus backend, Redpanda and web dashboard; fallback for inference |

## **Out of scope**

Things that are easy to add mid-way but **will not be built**:

> * Expiry-date tracking, recipe suggestions, shopping lists  
> * A separate mobile app for users (web dashboard only)  
> * Fines, payments, or SMS/email notifications  
> * Multiple fridges or multiple cameras at once  
> * Cloud deployment of the app; the demo runs locally on the Mac. Exception: model inference may run on a rented cloud GPU server, called from the Mac  
> * Training models from scratch; use existing models, then combine and fine-tune

Rule: new ideas go here first. They move into scope only after the main flow (one person, one item, put in then taken out) runs end to end.

## **Decisions**

The hackathon ends at 13:00 on 11/8/2026 and submission is a demo video, with no live pitch.

| Question | Decision |
| :---- | :---- |
| Item recognition | Pure vision, no QR or stickers: users buy items and put them straight into the fridge |
| Cameras | Two team phones: Galaxy Z Flip films people, another phone films items and hands |
| Door-open detection | Proposed, pending: no IMU; the item camera detects the fridge light turning on |
| Liveness (anti-spoofing) | Proposed, pending: outside the demo, only if time allows |
| Body re-ID | Not doing it |
| Watermark join | Doing it: data skew between two cameras is a real problem |
| Shadow deployment | Not doing it: accuracy numbers come from Role 4's test clip script |
| 3-node Redpanda cluster \+ chaos test | Doing it, after the main flow runs on 1 node |
| Team | 4 people, everyone can code every part; roles as in Work split |
| Deliverable | Demo video |
