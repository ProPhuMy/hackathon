# Worker tool availability and branch policy

Development continues on `dashboard`, created from88bcbab after the requested
main synchronization. The main checkout is not the implementation branch.

Confirmed by three agy diagnostic runs: the default agent exposed native
read_file, write_file, edit_file and run_command, while custom editing roles
without a tools field exposed only read_file plus common/MCP tools. Merely
resuming in accept-edits mode did not supply the missing tools. Explicit role
frontmatter tools now supplies those four native tools to frontend-integrator,
3d-modeler and motion-engineer. An independent diagnostic confirmed availability,
and actual native writes/commands succeeded. `call_mcp_tool` is implicit and must
not be listed as a registry component (the CLI rejected that name there).

Workers use separate Git worktrees from the reviewed committed dashboard state.
Their per-run settings grant only their checkout for writes, relevant snapshots
and shared Git metadata for reads, and documented proceed-in-sandbox behavior for
local commands. Canonical macOS /private paths need to match permissions. The
shared node_modules symlink can cause Vite temporary-config cache writes to fail
inside the worker sandbox; native config loading or lead-side verification avoids
changing production build behavior. Do not diagnose that as an application bug.

No credential files or model weights are copied to worker checkouts. Browser
MCP is for UI evidence, not filesystem editing. Read-only QA keeps source untouched.
Do not mistake an agy SUCCESS envelope with empty response/denied_actions for a
completed task; inspect actual diff and command outcomes.
