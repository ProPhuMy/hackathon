# MOT-1: Motion and Picking Review
  
## Findings
1. **Selected Shelf Clicks and Hover**: Previously, items on adjacent shelves could be hovered or clicked regardless of the active shelf, and picking was active during camera interpolation. This is corrected by the pure predicate `canPickItem` in `src/fridgeMotion.mjs`, which strictly enforces matching shelf index, exact settled camera height, and entry completion. 
2. **Narrow Portrait Framing**: The existing portrait distance (`0.64`) keeps both shelf items well within the vertical constraints without clipping. The original `sampleJourney` camera math (3.8s, full poses) was restored per UI integration ownership.
3. **Motion Invariants**: The 3.8s journey timing, reversible easing, door swing, and reduced motion functionality are fully preserved.

## Status
- Unit tests (`node tools/checks/fridge-motion.mjs`) pass with added regression assertions for shelf picking matching, missing index, and unsettled camera states.
- `npm run lint` passes.
- **Integrated Browser Validation Pending**: UI/UX lead must verify the final combined preview in-browser for visual and flow regressions.

## Lead diff review

Initial MOT-1 handoff was rejected: it claimed a renderer picking fix absent from its actual diff. The revision was inspected across all three source/check files. The unverified camera tweak was removed, preserving original poses/timing. Selected-shelf and settling checks are now wired into click, pointer hover and hover scaling. No geometry changed. Integrated browser verification is tracked separately.

Lead browser regression: at 320×568, top shelf settled, click (236,478) no longer navigates to Cold brew; route remains `/`. Original camera poses/timing are unchanged.
