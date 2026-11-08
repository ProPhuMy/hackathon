# QA-2 integrated review — blocked

The visual-qa worker was dispatched with Gemini against the combined accepted preview at http://127.0.0.1:5176/, from its refreshed isolated checkout. It returned HTTP 429 RESOURCE_EXHAUSTED for the daily gemini-3.1-pro generate-request quota (provider-reported limit 250, retry approximately five hours later). It returned no final review. Production files were unchanged by this QA attempt.

Independent combined-preview sign-off is **pending**, not passed. QA-1 baseline review was completed earlier; see baseline-qa.md. The prepared QA-2 assignment remains in the temporary team's briefs/qa-integrated.md and its criteria are in docs/team-dispatch.md.

## Lead verification completed separately

- Final build, lint, motion/model, seven-route and mapping checks all exit 0; Python runner syntax passes. See evidence/final-checks.txt.
- Chrome 156 headless at 1440×900, 390×844, 320×568, 844×390: all six accessible item routes, item opener focus and exit focus, reduced-motion endpoints, native dialogs, direct links, back/forward and interrupted entry pass. Touch contexts use hasTouch/isMobile where appropriate. No page errors or measured navigation/control collisions; touch-sized shelf targets are 44px. See evidence/final-browser-results.json.
- Six real desktop mesh clicks map to IDs 043..048 on their corresponding shelves. The original adjacent-shelf click at 320×568 no longer opens Cold brew while Top shelf is selected. Selection predicate checks also cover transition suppression.
- Final forced GLB failure and unavailable WebGL both show the static photograph, enabled Browse inventory and usable Inventory. Reduced-motion exit returns focus. Final fallback captures are retained in evidence/.
- Wheel check: tiny input ignored; deliberate input moves one shelf; burst input throttled; later input accepted; ArrowUp selects the preceding shelf.
- Same-device dev-server comparison after the motion change: approximately 60 rAF FPS before/after, 93 exterior and 71 interior draw calls/frame unchanged, readiness 942ms baseline / 924ms after. These are local fresh browser contexts with warm OS cache, not target-device or production-load certification. GPU memory unavailable. Model and .blend hashes unchanged.

## Remaining independent coverage

Repeat the complete QA-2 brief once Gemini quota is available. Include final normal-motion touch flows, settled-state screenshots, focus trapping, wheel behavior, picking during shelf transitions and browser errors. Actual Safari, older phones, hardware touch and GPU-memory profiling remain untested; emulation does not substitute for them. Final Figma synchronization waits for independent visual sign-off.
