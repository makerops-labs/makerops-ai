"""trigger.dev (background jobs) tools. Task triggering uses the project
secret key (tr_...); management endpoints would need a PAT and are not
included."""

import json

from fastmcp import FastMCP

from . import config, policy
from .client import fmt, make_client, request_json

mcp = FastMCP(
    "triggerdev",
    instructions="Background jobs (trigger.dev): inspect tasks and trigger runs.")
required_env = "TRIGGERDEV_SECRET_KEY"

_client = make_client(config.TRIGGERDEV_URL,
                      headers={"Authorization": f"Bearer {config.TRIGGERDEV_SECRET_KEY}"})


def _req(method: str, path: str, **kwargs):
    return request_json(_client, method, path, service="trigger.dev",
                        token_hint="TRIGGERDEV_SECRET_KEY", **kwargs)


@mcp.tool
def triggerdev_get_run(run_id: str) -> str:
    """Get the status and output of a background job run."""
    ok, data = _req("GET", f"/api/v3/runs/{run_id}")
    if not ok:
        return data
    keys = ("id", "taskIdentifier", "status", "createdAt", "startedAt",
            "finishedAt", "isSuccess", "output", "error")
    return fmt({k: data.get(k) for k in keys if k in data})


@mcp.tool
def triggerdev_list_runs(status: str | None = None, max_results: int = 10) -> str:
    """List recent background job runs, optionally filtered by status
    (e.g. COMPLETED, FAILED, EXECUTING, QUEUED)."""
    params: dict = {"page[size]": max(1, min(max_results, 50))}
    if status:
        params["filter[status]"] = status
    ok, data = _req("GET", "/api/v3/runs", params=params)
    if not ok:
        return data
    runs = data.get("data", [])
    if not runs:
        return "No runs found."
    return "\n".join(
        f"- {r.get('id')}: {r.get('taskIdentifier')} — {r.get('status')} "
        f"(created {r.get('createdAt')})" for r in runs)


# ── Writes ─────────────────────────────────────────────────────────────────────

def _do_trigger_task(params: dict) -> str:
    try:
        payload = json.loads(params.get("payload_json") or "{}")
    except ValueError:
        return "ERROR: payload_json is not valid JSON."
    ok, data = _req("POST", f"/api/v1/tasks/{params['task_id']}/trigger",
                    json={"payload": payload})
    if not ok:
        return data
    return (f"Task '{params['task_id']}' triggered — run id: {data.get('id')}. "
            f"Check progress with triggerdev_get_run.")


policy.register_executor("triggerdev", "triggerdev_trigger_task", _do_trigger_task)


@mcp.tool
def triggerdev_trigger_task(task_id: str, payload_json: str = "{}") -> str:
    """WRITE ACTION — triggers a trigger.dev background task with a JSON
    payload. Tasks can act on external systems, so this is held for the
    user's approval."""
    return policy.apply_policy(
        domain="triggerdev", tool="triggerdev_trigger_task", action_kind="effect",
        summary=f"Trigger background task '{task_id}'",
        params={"task_id": task_id, "payload_json": payload_json},
        changes=[f"Run task {task_id} with payload {payload_json[:200]}"])
