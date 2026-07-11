"""Debate domain: start and monitor a multi-round, file-relayed debate
between three fixed personas (entrepreneur, critic, monitor) run by the
local smolagents team, one turn per background job — running in series like
the agent job queue (see the agents domain's agent_dispatch), each turn
queued automatically once the previous one finishes. Session state
(session.json + manifest.jsonl + round files) lives in a directory shared
with the smolagents job worker via bind mount; the worker owns turn
advancement (see agents/jobs.py's _advance_debate). This domain only starts
a session, reads its state, and — narrowly — resumes a stuck session or
cancels an active one, mirroring jobs_store.py's own queued->cancelled
carve-out."""

import time

from fastmcp import FastMCP

from . import config, debate_store, jobs_store, policy

mcp = FastMCP(
    "debate",
    instructions=(
        "Multi-round, file-relayed debate between three fixed personas "
        "(entrepreneur, critic, monitor) that explores or stress-tests an "
        "idea over several turns, running in the background like the agent "
        "job queue — turns run one at a time, in series, each queued "
        "automatically once the previous one finishes, and every debate "
        "ends with an automatic human-facing synthesis (debate_result). "
        "debate_start begins one; debate_status/debate_manifest/"
        "debate_read_round/debate_list track it; debate_resume/"
        "debate_cancel handle a stuck or unwanted session. Refine the goal "
        "with the user into a concrete brief before starting — the "
        "personas cannot ask questions mid-debate."))
required_env = None  # writes to the bind mount, no token

_MODES = ("narrow", "broad")


def _default_max_rounds(mode: str) -> int:
    return (config.DEBATE_MAX_ROUNDS_NARROW if mode == "narrow"
            else config.DEBATE_MAX_ROUNDS_BROAD)


# ── Start ────────────────────────────────────────────────────────────────────

def _do_debate_start(params: dict) -> str:
    session = debate_store.create_session(
        goal=params["goal"], deliverables=params["deliverables"],
        mode=params["mode"], max_rounds=params["max_rounds"],
        monitor_every_n=params["monitor_every_n"],
        constraints=params["constraints"], resources=params["resources"],
        context=params["context"])
    job = jobs_store.create_job(
        brief={"objective": f"Debate turn 1 (entrepreneur): {params['goal'][:150]}",
              "deliverables": ["round 1 argument text"]},
        source="debate",
        debate={"session_id": session["id"], "round": 1,
               "persona": "entrepreneur"})
    debate_store.update_session(session["id"], queued_job_id=job["id"])
    return (f"OBJECT_ID={session['id']}\n"
            f"Debate {session['id']} started ({params['mode']}, max "
            f"{params['max_rounds']} rounds, monitor every "
            f"{params['monitor_every_n']} exchanges). Round 1 "
            f"(entrepreneur) is queued as {job['id']} and runs in the "
            f"background — each following turn queues itself "
            f"automatically. Track with debate_status('{session['id']}') "
            f"or debate_manifest('{session['id']}').")


policy.register_executor("debate", "debate_start", _do_debate_start)


@mcp.tool
def debate_start(goal: str, deliverables: list[str], mode: str = "narrow",
                 max_rounds: int = 0, monitor_every_n: int = 0,
                 constraints: list[str] | None = None,
                 resources: list[str] | None = None, context: str = "") -> str:
    """WRITE ACTION — start a multi-round, file-relayed debate between three
    fixed personas (entrepreneur, critic, monitor) that explores or
    stress-tests an idea over several turns. Turns run one at a time in the
    background, in series (like the agent job queue) — each is a background
    job; the next turn is queued automatically once the previous one
    finishes. goal: the question or idea to debate, as specific or
    open-ended as you like. mode: 'narrow' for a tight, well-scoped question
    (personas stay concrete, default max_rounds 6) or 'broad' for open-ended
    exploration (personas may research and range wider, default max_rounds
    16). deliverables: what a good outcome should produce (e.g. 'a go/no-go
    recommendation', 'the 3 strongest objections and how they would be
    addressed'). max_rounds: override the mode's default (hard-capped
    server-side). monitor_every_n: override how many entrepreneur+critic
    exchanges happen between monitor check-ins (server default 2; the
    monitor decides continue/redirect/conclude each check-in). Refine the
    goal with the user first — the personas cannot ask questions
    mid-debate. Returns the session id; track with debate_status,
    debate_manifest, or debate_read_round. The user is notified with a
    summary."""
    if not goal.strip():
        return "ERROR: goal is empty — refine the request with the user first."
    deliverables = [d for d in (deliverables or []) if d.strip()]
    if not deliverables:
        return ("ERROR: at least one explicit deliverable is required "
                "(what should a good debate outcome produce?).")
    if mode not in _MODES:
        return f"ERROR: mode must be one of {_MODES}."
    resolved_max_rounds = max_rounds or _default_max_rounds(mode)
    if not (0 < resolved_max_rounds <= config.DEBATE_HARD_MAX_ROUNDS):
        return (f"ERROR: max_rounds must be between 1 and "
                f"{config.DEBATE_HARD_MAX_ROUNDS}.")
    resolved_monitor_every_n = monitor_every_n or config.DEBATE_MONITOR_EVERY_N_DEFAULT
    if resolved_monitor_every_n < 1:
        return "ERROR: monitor_every_n must be at least 1."
    if not jobs_store.available() or not debate_store.available():
        return ("ERROR: the debate store or agent job queue is not mounted "
                "— is mcp-tools running with its default volumes (and "
                "smolagents started)?")
    return policy.apply_policy(
        domain="debate", tool="debate_start", action_kind="create",
        summary=f"Start debate ({mode}): {goal[:100]}",
        params={"goal": goal, "deliverables": deliverables, "mode": mode,
                "max_rounds": resolved_max_rounds,
                "monitor_every_n": resolved_monitor_every_n,
                "constraints": constraints or [], "resources": resources or [],
                "context": context},
        changes=[f"New debate: {goal[:100]}"],
        created_object_id_from_result=True)


