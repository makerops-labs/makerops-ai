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
| Best-practice guidance library | `GET /context/guidance[/<doc>]` | `tools_help('guidance[/<doc>]')` |

The `guidance` branch serves [docs/guidance/](../docs/guidance/) (read via
the existing whole-repo mount) — distilled operating best practices agents
can pull on demand.

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
| `x` | `x_search_recent` (X/Twitter, last 7 days) — **costs real money per read** (~$0.005-0.01/read, no free tier; confirmed live 2026-07-09 at the $0.005 tier), used by the self-improvement research sweep. Defaults to/caps at 100 results/call → **$0.50-$1.00/call**; see [docs/ai-setup-checklist.md](../docs/ai-setup-checklist.md) "§5e" for the full per-loop-iteration cost math | `X_API_BEARER_TOKEN` |
| `outline` | search/get/list, create/update documents | `OUTLINE_API_TOKEN` |
| `inventree` | search/get parts, list stock, create part, adjust stock | `INVENTREE_API_TOKEN` |
| `plane` | list projects/issues, get issue, create/update issue, comment | `PLANE_API_KEY` + `PLANE_WORKSPACE_SLUG` |
| `n8n` | list workflows/executions, activate, run webhook (approval-gated) | `N8N_API_KEY` |
| `n8nmcp` | passthrough proxy of the standalone [n8n-mcp](../n8n-mcp/) service (:8104): node docs, templates, validation, workflow create / diff-based update — so the smolagents `n8n_builder` persona can reach it. Destructive + execution tools disabled on the n8n-mcp side; **no** approval gate here. Open WebUI's n8n Architect preset connects to :8104 directly instead | `N8NMCP_AUTH_TOKEN` (+ `n8n-mcp` service running) |
| `comfyui` | `comfyui_generate_image` | makerops-core/ai/comfyui running (GPU) |
| `freescout` | list/get conversations, reply (draft-first), create conversation | `FREESCOUT_API_KEY` (paid API & Webhooks module) |
| `drawio` | `drawio_create_diagram_link` | — |
| `triggerdev` | trigger task, get/list runs | `TRIGGERDEV_SECRET_KEY` |
| `speech` | `speech_list_voices`, `speech_generate_audio` (TTS → `/files/audio/`) | speech (Kokoro, 8093) running |
| `trellis` | `trellis_image_to_3d` (image → GLB → `/files/models/`) | trellis (8094) running — GPU, start-on-demand |
| `agents` | `agent_list`, `agent_dispatch`, `agent_job_status`, `agent_job_result`, `agent_jobs_list`, `agent_job_history`, `agent_read`, `agent_create`, `propose_code_change` | smolagents running (for dispatch) |
| `approvals` | `approval_status`, `list_pending_approvals`, `agent_audit_history` (read-only for models) | — |
| `project` | `project_read_file`, `project_list_dir`, `project_glob`, `project_grep` (read anywhere under `~/workspace`); `project_register`, `project_write_file`, `project_edit_file`, `project_set_status`, `project_list`, `project_run_command` (write/execute, confined to a registered project) | `WORKSPACES_ROOT` mounted (+ `sandbox` running for `project_run_command`) |
| `devteam` | `devteam_start`, `devteam_status`, `devteam_list`, `devteam_result` (track); `devteam_answer`, `devteam_approve`, `devteam_revise`, `devteam_resume`, `devteam_cancel` (the five user-driven transitions) — software-development engagements: a lead-architect team builds an app in a registered project from a product plan, phase by phase, with sign-off gates and mid-run questions (see root README "Devteam engagements") | smolagents running (phases are background jobs); the target project registered via `project` |

`fetch_url` reviews any file type it can extract information from: web pages
(→ markdown), JSON/XML/CSV/source (as text), PDF/docx/xlsx/pptx/epub (text
extracted via markitdown). Images report metadata only; executables and other
binaries are **never executed** — only their type and size are reported.
Downloads are capped at 20 MB.

**Local models degrade with long tool lists.** Prefer connecting a client to
the per-domain endpoints (`/mcp/web`, `/mcp/outline`, ...) over the full
`/mcp` when the task doesn't need everything.

**Write-tool docstring convention** (per
[docs/guidance/small-model-tooling.md](../docs/guidance/small-model-tooling.md)):
every `WRITE ACTION` docstring ends with a terse `Preconditions:` /
`Effects:` / `Failure modes:` trailer — models (especially small local ones)
infer tool semantics from names and guess the rest, so the semantics must be
in the description. Keep each line short: descriptions ship in tool schemas
to every attached agent.

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

Tune trust over time in `.env` (comments go on their own line — `env_file`
would otherwise make the comment part of the value):

```text
# gate → notify
APPROVAL_GATE_EXEMPT=comfyui,inventree.inventree_adjust_stock
# notify → gate
APPROVAL_FORCE_GATE=outline
```

The approvals UI (`/approvals`, `/inbox`) requires `APPROVALS_TOKEN`, which
`start.sh` generates on first run. If it is ever unset, the UI **fails
closed**: it answers 503 and nothing can be approved until a token is set
(pending actions stay queued).

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
- **`agent_job_history(days, status)`** / **`agent_audit_history(limit)`**
  (the latter on the `approvals` domain) — recency-bounded job and
  write-action history, the evidence base for the self-improvement loop
  (`maintainer` agent — see [smolagents/README.md](../smolagents/README.md)
  "Self-improvement loop").
