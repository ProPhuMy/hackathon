# INT-1 accepted integration

The frontend-integrator implemented stable demo-ID resolution, matching shelf-button lookup, mapping checks and responsive CSS in its isolated checkout. Lead reviewed both the initial diff and the scoped revision.

## Accepted behavior

- `src/itemMapping.js` maps fixed legacy mesh slots to demo IDs 043..048. Reordering inventory preserves identity; missing records return null and their buttons are omitted; extra inventory records remain in Inventory but are not assigned arbitrary model slots. This is a demo adapter, not an agreed backend ID contract.
- Mobile navigation forms one row with 44px targets. Exterior scene bounds reserve invitation and footer space; immersive canvas remains full viewport.
- Mobile shelf buttons have 44px targets. Short landscape uses separate horizontal shelf and item control groups.
- Existing routes, lazy loading, model fallback and demo disclaimers remain.

## Lead corrections and review evidence

Initial CSS was rejected: its intro overlapped mobile navigation and its short-height heading covered the exit. Initial claimed screenshots were absent. Revision produced real screenshots and improved portrait layout, but still needed explicit landscape widths and header/intro separation. Lead corrected these small CSS rules and fallback placement.

The integrator's duplicate closePanel and timer-based focus patch was removed in revision. Independent browser testing then reproduced native focus loss when a routed item dialog was removed. Lead added opener capture/restoration in Modal, preserving that opener across React StrictMode effect replay and avoiding close events during cleanup.

Final lead browser matrix passed at 1440×900, 390×844, 320×568 and 844×390: no nav/intro, exit/heading or shelf/item control collisions; no horizontal overflow; 44px shelf targets in touch-sized views; all six accessible item routes and opener focus; scene exit focus; seven direct routes; back/forward; interrupted entry. Touch contexts use hasTouch/isMobile, not viewport resize alone. No page errors. See evidence/final-browser-results.json and final screenshots. Independent QA is tracked in integrated-qa.md.

The worker's preview was localhost:5177 (later a bundle at 4173). The accepted combined preview is http://127.0.0.1:5176/.
