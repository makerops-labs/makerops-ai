"""FreeScout (help desk) tools. Requires the paid "API & Webhooks" module;
auth via X-FreeScout-API-Key header.

FreeScout serves an HTML "Access denied" 403 when the request Host does not
match its SITE_URL, so requests reaching it via host.docker.internal must
carry the Host header of the browser-facing URL (FREESCOUT_SITE_HOST)."""

from fastmcp import FastMCP

from . import config, policy
from .client import make_client, request_json

mcp = FastMCP(
    "freescout",
    instructions="Help desk (FreeScout): read customer conversations and draft replies.")
required_env = "FREESCOUT_API_KEY"

_headers = {"X-FreeScout-API-Key": config.FREESCOUT_API_KEY}
if config.FREESCOUT_SITE_HOST:
    _headers["Host"] = config.FREESCOUT_SITE_HOST
_client = make_client(config.FREESCOUT_URL, headers=_headers)


def _req(method: str, path: str, **kwargs):
    return request_json(_client, method, path, service="FreeScout",
                        token_hint="FREESCOUT_API_KEY (requires the API & Webhooks module)",
                        **kwargs)


@mcp.tool
def freescout_list_conversations(mailbox_id: int | None = None,
                                 status: str = "active",
                                 max_results: int = 10) -> str:
    """List help-desk conversations. status: active, pending, closed, or spam."""
    params: dict = {"status": status, "pageSize": max(1, min(max_results, 50))}
    if mailbox_id is not None:
        params["mailboxId"] = mailbox_id
    ok, data = _req("GET", "/api/conversations", params=params)
    if not ok:
        return data
    convs = (data.get("_embedded", {}) or {}).get("conversations", [])
    if not convs:
        return f"No {status} conversations found."
    return "\n".join(
        f"- #{c.get('number')} (id: {c.get('id')}) [{c.get('status')}] "
        f"{c.get('subject')} — {(c.get('customer') or {}).get('email', '?')}"
        for c in convs)


@mcp.tool
def freescout_get_conversation(conversation_id: int) -> str:
    """Read one conversation including its message threads."""
    ok, data = _req("GET", f"/api/conversations/{conversation_id}",
                    params={"embed": "threads"})
    if not ok:
        return data
    threads = (data.get("_embedded", {}) or {}).get("threads", [])
    lines = [f"#{data.get('number')} [{data.get('status')}] {data.get('subject')}",
             f"customer: {(data.get('customer') or {}).get('email', '?')}", ""]
    for t in threads:
        who = (t.get("createdBy") or {}).get("email", t.get("type", "?"))
        body = (t.get("body") or "").replace("\n", " ")
        lines.append(f"--- {t.get('type')} from {who} at {t.get('createdAt')}:")
        lines.append(body[:1500])
    return "\n".join(lines)


# ── Writes ─────────────────────────────────────────────────────────────────────

def _do_reply(params: dict) -> str:
    payload = {"type": "reply" if not params["draft"] else "reply",
               "text": params["text"], "user": params.get("user_id", 1),
               "state": "draft" if params["draft"] else "published"}
    ok, data = _req("POST", f"/api/conversations/{params['conversation_id']}/threads",
                    json=payload)
    if not ok:
        return data
    kind = "Draft reply saved (a human must send it)" if params["draft"] \
        else "Reply sent to the customer"
    return f"{kind} on conversation {params['conversation_id']}."


def _do_create_conversation(params: dict) -> str:
    payload = {
        "type": "email", "mailboxId": params["mailbox_id"],
        "subject": params["subject"],
        "customer": {"email": params["customer_email"]},
        "threads": [{"type": "message", "text": params["text"],
                     "user": params.get("user_id", 1), "state": "draft"}],
        "status": "active",
    }
    ok, data = _req("POST", "/api/conversations", json=payload)
    if not ok:
        return data
    return (f"OBJECT_ID={data.get('id')}\n"
            f"Created conversation #{data.get('number')} (id: {data.get('id')}) "
            f"with a draft first message — a human must send it.")


policy.register_executor("freescout", "freescout_reply", _do_reply)
policy.register_executor("freescout", "freescout_create_conversation",
                         _do_create_conversation)


@mcp.tool
def freescout_reply(conversation_id: int, text: str, draft: bool = True) -> str:
    """WRITE ACTION — replies to a help-desk conversation. With draft=True
    (default) the reply is saved as a draft for a human to send. draft=False
    sends the email to the customer immediately and is therefore held for the
    user's approval.
    Preconditions: conversation_id exists; draft=False only when the user
    explicitly asked to send.
    Effects: draft=True saves an unsent draft; draft=False (after approval)
    emails the customer — outward-facing and irreversible.
    Failure modes: draft=False returns PENDING APPROVAL #id (report, never
    retry); API errors as 'ERROR: ...'."""
    if draft:
        return policy.apply_policy(
            domain="freescout", tool="freescout_reply", action_kind="create",
            summary=f"Draft reply on conversation {conversation_id}",
            params={"conversation_id": conversation_id, "text": text, "draft": True},
            changes=[f"Draft reply ({len(text)} chars) on conversation {conversation_id}"])
    return policy.apply_policy(
        domain="freescout", tool="freescout_reply", action_kind="effect",
        summary=f"SEND reply to the customer on conversation {conversation_id}",
        params={"conversation_id": conversation_id, "text": text, "draft": False},
        changes=[f"Outbound customer email ({len(text)} chars): {text[:200]}"])


@mcp.tool
def freescout_create_conversation(mailbox_id: int, customer_email: str,
                                  subject: str, text: str) -> str:
    """WRITE ACTION — creates a new help-desk conversation with a draft first
    message (nothing is emailed until a human sends it). The user is notified
    with a summary.
    Preconditions: mailbox_id exists; customer_email is the right recipient.
    Effects: a new conversation holding an UNSENT draft; user notified —
    nothing reaches the customer until a human sends it.
    Failure modes: 'ERROR: ...' when the FreeScout API rejects the mailbox
    or email."""
    return policy.apply_policy(
        domain="freescout", tool="freescout_create_conversation",
        action_kind="create",
        summary=f"New conversation '{subject}' for {customer_email}",
        params={"mailbox_id": mailbox_id, "customer_email": customer_email,
                "subject": subject, "text": text},
        changes=[f"New draft conversation '{subject}' → {customer_email}"],
        created_object_id_from_result=True)
