# Infrastructure handoff

Updated 2026-11-07. This is the current infrastructure plan and remaining-work checklist, incorporating the lead review of the initial agy draft.

## Current status

**Planned, not implemented or deployed.** No Kubernetes manifests or deployment scripts exist in `infra/k8s/` yet. Workers are paused.

The existing local backend, Postgres and single Redpanda broker previously processed synthetic PUT, TAKE and ownership-mismatch events through API and SSE. That is a local integration baseline, not Kubernetes readiness or physical-camera validation.

Dashboard acceptance comes first. Its live candidate still needs route/UI fixes, actual Nginx verification and independent visual QA. See [the current checkpoint](next-session.md). Video remains deferred until the project is complete.

## Scope and workflow

- Khang owns `dashboard/`, `eval/` and `infra/k8s/`. Develop on `dashboard`, not `main`.
- Put infrastructure implementation in `infra/k8s/`; keep plans and review evidence in `dashboard/docs/`.
- Reuse teammate services and existing contracts. Do not edit their source, the shared Compose file or root documentation.
- Use agy: detailed brief → worker plan → lead review → scoped coding → diff and runtime verification. Parallel editing workers need separate checkouts and disjoint file ownership.
- Local k3d hosts the dashboard, backend, data services and lightweight CPU workers. GPU inference stays outside this cluster and remains a teammate dependency. No cloud provisioning or video work is included.

## Assignments and acceptance

All stages below are pending. Stage 1 begins after dashboard acceptance.

| Stage | Owner | Owned artifacts | Dependency | Definition of done |
| --- | --- | --- | --- | --- |
| 1. Core deployment | frontend-integrator, infrastructure assignment | Infrastructure-owned backend Dockerfile, core manifests, cluster/build/deploy scripts and runbook | Accepted dashboard image; verified tool/image versions and resource budget | Isolated k3d runs Postgres, one Redpanda broker, singleton backend and live dashboard; repeated deployment is safe |
| 2. Core verification | visual-qa with lead runtime review | Infra seed/check scripts and evidence under `dashboard/docs/reviews/evidence/infrastructure/` | Healthy stage 1 | PUT adds the correct owner/item, TAKE removes it, wrong-owner TAKE produces an alert; API/SSE/dashboard agree; persisted state survives restart |
| 3. Broker resilience | frontend-integrator, infrastructure assignment | Replicated-broker overlay and bounded recovery script | Stage 2 passes | Three brokers have verified replication; one broker failure recovers without missing or duplicate application results |
| 4. Autoscaling | frontend-integrator, separate scoped assignment | CPU consumer, image and KEDA overlay | Stable core; defined consumer purpose and partition count | Independent consumer group scales on measured lag and drains backlog; backend stays singleton |
| 5. Observability | frontend-integrator with visual-qa review | Prometheus/Grafana configuration and evidence | Defined metrics and measured memory headroom | Working panels show broker/consumer health, lag and replicas using collected metrics |

UI/UX reviews dashboard status changes only if needed. Motion and model workers have no infrastructure edits assigned.

## Core deployment requirements

### Isolation and resource budget

- Use a dedicated cluster, namespace and kubeconfig. Do not switch the user's default context. Every command must explicitly target the dedicated context.
- Docker was observed with approximately 8 GB RAM and 8 CPUs on a 24 GB Mac. This is a planning constraint, not proof that the full stack fits.
- Budget for k3s, Postgres, broker memory, backend replay, dashboard and existing review containers. Add KEDA and monitoring only after measuring headroom.
- Broker runtime memory must fit below its container limit. Review the full three-broker budget; the initial draft's smaller limits were not accepted.
- Expose the dashboard on a free loopback port, proposed `127.0.0.1:18080`. Connect it to an actual NodePort (proposed `30080`) or configured ingress. Mapping to port 80 without ingress is insufficient.
- Do not take over native Postgres port 5432 or the review broker's port 19092. Publish verification events inside the dedicated cluster.

### Packaging and startup order

