# Lead review of the UI/UX handoff

This report describes the UNACCEPTED live candidate saved at local commit2ce1222,
not the accepted dashboard branch. Source line references belong to that candidate.
The screenshot confirms the narrow-mobile interior overlap. Exterior footer
clipping and expanded retry-header collision need reproduction after the lifecycle
fix; the latter was inferred from source rather than observed during an outage.
Do not blindly apply proposed CSS offsets; verify portrait and short landscape.

Reject the proposed enrollment wording: UNKNOWN does not mean unenrolled or
pending, and no dashboard enrollment endpoint exists. Keep “Enrollment status
unknown” with clear explanation. Do not claim live sensing or real-time verification
while disconnected/loading. Live model placement is intentionally unsupported,
not an untested implemented feature. Fix product jargon with truthful plain copy.

# UI/UX Final Review & Handoff

**Target Previews:** Live Integration (`http://127.0.0.1:5178/`) · Demo Baseline (`http://127.0.0.1:5176/`)  
**Scope:** Read-only audit across Desktop 1440×900, Mobile 390×844, and Mobile 320×568.  
**Source Status:** Untouched (0 source edits made).

---

## Screenshot Evidence

All evidence captured and saved to [docs/reviews/evidence/live-ux/](evidence/live-ux):

- **Desktop (1440×900):**
  - Exterior Live: [`desktop-1440-live.png`](evidence/live-ux/desktop-1440-live.png)
  - Interior 3D View: [`desktop-1440-inside-live.png`](evidence/live-ux/desktop-1440-inside-live.png)
  - People Modal (+ Register Form): [`desktop-1440-people-modal.png`](evidence/live-ux/desktop-1440-people-modal.png)
  - Inventory Modal: [`desktop-1440-inventory-modal.png`](evidence/live-ux/desktop-1440-inventory-modal.png)
- **Mobile Portrait (390×844):**
  - Exterior Live: [`mobile-390-live.png`](evidence/live-ux/mobile-390-live.png)
  - Interior 3D View: [`mobile-390-inside-live.png`](evidence/live-ux/mobile-390-inside-live.png)
  - People Modal (+ Register Form): [`mobile-390-people-modal.png`](evidence/live-ux/mobile-390-people-modal.png)
- **Compact Mobile (320×568):**
  - Exterior Live: [`mobile-320-live.png`](evidence/live-ux/mobile-320-live.png)
  - Interior Collision: [`mobile-320-inside-live.png`](evidence/live-ux/mobile-320-inside-live.png)
  - People Modal Form: [`mobile-320-people-modal.png`](evidence/live-ux/mobile-320-people-modal.png)

---

## Findings & Actionable Fix Requirements

### 1. [HIGH] 320×568 Interior Shelf Navigation & Notice Collision (35px Overlap)
- **File:** [src/App.css](../../src/App.css)
- **Selectors:** `.shelf-navigation`, `.shelf-items`, `.live-shelf-notice`
- **Issue:** At 320×568, `.shelf-navigation` (`bottom: 108px`, bounding y: 416–460) and `.shelf-items` (`bottom: 24px`, bounding y: 425–544) collide directly by ~35px. In live mode, `.live-shelf-notice` renders text plus a button (119px height), causing `.shelf-items` to cover the shelf tabs (`Top shelf`, `Middle shelf`, `Lower shelf`), blocking touch interaction.
- **Fix Requirement (DoD):**
  - Unify `.inside-controls` on mobile into a single flex column pinned to the bottom:
    ```css
    @media (max-width: 680px) {
      .shelf-navigation { bottom: 160px; left: 20px; right: 20px; }
      .shelf-items { bottom: 20px; left: 20px; right: 20px; }
    }
    ```
  - Verify zero pixel bounding overlap between `.shelf-navigation` and `.shelf-items` at 320×568.

