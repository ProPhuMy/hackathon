# Implementation Plan: Live Backend Integration, Content-Hashed Model, and Production Serving

**Role:** `frontend-integrator`  
**Workspace:** `/private/tmp/fridge-ship-2wgggr96/frontend-integrator/dashboard`  
**Context & Baseline:** Integration against backend at `../services/backend` (commit `619d1ed`), canonical contracts at `../contracts/fridge.event.schema.json`, and existing baseline preview on `http://127.0.0.1:5176`.

---

## 1. Overview & Architecture Strategy

### 1.1 Dual-Mode Operation (`Live` vs `Demo`)
- **Mode Toggle:** Driven by the build-time environment variable `VITE_API_BASE`.
  - When `VITE_API_BASE` is unset (or empty): Preserves the self-contained, labelled local demo data (`043`–`048` items, hardcoded roommate demo events, and slot mapping).
  - When `VITE_API_BASE=/api`: Enables live mode connecting via same-origin `/api` to the backend.
- **Fail-Closed Guarantee:** Live errors (network down, HTTP 503 matcher failure, 5xx) must **never** silently fall back to demo data. If live mode is active and the backend is unreachable or unhealthy, the UI displays an explicit error/reconnecting banner with a retry trigger.
- **Status Indicator:**
  - Demo mode: `● LOCAL DEMO` / `ONE FRIDGE. FOUR ROOMMATES.`
  - Live mode: `● LIVE BACKEND` / `CONNECTED / SSE ACTIVE` (or `● RECONNECTING / STALE` if stream breaks, `● SERVICE UNAVAILABLE (503)` if matcher fails).

### 1.2 SSE Invalidation with Authoritative Coalesced Snapshot Refetch
Rather than incrementally applying streaming SSE events to local state (which risks corrupted state upon outbox history replay from `start_after_id = 0`, duplicate events, or out-of-order timestamps):
1. **SSE as Invalidation Trigger:** The frontend opens `${VITE_API_BASE}/stream` (`event: fridge.event`). When an event arrives, it marks the local cache dirty and schedules a debounced refetch (e.g. 100ms).
2. **Coalesced Bounded Refresh:** High-frequency event bursts or historical replay from reconnect are coalesced into a single snapshot query across `/inventory`, `/events?limit=50`, `/alerts?limit=50`, and `/people`.
3. **Race Prevention:** Monotonic request sequence IDs (`fetchSeq`) ensure out-of-order network responses are discarded.
4. **Authoritative Consistency:** The backend's `/inventory` strictly computes state via `consistency.apply` over historical outbox events. Snapshot refetches guarantee the frontend always mirrors authoritative backend projections.

### 1.3 3D Fridge Slot Decoupling in Live Mode
- In demo mode, `src/itemMapping.js` maps fixed slots `0..5` to demo IDs `043..048`.
- In live mode, backend items have dynamic UUIDs or arbitrary strings (`milk_01`, `cheese_02`). Live items **must not** attach to demo 3D meshes even if an ID happens to match.
- The 3D scene remains interactive as an illustrative visualization:
  - Interior header labels: `ILLUSTRATIVE FRIDGE · 3D PLACEMENT UNAVAILABLE FOR LIVE ITEMS`.
  - Picking a mesh or clicking shelf slots in live mode displays an honest prompt: `"3D mesh placement is unavailable for live inventory. View full receipts in Inventory."` and routes to `/inventory`.

---

## 2. Exact File Plan

### Modified Existing Files
| File | Changes |
| --- | --- |
| `vite.config.js` | Add local dev proxy forwarding `/api` to `http://localhost:8000` (or `process.env.VITE_BACKEND_URL`), rewriting path prefix `/api` $\to$ `/`. |
| `src/App.jsx` | Integrate live data adapter hook (`useFridgeData`), dynamic alert counts, live receipts, safe URL decoding for real item/event IDs, truthful person registration, and live fail-closed banners. |
| `src/Fridge3D.jsx` | Import content-hashed GLB via Vite asset pipeline (`import modelUrl from './assets/mini-fridge.glb'`) instead of `public/models/mini-fridge.glb?v=3`. Support live disclosure state when inspecting 3D slots. |
| `src/itemMapping.js` | Guard `resolveItemBySlot`: return `null` in live mode so live items never attach to fixed demo meshes. |
| `tools/checks/fridge-motion.mjs` | Update GLB path assertion to point to `src/assets/mini-fridge.glb`. |
| `tools/checks/routes.mjs` | Test deep links using realistic backend string IDs (e.g. `/items/milk_01`, `/events/uuid-test-1234`). |

