# Main synchronization checkpoint — 2026-11-07

User requested fetching latest main, merging locally and pushing before further
implementation. Original checkout was already on main. Fetched origin/main at
007f6a4 (includes person/item work and Phong backend PR), merged cleanly with
local history, and preserved all97 pending files byte-for-byte through merge.
The reviewed dashboard, model source/assets, references and review evidence are
being committed together. No unfinished worker patch was copied into the app.

Verification after merge: npm run build, npm run lint, motion/model, all7 route
checks and mapping checks PASS. Known large lazy3D chunk warning remains.
The unchanged backend previously passed all191 tests using isolatedPostgres15432;
newly fetched person/item model pipelines have not been runtime-validated here.
Git whitespace check identifies two preexisting blank lines with trailing spaces
(App.css:158 and App.jsx:77); no behavioral failure. Credentials stay ignored.

Workers are stopped. The resumed integrator conversation retained a read-only
planning toolset and returned proposed code in text, not accepted source edits;
its output also ended in a stream interruption. Modeler planning ended with a
provider connection reset. Resume with a fresh accept-edits coding conversation
and the reviewed detailed brief, verify actual write tools/diffs, and do not treat
text-only code or earlier worker claims as implementation.

Next: re-read new person/item setup and backend contracts; recreate worker
checkouts from updated main; finish agy live integration and asset release work
under docs/briefs and docs/reviews/dashboard-plan-review.md, then independent
combined-preview QA. Only after dashboard acceptance proceed to infra/k8s.
Video remains deferred until project completion. User's agy plan → lead review →
agy code → lead review workflow remains in force. Below is historical context.

---

# Active continuation — dashboard then infrastructure

Updated 2026-11-07. This section supersedes older queue/provider notes below.
User requires agy to write implementation: detailed brief → agy plan → lead
review → agy code → lead diff/check/browser review. Complete dashboard first,
then infra/k8s. Video waits until project completion. Current signed-in agy
provider is usable; do not assume the old Gemini API daily quota still blocks it.

- Phong pushed origin/phong commit619d1ed. Lead fetched and merged it cleanly;
  divergent documentation history required a merge commit, with no conflicts.
  All 80 previously snapshotted pending dashboard files remained byte-identical.
- Backend checks: uv run pytest -q →188 passed,3 skipped,2 deprecation warnings.
  API inventory/events/alerts/people/SSE and person metadata registration now
  exist. Enrollment remains unknown; no auth or dynamic model placement contract.
- Active: frontend-integrator read-only revised plan against real backend;
  visual-qa independent baseline review at http://127.0.0.1:5176/.
- Detailed briefs: docs/briefs/dashboard-completion.md and backend-integration.md.
- Temporary worktrees/raw results: /private/tmp/fridge-ship-2wgggr96. No product
  code accepted in this continuation yet. Preserve pending original work.
- Docker Desktop was started for subsequent production serving verification.
  No infrastructure deployment has begun. k3d/helm not on PATH, kubectl has no
  current context. Root shared compose is unchanged.

Next: review agy integration plan before authorizing code; use same-origin proxy,
truthful live/demo state, stable backend IDs, SSE invalidation and metadata-only
registration. Validate production serving and independent combined preview,
then brief and plan infra/k8s. Do not call dashboard/live-system finished until
these gates have evidence. Save latest status here when stopping.

---

# Next-session checkpoint — Fridge Tracker

Saved: 2026-11-07, after the coordinated Antigravity pass.
Purpose: resume the unfinished work without repeating accepted implementation.
This is a persistent handoff, not a scheduled task or an automatic retry.

## Current state to preserve

- Accepted changes are in the original dashboard checkout, still uncommitted.
  Preserve all pending work; HEAD alone does not contain the finished dashboard.
- Implemented: responsive portrait/short-landscape layout, 44px touch-sized shelf
  controls, selected-shelf mesh/hover guards, stable demo-ID mapping, dialog
  opener focus restoration across StrictMode, and PATH-based uvx resolution.
- Original 3.8-second reversible camera path and GLB/.blend assets are unchanged.
- Build, lint, motion/model, route and mapping checks passed. Lead Chrome checks
  passed at 1440×900, 390×844, 320×568 and 844×390, including touch contexts,
  focus, picking, wheel, reduced motion and forced model/WebGL fallback.
- Independent baseline QA completed. Independent **combined-preview QA did not**:
  Gemini returned HTTP 429 at its daily gemini-3.1-pro request quota. The retry
  estimate recorded then was about five hours; recheck availability next session
  rather than treating that old estimate as current.
- Last accepted preview: http://127.0.0.1:5176/. Confirm it is serving this checkout
  or start Vite and use its printed URL. Worker previews at 5177/4173 were stopped.
- No commit, publication or deployment was performed.

## First actions on return

1. Read `AGENTS.md`, `README.md`, this checkpoint, `docs/implementation-log.md`,
   `docs/team-dispatch.md` and `docs/reviews/integrated-qa.md`.
2. Inspect current Git status and source changes. Compare relevant files with
   `docs/reviews/evidence/final-source-hashes.json`; newer user changes take
   precedence. Re-run affected checks when the source has changed.
3. Restore a working preview. Prioritize QA-2 below once Gemini quota is available.
   Do not replay completed UX-1, MOD-1, MOT-1 or INT-1 by default.
4. Dispatch at most two independent assignments. Editing workers need separate
   checkouts containing the current pending dashboard work; never start from HEAD
   alone. Review actual diffs and screenshot files before accepting worker claims.
5. Update this checkpoint and the implementation log with new evidence, decisions,
   blockers and the next action when work stops.

