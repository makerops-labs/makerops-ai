"""Alexa liaison domain: the MCP surface for the alexa-bridge service — a
narrow, signature-verified HTTPS endpoint (see makerops-ai/alexa-bridge/)
that turns Amazon Alexa voice requests into calls here. liaison_turn
appends the user's new utterance to that Alexa userId's session and queues
one background job for it, running through the same job-record mechanism
as agent_dispatch (see agents_domain.py) but against a second, dedicated
agent (agents/alexa_liaison.py) built for turn-by-turn spoken dialogue
rather than one-shot background tasks. Session state (one JSON file per
userId) lives in a directory shared with the smolagents job worker via bind
mount; the worker owns appending the liaison's own answer and the pending
job/action pointers once a turn actually runs (see agents/jobs.py's
_run_liaison_turn) — mirrors debate_domain.py's ownership split against
jobs_store.py.

Deterministic voice commands (ending a session, confirming/denying a
pending write approval, checking status, starting over) are handled by the
alexa-bridge itself, via liaison_session_status / liaison_reset_session /
liaison_clear_pending_action and the existing /approvals/{id}/{verb} route
and agent_job_status — never by routing that free text through the
liaison agent's own judgment, which is the whole point of keeping them
deterministic. Only genuinely free-form utterances reach liaison_turn."""

from fastmcp import FastMCP

from . import jobs_store, liaison_store, policy

mcp = FastMCP(
    "liaison",
    instructions=(
        "Backend for the Alexa voice bridge. liaison_turn queues one "
        "conversation turn (spoken utterance in, spoken reply out via a "
        "background job run by the dedicated alexa_liaison agent) for a "
        "given Alexa user id — poll its result with agent_job_status. "
        "liaison_session_status reads a session's pending job/action "
        "pointers. liaison_reset_session clears a session's history. "
        "liaison_clear_pending_action clears a resolved approval pointer. "
        "These are called by the alexa-bridge service, not directly by "
        "chat clients."))
required_env = None  # writes to the bind mount, no token


# ── Turn dispatch ────────────────────────────────────────────────────────────

def _do_liaison_turn(params: dict) -> str:
    liaison_store.append_turn(params["user_id"], role="user",
                              text=params["utterance"])
    job = jobs_store.create_job(
        brief={"objective": f"Liaison turn for {params['user_id']}: "
                            f"{params['utterance'][:150]}",
              "deliverables": ["a short spoken reply"]},
        source="alexa", liaison={"user_id": params["user_id"]})
    liaison_store.update_session(params["user_id"], last_job_id=job["id"])
    return (f"OBJECT_ID={job['id']}\n"
           f"Turn queued as {job['id']}. Poll with "
           f"agent_job_status('{job['id']}') or "
           f"liaison_session_status('{params['user_id']}').")


policy.register_executor("liaison", "liaison_turn", _do_liaison_turn)


@mcp.tool
def liaison_turn(user_id: str, utterance: str) -> str:
    """WRITE ACTION — called by the alexa-bridge with one free-form spoken
    utterance from a specific Alexa user. Appends it to that user's
    conversation session and queues a background job for the dedicated
    alexa_liaison agent to answer or delegate. Executes immediately (notify
    tier — this only ever creates a new turn record, nothing to gate).
    Returns the job id; poll agent_job_status(job_id) for the reply (status
    'completed' or 'needs_clarification' means report.speech is ready to
    read aloud; 'deferred' means a longer background task was kicked off
    separately, track that job's own id from report.job_id).
    Preconditions: non-empty user_id and utterance; job queue and session
    store mounted.
    Effects: appends one turn to that user's session and queues one liaison
    job; returns the job id immediately.
    Failure modes: 'ERROR: ...' on empty input or unmounted stores; the
    queued job may itself end failed — poll agent_job_status."""
    if not user_id.strip():
        return "ERROR: user_id is empty."
    if not utterance.strip():
        return "ERROR: utterance is empty."
    if not (jobs_store.available() and liaison_store.available()):
        return ("ERROR: the liaison session store or agent job queue is "
                "not mounted — is mcp-tools running with its default "
                "volumes (and smolagents started)?")
    return policy.apply_policy(
        domain="liaison", tool="liaison_turn", action_kind="create",
        summary=f"Alexa liaison turn ({user_id}): {utterance[:100]}",
        params={"user_id": user_id, "utterance": utterance},
        changes=[f"New liaison turn from {user_id}"],
        created_object_id_from_result=True)