# ── Read-only status ───────────────────────────────────────────────────────────

def _session_summary_line(session: dict) -> str:
    return (f"{session['id']} [{session['status']}] {session['mode']} round "
            f"{session['current_round']}/{session['max_rounds']} — "
            f"{session['goal'][:80]} (created {session['created_at']})")


@mcp.tool
def debate_status(session_id: str) -> str:
    """Status of a debate: mode, round/max_rounds, last persona to speak,
    whether it's active/stuck/concluded/cancelled, and the liveness of its
    current turn's background job."""
    session = debate_store.get_session(session_id)
    if session is None:
        return f"ERROR: no debate named '{session_id}'."
    lines = [_session_summary_line(session), f"Goal: {session['goal'][:200]}"]
    if session.get("last_persona"):
        lines.append(f"Last to speak: {session['last_persona']}")
    if session.get("stop_reason"):
        lines.append(f"Stop reason: {session['stop_reason']}")
    job = (jobs_store.get_job(session["current_job_id"])
          if session.get("current_job_id") else None)
    if job:
        note = ""
        if job.get("status") == "running" and job.get("heartbeat_ts"):
            note = f" (last activity {int(time.time() - job['heartbeat_ts'])}s ago)"
        lines.append(f"Current turn job {job['id']}: {job['status']}{note}")
    if session["status"] == "concluded":
        lines.append(f"Final synthesis: debate_result('{session_id}')")
    lines.append(f"Full manifest: debate_manifest('{session_id}') · "
                f"inbox: {config.MCPTOOLS_PUBLIC_URL}/inbox")
    return "\n".join(lines)


@mcp.tool
def debate_manifest(session_id: str, limit: int = 0) -> str:
    """Compact, sequenced index of every completed round in a debate: round
    number, persona, word count, a one-line description, and its file path
    — the same bounded view a turn's own prompt gets, so you can decide
    what's worth reading in full with debate_read_round rather than reading
    everything. limit: cap how many of the most recent rounds render in
    full (0 = server default); older rounds collapse to a count."""
    if debate_store.get_session(session_id) is None:
        return f"ERROR: no debate named '{session_id}'."
    return debate_store.render_manifest(
        session_id, limit or config.DEBATE_MANIFEST_RENDER_LIMIT)


@mcp.tool
def debate_read_round(session_id: str, round: int) -> str:
    """Full text of one completed round: its one-line abstract and full
    argument, exactly as the persona wrote it."""
    if debate_store.get_session(session_id) is None:
        return f"ERROR: no debate named '{session_id}'."
    text = debate_store.read_round(session_id, round)
    if text is None:
        return f"ERROR: no round {round} in debate '{session_id}' yet."
    return text


@mcp.tool
def debate_result(session_id: str) -> str:
    """The debate's final human-facing synthesis — what was decided or
    learned, the strongest surviving objections, and recommended next
    steps, written automatically by the monitor as the debate's closing
    turn. This is the one document to show the user; the per-round files
    (debate_read_round) are the underlying working record. Errors if the
    debate hasn't finished its synthesis yet."""
    session = debate_store.get_session(session_id)
    if session is None:
        return f"ERROR: no debate named '{session_id}'."
    summary = debate_store.read_summary(session_id)
    if summary is not None:
        return summary
    status = session.get("status")
    if status == "cancelled":
        reason = session.get("stop_reason") or "no reason recorded"
        return (f"Debate '{session_id}' was cancelled before producing a "
               f"final synthesis ({reason}). Its rounds are still readable "
               f"with debate_manifest/debate_read_round.")
    return (f"Debate '{session_id}' has not produced its final synthesis "
           f"yet (status: {status}). The synthesis is written "
           f"automatically as the closing turn once the debate ends — "
           f"check debate_status('{session_id}').")