### 2. [HIGH] 320×568 Exterior Viewport Clipping (`overflow: hidden` + `min-height: 680px`)
- **File:** [src/App.css](../../src/App.css), [src/App.css](../../src/App.css)
- **Selectors:** `.app`, `footer`, `.fridge-caption`
- **Issue:** `.app` enforces `min-height: 680px` under `max-width: 680px`, but also has `overflow: hidden`. On a 568px viewport (iPhone SE), the footer is positioned at `y = 605px..680px` and `.fridge-caption` at `y = 570px`, pushing both completely outside the screen where they are clipped. Users cannot see or tap the Latest Signal ticker.
- **Fix Requirement (DoD):**
  - Remove `min-height: 680px` from `.app` on small screens, or set `min-height: 100svh`.
  - Tighten vertical spacing (`intro h1 { margin: 4px 0 }`, `intro { top: 96px }`) so `site-header`, `intro`, `fridge-caption`, and `footer` coexist without clipping on 568px height viewports.

### 3. [MEDIUM] Product Copy Leaking Implementation Details
- **File:** [src/App.jsx](../../src/App.jsx), [src/App.jsx](../../src/App.jsx), [src/App.jsx](../../src/App.jsx), [src/App.jsx](../../src/App.jsx)
- **Selectors:** `.person-form + .demo-note`, `.side-note`, `.inventory-list + .demo-note`
- **Issue:** The UI exposes internal architecture jargon to regular household users:
  - People modal: *"Face enrollment is handled separately via the CLI."* (Household users do not use CLI).
  - Side note: *"LIVE EVENT STREAM · AUTHORITATIVE OUTBOX"* (internal backend term).
  - Inventory: *"Authoritative outbox projection"* (internal database concept).
- **Fix Requirement (DoD):**
  - Replace People copy with: *"Metadata registered. Face recognition enrollment is completed on-device."*
  - Replace side note with: *"LIVE SENSING ACTIVE · REAL-TIME VERIFICATION"*
  - Replace Inventory note with: `"{count} of {total} items · Live fridge inventory"`

### 4. [MEDIUM] Unknown Enrollment Status Formatting & Accessibility
- **File:** [src/App.jsx](../../src/App.jsx)
- **Selectors:** `.person-state`
- **Issue:** Under live mode, people cards render an unstyled, raw uppercase tag: `ENROLLMENT: UNKNOWN`. It looks like an unhandled enum fallback and lacks accessibility context.
- **Fix Requirement (DoD):**
  - Render as a styled chip: `<span className="person-state badge-pending" aria-label="Face recognition not yet enrolled">FACE PENDING</span>`.
  - Add `.person-state.badge-pending { background: #e5e4d7; color: #6d725e; padding: 2px 6px; border-radius: 2px; }`.

### 5. [MEDIUM] Status Indicator / Retry Button Header Collision at 320px Width
- **File:** [src/App.jsx](../../src/App.jsx), [src/App.css](../../src/App.css)
- **Selectors:** `.system-status`, `.wordmark`
- **Issue:** `.system-status` is positioned absolute `top: 30px; right: 24px`. In disconnected/reconnecting states (`SERVICE UNAVAILABLE (503)` + `[Retry]` button), width expands to ~210px. On 320px screens, this collides with `.wordmark` (`fridge—`, width ~80px at `left: 12px`), causing text overlap.
- **Fix Requirement (DoD):**
  - In `@media (max-width: 480px)`, allow `.system-status` to wrap or place it within normal flow below `.wordmark`:
    ```css
    @media (max-width: 480px) {
      .system-status { top: 62px; right: 12px; font-size: 8px; }
      nav { margin-top: 18px; }
    }
    ```

---

## Untested States & Honest Gaps

1. **Populated 3D Mesh Items in Live Mode:** Backend preview is currently returning snapshot initialization/empty inventory; verified the `.live-shelf-notice` fallback, but live 3D mesh placement of individual items remains untested.
2. **Active Mid-Stream Network Drop (SSE disconnect):** Status indicator transitions to `RECONNECTING / STALE` were reviewed in source logic; dynamic recovery after socket abrupt termination was not manually triggered during active stream.
3. **Screen Reader Live Announcements:** VoiceOver/ARIA live-region announcement cadence during high-frequency live events was verified structurally via `role="status"` and `role="alert"`, but not tested with a physical screen reader audio session.
