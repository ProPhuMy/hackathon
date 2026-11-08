# Fridge Tracker: Stage 1 Kubernetes Deployment (k3d)

This directory contains the local, isolated, CPU-only Kubernetes deployment for **Fridge Tracker** using `k3d`.

> [!IMPORTANT]
> **Implementation Note**: In accordance with the execution protocol, all manifests and scripts in this directory were written and validated syntactically without running live cluster commands. Reviewers should verify host prerequisites before invoking the scripts.

---

## Prerequisites & Version Verification

Before executing the scripts, verify that the following tools are installed and operational on your host:

1. **Docker**: `docker --version` (tested for Docker Desktop / engine >= 24.0.0; allocate at least 8 GB RAM and 4–8 CPU cores in Docker settings).
2. **k3d**: `k3d --version` (recommended >= v5.6.0).
3. **kubectl**: `kubectl version --client` (compatible with Kubernetes v1.30+).
4. **Python 3**: `python3 --version` (Python 3.11+ standard library used for JSON formatting/parsing).
5. **curl**: `curl --version` (used by verification scripts).

The cluster image used by `cluster-up.sh` defaults to:
```bash
K3S_IMAGE="rancher/k3s:v1.30.6-k3s1"
```
Verify or override `K3S_IMAGE` if your local environment pins an alternative k3s build.

---

## Architecture & Isolation

- **Cluster & Namespace**: Cluster `fridge-dev`, namespace `fridge`.
- **Kubeconfig Context Scoping**: Does NOT touch or switch your host default kubeconfig. Kubeconfig is written to:
  ```bash
  ${FRIDGE_KUBECONFIG:-$HOME/.config/fridge-k3d/kubeconfig}
  ```
  Context name is `k3d-fridge-dev`. Every script sources `common.sh` and executes commands exclusively via the helper function `kc`.
- **Port Mapping**:
  - `127.0.0.1:18080` on the host forwards to NodePort `30080` on `k3d-fridge-dev-server-0` (for dashboard UI verification).
  - PostgreSQL port `5432` and Redpanda Kafka port `19092` are **NOT** bound to host ports, preventing collisions with local databases or review brokers.
  - Backend API verification uses on-demand `kc port-forward svc/backend 18000:8000`.
- **Single-Writer Topology**:
  - Backend is deployed as a singleton (`replicas: 1`, `strategy: Recreate`) because matcher and outbox recovery do not permit concurrent multi-replica writers.
  - PostgreSQL and Redpanda are single-replica StatefulSets backed by local persistent volumes (`1Gi` each).

---

## Container Resource Allocation

Target machine budget: ~8 GB RAM / 8 CPU cores. Explicit requests and limits are configured on every container:

| Container | CPU Request | CPU Limit | Memory Request | Memory Limit | Purpose |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **PostgreSQL** (`postgres:16`) | `100m` | `500m` | `256Mi` | `512Mi` | Relational store, journal & outbox |
| **Redpanda** (`redpanda:v24.2.7`) | `250m` | `1000m` | `512Mi` | `1024Mi` | Event broker (dev-container mode) |
| **Topics Job** (`topics-bootstrap`) | `100m` | `500m` | `128Mi` | `256Mi` | One-shot idempotent topic initialization |
| **Backend** (`fridge-backend:dev`) | `200m` | `1000m` | `256Mi` | `512Mi` | FastAPI + Matcher engine worker |
| **Dashboard** (`fridge-dashboard:dev`) | `50m` | `200m` | `64Mi` | `128Mi` | Static web UI and API reverse proxy |
| **Steady-State Total** | **0.60 CPU** | **2.70 CPU** | **1,088 MiB (~1.06 GiB)** | **2,176 MiB (~2.13 GiB)** | Steady running state |
| **Peak Total (with Job)** | **0.70 CPU** | **3.20 CPU** | **1,216 MiB (~1.19 GiB)** | **2,432 MiB (~2.38 GiB)** | Peak during deployment bootstrap |

---

## Execution Sequence

Run all commands from the repository root:

### 1. Provision Cluster
```bash
./infra/k8s/scripts/cluster-up.sh
```
Creates `fridge-dev` with port mapping `127.0.0.1:18080:30080@server:0` and exports context to `${FRIDGE_KUBECONFIG:-$HOME/.config/fridge-k3d/kubeconfig}` with `chmod 600`. Idempotent: if the cluster exists, it refreshes the kubeconfig without recreation.

