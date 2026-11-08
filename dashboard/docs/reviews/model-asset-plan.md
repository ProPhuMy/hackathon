# Implementation Plan: Vite Content-Hashed 3D Model Asset Delivery

## Goal Description
Transition the 3D fridge model from a static unhashed public file (`public/models/mini-fridge.glb?v=3`) to Vite content-hashed asset delivery (`src/assets/mini-fridge.glb`). This preserves exact asset bytes (6,620,040 bytes, 53 nodes, 46 primitives, 187,068 triangles), maintains lazy loading and preloading contracts, eliminates duplicate assets in production builds, updates Blender rebuild/export targets and motion assertions, and adds a dedicated verification check for single-GLB emission and content-hash mutation.

---

## User Review Required
> [!IMPORTANT]
> - **Zero geometry/material/motion rebuild**: The existing binary `mini-fridge.glb` is moved byte-for-byte without running a Blender export or touching geometry, materials, `.blend`, or camera coordinates.
> - **Out-of-scope files preserved**: `App.jsx`, `App.css`, `datahook/client`, `src/itemMapping.js`, `Dockerfile`, `vite.config.js`, `README.md`, fonts, and `public/images/` will not be modified.

---

## Proposed Changes

### 1. Asset Relocation
- **Move**: [`public/models/mini-fridge.glb`](file:///private/var/folders/wt/jmtpq7xx6dg_7qkwsqv1t3fm0000gn/T/fridge-dashboard-zgvb55xu/3d-modeler/dashboard/public/models/mini-fridge.glb) $\rightarrow$ `src/assets/mini-fridge.glb`
- **Integrity**: Verify exact binary size matches baseline 6,620,040 bytes and SHA-256 hash before deleting the public copy.
- **Cleanup**: Remove `public/models/mini-fridge.glb` (and clean up `public/models/` if empty) to ensure no duplicate or unhashed asset is copied into production `dist/`.

---

### 2. Renderer URL & Preload
#### [MODIFY] [`src/Fridge3D.jsx`](file:///private/var/folders/wt/jmtpq7xx6dg_7qkwsqv1t3fm0000gn/T/fridge-dashboard-zgvb55xu/3d-modeler/dashboard/src/Fridge3D.jsx)
- Import the model using Vite's explicit URL asset query:
  ```javascript
  import fridgeModelUrl from './assets/mini-fridge.glb?url'
  ```
- Replace line 15:
  ```diff
  - const { scene } = useGLTF('/models/mini-fridge.glb?v=3')
  + const { scene } = useGLTF(fridgeModelUrl)
  ```
- Add module preload with the shared URL at the bottom of the module:
  ```javascript
  useGLTF.preload(fridgeModelUrl)
  ```
- Maintain lazy loading: Since `Fridge3D.jsx` is dynamically loaded via `React.lazy` in `App.jsx`, importing the asset inside `Fridge3D.jsx` ensures the asset chunk and GLB URL are only evaluated when the 3D view is activated.

---

### 3. Blender Rebuild & Export Scripts
#### [MODIFY] [`tools/blender/build_fridge.py`](file:///private/var/folders/wt/jmtpq7xx6dg_7qkwsqv1t3fm0000gn/T/fridge-dashboard-zgvb55xu/3d-modeler/dashboard/tools/blender/build_fridge.py)
- Update the export directory from `public/models` to `src/assets`:
  ```diff
  - (root/'public/models').mkdir(exist_ok=True)
  - bpy.ops.export_scene.gltf(filepath=str(root/'public/models/mini-fridge.glb'),export_format='GLB',use_selection=True,export_apply=True,export_yup=True,export_extras=True)
  + (root/'src/assets').mkdir(exist_ok=True)
  + bpy.ops.export_scene.gltf(filepath=str(root/'src/assets/mini-fridge.glb'),export_format='GLB',use_selection=True,export_apply=True,export_yup=True,export_extras=True)
  ```

#### [MODIFY] [`tools/blender/remodel_via_mcp.py`](file:///private/var/folders/wt/jmtpq7xx6dg_7qkwsqv1t3fm0000gn/T/fridge-dashboard-zgvb55xu/3d-modeler/dashboard/tools/blender/remodel_via_mcp.py)
- Confirm `fridge_dashboard_root` resolution aligns with the new `src/assets` destination and any verify output messages reflect authoritative paths.

---

### 4. Existing Motion & Model Test Assertions
#### [MODIFY] [`tools/checks/fridge-motion.mjs`](file:///private/var/folders/wt/jmtpq7xx6dg_7qkwsqv1t3fm0000gn/T/fridge-dashboard-zgvb55xu/3d-modeler/dashboard/tools/checks/fridge-motion.mjs)
- Update model assertion path at line 39:
  ```diff
  - const file = readFileSync(new URL('../../public/models/mini-fridge.glb', import.meta.url))
  + const file = readFileSync(new URL('../../src/assets/mini-fridge.glb', import.meta.url))
  ```
- Retain all existing assertions: glTF magic header, `DoorPivot` child hierarchy, 6 `Food_0`–`Food_5` nodes with `itemIndex`, and single self-contained buffer check.

---

### 5. Dedicated Model Asset Verification Check
#### [NEW] `tools/checks/model-asset.mjs`
Automated check using Node standard libraries (`node:fs`, `node:path`, `node:crypto`, `node:assert/strict`, `node:os`) and Vite programmatic API (`import { build } from 'vite'`):
1. **Source Asset Integrity**:
   - Asserts `src/assets/mini-fridge.glb` exists.
   - Asserts exact size: `6,620,040` bytes.
   - Asserts valid glTF header (`0x46546C67` / `glTF`).
   - Asserts `public/models/mini-fridge.glb` does NOT exist.
2. **Single GLB Build Output**:
   - Runs `vite.build()` (or inspects standard build output).
   - Scans `dist/`: confirms exactly one `.glb` file exists (located at `dist/assets/mini-fridge-[hash].glb`).
   - Asserts built GLB payload matches 6,620,040 bytes.
   - Asserts no unhashed GLB exists under `dist/models/`.
3. **Content-Hash Mutation Verification**:
   - In an isolated temporary directory (never mutating the source asset `src/assets/mini-fridge.glb`):
     - Copies minimal build harness or runs isolated build with a mutated 1-byte payload.
     - Confirms the resulting output asset hash in the filename is strictly different from the baseline hash.
     - Always cleans up temporary directories in a `finally` block to guarantee source integrity.

---

## Verification Plan

### Automated Tests
Execute sequentially from the dashboard root:
```sh
# 1. Verify fridge motion and relocated GLB node/buffer contract
node tools/checks/fridge-motion.mjs

# 2. Verify model asset delivery: exact bytes, single GLB, content hash & mutation
node tools/checks/model-asset.mjs

# 3. Verify production Vite build (emits single hashed GLB in dist/assets/)
npm run build

# 4. Verify route rendering and SSR loader module compatibility
node tools/checks/routes.mjs

# 5. Linter check
npm run lint
```

### Manual Inspection & Post-Build Assertions
- Inspect `dist/` directory structure to confirm:
  - `dist/assets/mini-fridge-[hash].glb` is present (~6.62 MB).
  - No `dist/models/` directory or duplicate `.glb` exists.
- Confirm SHA-256 hash of `src/assets/mini-fridge.glb` is identical to original `public/models/mini-fridge.glb`.
