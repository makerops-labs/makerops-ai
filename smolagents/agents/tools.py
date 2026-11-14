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
from .tool_schema import normalize_inputs

_clients: list[MCPClient] = []
_mounted: set[str] | None | bool = False  # False = not yet fetched
_domain_tools_cache: dict[str, list] = {}


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
    """Domains the tool server reports as mounted; None if it is unreachable.
    Only a successful fetch is cached — caching a failure (the old behavior)
    meant one transient blip at startup disabled every MCP domain for the
    process lifetime (the 2026-07-16 yield-logic devteam incident)."""
    global _mounted
    if _mounted is False or _mounted is None:
        try:
            resp = httpx.get(f"{config.MCP_TOOLS_URL}/healthz", timeout=5)
            _mounted = set(resp.json().get("domains", []))
        except (httpx.HTTPError, ValueError):
            _mounted = None
    return _mounted


def get_domain_tools(domain: str) -> list:
    """Tools from one mcp-tools domain endpoint. Empty list if unavailable.

    Cached per domain for the process lifetime: many agents in the same
    process request the same domain (e.g. every devteam specialist wants
    'project'), and each MCPClient holds a persistent connection to
    mcp-tools — opening one per agent instead of one per domain multiplies
    concurrent connections with the size of the team and was observed live
    to starve mcp-tools' connection handling during a large team's startup
    (dozens of agents piling on). The returned Tool objects are stateless
    wrappers around the shared client's calls, safe to hand to multiple
    agents at once."""
    if domain in _domain_tools_cache:
        return _domain_tools_cache[domain]
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
    for mcp_tool in tools:
        # mcpadapt drops `required`/null info: without this every defaulted
        # or optional argument is mandatory (see tool_schema). A schema we
        # can't repair keeps its original inputs rather than losing the domain.
        try:
            mcp_tool.inputs = normalize_inputs(mcp_tool.inputs)
        except Exception as exc:  # noqa: BLE001
            print(f"[tools] could not repair schema of {mcp_tool.name} ({exc!r}); kept as-is.")
    _clients.append(client)  # keep the session alive for the app lifetime
    _domain_tools_cache[domain] = tools
    return tools


def tools_session_alive() -> bool:
    """True when the cached MCP tool sessions still answer a real round
    trip. The persistent MCPClient sessions die silently when mcp-tools
    restarts (and stay dead — no reconnect), and an agent built while the
    server was down has no MCP tools at all; both states look identical
    from the agent's side: every project_*/... call fails while the job
    keeps running. One cached domain's tools_help('') proves the shared
    server session; all clients connect to the same server, so one dead
    session means all are dead."""
    for tools in _domain_tools_cache.values():
        for mcp_tool in tools:
            if mcp_tool.name == "tools_help":
                try:
                    mcp_tool(path="")
                    return True
                except Exception:  # noqa: BLE001 — any failure means dead
                    return False
    return False  # nothing cached — tools were never loaded


def reset_tools() -> None:
    """Forget every cached client, tool list, and mounted-domain result so
    the next get_domain_tools() reconnects fresh. Call after a dead-session
    detection (tools_session_alive() False) before rebuilding agents; the
    stale Tool objects held by existing agents keep pointing at the dead
    clients, so agents must be rebuilt afterwards, not reused."""
    global _mounted
    for client in _clients:
        try:
            client.disconnect()
        except Exception:  # noqa: BLE001 — dead sessions may refuse cleanup
            pass
    _clients.clear()
    _domain_tools_cache.clear()
    _mounted = False


def get_domains_tools(*domains: str) -> list:
    """Merged tools from several domains, deduplicated by name — every domain
    endpoint carries the shared tools_help tool, and smolagents requires
    unique tool names per agent. The local current_datetime tool rides along
    so every ToolCallingAgent has clock access (models confabulate dates —
    observed live). Appended only when MCP tools loaded, so the callers'
    `get_domains_tools(...) or [fallback]` degradation still fires when the
    tool server is down — and only when the server didn't already provide
    its own current_datetime (registered on every domain endpoint alongside
    tools_help; a duplicate name crashes agent init)."""
    seen: set[str] = set()
    merged = []
    for domain in domains:
        for mcp_tool in get_domain_tools(domain):
            if mcp_tool.name in seen:
                continue
            seen.add(mcp_tool.name)
            merged.append(mcp_tool)
    if merged and current_datetime.name not in seen:
        merged.append(current_datetime)
    return merged