### New Files
| File | Purpose |
| --- | --- |
| `src/api.js` | Bare-list API client (`/inventory`, `/events`, `/alerts`, `/people`, `POST /people`), input validation, and SSE event listener. |
| `src/useFridgeData.js` | React hook managing dual-mode state, snapshot coalescing, abort signals, reconnection backoff, and stale/error states. |
| `src/assets/mini-fridge.glb` | Moved from `public/models/mini-fridge.glb` (identical bytes, preserved DoorPivot and Food_0..5 metadata) to enable Vite content hashing. |
| `Dockerfile` | Multi-stage non-root container (`node:22-alpine` builder $\to$ `nginxinc/nginx-unprivileged:1.27-alpine` runner on port 8080). |
| `nginx.conf` | Unprivileged Nginx configuration with SPA history fallback, asset immutability, `/healthz` probe, and unbuffered `/api/` proxy. |
| `tools/checks/model-asset.mjs` | Build assertion verifying single content-hashed GLB in `dist/assets/`, no duplicate in `dist/models/`, and hash mutation on byte changes. |
| `tools/checks/live-adapter.mjs` | Mock contract fixture test verifying bare-list parsing, SSE debouncing, 503 fail-closed behavior, and person validation. |
| `tools/checks/production-serving.mjs` | Production container/server test verifying SPA fallback, cache headers, non-root user, and proxy endpoints. |

### Deleted / Moved Files
| Action | File | Reason |
| --- | --- | --- |
| Move / Delete | `public/models/mini-fridge.glb` | Moved to `src/assets/mini-fridge.glb` to prevent 6.6 MB duplication in `dist/`. |

---

## 3. Data Adapters & Backend Contract Specifications

### 3.1 Endpoint Mapping
| Method | Endpoint | Request Body | Response Shape |
| --- | --- | --- | --- |
| `GET` | `/api/inventory` | — | Bare list: `[{ item_id: string, item_label: string, owner_id: string \| null, since_ts: string }]` |
| `GET` | `/api/events?limit=50` | — | Bare list of canonical `fridge.event` objects, newest first |
| `GET` | `/api/alerts?limit=50` | — | Bare list of canonical `fridge.event` with `status IN ('wrong_owner', 'uncertain')` |
| `GET` | `/api/people` | — | Bare list: `[{ person_id: string, name: string, enrollment_status: 'unknown', created_at, updated_at }]` |
| `POST` | `/api/people` | `{ person_id: string, name: string }` | 201 Created: returns full person record; 409 on duplicate ID; 422 on invalid schema |
| `GET` | `/api/stream` | Header `Last-Event-ID` (optional) | SSE stream: `id: <uuid>\nevent: fridge.event\ndata: {...}\n\n` with `: ping\n\n` keepalive |

### 3.2 Data Normalization & Handling Rules
1. **Items:**
   - Display name: `item_label || item_id`.
   - Owner display: Resolve `owner_id` against `/people` roster name; if null or unmapped, show `owner_id || 'Unknown owner'`.
   - Deep link: `/items/${encodeURIComponent(item_id)}`.
2. **Events & Alerts:**
   - Deep link: `/events/${encodeURIComponent(event_id)}`.
   - Confidence: Displayed as formatted percentage `Math.round(confidence * 100)%`.
   - Status mapping:
     - `ok`: Verified.
     - `wrong_owner`: Ownership Mismatch (alert).
     - `uncertain`: Uncertain Identity (alert).
   - Person/Taker: Resolved person name or `"Person not reliably recognized"`.
3. **People & Truthful Enrollment:**
   - Display: Displays actual `person_id`, `name`, and truthfully shows `ENROLLMENT: UNKNOWN`.
   - Form Fields: Strictly asks for `person_id` (validated: `^[a-zA-Z0-9_-]+$`, 1–64 characters) and `name` (1–100 characters, no control characters).
   - Truthful Disclosure: No fake face enrollment. Notice explicitly states: *"Metadata registered. Face enrollment is handled by Vision service (Role 1)."*
4. **Dynamic Header & Footer Signals:**
   - Header: Nav badge displays `{alerts.length}` dynamically (hidden if 0).
   - Footer: Displays latest alert (`"LATEST SIGNAL: Someone took [Owner]'s [Item]"` or `"Uncertain take"`); if no alerts, displays latest event or `"SYSTEM IDLE · ALL CLEAR"`.

---

## 4. Content-Hashed Model & Production Serving Plan

### 4.1 Content-Hashed GLB Pipeline
1. **Source Location:** Move GLB to `src/assets/mini-fridge.glb`.
2. **Vite Ingestion:** In `src/Fridge3D.jsx`:
   ```javascript
   import fridgeGlbUrl from './assets/mini-fridge.glb'
   // ...
   const { scene } = useGLTF(fridgeGlbUrl)
   ```
3. **Duplication Elimination:** Because the file is no longer in `public/models/`, Vite only emits a single asset: `dist/assets/mini-fridge-[hash].glb`. The build artifact avoids duplicating 6.6 MB.
4. **Verification:** `tools/checks/model-asset.mjs` verifies that `dist/models/` is empty, `dist/assets/*.glb` has exactly 1 file matching source SHA-256, and that changing a byte produces a different filename hash.

