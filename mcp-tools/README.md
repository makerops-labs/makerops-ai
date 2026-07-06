# MCP Tools — Shared LLM Tool Server

One [MCP](https://modelcontextprotocol.io) server holding all the tools the
local LLMs can use: internet search (via [searxng](../searxng/)), URL
fetching for any reviewable file type, and read/write access to the stack's
services. Both LLM clients consume it:

- **openwebui** — connect it as an external MCP tool server (see below).
- **smolagents** — agents load tools from the per-domain endpoints.

Built with [FastMCP](https://gofastmcp.com) + httpx. No other framework.

## Start

```bash
./start.sh
```

- MCP endpoint (all domains): `http://localhost:8099/mcp`
- Per-domain endpoints: `http://localhost:8099/mcp/<domain>`
- Approvals UI: <http://mcp.localhost/approvals> (token printed by start.sh)
- Task inbox (agent jobs): <http://mcp.localhost/inbox> (same token/cookie)
- Generated media (speech audio, ...): `http://mcp.localhost/files/...`
- Health: `http://localhost:8099/healthz`

Requires searxng for the web domain. Service domains additionally need an
API token in `.env` — **domains without a token are skipped at startup** (the
log and `/healthz` report which), so you can enable services one at a time.

## Tool documentation tree (`/context` + `tools_help`)

The server publishes a progressive-disclosure documentation tree so agents
can discover tools without carrying the full catalog in context:

| Level | HTTP | MCP |
| --- | --- | --- |
| Root manifest (domain per line) | `GET /context` | `tools_help('')` |
| One domain's tools | `GET /context/<domain>` | `tools_help('<domain>')` |
| Full usage doc for one tool | `GET /context/<domain>/<tool>` | `tools_help('<domain>/<tool>')` |

`tools_help(path)` is registered on **every** domain endpoint (and the
composed `/mcp`), so any connected agent can browse the tree with plain tool
calling. Content is rendered live from the mounted domains (each domain's
`FastMCP(..., instructions=...)` blurb + tool docstrings + parameter
schemas) and cached per process. smolagents injects the root manifest into
every agent's instructions as baseline context (see
[smolagents/README.md](../smolagents/README.md)); Open WebUI presets carry a
static baseline block ([openwebui/contexts/_baseline.md](../openwebui/contexts/_baseline.md)).


## Tool domains

| Domain | Tools | Needs |
|---|---|---|
| `web` | `web_search`, `fetch_url` | searxng running |
| `outline` | search/get/list, create/update documents | `OUTLINE_API_TOKEN` |
| `inventree` | search/get parts, list stock, create part, adjust stock | `INVENTREE_API_TOKEN` |
| `plane` | list projects/issues, get issue, create/update issue, comment | `PLANE_API_KEY` + `PLANE_WORKSPACE_SLUG` |
| `n8n` | list workflows/executions, activate, run webhook | `N8N_API_KEY` |
| `comfyui` | `comfyui_generate_image` | makerops-core/ai/comfyui running (GPU) |
| `freescout` | list/get conversations, reply (draft-first), create conversation | `FREESCOUT_API_KEY` (paid API & Webhooks module) |
| `drawio` | `drawio_create_diagram_link` | — |
| `triggerdev` | trigger task, get/list runs | `TRIGGERDEV_SECRET_KEY` |
| `speech` | `speech_list_voices`, `speech_generate_audio` (TTS → `/files/audio/`) | speech (Kokoro, 8093) running |
| `agents` | `agent_list`, `agent_dispatch`, `agent_job_status`, `agent_job_result`, `agent_jobs_list`, `agent_read`, `agent_create` | smolagents running (for dispatch) |
| `approvals` | `approval_status`, `list_pending_approvals` (read-only for models) | — |

`fetch_url` reviews any file type it can extract information from: web pages
(→ markdown), JSON/XML/CSV/source (as text), PDF/docx/xlsx/pptx/epub (text
extracted via markitdown). Images report metadata only; executables and other
binaries are **never executed** — only their type and size are reported.
Downloads are capped at 20 MB.

**Local models degrade with long tool lists.** Prefer connecting a client to
the per-domain endpoints (`/mcp/web`, `/mcp/outline`, ...) over the full
`/mcp` when the task doesn't need everything.

## Write policy (human-in-the-loop)

Every write tool routes through a tiered policy:

- **Notify tier** — additive changes (new documents, issues, parts, draft
  replies, images, diagrams, agents) execute immediately; a change summary is
  appended to the audit log and POSTed to `APPROVAL_NOTIFY_WEBHOOK` so you can
  review at your leisure.
- **Gate tier** — held as a pending action you must approve in the web UI at
  `/approvals` before it executes. Gated by default: overwrites of documents
  or issues **you** created (or previously approved — tracked in a provenance
  registry), and business-effect mutations (stock adjustments, workflow
  activation, webhook/task triggers, sending customer email). Deletions would
  always gate (none exist yet). Pending actions expire after
  `APPROVAL_TTL_HOURS`.

Update tools require a `changes_summary` list from the model, and document
updates include a unified diff in the review UI. Models can poll
`approval_status` but **cannot approve** — approval only happens in the UI.

Tune trust over time in `.env`:

```text
APPROVAL_GATE_EXEMPT=comfyui,inventree.inventree_adjust_stock   # gate → notify
APPROVAL_FORCE_GATE=outline                                     # notify → gate
```

Apply `.env` changes with `docker compose -p mcp-tools up -d` (recreate).

### Notifications

Set `APPROVAL_NOTIFY_WEBHOOK` to an n8n **production webhook URL** to get
notified of every write. Suggested workflow: Webhook node (POST) → Send Email
node. The JSON body contains `event` (`action.completed` or `action.pending`),
`domain`, `tool`, `summary`, `changes`, and `approvals_url`. Without a
webhook, notify-tier events still land in the audit log (visible at
`/approvals`), and the model relays pending-approval messages in chat.

## Agent workforce (dispatch + scaffolding)

The `agents` domain is the bridge to the smolagents team:

- **`agent_dispatch(objective, deliverables, ...)`** queues a background
  job for the agent manager and returns `JOB #<id>` immediately. The queue
  is a shared directory (`smolagents/data/smolagents/jobs`, bind-mounted
  here as `/agent-jobs`, override with `SMOLAGENTS_JOBS_PATH`); the
  smolagents job worker picks jobs up and owns every status transition —
  this side only creates `queued` records. Track with
  `agent_job_status` / `agent_job_result` / `agent_jobs_list`; finished
  reports and needs-attention items render in the **task inbox** at
  `/inbox`, and the smolagents side can notify via
  `SMOLAGENTS_NOTIFY_WEBHOOK` (see
  [smolagents/README.md](../smolagents/README.md) "Background jobs").
- **`agent_list`** shows the live roster (from `jobs/roster.json`, written
  by the worker at startup) plus custom agents.
- **`agent_create`** writes a new smolagents agent module into
  `smolagents/agents/custom/` **in the repo working tree** — review it with
  `git diff`, revert with `git checkout`. The content comes from a fixed
  template (the LLM supplies parameters, never raw Python), names are
  validated, and existing files are never overwritten. The new agent is
  picked up after `docker compose -p smolagents restart`.

## Connecting clients

**Open WebUI:** Admin Settings → External Tools → Add Connection → type
**MCP (Streamable HTTP)** → URL `http://host.docker.internal:8099/mcp` (or a
per-domain URL). Then enable the tool server per-model or per-chat and turn on
native function calling for tool-capable models. If your Open WebUI build
lacks native MCP support, run [mcpo](https://github.com/open-webui/mcpo) as an
OpenAPI proxy in front of this server instead.

**smolagents:** already wired — `agents/tools.py` loads tools from
`/mcp/<domain>` endpoints (see [smolagents/README.md](../smolagents/README.md)).

## Verify

```bash
curl -s http://localhost:8099/healthz | jq
# List tools over MCP (from this directory):
uv run --no-sync python -c "
import asyncio
from fastmcp import Client
async def main():
    async with Client('http://localhost:8099/mcp') as c:
        print(sorted(t.name for t in await c.list_tools()))
asyncio.run(main())"
```

## Development

Code is bind-mounted read-only; edit `tools/*.py` or `server.py` and
`docker compose -p mcp-tools restart`. **`.env` changes (tokens, policy
lists) need the container recreated instead:** `docker compose -p mcp-tools
up -d` — a plain restart does not re-read the env file. Rebuild
(`./start.sh`) only when dependencies change. Data (approvals, audit log,
provenance, saved diagrams) lives under `data/mcp-tools/`.

## Stop / Teardown

```bash
./stop.sh      # container stops, data preserved
./teardown.sh  # removes containers, volumes, images (confirmation prompt)
```