@mcp.tool
def debate_list(status: str = "") -> str:
    """Recent debates, newest first. status filters to one of: active,
    concluding (rounds done, final synthesis being written), stuck,
    concluded, cancelled. Empty lists everything."""
    if not debate_store.available():
        return "ERROR: the debate store is not mounted."
    sessions = debate_store.list_sessions(status=status)
    if not sessions:
        return "No debates" + (f" with status '{status}'." if status else " yet.")
    return "\n".join(_session_summary_line(s) for s in sessions)


# ── Resume / cancel — the two narrow exceptions to "the worker owns every
# transition", mirroring jobs_store.py's own queued->cancelled carve-out ──────

def _do_debate_resume(params: dict) -> str:
    session = debate_store.get_session(params["session_id"])
    if session is None:
        return f"ERROR: no debate named '{params['session_id']}'."
    next_expected = session["next_expected"]
    synthesis = bool(next_expected.get("synthesis"))
    job = jobs_store.create_job(
        brief={"objective": f"Debate turn {next_expected['round']} "
                            f"({next_expected['persona']}"
                            f"{', synthesis' if synthesis else ''}), "
                            f"resumed: {session['goal'][:120]}",
              "deliverables": ["final human-facing synthesis" if synthesis
                               else "round argument text"]},
        source="debate",
        debate={"session_id": session["id"], "round": next_expected["round"],
               "persona": next_expected["persona"], "synthesis": synthesis})
    debate_store.update_session(session["id"],
                                status="concluding" if synthesis else "active",
                                queued_job_id=job["id"])
    return (f"Resumed debate {session['id']} — round "
           f"{next_expected['round']} ({next_expected['persona']}"
           f"{', synthesis' if synthesis else ''}) is queued as {job['id']}.")


policy.register_executor("debate", "debate_resume", _do_debate_resume)


@mcp.tool
def debate_resume(session_id: str) -> str:
    """WRITE ACTION — re-queue the interrupted turn of a debate stuck after
    a crash or a turn that ended needs_attention/failed (status 'stuck').
    Only valid on a stuck debate — an active one is already progressing on
    its own. Executes immediately (notify tier); the user is notified with
    a summary."""
    session = debate_store.get_session(session_id)
    if session is None:
        return f"ERROR: no debate named '{session_id}'."
    if session["status"] != "stuck":
        return (f"ERROR: debate '{session_id}' is '{session['status']}', "
               "not 'stuck' — nothing to resume.")
    return policy.apply_policy(
        domain="debate", tool="debate_resume", action_kind="update",
        target_id=session_id,
        summary=f"Resume debate {session_id} at round "
                f"{session['next_expected']['round']} "
                f"({session['next_expected']['persona']})",
        params={"session_id": session_id},
        changes=[f"Re-queued round {session['next_expected']['round']}"])


def _do_debate_cancel(params: dict) -> str:
    session = debate_store.get_session(params["session_id"])
    if session is None:
        return f"ERROR: no debate named '{params['session_id']}'."
    cancelled_job = bool(session.get("queued_job_id")) and jobs_store.cancel_job(
        session["queued_job_id"])
    debate_store.update_session(session["id"], status="cancelled",
                                stop_reason="cancelled by user")
    note = (" Its queued next turn was also cancelled." if cancelled_job else
           " If a turn is currently running it will finish and its round "
           "file will still be written, but no further turn will be queued.")
    return f"Debate '{session['id']}' cancelled.{note}"


policy.register_executor("debate", "debate_cancel", _do_debate_cancel)


@mcp.tool
def debate_cancel(session_id: str) -> str:
    """WRITE ACTION — stop a debate. If its next turn is still queued (not
    yet picked up by the worker), that job is cancelled outright; if a turn
    is already running, it's allowed to finish and write its round file,
    but no further turn is queued after it. Executes immediately (notify
    tier); the user is notified with a summary."""
    session = debate_store.get_session(session_id)
    if session is None:
        return f"ERROR: no debate named '{session_id}'."
    if session["status"] in ("concluded", "cancelled"):
        return f"ERROR: debate '{session_id}' is already {session['status']}."
    return policy.apply_policy(
        domain="debate", tool="debate_cancel", action_kind="update",
        target_id=session_id,
        summary=f"Cancel debate {session_id}",
        params={"session_id": session_id},
        changes=["status -> cancelled"])
