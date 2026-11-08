# Lead review

Plan approved with one correction: backend heartbeat is15seconds, so the bounded SSE test must allow20seconds, not5. Source implementation had not begun when workers were paused. Lead owns Docker execution; sandbox access was denied.

### Production Serving Plan

#### Objectives & Scope
Deliver a non-root production container, hardened Nginx proxy/caching configuration, and HTTP-based verification suite without touching application source files (`src/`).

**Owned Files:**
1. [Dockerfile](file:///private/var/folders/wt/jmtpq7xx6dg_7qkwsqv1t3fm0000gn/T/fridge-dashboard-zgvb55xu/serving/dashboard/Dockerfile)
2. [nginx.conf.template](file:///private/var/folders/wt/jmtpq7xx6dg_7qkwsqv1t3fm0000gn/T/fridge-dashboard-zgvb55xu/serving/dashboard/nginx.conf.template)
3. [.dockerignore](file:///private/var/folders/wt/jmtpq7xx6dg_7qkwsqv1t3fm0000gn/T/fridge-dashboard-zgvb55xu/serving/dashboard/.dockerignore)
4. [tools/checks/production-serving.mjs](file:///private/var/folders/wt/jmtpq7xx6dg_7qkwsqv1t3fm0000gn/T/fridge-dashboard-zgvb55xu/serving/dashboard/tools/checks/production-serving.mjs)
5. [README.md](file:///private/var/folders/wt/jmtpq7xx6dg_7qkwsqv1t3fm0000gn/T/fridge-dashboard-zgvb55xu/serving/dashboard/README.md) (production setup sections only)

---

#### 1. Configuration Hardening

- **Dockerfile:**
  - Fix `NGINX_ENVSUBST_FILTER`: replace broken space-separated list with anchored regex `^(BACKEND_HOST|BACKEND_PORT)$` so Nginx environment substitution executes without stripping Nginx variables (`$uri`, `$host`, `$remote_addr`).
  - Maintain inherited unprivileged non-root runtime UID 101 (`nginxinc/nginx-unprivileged:1.28-alpine`) exposing port 8080.
- **nginx.conf.template:**
  - `/api/`: Prioritize with `location ^~ /api/` so proxy requests bypass regex matching. Pass to `http://${BACKEND_HOST}:${BACKEND_PORT}/` with `proxy_http_version 1.1`, `proxy_buffering off;`, `proxy_cache off;`, `proxy_read_timeout 86400s;`, and empty `Connection ""` header for unbuffered SSE streaming.
  - `/assets/`: Keep `location ^~ /assets/` with `try_files $uri =404;` and immutable caching (`max-age=31536000, immutable`).
  - Missing static assets: Add strict 404 handling for static prefixes (`/images/`, `/fonts/`, legacy `/models/`) and root static assets (`/missing.js`, `/favicon.ico`) with revalidation (`Cache-Control: no-cache`).
  - SPA Routing & Deep Links: Restrict SPA fallback to `location /` (`try_files $uri $uri/ /index.html;`) and emit `no-cache, no-store, must-revalidate` for `index.html`. Guarantees valid deep-links ending with file extensions (e.g. `/items/milk.png`, `/events/receipt.json`) resolve to 200 HTML rather than false 404s.
  - `/healthz`: Static health probe returning HTTP 200 `OK\n` (`text/plain`).
- **.dockerignore:**
  - Exclude `.env`, `.env.*`, `credentials*`, `node_modules`, `dist`, `.git`, `docs/reviews/evidence`, `docs/evidence`, `tools/blender`, and `*.blend*`, preserving only required build context.

---

#### 2. Verification Suite (`production-serving.mjs`)

- Eliminate fake Node HTTP frontend server and mock GLB injection entirely.
- Assert required `PRODUCTION_URL` environment variable; terminate with actionable setup instructions if missing or unreachable.
- Discover actual single hashed GLB in `dist/assets/mini-fridge-*.glb`, verify HTTP 200, matching SHA-256 byte payload, and immutable caching header.
- Execute real HTTP assertions against the running container:
  - `GET /healthz` -> 200 `OK\n`.
  - Static 404s: `GET /missing.js` -> 404, `GET /assets/nonexistent.glb` -> 404, `GET /images/missing.png` -> 404.
  - SPA deep-links: `GET /items/milk.png` and `GET /events/receipt.json` -> 200 HTML with `no-store`.
  - Upstream `/api/inventory` -> 200 JSON list.
  - Upstream `/api/stream` -> 200 `text/event-stream`, unbuffered headers, receiving initial event or heartbeat within bounded timeout (5s).

---

#### 3. README Instructions
Document exact Docker build (`--build-arg VITE_API_BASE=/api`), container launch with loopback port mapping and backend host injection, declared non-root UID 101, and `PRODUCTION_URL` check execution.

---

#### Real External Dependency
- **Build Blocker in [src/App.jsx](file:///private/var/folders/wt/jmtpq7xx6dg_7qkwsqv1t3fm0000gn/T/fridge-dashboard-zgvb55xu/serving/dashboard/src/App.jsx#L114):** Syntax error (`const wasInside.current = false`) owned by the parallel integration worker must be resolved before the Docker image build.