The previous team's `/private/tmp/fridge-team-20261107-2128/` contains snapshots,
briefs and raw responses but may disappear. The repository documentation and
`docs/reviews/evidence/` are the durable handoff; recreate temporary checkouts if
needed. Never copy credential files into them.

Antigravity dispatch uses `agy --settings '{"modelProvider":"gemini"}' --agent
<role>` with the appropriate mode and scoped tool permissions. The previous
session's inherited environment lacked GEMINI_API_KEY. The user authorized
`dashboard/.env`, which names the credential ANTIGRAVITY_KEY; the launcher mapped
it into GEMINI_API_KEY for worker processes only. Parse that file safely if still
needed; do not assume it is shell-sourceable or print the credential.

## Pending work, owners and completion gates

| Priority / status | Owner | Next action and files/artifacts | Done when |
| --- | --- | --- | --- |
| P0 — blocked on provider quota | `visual-qa` | Retry QA-2 on the combined preview; update `docs/reviews/integrated-qa.md` and save fresh evidence | Independent report covers the full brief below, with actual screenshots, pass/fail/untested cases and reviewed findings |
| P1 — needs devices/tools | `visual-qa`, with `motion-engineer` / `3d-modeler` for findings | Real Safari, iOS/Android, older hardware, physical touch and performance measurements | Device/browser/cache conditions, FPS/frame timing, draw calls, cold load and available GPU-memory data recorded; unsupported metrics remain explicit gaps |
| P1 — addon responsiveness blocked | `3d-modeler` | Diagnose loopback Blender addon on 9876; `tools/blender/` and a dedicated project scene only | Read-only `--verify` completes; then prove rebuild/render reproducibility without altering unrelated Blender work. The last attempt timed out in addon handshake after 180 seconds |
| P1 — teammate/API dependencies | `frontend-integrator` + Phong; Dang for shared contracts; Viet for enrollment | Reinspect backend progress, agree HTTP/SSE, inventory/person schemas, server IDs, authentication, reconnect/error behavior and enrollment/persistence | Agreed contracts exist and integration tests cover live flows. Until then retain clearly labeled demo data; do not invent endpoints or server IDs |
| P2 — follows agreed ID contract | `frontend-integrator` + `3d-modeler` | Evolve `src/itemMapping.js`, model metadata and shelf placement for dynamic data | Stable server IDs work across meshes/buttons; missing/new items have agreed behavior. The current demo adapter is complete, but GLB still has legacy itemIndex metadata |
| P2 — conditional on measured need | `3d-modeler` + `motion-engineer`, direction from `ui-ux-designer` | Consider compression/LOD, materials, lighting or framing only from device findings | Measured improvement with preserved packaging legibility, picking, door clearance and same-device before/after evidence; no speculative asset growth |
| P2 — queued release work | `frontend-integrator` + lead | Choose hosting/history fallback, replace manual `?v=3` with content-based asset versioning, document release setup | Built deployment serves all deep links, updates model caches correctly and passes release checks; actual commit/deployment follows the user's release instruction |
| P2 — waits for QA-2 sign-off | `ui-ux-designer` + lead | Capture approved exterior, opening, all shelves, item dialog, exit and fallback; synchronize final Figma/FigJam handoff | Approved states, responsive behavior and timing are documented in the design handoff |

Backend observation from this pass: only the event builder and contract test were
present, not HTTP inventory/people endpoints or an SSE server. Recheck this later;
other teammates may have progressed. Respect `contracts/fridge.event.schema.json`
and the root ownership table; dashboard workers do not edit sibling services or
shared contracts.

## Durable QA-2 brief

Review the current combined preview independently; production source is read-only.
Read the accepted integration/motion reports and lead decisions. Preserve the warm
light theme, root sketch and pixel-font reference. Verify:

- Desktop 1440×900, portraits 390×844 and 320×568, short landscape 844×390.
  Capture settled exterior/interior states; no navigation/invitation, exit/heading
  or shelf/item control collisions; touch-sized shelf controls at least 44px.
- True touch emulation where supported, keyboard and wheel; label emulation
  separately from actual hardware tests.
- Every shelf and all six accessible buttons plus matching food meshes. Adjacent
  shelves must not open the wrong item, including during camera interpolation.
  Original reproduction: 320×568, Top shelf, wait until settled, click (236,478);
  this used to open Cold brew `/items/046` and should now leave the route unchanged.
- Item dialog focus trapping; Escape closes the dialog first and restores its
  opener; subsequent Escape exits and focuses Open the fridge. Rapid/interrupted
  entry and exit must not leave controls stuck or hidden.
- Reduced-motion entry, exit and shelf changes. Forced GLB failure and unavailable
  WebGL both retain `fridge-front.png`, an enabled inventory action and navigation.
- All seven direct routes, browser back/forward, missing records and console errors.

Return precise passed/failed/untested cases, reproduction steps, browser/viewport,
and screenshot paths that actually exist. Do not substitute lead verification
for independent sign-off. Route new findings to their responsible role, review
the diff, integrate, and recheck the affected flow.

## Checks after relevant changes / before final sign-off

```sh
npm run build
npm run lint
node tools/checks/fridge-motion.mjs
node tools/checks/routes.mjs
node tools/checks/mapping.mjs
```

Use `uv run --with mcp python tools/blender/remodel_via_mcp.py --verify` from the
dashboard for the read-only addon check when troubleshooting Blender. Blender is
not needed to run the frontend. Compare performance on the same device if motion
or model complexity changes; distinguish export counts from live-scene totals.

Evidence already retained: `docs/reviews/evidence/final-checks.txt`,
`final-browser-results.json`, `mesh-results.json`, performance JSON, source hashes
and screenshots. Local baseline was approximately 60 rAF FPS with 93 exterior /
71 interior draw calls per frame; it does not certify phone performance.
