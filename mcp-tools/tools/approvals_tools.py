"""Model-facing approval tools: models can inspect pending writes but can
never approve them — approval happens only in the human web UI."""

from fastmcp import FastMCP

from . import policy

mcp = FastMCP(
    "approvals",
    instructions=("Check and list the human write-approval queue for gated "
                 "write actions, and review audit history across all domains."))
required_env = None  # always mounted


@mcp.tool
def approval_status(action_id: str) -> str:
    """Check the status of a write action that was held for human approval
    (pending, approved, rejected, expired, or failed)."""
    action = policy.get_action(action_id)
    if action is None:
        return f"ERROR: no action with id {action_id}."
    lines = [f"Action #{action['id']}: {action['status']}",
             f"- tool: {action['domain']}.{action['tool']}",
             f"- summary: {action['summary']}"]
    if action.get("result"):
        lines.append(f"- result: {action['result'][:500]}")
    if action["status"] == "pending":
        lines.append("- waiting for the user to approve it in the approvals UI.")
    return "\n".join(lines)


@mcp.tool
def list_pending_approvals() -> str:
    """List write actions currently waiting for human approval."""
    pending = policy.list_actions(status="pending")
    if not pending:
        return "No write actions are waiting for approval."
    return "\n".join(
        f"#{a['id']} [{a['domain']}.{a['tool']}] {a['summary']} (since {a['created_at']})"
        for a in pending)


@mcp.tool
def agent_audit_history(limit: int = 50) -> str:
    """Recent write-action history across every domain: completed,
    approved, rejected, and failed actions (not just pending ones). Useful
    for spotting patterns — e.g. which tools get rejected often, or which
    domains generate the most write activity."""
    entries = policy.read_audit(limit)
    if not entries:
        return "No audit history yet."
    lines = []
    for e in entries:
        detail = e.get("summary") or e.get("error") or ""
        lines.append(f"{e.get('ts', '?')} — {e.get('event', '?')} "
                     f"{e.get('domain', '?')}.{e.get('tool', '?')}: {detail}")
    return "\n".join(lines)