# ── Read-only status ───────────────────────────────────────────────────────

@mcp.tool
def liaison_session_status(user_id: str) -> str:
    """Current state of one Alexa user's liaison session: whether a turn is
    still running (pending_job_id) and whether a write action from earlier
    in the conversation is still awaiting approval (pending_action_id). The
    alexa-bridge calls this for its deterministic 'status'/'confirm'/'deny'
    voice commands rather than routing them through the liaison agent."""
    session = liaison_store.get_session(user_id)
    if session is None:
        return f"NO_SESSION user_id={user_id}"
    return "\n".join([
        f"user_id={session['user_id']}",
        f"last_job_id={session.get('last_job_id') or ''}",
        f"pending_job_id={session.get('pending_job_id') or ''}",
        f"pending_action_id={session.get('pending_action_id') or ''}",
        f"turns={len(session.get('history', []))}",
        f"updated_at={session.get('updated_at', '')}",
    ])


# ── Deterministic bookkeeping — narrow exceptions the bridge calls directly
# after resolving something itself (an approval via /approvals, a "start
# over" command), mirroring debate_domain.py's own narrow resume/cancel
# exceptions. action_kind="create" below is a tier choice, not a literal
# claim of creating an object: both tools only ever clear THIS system's own
# bookkeeping pointers, never user-owned content, so the notify tier
# (immediate, no human review) is correct regardless of provenance — using
# "update" would incorrectly gate them, since a bare user_id was never
# registered as an agent-owned object.

def _do_liaison_reset_session(params: dict) -> str:
    liaison_store.reset_session(params["user_id"])
    return f"Liaison session for {params['user_id']} reset."


policy.register_executor("liaison", "liaison_reset_session",
                         _do_liaison_reset_session)


@mcp.tool
def liaison_reset_session(user_id: str) -> str:
    """WRITE ACTION — clears one Alexa user's conversation history and
    pending pointers (the 'start over' voice command). Executes immediately
    (notify tier).
    Preconditions: only on the user's explicit 'start over' intent.
    Effects: irreversibly erases that user's conversation history and
    pending pointers; any in-flight turn's context is lost.
    Failure modes: 'ERROR: ...' when the session store is not mounted."""
    if not user_id.strip():
        return "ERROR: user_id is empty."
    if not liaison_store.available():
        return "ERROR: the liaison session store is not mounted."
    return policy.apply_policy(
        domain="liaison", tool="liaison_reset_session", action_kind="create",
        summary=f"Reset liaison session for {user_id}",
        params={"user_id": user_id},
        changes=[f"Cleared conversation history for {user_id}"])


def _do_liaison_clear_pending_action(params: dict) -> str:
    if liaison_store.get_session(params["user_id"]) is None:
        return f"ERROR: no liaison session for {params['user_id']}."
    liaison_store.update_session(params["user_id"], pending_action_id="")
    return f"Cleared pending action pointer for {params['user_id']}."


policy.register_executor("liaison", "liaison_clear_pending_action",
                         _do_liaison_clear_pending_action)


@mcp.tool
def liaison_clear_pending_action(user_id: str) -> str:
    """WRITE ACTION — clears the pending_action_id pointer on one Alexa
    user's session, called by the alexa-bridge right after it resolves a
    pending approval directly via /approvals/{id}/{verb} (the confirm/deny
    voice commands). This tool never approves or rejects anything itself —
    it only stops the liaison from continuing to mention an action that was
    already resolved elsewhere. Executes immediately (notify tier).
    Preconditions: the pending action was ALREADY resolved via /approvals;
    a session exists for user_id.
    Effects: clears the session's pending_action_id pointer, nothing else.
    Failure modes: 'ERROR: ...' when no session exists or the store is not
    mounted."""
    if not user_id.strip():
        return "ERROR: user_id is empty."
    if not liaison_store.available():
        return "ERROR: the liaison session store is not mounted."
    return policy.apply_policy(
        domain="liaison", tool="liaison_clear_pending_action",
        action_kind="create",
        summary=f"Clear pending-action pointer for {user_id}",
        params={"user_id": user_id}, changes=[])