### 4.2 Non-Root Production Container (k3d Ready)
- **Base Images:**
  - Build stage: `node:22-alpine` (runs `npm ci` and `VITE_API_BASE=/api npm run build`).
  - Runtime stage: `nginxinc/nginx-unprivileged:1.27-alpine` (runs as non-root user `nginx`, UID 101, listening on port 8080).
- **Nginx Configuration Features:**
  - `listen 8080;`
  - `location /healthz { return 200 'OK\n'; add_header Content-Type text/plain; }`
  - SPA Fallback: `location / { try_files $uri $uri/ /index.html; }`
  - Caching Policy:
    - `/index.html`: `Cache-Control: no-cache, no-store, must-revalidate;`
    - `/assets/`: `Cache-Control: public, max-age=31536000, immutable;`
  - API & SSE Reverse Proxy:
    ```nginx
    location /api/ {
        proxy_pass http://${BACKEND_HOST:-fridge-backend}:${BACKEND_PORT:-8000}/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
    }
    ```
- **Local Isolation:** Keeps all container configuration within `dashboard/`. Does not modify `infra/docker-compose.yml`.

---

## 5. Implementation Sequence

1. **Step 1: Model Asset Relocation & Build Hash Verification**
   - Move `public/models/mini-fridge.glb` to `src/assets/mini-fridge.glb`.
   - Update `Fridge3D.jsx` import.
   - Update `tools/checks/fridge-motion.mjs`.
   - Create `tools/checks/model-asset.mjs` to assert single hashed asset output and zero duplication.
2. **Step 2: API Client & Resilient Live Hook**
   - Implement `src/api.js` with bare-list fetchers, validation, and SSE reader.
   - Implement `src/useFridgeData.js` with dual-mode toggle (`VITE_API_BASE`), snapshot invalidation, debouncing, AbortController cancellation, and stale/error tracking.
   - Create `tools/checks/live-adapter.mjs` with contract fixture server.
3. **Step 3: UI Integration & Live State Wiring**
   - Wire `App.jsx` to live data hook.
   - Implement dynamic alerts, live history, people registration, and safe deep linking.
   - Enforce fail-closed state on backend failure (no silent demo fallback).
   - In `src/itemMapping.js`, disable 3D slot attachment in live mode and add UI disclosure.
4. **Step 4: Production Serving & Container Boundary**
   - Configure Vite dev proxy in `vite.config.js`.
   - Write `dashboard/Dockerfile` and `dashboard/nginx.conf`.
   - Create `tools/checks/production-serving.mjs` to verify SPA routing, headers, and `/healthz`.
5. **Step 5: Full Verification Suite Run**
   - Execute all checks: build, lint, motion, routes, mapping, model asset, adapter, and serving.

---

## 6. Verification Plan & Test Cases

### Automated Test Gates
```bash
# 1. Standard build and lint
npm run build
npm run lint

# 2. Existing checks
node tools/checks/fridge-motion.mjs
node tools/checks/routes.mjs
node tools/checks/mapping.mjs

# 3. New contract & integration checks
node tools/checks/model-asset.mjs        # Proves single hashed GLB & no duplication
node tools/checks/live-adapter.mjs       # Proves bare-list contract, SSE coalescing & 503 fail-closed
node tools/checks/production-serving.mjs # Proves SPA fallback, cache headers & healthz
```

### Key Contract Test Cases Covered in `live-adapter.mjs`
1. **Bare-list contract parsing:** Validates parsing of `/inventory`, `/events`, `/alerts`, and `/people` without wrapper objects.
2. **Replay coalescing:** Simulates an SSE outbox replay of 50 `fridge.event` messages in 50ms; asserts that exactly 1 snapshot refetch is fired.
3. **Fail-Closed on 503:** When backend returns 503 (matcher failed), verifies UI sets error state and does not revert to demo items.
4. **Person Validation:** Verifies registration rejects invalid IDs (spaces, control characters) and prohibits client-supplied `enrollment_status`.
5. **Safe Deep Links:** Verifies URL-encoded parameter extraction for item IDs containing special characters.

---

## 7. Rollback & Dependencies

- **Zero Dependency Additions:** No new packages added to `package.json`. Relies solely on native Web APIs (`fetch`, `EventSource`, `AbortController`) and Node built-ins (`node:assert`, `node:http`, `node:crypto`, `node:fs`).
- **Rollback:** Single-command rollback to baseline:
  ```bash
  git checkout -- src/ vite.config.js tools/ public/
  rm -f src/assets/mini-fridge.glb src/api.js src/useFridgeData.js Dockerfile nginx.conf tools/checks/model-asset.mjs tools/checks/live-adapter.mjs tools/checks/production-serving.mjs
  ```
- **Astra / Lead Sign-Off Gate:** This plan requires lead approval before writing code. Existing live preview on port 5176 remains the baseline.
