"""Model-facing approval tools: models can inspect pending writes but can
never approve them — approval happens only in the human web UI."""

from fastmcp import FastMCP

from . import policy

mcp = FastMCP(
    "approvals",
    instructions="Check and list the human write-approval queue for gated write actions.")
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
