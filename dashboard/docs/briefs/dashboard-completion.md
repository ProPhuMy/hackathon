# Dashboard completion brief — plan before implementation

## User direction and workflow

Khang owns the dashboard, Kubernetes infrastructure and final project video.
Complete the dashboard work first, then infrastructure. Video is explicitly
deferred until the project is done. Antigravity writes implementation code;
Codex prepares briefs, reviews plans, reviews actual diffs and verifies results.
Do not implement before Codex has reviewed and accepted your plan. Any correction
also goes back through Antigravity, rather than silent lead-written product code.
Use the user's signed-in agy configuration; do not load credential files.

## Phase 1: read-only plan

Role: frontend-integrator. Read AGENTS.md, README.md, docs/next-session.md,
docs/implementation-log.md, docs/reviews/integration.md and integrated-qa.md.
Inspect current source and build configuration; do not assume historical findings
remain open. The isolated checkout includes all pending dashboard work. HEAD in
the user's original repository is not the accepted baseline.

Read root README.md and the project overview for ownership and scope. Phong's
origin/phong commit 619d1ed was fetched and merged cleanly on 2026-11-07. Backend
API/SSE and people metadata endpoints now exist in services/backend. Review
src/fridge_backend/api.py, store.py, config.py and tests/test_api.py. No backend
source changes are owned by the dashboard worker. Face enrollment and dynamic
fridge placement remain separate contracts. See backend-integration.md for the
revised detailed integration brief; this supersedes earlier API-absence notes.

Return a precise, bounded implementation plan covering the work that can finish
the frontend now:

1. Independently verified dashboard behavior, with concrete fixes only for
   reproduced failures. A separate visual-qa worker examines the current preview.
2. Content-based model asset versioning replacing `/models/mini-fridge.glb?v=3`.
   Prefer Vite's existing asset pipeline over custom manifests or extra packages.
   Keep model bytes, pivot, picking metadata and editable source unchanged. Explain
   the exact source/output asset paths and avoid accidental 6.6 MB duplication in
   the production artifact. Tests must prove the built reference resolves and
   changing bytes changes its URL; existing model assertions must still locate
   the authoritative source artifact.
3. A minimal production serving/container boundary suitable for the project's
   later local k3d stage: SPA deep-link fallback, correct static-file behavior,
   sensible HTML versus versioned-asset cache policy, loopback/local testing and
   a health endpoint if the chosen runtime needs one. Do not prescribe an API
   proxy route or upstream until its contract exists. Explain runtime selection,
   image versions, build context, dependency install and non-root operation.
   Keep production-serving files inside dashboard. Do not edit shared compose.
4. Focused checks of the actual production build, including deep links, missing
   static assets, model delivery and fallback. Reuse existing checks and tooling;
   avoid introducing a general test framework for a narrow serving change.
5. Accurate README and handoff updates distinguishing frontend completion from
   live-system completion and unavailable real-device/Blender/Figma coverage.

For each step specify objective, exact files, dependencies, minimal change,
acceptance evidence, failure cases and rollback. Separate ready work from blocked
work. Flag decisions needing review; do not call a plan executed or tests passed.

## Behavior and design to preserve

- Vite/React, TanStack Router and persistent lazy-loaded R3F scene. No framework
  migration, backend implementation, new product feature or visual redesign.
- Warm light room, prominent fridge and the root mainscreen.png sketch; image.png
  is the pixel alphabet reference, not fallback artwork. Fallback remains the
  fridge photograph. Dense inventory content remains legible.
- Routes `/`, `/inventory`, `/history`, `/alerts`, `/people`, `/items/$itemId`,
  `/events/$eventId`; direct loads and back/forward; inventory search/owner filter;
  history, illustrative alerts, and session-only demo people.
- The existing 3.8-second reversible journey, DoorPivot and -2.05-radian open
  angle, six Food_0..Food_5 roots and selected-shelf picking/hover guard. Keep the
  original camera path, shelf heights, model geometry and materials.
- Fixed slots map to demo IDs 043..048 through src/itemMapping.js. Both mesh
  inspection and shelf buttons resolve by ID. Reordering is safe; missing items
  do not open a different record; new items are not assigned an arbitrary mesh.
- Portrait and short-landscape layouts, 44px touch-sized shelf targets, readable
  controls, Escape priority, dialog opener focus across StrictMode, scene-exit
  focus, reduced motion and inventory access on GLB/WebGL failure.

## Implementation rules after plan approval

Only edit the approved dashboard files in this isolated checkout. Do not delegate,
commit, push, deploy, access .env/credentials, modify sibling services/shared
contracts/compose, or create video material. Use ordinary file/terminal tools for
edits; browser tools are for browser evidence, not a substitute filesystem editor.
Use the existing dependency lockfile. Add a dependency only when justified in the
accepted plan. Keep changes readable, bounded and reversible; avoid unrelated
formatting/refactoring. If a real check fails, fix the responsible layer and retain
the regression proof. Do not weaken a check to make it green.

Use Playwright for rendered evidence at 1440×900, 390×844, 320×568 and 844×390.
Wait for the actual settled scene state before capturing. Use true touch context
settings where supported; a viewport resize is not physical-device testing.
Do not claim unavailable Safari, phone, GPU-memory or Blender tests passed.

Required gates: npm run build; npm run lint; node tools/checks/fridge-motion.mjs;
node tools/checks/routes.mjs; node tools/checks/mapping.mjs; accepted production
delivery checks; independent final visual QA. Return changed files, actual command
exit codes/output locations, real screenshot paths, preview URL, limitations and
open dependencies. Review your own git diff before declaring completion.

## Boundary before infrastructure

Infrastructure implementation starts only after the ready dashboard slice and
independent review are accepted. Missing teammate services remain explicit gates
for end-to-end live completion. Infrastructure then follows its own detailed
brief → read-only plan → lead review → agy implementation → lead review cycle.
Khang's infrastructure scope is infra/k8s. Shared infra/docker-compose.yml belongs
to Dang. The project targets local Mac/k3d, not cloud; vision inference stays on
macOS. Start from one working event-bus node before replication, autoscaling or
observability expansion. No video work in this phase.
