# Fridge Tracker front-end team

The dashboard is Khang's area in the repository ownership table. Keep worker edits inside the dashboard and respect the existing service contracts. Read `README.md` and `docs/implementation-log.md` before briefing workers. The Vite/React app already uses TanStack Router, React Three Fiber, a Blender-authored fridge, a reversible entry sequence, and local demo data.

Antigravity workers follow their selected role and the task brief. The coordination and dispatch instructions below apply to the Codex lead.

## Astra's role

Act as creative director and final reviewer. Start with the live experience and the existing references in the repo root, `mainscreen.png` and `image.png`. Keep the fridge as the focal point and inventory access clear. For a visual polish pass, review the full path from the exterior to opening the fridge, choosing a shelf and item, and leaving the scene.

1. Set the brief and acceptance criteria. Ask UI/UX to resolve visual direction, framing, and touch and keyboard behavior first. For a significant redesign, compare two directions on both desktop and mobile before commissioning implementation.
2. Agree on the model and motion handoff before running those roles in parallel. Specify the door pivot, food identifiers, shelf viewpoints, trigger and exit behavior, and static fallback. Let the integrator build against that agreement.
3. Brief each worker with the objective, relevant references, files it owns, behavior to preserve, preview URL if available, and evidence to return. Keep editing workers in separate Git worktrees only when each can start from the same reviewed baseline. Preserve pending local changes and ensure that worker checkouts include any needed uncommitted dashboard work before dispatch.
4. Inspect worker diffs and the integrated browser preview. Give visual QA the integrated preview for independent review. Use specific findings for revisions and review the final result against the brief.

## Dispatch

Start Astra from the dashboard so Codex loads this file and Antigravity discovers the workspace roles. Begin with two independent workers at a time.

```sh
cd dashboard  # from the repository root
codex -m gpt-6-astra
```

Run each worker from the dashboard directory in its assigned checkout. For example, set `preview_url` to the URL printed by Vite, then brief the read-only reviewer.

```sh
preview_url=http://localhost:5173
agy --agent visual-qa --mode plan --sandbox --output-format json \
  -p "Review the dashboard at $preview_url. Inspect entry, shelf and item selection, Escape and focus return on desktop and mobile. Report findings with screenshots and reproduction steps. Keep source files untouched."
```

Use `--mode accept-edits` for scoped implementation tasks. Check the worker's actual diff and tool results before treating the run as complete. Each handoff should include changed files or artifacts, checks and evidence, and open issues.

| Worker ID | Assignment | MCP tools to use |
| --- | --- | --- |
| `ui-ux-designer` | Visual direction, responsive specs, flow and state design | Playwright, optional Figma Desktop |
| `motion-engineer` | Fridge entry, exit, shelf movement, and microinteractions | Playwright, Chrome DevTools |
| `3d-modeler` | Blender source, GLB, and fallback artwork | Blender, Playwright |
| `frontend-integrator` | Production UI, routes, responsive and loading states | Playwright, optional Figma Desktop |
| `visual-qa` | Independent browser, accessibility, and performance review | Playwright, Chrome DevTools |

## MCP connections

Antigravity loads `.agents/mcp_config.json` from the dashboard. Start `agy` from the dashboard, then use `/agents` to confirm the five roles and `/mcp` to check the connections. The browser servers use separate profiles. Start a local Vite preview with `npm run dev` and use the URL Vite prints.

- Blender uses the project's existing community addon and `uvx mcp-for-blender`. Keep the addon on loopback port 9876 and use a dedicated project scene for the modeler. See the dashboard README for rebuild and verification steps.
- Figma Desktop is an optional read-only reference for workers. Enable its desktop MCP server in Figma and set `figma-desktop.disabled` to `false` in the workspace config when available. Until then, use the existing screenshots and project notes.
- Astra can use Codex's separate Figma Remote connection for canvas edits and Playwright for direct browser review. Worker MCP configuration applies to Antigravity.

## Final review

Run `npm run build`, `npm run lint`, `node tools/checks/fridge-motion.mjs`, and `node tools/checks/routes.mjs` from the dashboard. Review desktop and narrow mobile, keyboard and touch, interrupted entry and exit, focus return, reduced motion, and the static fallback. Check that the selected shelf and item agree between mesh interactions and accessible controls. If motion or model complexity changes, compare performance with the current dashboard on the same device and document the result.
