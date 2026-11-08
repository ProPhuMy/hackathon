# Fridge dashboard

For completed work, verification evidence, and prioritized next steps, see
[the implementation and handoff log](docs/implementation-log.md).

React + Vite frontend for Fridge Tracker. The main screen follows Khang’s
`mainscreen.png` sketch: navigation at the top left, pixel typography, and a
large interactive mini fridge. A Blender GLB now provides the model; the original
Figma photograph remains as the fallback.

```sh
npm ci
npm run dev
npm run build
npm run lint
```

Click the fridge or “Open the fridge” for a 3.8-second orbit, door-opening,
and dolly into a full-screen interior. Navigation and the invitation fade away.
The top-left “Leave the fridge” control or Escape reverses the same path, even
mid-entry. Select shelves with their buttons, the mouse wheel, or ↑ / ↓.
Select a food model or its labeled button for owner and item details. Top-left navigation opens inventory (search and owner
filter), event history (search), alerts (event inspection), and people panels.
Escape closes a panel first, then exits the fridge. Focus returns to the opening
control after exit. Reduced-motion preferences switch directly between views.

All inventory, people and events currently use illustrative local demo data.
Adding a demo person lasts for the current page session; live registration,
face capture, API requests and SSE updates await the backend integration.

The selected Fridge Pixel font follows `image.png`. Font sources and usage
notes are in `public/fonts/README.md` and `tools/build_fridge_pixel.py`.

## TanStack routing and Blender model

TanStack Router now owns `/`, `/inventory`, `/history`, `/alerts`, `/people`,
`/items/$itemId`, and `/events/$eventId`. The persistent root preserves the
fridge scene while panels follow the URL, including direct links and back/forward.
Run `node tools/checks/routes.mjs` for the focused route checks.

`src/Fridge3D.jsx` renders `public/models/mini-fridge.glb` with React Three Fiber.
The model was authored through the community MCP for Blender server. Its
53 nodes contain roughly 99,000 modeled polygons, merged by material and parent
for fewer draw calls. Details include folded satin-metal panels, a recessed grip,
layered seals, glass shelves, a crisper drawer, a freezer flap, vents, thermostat,
LED strips, and six separately selectable food groups with printed packaging.
The self-contained GLB is about 6.3 MB. `DoorPivot` owns the door and `Food_0`
through `Food_5` carry item indices. The renderer remains lazy-loaded.
WebGL/model errors retain the photograph and inventory access.

`src/fridgeMotion.mjs` defines the reversible camera path. The door clears before
the camera moves through the opening. Each shelf has its own close-up viewpoint;
portrait framing backs away slightly to keep both food items visible. Hover adds
a subtle scale response, and the inside camera has restrained pointer parallax.
Run `node tools/checks/fridge-motion.mjs` for reversal, reduced-motion, camera
clearance, aspect ratio, and exported-model checks.

The editable Blender source and rebuild scripts are in `tools/blender/`.
Blender must be running with its MCP addon listening on loopback port 9876.
Install `uv` and make `uvx` available on `PATH`; the runner resolves it there
instead of requiring a contributor-specific executable path.
The Codex MCP server is registered as `blender` (`uvx mcp-for-blender`).
Rebuild from the repository root:

```sh
uv run --with mcp python dashboard/tools/blender/remodel_via_mcp.py
uv run --with mcp python dashboard/tools/blender/remodel_via_mcp.py --verify
# Optional: offline model/camera QA renders, without saving the source scene
uv run --with mcp python dashboard/tools/blender/remodel_via_mcp.py --render
```

Deployments must serve `index.html` for frontend routes. This remains a Vite
SPA with TanStack Router; it does not add TanStack Start server rendering.
The Three.js renderer adds an approximately 283 KB gzipped lazy-loaded chunk.

## Demo model mapping

`src/itemMapping.js` maps the six fixed model slots to demo IDs `043`–`048`.
Mesh inspection and shelf buttons both resolve by ID, so inventory order can
change safely. Missing records are not opened and their shelf buttons are omitted;
new, unmapped records remain available in Inventory. Mesh picking and hover are
limited to the selected shelf after its camera transition settles.

Run `node tools/checks/mapping.mjs` for the mapping checks. The GLB retains its
legacy `itemIndex` metadata; live server IDs and dynamic model placement still
require the backend contract. See [the team review](docs/team-dispatch.md) for
accepted changes, browser evidence, and remaining dependencies.
