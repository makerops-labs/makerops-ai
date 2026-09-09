"""n8n-mcp passthrough domain.

Re-exposes the standalone n8n-mcp service (czlonkowski/n8n-mcp, a separate
compose project at ../n8n-mcp/, reachable at config.N8NMCP_URL) as a mountable
mcp-tools sub-server, so the smolagents ``n8n_builder`` persona can reach its
node-documentation / template / validation / workflow-management tools —
smolagents' ``get_domain_tools`` only speaks to mcp-tools ``/mcp/<domain>/``
endpoints, never a third-party MCP server directly.

Thin FastMCP proxy: each tool call opens a fresh streamable-http session to
n8n-mcp (a disconnected transport → per-request sessions), so there is no
process-lifetime backend socket to die silently when n8n-mcp restarts.

There is deliberately **no approval gate here** — the destructive tools
(delete workflow, credentials, data tables, folders, version rollback) are
already removed on the n8n-mcp side via DISABLED_TOOLS / DISABLED_TOOL_OPERATIONS
(see ../n8n-mcp/.env.example). The existing ``n8n`` domain (tools/n8n.py: read +
approval-gated webhook trigger) is a separate capability and is untouched.

Open WebUI's "n8n Architect" preset talks to n8n-mcp DIRECTLY (port 8104); only
smolagents goes through this proxy.

Escape hatch if the proxy misbehaves: add ``get_n8nmcp_tools()`` to
smolagents/agents/tools.py that opens an MCPClient straight to
``config.N8NMCP_URL + "/mcp"`` with an ``Authorization: Bearer`` header, guarded
by a ``GET /health`` pre-check (mirror the ``/healthz`` guard — mcpadapt's
MCPClient hangs forever on a 404 MCP URL), and point the persona at that.
"""

from fastmcp import FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.proxy import ProxyClient

from . import config

required_env = "N8NMCP_AUTH_TOKEN"

# A bare string auth is coerced to httpx BearerAuth(token); httpx applies it in
# the auth flow, overriding any inbound Authorization header the proxy forwards.
_backend = StreamableHttpTransport(
    f"{config.N8NMCP_URL}/mcp",
    auth=config.N8NMCP_AUTH_TOKEN,
)

mcp = FastMCP.as_proxy(
    ProxyClient(_backend),
    name="n8nmcp",
    instructions=(
        "Agentic n8n workflow management (via n8n-mcp): node documentation, "
        "template discovery, multi-level validation, and workflow "
        "create / diff-based update against the live n8n instance. Delete, "
        "execution/test-run, credential, data-table and folder tools are "
        "disabled. Method: templates first; discover nodes; set every "
        "parameter explicitly (never trust defaults); validate each node, then "
        "the whole workflow; deploy; validate the deployed workflow."
    ),
)