### 2. Build & Import Container Images
```bash
./infra/k8s/scripts/build-import.sh
```
Builds `fridge-backend:dev` from repository root using `infra/k8s/backend.Dockerfile` and imports it into `fridge-dev`. If `fridge-dashboard:dev` exists locally, it imports it; otherwise it notifies the operator and skips.

> [!NOTE]
> **Dashboard Image Dependency**: The dashboard Dockerfile and frontend build are owned by Role 4 under `dashboard/`. If you wish to test the dashboard, build it first via:
> ```bash
> docker build -t fridge-dashboard:dev --build-arg VITE_API_BASE=/api dashboard/
> ```
> Then run `build-import.sh`.

### 3. Deploy Stack in Dependency Order
```bash
./infra/k8s/scripts/deploy.sh
```
Orchestrates the ordered startup:
1. Namespace `fridge`, StatefulSets `postgres` and `redpanda`.
2. Waits for PostgreSQL and Redpanda readiness probes.
3. Deletes any previous `topics-bootstrap` job and runs topic creation for `person.seen`, `item.event`, and `fridge.event` with finite timeout (180s).
4. Deploys `backend` and waits for startup/readiness probes (timeout 300s).
5. If `fridge-dashboard:dev` is present in the cluster image store, deploys `dashboard`.

### 4. Seed Synthetic Verification Scenario
```bash
./infra/k8s/scripts/seed.sh
```
Generates the standard synthetic demo scenario on the host using `python3` (validating against contracts and formatting ISO UTC timestamps ending in `Z` with milliseconds), then pipes each event directly into Redpanda inside the cluster:
1. `person.seen`: `track_id=1`, `person_id="p_01"`, `confidence=0.94`
2. `item.event`: `PUT`, `item_id="item_042"`, `item_label="milk carton"`, `confidence=0.90`
3. `person.seen`: `track_id=2`, `person_id="p_02"`, `confidence=0.91`
4. `item.event`: `TAKE`, `item_id="item_042"`, `item_label="milk carton"`, `confidence=0.87` (triggers `wrong_owner` alert)

### 5. Verify Scenario Assertions
```bash
./infra/k8s/scripts/check.sh
```
Sets up a background port-forward to `svc/backend 18000:8000` (auto-cleaned by trap on exit), polls `/alerts` for up to 60s, and asserts:
- `/alerts` contains a `wrong_owner` alert for `item_042`.
- `/events` contains a `PUT` for `item_042` with `person_id=p_01` and `status=ok`.
- `/events` contains a `TAKE` for `item_042` with `person_id=p_02` and `status=wrong_owner`.
- `/inventory` no longer contains `item_042`.
- If dashboard is deployed, checks `http://127.0.0.1:18080/healthz` returns `200`.

---

## Operational Procedures

### Restarting the Backend
The backend application persists state to PostgreSQL:
```bash
source infra/k8s/scripts/common.sh
kc rollout restart deployment/backend
kc rollout status deployment/backend --timeout=300s
```
On startup, the backend preflight validates schema versioning and replays the in-memory `Matcher` journal from PostgreSQL. No state is lost.

### Rolling Back a Deployment
```bash
source infra/k8s/scripts/common.sh
kc rollout undo deployment/backend
kc rollout status deployment/backend --timeout=300s
```

### Teardown & Data Loss Notice
```bash
./infra/k8s/scripts/teardown.sh --yes
```
Deletes cluster `fridge-dev` and removes the local kubeconfig file.
> [!CAUTION]
> This permanently destroys the persistent volume claims (`pgdata` and `redpandadata`). Local Docker images and Docker Compose volumes are untouched.

---

## Out of Scope & Limitations

The Stage 1 infrastructure deliberately excludes:
- Multi-broker Redpanda HA clustering (planned for future staging).
- Autoscaling with KEDA or HPA (backend is strictly a single writer).
- Production observability stacks (Prometheus, Grafana, OpenTelemetry).
- Ingress controllers (traffic routing uses k3d port mapping and NodePort `30080`).
- Hardware camera integrations, RTSP streams, or live face enrollment (synthetic test loads only).
