# redeploy — Docker-socket-scoped restart proxy

The **only** service in this stack with Docker socket access. Exists
entirely to support the self-improvement loop (`docs/ai-setup-checklist.md`
"Self-improvement loop"): once a human approves a `propose_code_change`
diff at `mcp.localhost/approvals`, mcp-tools calls this service to write
the file and restart the affected container — rather than mcp-tools
holding Docker access itself.

## Why a separate service

A container with the Docker socket mounted can generally do far more than
"restart one named container" — create privileged containers, mount host
paths, etc. Isolating that capability into one small, auditable service
with a hardcoded allowlist (`ALLOWED_SERVICES` in `main.py`, currently
`{smolagents, mcp-tools}`) keeps the blast radius of a bug or a bad prompt
to "restart a container we already trust," not "arbitrary Docker control."

## API

- `POST /restart` — body `{"service": str, "file_path": str, "new_content": str, "old_content": str}`, header `X-Redeploy-Token: <REDEPLOY_TOKEN>`. Writes `new_content` to `file_path` (any path under the repo mount — `propose_code_change` has no file-scope restriction, gating is the safety boundary), then if `service` is allowlisted: restarts it, polls health for up to 30s, and **reverts to `old_content` and restarts again** if it doesn't come back healthy. Returns immediately (`{"accepted": true}`) — the actual work runs in a background thread, because the caller may be the very container about to restart.
- `GET /healthz` — liveness.

## Outcome reporting

Redeploy writes its own audit entries directly to mcp-tools' `audit.jsonl`
(shared bind mount) and POSTs its own webhook notification — independent
of mcp-tools being reachable at the time, since restarting mcp-tools is
exactly the case where it might not be. Events: `redeploy.completed`
(healthy), `redeploy.reverted` (failed health check, rolled back),
`redeploy.skipped` (file written, but `service` isn't restartable — e.g.
docs or config with no live process), `redeploy.failed` (named container
doesn't exist). All show up in `mcp.localhost/approvals` "Recent activity"
with no changes to that page.

## Setup

`./start.sh` generates a random `REDEPLOY_TOKEN` on first run and prints
it — copy that value into `mcp-tools/.env`'s `REDEPLOY_TOKEN` (must match
on both sides) and recreate mcp-tools (`docker compose -p mcp-tools up -d`).

## Expanding the allowlist

Adding a third restartable service means editing `ALLOWED_SERVICES` in
`main.py`. Once the self-improvement loop exists, even this file is a
legitimate `propose_code_change` target — loosening this boundary still
goes through the same human-reviewed diff as anything else.
