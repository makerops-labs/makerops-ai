"""Baseline tool-environment context appended to every agent's instructions.

The root of the mcp-tools documentation tree (GET /context) is the baseline:
one line per domain — enough to decide where to look — with the tools_help()
tool on every domain endpoint for drilling deeper (progressive disclosure,
so no agent carries the full tool catalog in context). Fetched once per
process and cached; a static fallback keeps agents working when mcp-tools
is down.
"""

import httpx

from . import config

_FALLBACK = (
    f"A shared MCP tool server (mcp-tools) runs at {config.MCP_TOOLS_URL}. "
    "Each tool domain is its own endpoint at /mcp/<domain>/, and every domain "
    "includes a tools_help(path) tool: tools_help('') lists the domains, "
    "tools_help('<domain>') lists a domain's tools, and "
    "tools_help('<domain>/<tool>') gives full usage details. Tools marked "
    "WRITE ACTION may answer 'PENDING APPROVAL #id' — report that to the "
    "user and stop; never retry a pending write. The agents domain also "
    "lets a client dispatch background jobs to the local agent team "
    "(agent_dispatch / agent_job_status / agent_job_result)."
)

_GUIDANCE = (
    "Before using an unfamiliar tool, drill down with tools_help('<domain>') "
    "and tools_help('<domain>/<tool>'); back out of a branch that does not "
    "fit the task. Domains not attached to this agent are reachable by "
    "delegating to the agent that owns them or reporting the option to the "
    "user."
)

_baseline: str | None = None


def get_baseline_context() -> str:
    """Root manifest of the tool documentation tree; static fallback if down."""
    global _baseline
    if _baseline is None:
        try:
            resp = httpx.get(f"{config.MCP_TOOLS_URL}/context", timeout=5)
            resp.raise_for_status()
            _baseline = resp.text.strip()
        except (httpx.HTTPError, ValueError):
            print(f"[context] mcp-tools /context unreachable at "
                  f"{config.MCP_TOOLS_URL} — using static fallback.")
            _baseline = _FALLBACK
    return _baseline


def with_baseline(instructions: str | None) -> str:
    """Agent-specific instructions plus the shared tool-environment baseline."""
    parts = [instructions.strip()] if instructions and instructions.strip() else []
    parts.append("## Tool environment\n\n" + get_baseline_context()
                 + "\n\n" + _GUIDANCE)
    return "\n\n".join(parts)
