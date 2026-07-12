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

from datetime import datetime

import httpx
from smolagents import tool
from smolagents.mcp_client import MCPClient

from . import config

_clients: list[MCPClient] = []
_mounted: set[str] | None | bool = False  # False = not yet fetched


@tool
def current_datetime() -> str:
    """Current date and time (the container's local timezone). Call this
    whenever a date matters — report headers, memo filenames, judging how
    stale a source or a prior document is — instead of guessing; a guessed
    date is usually wrong.

    Returns e.g. '2026-07-12 13:05 -0500 (Saturday)'.
    """
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z (%A)")


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


def get_domains_tools(*domains: str) -> list:
    """Merged tools from several domains, deduplicated by name — every domain
    endpoint carries the shared tools_help tool, and smolagents requires
    unique tool names per agent. The local current_datetime tool rides along
    so every ToolCallingAgent has clock access (models confabulate dates —
    observed live). Appended only when MCP tools loaded, so the callers'
    `get_domains_tools(...) or [fallback]` degradation still fires when the
    tool server is down."""
    seen: set[str] = set()
    merged = []
    for domain in domains:
        for mcp_tool in get_domain_tools(domain):
            if mcp_tool.name in seen:
                continue
            seen.add(mcp_tool.name)
            merged.append(mcp_tool)
    if merged:
        merged.append(current_datetime)
    return merged
