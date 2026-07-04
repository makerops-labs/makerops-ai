"""n8n (workflow automation) tools. API: /api/v1 with X-N8N-API-KEY auth.
Webhook triggering is the sanctioned way for agents to run workflows."""

import json

import httpx
from fastmcp import FastMCP

from . import config, policy
from .client import DEFAULT_TIMEOUT, make_client, request_json

mcp = FastMCP("n8n")
required_env = "N8N_API_KEY"

_client = make_client(config.N8N_URL, headers={"X-N8N-API-KEY": config.N8N_API_KEY})


def _req(method: str, path: str, **kwargs):
    return request_json(_client, method, path, service="n8n",
                        token_hint="N8N_API_KEY", **kwargs)


@mcp.tool
def n8n_list_workflows(active_only: bool = False) -> str:
    """List automation workflows with their ids and active state."""
    params = {"limit": 100}
    if active_only:
        params["active"] = "true"
    ok, data = _req("GET", "/api/v1/workflows", params=params)
    if not ok:
        return data
    flows = data.get("data", [])
    if not flows:
        return "No workflows found."
    return "\n".join(f"- {w.get('name')} (id: {w.get('id')}, "
                     f"{'active' if w.get('active') else 'inactive'})" for w in flows)


@mcp.tool
def n8n_get_workflow(workflow_id: str) -> str:
    """Get a workflow's name, active state, node list, and webhook paths (if any)."""
    ok, data = _req("GET", f"/api/v1/workflows/{workflow_id}")
    if not ok:
        return data
    nodes = data.get("nodes", [])
    webhook_paths = [n.get("parameters", {}).get("path")
                     for n in nodes if n.get("type") == "n8n-nodes-base.webhook"]
    lines = [f"Workflow: {data.get('name')} (id: {data.get('id')}, "
             f"{'active' if data.get('active') else 'inactive'})",
             "Nodes: " + ", ".join(f"{n.get('name')} [{n.get('type', '').split('.')[-1]}]"
                                   for n in nodes)]
    if webhook_paths:
        lines.append("Webhook paths: " + ", ".join(p for p in webhook_paths if p))
    return "\n".join(lines)


@mcp.tool
def n8n_list_executions(workflow_id: str | None = None,
                        status: str | None = None, max_results: int = 10) -> str:
    """List recent workflow executions. status: success, error, or waiting."""
    params: dict = {"limit": max(1, min(max_results, 100))}
    if workflow_id:
        params["workflowId"] = workflow_id
    if status:
        params["status"] = status
    ok, data = _req("GET", "/api/v1/executions", params=params)
    if not ok:
        return data
    runs = data.get("data", [])
    if not runs:
        return "No executions found."
    return "\n".join(
        f"- execution {r.get('id')}: workflow {r.get('workflowId')} — "
        f"{r.get('status', 'unknown')} at {r.get('startedAt')}" for r in runs)


# ── Writes ─────────────────────────────────────────────────────────────────────

def _do_set_workflow_active(params: dict) -> str:
    verb = "activate" if params["active"] else "deactivate"
    ok, data = _req("POST", f"/api/v1/workflows/{params['workflow_id']}/{verb}")
    if not ok:
        return data
    return f"Workflow {params['workflow_id']} is now {'active' if params['active'] else 'inactive'}."


def _do_run_webhook(params: dict) -> str:
    try:
        payload = json.loads(params.get("payload_json") or "{}")
    except ValueError:
        return "ERROR: payload_json is not valid JSON."
    try:
        resp = httpx.post(f"{config.N8N_URL}/webhook/{params['webhook_path'].lstrip('/')}",
                          json=payload, timeout=DEFAULT_TIMEOUT)
    except httpx.HTTPError as exc:
        return f"ERROR: webhook call failed: {exc}"
    if resp.status_code == 404:
        return ("ERROR: webhook not found — the workflow may be inactive or the "
                "path wrong (production webhooks require the workflow active).")
    return f"Webhook triggered (HTTP {resp.status_code}). Response: {resp.text[:500]}"


policy.register_executor("n8n", "n8n_set_workflow_active", _do_set_workflow_active)
policy.register_executor("n8n", "n8n_run_webhook", _do_run_webhook)


@mcp.tool
def n8n_set_workflow_active(workflow_id: str, active: bool) -> str:
    """WRITE ACTION — activates or deactivates an automation workflow. This
    changes live automation behavior, so it is held for the user's approval."""
    return policy.apply_policy(
        domain="n8n", tool="n8n_set_workflow_active", action_kind="effect",
        summary=f"{'Activate' if active else 'Deactivate'} workflow {workflow_id}",
        params={"workflow_id": workflow_id, "active": active},
        changes=[f"workflow {workflow_id} → {'active' if active else 'inactive'}"])


@mcp.tool
def n8n_run_webhook(webhook_path: str, payload_json: str = "{}") -> str:
    """WRITE ACTION — triggers an n8n workflow via its production webhook path
    with a JSON payload. Workflows can act on external systems, so this is held
    for the user's approval."""
    return policy.apply_policy(
        domain="n8n", tool="n8n_run_webhook", action_kind="effect",
        summary=f"Trigger n8n webhook '{webhook_path}'",
        params={"webhook_path": webhook_path, "payload_json": payload_json},
        changes=[f"POST /webhook/{webhook_path} with payload {payload_json[:200]}"])