1. Verify and pin compatible k3d, Kubernetes, image and chart versions before installation. At the checkpoint, k3d/Helm were absent; kubectl was installed without an active context.
2. Build the backend using an infrastructure-owned Dockerfile with repository-root context. Preserve Python 3.11, locked dependencies, migration paths and required contract files. Use a nonroot runtime.
3. Build the accepted dashboard with `VITE_API_BASE=/api`. Configure Nginx with backend service host/port, container port 8080 and nonroot runtime. Verify actual API/SSE proxy behavior.
4. Start Postgres and the broker, wait for readiness, then create `person.seen`, `item.event` and `fridge.event` idempotently.
5. Start backend/dashboard only after topic bootstrap succeeds. Applying all manifests together and waiting for a Job afterward does not enforce ordering.
6. Keep backend `replicas: 1` with `Recreate`. Its matcher/journal contract does not support safe horizontal replicas. Postgres also needs a single-writer rollout and durable storage.
7. Use real API readiness, such as `/events?limit=1`, with enough startup allowance for migrations and replay. There is no backend `/health` endpoint. Dashboard `/healthz` checks static serving only. Verify probe behavior during dependency failure before using aggressive restarts.

## Replication, scaling and cleanup

- Three brokers need per-pod advertised addresses, RPC seeds and working service discovery. Increasing StatefulSet replicas alone is insufficient.
- Verify and migrate replication of existing application topics and relevant internal consumer-offset data. Changing defaults does not migrate existing topics.
- Identify the broker/partition leader actually being tested. Record event IDs before failure, inject a bounded failure in the dedicated cluster, wait for recovery and compare committed results.
- KEDA targets a separate CPU consumer with a defined useful output, such as contract-validation metrics. Use an independent consumer group and enough partitions for intended scaling. Do not scale the backend or invent a multi-fridge contract.
- Synthetic load must remain valid and clearly labeled. It does not establish camera integration, recognition accuracy or face enrollment.
- Scripts must be finite, context-scoped and fail visibly. Document restart, rollback and cleanup separately. Cleanup may remove only dedicated test resources and must explain data loss; it must not delete unrelated images, volumes or services.

## Expected implementation artifacts

These paths are proposed, not existing runnable files:

- `infra/k8s/backend.Dockerfile`: backend packaging from existing source.
- `infra/k8s/base/`: namespace, durable Postgres, single broker, topic bootstrap, singleton backend and dashboard manifests.
- `infra/k8s/overlays/replicated-redpanda/`: broker discovery, replication migration and resource configuration.
- `infra/k8s/overlays/keda-worker/`: independent consumer deployment and scaling configuration.
- `infra/k8s/observability/`: reviewed metrics collection and Grafana configuration.
- `infra/k8s/scripts/`: cluster creation, image build/import, ordered deployment, seed/verification, broker recovery and scoped teardown.
- `infra/k8s/README.md`: exact tested commands, resource budget, dependencies and recovery instructions.

## Required evidence

- Tool/image versions, rendered manifests, resource requests/limits, successful builds and runtime users.
- Topic bootstrap before backend startup, pod readiness/restarts and relevant logs.
- PUT inventory, TAKE inventory, mismatch alert and matching SSE event IDs; browser screenshot showing the same result.
- Backend restart with persisted state and no concurrent matcher instance.
- Three-broker replication state and before/during/after recovery results.
- KEDA consumer lag, replica changes and backlog recovery; Grafana panels backed by actual metrics.
- Explicit failures and untested cases. Configuration inspection alone is not deployment or resilience evidence.

## Resume instructions

Finish [dashboard acceptance](next-session.md) and the [production-serving assignment](briefs/production-serving-parallel.md) first. Then brief agy from this document and the [original infrastructure brief](briefs/infrastructure-parallel.md), request a concrete file-level plan and review it before coding.

The local `dashboard-infra-wip` branch contains only the accepted dashboard baseline, not infrastructure implementation. The original worker draft remains in Git history at `75a2af3`; its port mapping, context switching, resource assumptions and replica-only recovery approach are superseded by this handoff.
