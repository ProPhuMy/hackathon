# Lead decisions after reviewing UX and QA evidence

Approved: fix narrow exterior invitation/footer overlap, give mobile targets at least 44px height, keep short-landscape controls compact and reachable, preserve current identity and 3.8s reversible timing. Retain native dialog Escape/focus behavior and existing GLB failure recovery.

Corrections to UX report: this is a warm light theme, not dark; image.png is a typography reference, NOT fallback artwork. Fallback is public/images/fridge-front.png. Do not replace it or remove working inventory access. No mobile menu redesign is commissioned. Short-landscape shelf navigation is on the left, not right. Baseline failure tests passed; only adjust fallback framing if reproduced necessary.

Lead evidence is in /Users/khang/Desktop/hackathon/dashboard/docs/reviews/evidence. Both selected foods must remain identifiable and clickable. Report any visible adjacent-shelf food that can open an item inconsistent with selected shelf; this matters for stable mapping. Do not optimize geometry merely from file size: local baseline (Chrome 156 headless, 1440x900, dev server, fresh browser context/warm OS cache) measured ~60 rAF FPS, 93 exterior and 71 interior draw calls, GLB 6,620,040 bytes/187,068 exported triangles. Real older-device/GPU-memory testing is still pending.

Model/motion interface stays frozen this wave: DoorPivot transform and -2.05 rotation; Food_0..5 nodes and legacy itemIndex 0..5; shelf heights 1.48/1.08/.68. No geometry/material or ID metadata migration in MOD-1. Integrator will use a named-slot→stable demo-ID adapter and gracefully ignore missing/unmapped records, with explicit reorder/removal/addition tests; future backend/model IDs await a contract.

## Confirmed mesh mismatch

Lead reproduced on baseline Chrome at 320×568: enter Top shelf, wait 4.6 seconds, click canvas coordinate (236, 478), which is a visible Cold brew mesh from the middle shelf. URL becomes `/items/046` while selected shelf remains Top. Filter mesh click and hover by the selected shelf and suppress stale mesh clicks while shelf height is transitioning. This is a code-supported functional bug, not just a visual concern. Evidence: lead-adjacent-mesh.png in the temporary result directory.