- **`propose_code_change(file_path, new_content, rationale)`** — proposes
  an edit to *any* file in the repo (bind-mounted read-write at `/repo`,
  `REPO_ROOT` env) as a human-reviewed diff. No path allowlist — gating on
  approval is the safety boundary — but `.env` files and anything under
  `.git/` or a `data/` directory are hard-excluded (confidentiality and
  VCS/runtime-content integrity, which approval-gating doesn't itself
  protect), and `.py` content is `ast.parse`-checked before it ever
  reaches the approval queue. On approval, mcp-tools hands the write and
  restart off to the separate [redeploy](../redeploy/) service (`POST
  /restart`, `REDEPLOY_URL`/`REDEPLOY_TOKEN` in `.env`) rather than
  touching Docker itself — see that service's README for why. Approving a
  change to mcp-tools' own source restarts the very process handling the
  approval; redeploy owns the outcome report (audit log + notify webhook)
  independently so that's not a problem. A failed post-restart health
  check triggers an automatic revert to the prior content and another
  restart — nothing is left broken silently.

## Project workspaces

The `project` domain gives agents access to durable, user-assigned project
directories — distinct from the ephemeral per-job working-memory workspace
described above (that one lives under `smolagents/data/smolagents/jobs/<id>/
workspace/` and is gone once the job finishes; a project persists across many
jobs and lives on disk under `~/workspace/`).

- **Mount**: `WORKSPACES_ROOT` (your absolute `~/workspace` path) is
  bind-mounted read-write at `/workspaces`, in **mcp-tools only** — never
  into smolagents, so even the code-executing `manager`/`coder` agents can
  only reach it through these tools, not raw `pathlib`.
- **Reads are broad**: `project_read_file`, `project_list_dir`,
  `project_glob`, `project_grep` work anywhere under `~/workspace`, including
  directories nobody has registered — sibling projects, or this stack's own
  source — so agents can use them as prior-art reference. `.env`/`.env.*`
  files are blocked everywhere, regardless of registration.
- **Writes are narrow**: `project_write_file`/`project_edit_file` only work
  inside a project registered with `project_register`, which requires the
  directory to already exist under `~/workspace/` — **you create it by
  hand**; that's the authorization to write there. `~/workspace/makerops/`
  itself can never be registered — that subtree stays governed by
  `propose_code_change`/`redeploy` above, not this domain.
- **Notify tier by default**: writes execute immediately (via
  `APPROVAL_GATE_EXEMPT=project` in `.env.example`) since creating/assigning
  the directory is itself the approval. Tighten a specific project later
  with `APPROVAL_FORCE_GATE=project.project_write_file` if you ever want to.
- **`PROJECT_CONTEXT.md`**: every registered project gets a starter copy
  seeded at its root automatically (never overwritten if one already
  exists). It's the always-read-first orientation doc — current state, a
  short architecture summary, and pointers to detail docs — so a stateless
  agent picking up the project later (possibly a different job entirely)
  isn't starting from nothing. The manager reads it first and keeps it
  current as the project's state changes; `writer` typically drafts/updates
  its prose, the same way it owns Outline documents.
- **Dispatching work at a project**: pass `project="<name>"` to
  `agent_dispatch` once you've reviewed a proposal and created the
  directory — the manager and `coder`/`writer` pick it up from there.
- **Command execution**: `project_run_command` runs a shell command (test
  runner, linter, build, `git`, package install) inside an isolated,
  resource-capped, ephemeral container with exactly one registered
  project's directory mounted — nothing else, no Docker access from
  inside, network allowed (bridge). It's a separate Docker-socket-scoped
  service ([sandbox/](../sandbox/), alongside `redeploy`), not mcp-tools
  itself — see its README for the full containment model. Notify tier,
  same as the other writes; `manager`/`coder` hold it, `writer`/`ops`/
  `studio` don't.

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

### Tests

Safety-policy tests run on the host with no network and no running services
(write executors are replaced by in-memory spies, real HTTP transports are
blocked, and all state goes to a temp dir):

```bash
uv run pytest            # from mcp-tools/; pytest is a dev-only dependency
```

| File | What it proves |
| --- | --- |
| `tests/test_policy.py` | `delete`/`effect` actions and overwrites of user-owned content are held as `PENDING APPROVAL` and never execute before approval; additive `create`s execute and notify, and a crashing executor is audited as `action.failed` instead of reported as success; unknown action kinds fall back to gate; unregistered tools are refused; `APPROVAL_GATE_EXEMPT` / `APPROVAL_FORCE_GATE` overrides apply per domain or per tool and can never exempt a delete; approve executes exactly once, reject never executes; approvals older than `APPROVAL_TTL_HOURS` expire and cannot execute. |
| `tests/test_tool_routing.py` | Every tool documented as `WRITE ACTION` routes through `policy.apply_policy` (static AST check, so a new tool can't silently bypass the gate); every `action_kind` is a literal; a real tool (`inventree_adjust_stock`) is held until approved. |
| `tests/test_approvals_http.py` | `/approvals` and the approve/reject endpoints refuse requests without a valid `APPROVALS_TOKEN` (query param or cookie) and change nothing when refused; with no token configured they fail closed (503); unknown verbs are refused (400). |

The suite was mutation-checked: breaking the gate for `effect` actions,
ignoring the TTL, letting exemptions apply to deletes, or allowing a second
approval each makes it fail.

## Stop / Teardown

```bash
./stop.sh      # container stops, data preserved
./teardown.sh  # removes containers, volumes, images (confirmation prompt)
```
