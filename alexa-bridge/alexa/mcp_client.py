"""Thin async client for the alexa-bridge's two mcp-tools dependencies: the
liaison domain (turn dispatch, session status/reset/pending-clear) and the
agents domain (job result, used by the deterministic 'status' voice command
and to pick up a liaison turn's finished reply). Uses fastmcp.Client
directly — the same library mcp-tools itself is built on, and the pattern
its own README verification snippet uses — rather than the bare `mcp` SDK
or smolagents' MCPClient wrapper, both of which pull in more than this
bridge needs.

Approvals are deliberately NOT reachable over MCP (see mcp-tools/tools/
policy.py: "models can poll status but cannot approve") — resolve_approval
below calls the same plain HTTP route the mcp-tools web UI itself uses."""

import json
import re

import httpx
from fastmcp import Client

from . import config

# jobs_store.create_job's id format: f"job-{int(time.time())}-{hex6}".
# mcp-tools' policy.apply_policy strips write actions' "OBJECT_ID=<id>"
# line before returning (it's consumed internally for provenance, not
# meant for callers — see policy.py) — liaison_turn's remaining text still
# names the id in prose ("Turn queued as <id>. Poll with
# agent_job_status('<id>')..."), so match the id's own stable shape
# directly rather than depending on a specific phrasing surviving.
_JOB_ID_RE = re.compile(r"job-\d+-[0-9a-f]{6}")


def _text(result) -> str:
    data = result.data if hasattr(result, "data") else result
    return data if isinstance(data, str) else str(data)


async def liaison_turn(user_id: str, utterance: str) -> str:
    async with Client(f"{config.MCP_TOOLS_URL}/mcp/liaison/") as c:
        result = await c.call_tool(
            "liaison_turn", {"user_id": user_id, "utterance": utterance})
        return _text(result)


async def liaison_session_status(user_id: str) -> str:
    async with Client(f"{config.MCP_TOOLS_URL}/mcp/liaison/") as c:
        result = await c.call_tool(
            "liaison_session_status", {"user_id": user_id})
        return _text(result)


async def liaison_reset_session(user_id: str) -> str:
    async with Client(f"{config.MCP_TOOLS_URL}/mcp/liaison/") as c:
        result = await c.call_tool(
            "liaison_reset_session", {"user_id": user_id})
        return _text(result)


async def liaison_clear_pending_action(user_id: str) -> str:
    async with Client(f"{config.MCP_TOOLS_URL}/mcp/liaison/") as c:
        result = await c.call_tool(
            "liaison_clear_pending_action", {"user_id": user_id})
        return _text(result)


async def agent_job_result(job_id: str) -> dict | None:
    """Structured report (speech/status/...) once a job has finished, or
    None if it's still queued/running (agent_job_result returns a plain
    "still <status>" string in that case, not JSON — see agents_domain.py)
    or the id is unknown."""
    async with Client(f"{config.MCP_TOOLS_URL}/mcp/agents/") as c:
        result = await c.call_tool("agent_job_result", {"job_id": job_id})
        text = _text(result)
    try:
        payload = json.loads(text)
    except ValueError:
        return None
    return payload.get("report")


def extract_object_id(text: str) -> str:
    """Pulls a job id out of liaison_turn's result text (see _JOB_ID_RE)."""
    match = _JOB_ID_RE.search(text)
    return match.group(0) if match else ""


async def resolve_approval(action_id: str, verb: str) -> bool:
    """Calls mcp-tools' plain HTTP /approvals/{id}/{verb} route directly —
    the same one its own web UI uses (server.py's resolve_action) — rather
    than an MCP tool call, since approvals are deliberately outside the MCP
    surface. Auth is a query-string token, not a header (server.py's
    _authorized()). Returns True on success (a 303 redirect back to
    /approvals); a 409 means the action was already resolved or expired."""
    async with httpx.AsyncClient(follow_redirects=False, timeout=10.0) as c:
        resp = await c.post(
            f"{config.MCP_TOOLS_URL}/approvals/{action_id}/{verb}",
            params={"token": config.APPROVALS_TOKEN} if config.APPROVALS_TOKEN else {})
    return resp.status_code in (200, 303)
