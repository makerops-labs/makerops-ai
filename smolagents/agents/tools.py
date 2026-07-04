"""MCP tool loading: connects to the shared tool server (mcp-tools).

Each domain (web, outline, inventree, plane, n8n, comfyui, freescout,
drawio, triggerdev, agents, approvals) is a separate MCP endpoint so each
agent only sees the tools it needs — long tool lists degrade local models.

The server's /healthz reports which domains are mounted (a domain without
its API token is skipped server-side); connecting to an absent endpoint can
hang the MCP client, so availability is checked first. Clients are kept
alive for the app's lifetime; anything unavailable yields an empty list
instead of an error.
"""

import httpx
from smolagents.mcp_client import MCPClient

from . import config

_clients: list[MCPClient] = []
_mounted: set[str] | None | bool = False  # False = not yet fetched


def _mounted_domains() -> set[str] | None:
    """Domains the tool server reports as mounted; None if it is unreachable."""
    global _mounted
    if _mounted is False:
        try:
            resp = httpx.get(f"{config.MCP_TOOLS_URL}/healthz", timeout=5)
            _mounted = set(resp.json().get("domains", []))
        except (httpx.HTTPError, ValueError):
            _mounted = None
    return _mounted


def get_domain_tools(domain: str) -> list:
    """Tools from one mcp-tools domain endpoint. Empty list if unavailable."""
    mounted = _mounted_domains()
    if mounted is None:
        print(f"[tools] mcp-tools server unreachable at {config.MCP_TOOLS_URL} "
              f"— agents run without '{domain}' tools.")
        return []
    if domain not in mounted:
        print(f"[tools] MCP domain '{domain}' not mounted on the tool server "
              f"(missing API token?) — skipping.")
        return []
    try:
        client = MCPClient({"url": f"{config.MCP_TOOLS_URL}/mcp/{domain}/",
                            "transport": "streamable-http"},
                           structured_output=False)
        tools = client.get_tools()
    except Exception as exc:  # noqa: BLE001 — any connection failure degrades
        print(f"[tools] MCP domain '{domain}' unavailable "
              f"({type(exc).__name__}); continuing without it.")
        return []
    _clients.append(client)  # keep the session alive for the app lifetime
    return tools
