"""Plane (project management) tools. API: /api/v1 with X-API-Key auth."""

from fastmcp import FastMCP

from . import config, policy
from .client import fmt, make_client, request_json

mcp = FastMCP("plane")
required_env = "PLANE_API_KEY"

_BASE = f"/api/v1/workspaces/{config.PLANE_WORKSPACE_SLUG}"
_client = make_client(config.PLANE_URL, headers={"X-API-Key": config.PLANE_API_KEY})


def _req(method: str, path: str, **kwargs):
    if not config.PLANE_WORKSPACE_SLUG:
        return False, "ERROR: PLANE_WORKSPACE_SLUG is not set in mcp-tools/.env."
    return request_json(_client, method, path, service="Plane",
                        token_hint="PLANE_API_KEY", **kwargs)


@mcp.tool
def plane_list_projects() -> str:
    """List the workspace's projects with their ids."""
    ok, data = _req("GET", f"{_BASE}/projects/")
    if not ok:
        return data
    projects = data.get("results", data) if isinstance(data, dict) else data
    if not projects:
        return "No projects found."
    return "\n".join(f"- {p.get('name')} (id: {p.get('id')}, "
                     f"identifier: {p.get('identifier')})" for p in projects)


@mcp.tool
def plane_list_issues(project_id: str, max_results: int = 20) -> str:
    """List issues in a project (most recent first) with ids, names, priority,
    and state."""
    ok, data = _req("GET", f"{_BASE}/projects/{project_id}/issues/",
                    params={"per_page": max(1, min(max_results, 100))})
    if not ok:
        return data
    issues = data.get("results", data) if isinstance(data, dict) else data
    if not issues:
        return "No issues in this project."
    return "\n".join(
        f"- [{i.get('sequence_id', '?')}] {i.get('name')} (id: {i.get('id')}, "
        f"priority: {i.get('priority') or 'none'})" for i in issues)


@mcp.tool
def plane_get_issue(project_id: str, issue_id: str) -> str:
    """Get one issue's full detail: name, description, priority, state,
    assignees, dates."""
    ok, data = _req("GET", f"{_BASE}/projects/{project_id}/issues/{issue_id}/")
    if not ok:
        return data
    keys = ("id", "sequence_id", "name", "description_stripped", "priority",
            "state", "assignees", "labels", "start_date", "target_date",
            "created_at", "updated_at", "created_by")
    return fmt({k: data.get(k) for k in keys if k in data})


# ── Writes ─────────────────────────────────────────────────────────────────────

def _do_create_issue(params: dict) -> str:
    payload = {"name": params["name"]}
    if params.get("description"):
        payload["description_html"] = f"<p>{params['description']}</p>"
    if params.get("priority"):
        payload["priority"] = params["priority"]
    ok, data = _req("POST", f"{_BASE}/projects/{params['project_id']}/issues/",
                    json=payload)
    if not ok:
        return data
    return (f"OBJECT_ID={data.get('id')}\n"
            f"Created issue '{data.get('name')}' (id: {data.get('id')}, "
            f"#{data.get('sequence_id')}).")


def _do_update_issue(params: dict) -> str:
    payload = {}
    if params.get("name") is not None:
        payload["name"] = params["name"]
    if params.get("description") is not None:
        payload["description_html"] = f"<p>{params['description']}</p>"
    if params.get("priority") is not None:
        payload["priority"] = params["priority"]
    if params.get("state_id") is not None:
        payload["state"] = params["state_id"]
    ok, data = _req("PATCH",
                    f"{_BASE}/projects/{params['project_id']}/issues/{params['issue_id']}/",
                    json=payload)
    if not ok:
        return data
    return f"Updated issue '{data.get('name')}' (id: {data.get('id')})."


def _do_add_comment(params: dict) -> str:
    ok, data = _req("POST",
                    f"{_BASE}/projects/{params['project_id']}/issues/{params['issue_id']}/comments/",
                    json={"comment_html": f"<p>{params['text']}</p>"})
    if not ok:
        return data
    return f"OBJECT_ID={data.get('id')}\nComment added to issue {params['issue_id']}."


policy.register_executor("plane", "plane_create_issue", _do_create_issue)
policy.register_executor("plane", "plane_update_issue", _do_update_issue)
policy.register_executor("plane", "plane_add_comment", _do_add_comment)


@mcp.tool
def plane_create_issue(project_id: str, name: str, description: str = "",
                       priority: str = "") -> str:
    """WRITE ACTION — creates a new issue in a Plane project. Only call when
    the user asked for it. Priority: urgent, high, medium, low, or none.
    The user is notified with a summary."""
    return policy.apply_policy(
        domain="plane", tool="plane_create_issue", action_kind="create",
        summary=f"Create issue '{name}' in project {project_id}",
        params={"project_id": project_id, "name": name,
                "description": description, "priority": priority or None},
        changes=[f"New issue '{name}'" + (f" ({priority})" if priority else "")],
        created_object_id_from_result=True)


@mcp.tool
def plane_update_issue(project_id: str, issue_id: str,
                       changes_summary: list[str], name: str | None = None,
                       description: str | None = None,
                       priority: str | None = None,
                       state_id: str | None = None) -> str:
    """WRITE ACTION — modifies an existing issue. changes_summary must itemize
    every intended change. Updates to issues the agent did not create are held
    for the user's approval."""
    ok, current = _req("GET", f"{_BASE}/projects/{project_id}/issues/{issue_id}/")
    if not ok:
        return current
    return policy.apply_policy(
        domain="plane", tool="plane_update_issue", action_kind="update",
        target_id=issue_id,
        summary=f"Update issue '{current.get('name')}' (id: {issue_id})",
        params={"project_id": project_id, "issue_id": issue_id, "name": name,
                "description": description, "priority": priority,
                "state_id": state_id},
        changes=list(changes_summary))


@mcp.tool
def plane_add_comment(project_id: str, issue_id: str, text: str) -> str:
    """WRITE ACTION — adds a comment to an issue. Only call when the user asked
    for it. The user is notified with a summary."""
    return policy.apply_policy(
        domain="plane", tool="plane_add_comment", action_kind="create",
        summary=f"Comment on issue {issue_id}: {text[:80]}",
        params={"project_id": project_id, "issue_id": issue_id, "text": text},
        changes=[f"New comment ({len(text)} chars)"],
        created_object_id_from_result=True)
