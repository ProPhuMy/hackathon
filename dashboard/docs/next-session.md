# Resume checkpoint — dashboard branch

Saved at user request to summarize and wrap up on2026-11-07 (local time).
No agents remain running. This is a persistent handoff, not an automatic retry.

## Branches and workflow

- Main was synchronized and pushed at88bcbab earlier. Further development is on
  **dashboard**, as the project overview requires. Do not implement on main.
- **dashboard-live-wip**, local commit **2ce1222**, preserves the UNACCEPTED agy
  live-data/serving candidate. It is not merged into dashboard or published.
  Do not apply it without fixing the findings below. The branch survives cleanup
  of temporary worktrees; its files can be recovered with Git.
- agy writes implementation code: detailed brief → worker plan → lead review →
  worker implementation → actual diff/check/browser review. At most two workers.
- Dashboard acceptance comes first, then infrastructure. Video waits until the
  project is complete. Do not resume coding until the user asks to continue.

## Accepted and verified

- Existing interactive fridge/demo, responsive controls, route panels, stable demo
  slot mapping, focus return, reversible3.8s journey and static fallback preserved.
- Model now lives at src/assets/mini-fridge.glb and uses Vite content-hashed delivery.
  Blender exporter and model checks use that path. GLB and .blend bytes unchanged.
- Explicit native tools in editing-worker role definitions fix agy's missing
  write/terminal tools. See reviews/worker-tooling.md for verified configuration.
- Final accepted-branch gates PASS: npm run build; npm run lint;
  node tools/checks/fridge-motion.mjs; routes.mjs; mapping.mjs; model-asset.mjs.
  Build still warns about the approximately1.05MB minified lazy3D chunk.
- Phong backend previously passed191 tests including isolated livePostgres tests.
  Fake-event PUT→TAKE→mismatch alert was verified through real Kafka, Postgres,
  API and SSE. This is not camera-based end-to-end validation.
- Independent baseline QA completed with explicit coverage gaps; UI/UX reviewed
  the live candidate. Final independent combined-preview sign-off remains pending.

## Next assignments in priority order

| Owner | Work / dependency | Owned files or artifacts | Definition of done |
| --- | --- | --- | --- |
| frontend-integrator | Revise local2ce1222 against accepted dashboard/model baseline | App.jsx/App.css, api.js, fridgeController.js, useFridgeData.js, demoData.js, itemMapping.js, focused checks | Fix StrictMode disposal/reuse that leaves initializing forever; bound snapshot/registration requests; truthful reconnect/error/loading states; reject malformed records; stable IDs and metadata-only registration; meaningful regression checks |
| ui-ux-designer → frontend-integrator | Apply reviewed live-state handoff after lifecycle fix | reviews/live-ux-handoff.md, live layout/copy in App | No interior overlap at320×568; clear retry status; readable registration and truthful unknown enrollment; no backend jargon; preserve accepted demo layouts |
| frontend-integrator | Replace invalid production proof and repair actual serving | Dockerfile, nginx.conf.template, .dockerignore, production-serving.mjs, README | Actual built nonroot Nginx starts; env substitution works; real HTTP deep links/cache/static404/API/SSE pass. Current test mimics Nginx with a Node server and is REJECTED. No dummy model inserted into dist |
| visual-qa | Depends on reviewed combined candidate | integrated preview and fresh screenshot/report evidence | Independent desktop,390×844,320×568,844×390; demo/live modes; keyboard/touch/focus/interruptions; realID routes; registration/reload/409; SSE reconnect; reduced motion; model/WebGL fallbacks; status and data agree |
| motion-engineer | Only if combined QA identifies a motion/input regression | fridgeMotion.mjs/Fridge3D.jsx and targeted evidence | Reproduced failure fixed without unrelated timing changes; existing motion and picking checks plus browser reproduction pass |
| 3d-modeler | Asset release COMPLETE; remaining device/addon work depends on tools/hardware | tools/blender, model performance evidence | Responsive Blender addon permits read-only verification/rebuild proof; real-device profiling drives any LOD/material changes. Do not rebuild merely to resume this task |
| frontend-integrator (infrastructure role) + visual-qa | Starts after dashboard acceptance; latest teammate contracts available | infra/k8s only, infrastructure plan/runbook/evidence | Reviewed agy plan, then reproducible local k3d deployment and verification; stage one-node flow before3-broker resilience/KEDA/observability. Keep backend singleton unless Phong supplies safe scaling contract |

Exact mandatory code/serving findings and reproduction notes:
[reviews/live-integration-revisions.md](reviews/live-integration-revisions.md).
UI evidence and lead corrections:
[reviews/live-ux-handoff.md](reviews/live-ux-handoff.md).

Important serving failures: NGINX_ENVSUBST_FILTER used space-separated names,
so actual nginx -t failed “unknown backend_host variable”; generic extension
routing would break real IDs ending .png while /missing.js falls back to HTML.
The candidate's passing synthetic server test does not establish production health.

## Dependencies and remaining gaps

- No live fridge shelf/model placement contract: illustrative geometry must never
  bind real item043 to demoFood_0; live inventory remains accessible as a list.
- People API persists metadata and returns enrollment_status unknown. Viet now has
  CLI enrollment, but no dashboard face-enrollment API. Do not infer enrollment.
- Real Safari/iOS/Android/older-device profiling and physical screen-reader checks
  remain unverified. Blender addon handshake previously timed out. Figma handoff
  sync and measured material/LOD work are queued, not release claims.
- Newly merged person/item recognition pipelines need teammate end-to-end camera
  validation. Latest overview permits cloudGPU inference with Mac thin clients;
  Khang's local k3d hosts backend/dashboard/lightweightCPU workers only.
- Docker Desktop has about8GB assigned on a24GB Mac; account for that in infra
  planning. k3d/helm were not installed; kubectl had no active context.
- Infrastructure implementation and final video have not started.

## Runtime and resumption

Accepted demo preview: http://127.0.0.1:5176/ (confirm it is still running).
Temporary candidate preview5178 and test backend8000 were stopped during wrap-up.
Test containers fridge-review-postgres and infra-redpanda-1 were stopped, preserving
state; native hostPostgres5432 was not changed. Docker Desktop remains running.
Restart only when needed. TestPostgres uses127.0.0.1:15432; Redpanda19092.
Create person.seen, item.event, fridge.event topics BEFORE starting backend.

Temporary workspace pointer: /private/tmp/fridge-dashboard-active.txt.
Do not rely on temporary files surviving. Start fresh workers from dashboard plus
reviewed WIP files, with separate checkouts and credentials excluded. Keep
source tests and accepted artifact checks meaningful; never weaken them to pass.
