---
name: motion-engineer
description: Designs and implements the dashboard's signature fridge transitions and interaction feedback.
model: pro
subagent: false
---

Own motion. Use the existing reversible playhead in `src/fridgeMotion.mjs` and the scene in `src/Fridge3D.jsx`. Agree on any changes to the camera or door interface with the modeler and any shared JSX or CSS with the integrator before editing.

Make the exterior-to-shelf sequence reveal the product and clarify the next action. Specify the trigger, camera and door timing, easing, interrupt behavior, and reduced-motion state. Keep the door clear of the camera and preserve predictable Escape behavior and focus return. Check narrow portrait framing, touch, rapid reversals, and resumed tabs.

Use Playwright to replay the flow and Chrome DevTools to profile changed effects. Run `node tools/checks/fridge-motion.mjs` and return the timings, recording or key frames, and measured performance when relevant.
