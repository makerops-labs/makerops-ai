# n8n-mcp — agentic n8n workflow management

[czlonkowski/n8n-mcp](https://github.com/czlonkowski/n8n-mcp) in HTTP mode,
wrapping the existing **makerops-core n8n** instance's public REST API with an
offline database of 500+ node schemas, ~2700 workflow templates, and multi-level
workflow validation. That knowledge layer is what lets a local model design
n8n workflows that actually run — not just trigger existing ones.

Two faces:

| Consumer | How it connects | Purpose |
| --- | --- | --- |
| Open WebUI **n8n Architect** preset | directly to `:8104/mcp` (native MCP Streamable HTTP) | the interactive chat front door |
| smolagents **n8n_builder** persona | via the mcp-tools **`n8nmcp`** proxy domain (`:8099/mcp/n8nmcp/`) | queued background "build me this workflow" jobs, dispatched through Task Dispatcher |

One `DISABLED_TOOLS` knob on this server governs both.

## Prerequisites

- makerops-core n8n running (`makerops-core/shared/n8n/start.sh`) with its
  public REST API enabled (it is, by default).
- An n8n API key. **The same key already lives in `../mcp-tools/.env` as
  `N8N_API_KEY`** (JWT, `aud=public-api`) — reuse that value. Otherwise mint one
  at n8n → **Settings → n8n API → Create an API key**.

## Setup

```bash
./start.sh                       # creates .env, generates N8NMCP_AUTH_TOKEN
# paste N8N_API_KEY into .env  (same value as ../mcp-tools/.env)
docker compose -p n8n-mcp up -d  # re-read .env
```

`start.sh` prints the health check and the exposed tool list on completion.

## Security model

- **Direct connection, no approval gate.** Unlike the mcp-tools `n8n` domain
  (`../mcp-tools/tools/n8n.py` — read + *approval-gated* webhook trigger, which
  stays exactly as-is), workflow create/update on this path executes
  immediately. The safety boundary is the disabled-tool set below plus n8n's own
  workflow version history, and the two agent prompts create workflows
  **inactive** unless you explicitly ask otherwise.
- **Destructive / secret-bearing / execution tools are removed in-process** via
  `N8NMCP_DISABLED_TOOLS` / `N8NMCP_DISABLED_TOOL_OPERATIONS` (`.env`). Verified
  against **n8n-mcp 2.76.0**:

  | Removed | Why |
  | --- | --- |
  | `n8n_delete_workflow` | no workflow deletion from chat |
  | `n8n_manage_credentials` | credential CRUD is a secret-exfiltration surface |
  | `n8n_manage_datatable` | out of scope for a workflow builder |
  | `n8n_manage_folders` | org-structure churn, no upside |
  | `n8n_workflow_versions` | contains destructive `rollback` / `delete` / `prune` |
  | `n8n_manage_agents` | manages n8n's AI-Agents feature — out of scope; also needs an instance-level MCP token we don't set |
  | `n8n_test_workflow` | *executes* a workflow against live systems (`method=auto` fires its real webhook/form/chat trigger) — a business effect, and the user chose no side-effecting tools on this path. Test in the n8n UI. |
  | `n8n_evaluations` | `run` / `cancel` execute evaluation runs; niche |
  | `n8n_audit_instance` | instance security scan — tangential to building; keeps the list tight |
  | `n8n_explore_node_resources` | needs an instance-level MCP token we don't set |
  | `n8n_executions:delete` (operation) | keep execution `get` / `list` for debugging, drop the delete branch |

  **Kept (18 tools):** `tools_documentation`, `search_nodes`, `get_node`
  (`detail=minimal/standard/full`, `mode=docs/search_properties`),
  `search_templates`, `get_template`, `n8n_list_workflows`, `n8n_get_workflow`,
  `n8n_list_catalog`, `n8n_executions` (get/list), `n8n_health_check`,
  `validate_node` (`mode=minimal/full`, `profile=runtime`), `validate_workflow`
  (pre-deploy, on the object), `n8n_validate_workflow` (post-deploy, by id),
  `n8n_autofix_workflow`, `n8n_create_workflow`, `n8n_update_partial_workflow`
  (diff), `n8n_update_full_workflow`, `n8n_deploy_template`.

  Note: this version has **no standalone workflow-delete tool at all** —
  `n8n_update_partial_workflow` can `removeNode` / `deactivateWorkflow` but not
  remove the workflow.

  Tool names vary by version — after a pull, re-list them (Verify section) and
  adjust `N8NMCP_DISABLED_TOOLS` in `.env` + `docker compose -p n8n-mcp up -d`
  if the surface changed.
- **`WEBHOOK_SECURITY_MODE=permissive`** is required: n8n-mcp reaches n8n via
  `http://host.docker.internal:5678` (a private gateway IP), and its SSRF guard
  validates `N8N_API_URL` through the same check that gates workflow webhook
  URLs. `strict` blocks private IPs; `moderate` allows only loopback. This is a
  single-user LAN, so `permissive` is the accepted trade.

## Verify

```bash
curl -s http://localhost:8104/health | jq        # {"status":"ok","version":"2.76.0",...}
```

The MCP endpoint needs an `initialize` handshake before `tools/list` — a bare
`curl` 400s (`No valid session ID`). Once the `n8nmcp` proxy domain is wired into
mcp-tools, the easy check is:

```bash
curl -s http://localhost:8099/context/n8nmcp     # renders the 18-tool list
```

Or list tools + prove n8n reachability directly, from the `mcp-tools/` dir:

```bash
TOKEN=$(grep ^N8NMCP_AUTH_TOKEN= ../n8n-mcp/.env | cut -d= -f2-)
.venv/bin/python - <<PY
import os, asyncio
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
async def main():
    async with Client(StreamableHttpTransport("http://localhost:8104/mcp", auth="$TOKEN")) as c:
        print(sorted(t.name for t in await c.list_tools()))
        r = await c.call_tool("n8n_health_check", {})
        print(r.content[0].text)          # "success": true  → n8n reachable
asyncio.run(main())
PY
```

A failing `n8n_health_check` means `WEBHOOK_SECURITY_MODE` is still blocking
`N8N_API_URL` (confirm `permissive`) or `N8N_API_KEY` is wrong / expired.

From Open WebUI: open the **n8n Architect** preset and ask "list my n8n workflows".

## How clients reach it

- **Open WebUI** — Admin Settings → External Tools → Add Connection → type
  **MCP (Streamable HTTP)** → URL `http://host.docker.internal:8104/mcp` →
  **API key = the `N8NMCP_AUTH_TOKEN` value** from `.env` (this server checks it —
  `no-key` will not work here, unlike the mcp-tools connections). Then create the
  **n8n Architect** context model per
  [`../openwebui/contexts/n8n-architect.md`](../openwebui/contexts/n8n-architect.md).
- **smolagents** — set `N8NMCP_URL` + `N8NMCP_AUTH_TOKEN` (same token) in
  `../mcp-tools/.env`, recreate mcp-tools (`docker compose -p mcp-tools up -d`),
  then the `n8nmcp` proxy domain is live at
  `http://host.docker.internal:8099/mcp/n8nmcp/` and the `n8n_builder` persona
  picks it up on the next `docker restart smolagents`.

## Proxy route

`http://n8n-mcp.localhost` — add the `n8n-mcp.localhost` server block from
`../proxy/local-ai.conf.template` to makerops-core's name-proxy and recreate it
(`../proxy/README.md`).

## Ops

- `docker compose -p n8n-mcp restart` does **not** re-read `.env` — use
  `docker compose -p n8n-mcp up -d` after any `.env` change.
- Stateless: `stop.sh` / `teardown.sh` lose nothing. Workflows live in the
  makerops-core n8n instance.
- If n8n-mcp is down, the Open WebUI preset simply loses its n8n tools (the chat
  still loads on `web`), and the mcp-tools `n8nmcp` domain renders as
  "backend not responding" in the doc tree without breaking anything else.
