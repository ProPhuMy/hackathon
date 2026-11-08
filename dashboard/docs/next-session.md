# Resume checkpoint — 2026-11-07, 23:34 local

Infrastructure documentation is consolidated in [Infrastructure handoff](infrastructure.md). Use it as the current plan; it supersedes the initial review draft.

User requested a wrap-up after authorizing parallel agy work and a30–60minute delivery target. All agy workers are paused. No automatic continuation is scheduled. Resume when asked.

## Saved state

- Develop on `dashboard`; never implement on `main`.
- Accepted dashboard source remains `4a0dfd1` (already on origin/dashboard). It includes the unchanged, content-hashed fridge asset and accepted demo experience.
- Local **dashboard-live-wip at `4777d76`** preserves the latest UNACCEPTED live integration and partial revisions. It includes accepted dashboard changes through merge checkpoint `180560b`.
- Local **dashboard-serving-wip at `180560b`** has no new serving edits. The reviewed plan is saved; implementation was interrupted before writing files.
- Local **dashboard-infra-wip at `4a0dfd1`** has no infrastructure code. Plan and mandatory lead corrections are saved.
- These WIP branches are local only. Do not merge/push them as accepted work.
- Agy workflow: detailed brief → plan → lead review → agy code → actual diff/tests/browser review. User explicitly authorized more parallel workers. Give editing workers separate checkouts with the required pending baseline and disjoint file ownership.

## What actually passed in the latest candidate

Lead reran: build, lint, fridge-motion, mapping, model-asset, and live-adapter checks — PASS. The lazy3D chunk warning remains. Browser under React StrictMode loaded real Test owner/Test taker from backend and showed connected SSE with no page errors.

**routes.mjs FAILS**: `/items/cold brew` differs from expected `/items/cold%20brew`. Review TanStack internal-path versus browser URL semantics and exercise real IDs; do not simply weaken the assertion.

The adapter tests passing does not establish full acceptance. Full registration/reload/409 browser checks, final responsive review, actual Nginx tests, and independent combined QA have not run on this checkpoint.

## Remaining work, in order

| Owner | Assignment / owned files | Dependency | Done when |
| --- | --- | --- | --- |
| frontend-integrator — live source | `src/api.js`, `fridgeController.js`, `useFridgeData.js`, `App.jsx`, `App.css`, relevant checks | Start from local4777d76 plus current accepted docs | Resolve route failure; prove encoded real-ID navigation/reload; finish UI corrections below; verify timeout/retry/disposal/reconnect truth with real browser and focused tests |
| frontend-integrator — serving, separate instance | Dockerfile, nginx.conf.template, .dockerignore, production-serving.mjs, README production sections | Can code independently now from serving plan; final build requires corrected live source | Real nonroot Nginx starts, env substitution works, deep links/static404/cache/API/SSE pass against explicit PRODUCTION_URL; no fake frontend or dummy model |
| ui-ux-designer | Review live copy/layout and handoff evidence | Updated source preview | No320px interior overlap, truthful loading/stale/enrollment wording, clear touch/keyboard controls and registration |
| visual-qa | Independent combined preview screenshots/report | Reviewed source + serving combined by lead | Desktop,390×844,320×568,844×390; demo/live, keyboard/touch/focus, interruption, reduced motion, fallback, six demo mesh/button mappings, real IDs, registration and reconnect all checked; gaps explicit |
| motion-engineer | Motion/input regressions only, if QA finds one | Specific reproduced finding | Preserve accepted camera/door timing and pass targeted regression checks |
| 3d-modeler | Asset release complete; addon/device profiling queued | Responsive Blender addon or real device | Read-only Blender verification and measured performance evidence; no speculative model rebuild |
| frontend-integrator — infrastructure | `infra/k8s/` only | Dashboard acceptance; reviewed plan corrections | Runnable isolated k3d core with singleton backend, Postgres, Redpanda, live dashboard; fake PUT/TAKE/mismatch verified; then3-broker recovery, KEDA CPU consumer and Prometheus/Grafana |

### Live source review still required

- Current App still says “Face recognition enrollment is completed on-device.” This is unsupported. Backend enrollment is UNKNOWN; registration is metadata only.
- History rows remain mouse-only (`tr onClick`). Add an actual keyboard-operable control.
- Owner options mix demo person IDs (`khang`) with inventory names (`Khang`), potentially producing duplicate labels/empty filters. Live filtering must use stable IDs only. The `all` sentinel also collides with a valid person ID. Verify both modes and duplicate names.
- Verify real IDs with spaces, slashes, percent signs and file extensions. Avoid double encoding. Live event lookup must not accidentally use the demo timestamp alias.
- The fresh controller fixes the observed StrictMode loading failure. Later fixes for stale-on-reconnect, registration cancellation and strict validation are present and adapter checks pass, but need final diff review and browser recovery proof.
- Mobile controls now use a flow wrapper, but no final screenshot/layout proof has been reviewed for it. Do not assume the collision is solved from CSS alone.
- Validate required record fields without coercing malformed confidence/status/type into verified events. Preserve valid nullable owners/people.

### Production and infrastructure briefs

- [Production serving brief](briefs/production-serving-parallel.md) and [reviewed plan](reviews/production-serving-plan.md).
- [Infrastructure brief](briefs/infrastructure-parallel.md) and [draft plus mandatory lead corrections](reviews/infrastructure-plan.md).
- [Combined QA brief](briefs/combined-live-qa.md).
- Earlier detailed defects: [live integration revisions](reviews/live-integration-revisions.md); UI evidence: [live UX handoff](reviews/live-ux-handoff.md).

Infrastructure has NOT been implemented or deployed. k3d/helm remain uninstalled; kubectl had no current context. Core first, then replicated-broker recovery and autoscaling/observability. Keep backend replicas1/Recreate; no safe horizontal matcher contract exists. Do not edit teammate services or shared root files. No cloud provisioning or GPU models in k3d.

## Runtime / recovery

Worktree pointer: `/private/tmp/fridge-dashboard-active.txt`.
Team root: `/var/folders/wt/jmtpq7xx6dg_7qkwsqv1t3fm0000gn/T/fridge-dashboard-zgvb55xu`.
Subdirectories: frontend-integrator, serving, infrastructure; briefs/results retain raw worker evidence. Git branches preserve implementation if temporary directories disappear.

Wrap-up stops candidate previews5178/5179, test backend8000, and our containers fridge-review-postgres (15432) / infra-redpanda-1 (19092), preserving their data. Native Postgres5432 and Docker Desktop are untouched. Accepted demo preview5176 is retained if running.

On resume, start review containers and confirm person.seen/item.event/fridge.event topics before backend. Use POSTGRES_DSN pointing to isolated15432 and API_HOST=0.0.0.0 for Docker proxy access. Live Vite uses VITE_API_BASE=/api and VITE_BACKEND_URL=http://127.0.0.1:8000. Demo preview uses empty VITE_API_BASE. Never read or print .env credentials.

Worker conversations: live source a4fc4495-2d9d-4ead-8d98-009000481fe5; serving plan d2556b03-2798-41b7-badc-b3796d0e6823; serving code4a28b6d8-cf34-4ede-88cc-70ca3a3906d5; infrastructure plan9142ee6b-4f16-4820-9f1f-f050688e672a. Prefer fresh implementation sessions with explicit native tool declarations; scoped settings retained in teamroot. No Docker access is required for coding workers; lead runs containers.

Real camera/face-enrollment validation, Safari/physical-phone checks, Blender addon handshake, and older-device GPU profiling remain external gaps. Video is deliberately deferred until project completion.
