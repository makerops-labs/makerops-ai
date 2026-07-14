"""Devteam domain: start and steer a software-development engagement — a
lead-architect agent plus a specialist team (smolagents' agents/devteam/)
that builds an application in a registered ~/workspace/<project> directory
from a product plan, phase by phase (requirements → architecture → scaffold
→ milestones → qa → docs). Phases run as background jobs; between the
configured sign-off gates the team advances autonomously (the worker queues
the next phase itself). Session state lives in a directory shared with the
smolagents job worker via bind mount; the worker owns phase advancement.
This domain starts an engagement, reads its state, and performs exactly the
five user-driven transitions: answer questions (awaiting_input), approve or
request revision at a gate (awaiting_review), resume a stuck engagement,
and cancel — mirroring the debate domain's carve-outs."""

import time

from fastmcp import FastMCP

from . import config, devteam_store, jobs_store, policy
from .project import get_project

mcp = FastMCP(
    "devteam",
    instructions=(
        "Software-development engagements: a lead-architect agent and a "
        "specialist team build an application in a registered "
        "~/workspace/<project> directory from a product plan, phase by "
        "phase in the background. devteam_start begins one (the project "
        "must be registered first — see the project domain). The team "
        "works autonomously between sign-off gates; it pauses as "
        "awaiting_input when the architect has questions (relay them, then "
        "devteam_answer) and as awaiting_review at a gate (summarize "
        "devteam_result, then devteam_approve or devteam_revise — ONLY on "
        "the user's explicit instruction). devteam_status/devteam_list "
        "track progress; devteam_resume/devteam_cancel handle a stuck or "
        "unwanted engagement."))
required_env = None  # writes to the bind mount, no token

_MIN_PLAN_CHARS = 80


def _resolve_gates(gates: str) -> list[str] | str:
    """A preset name or an explicit comma-separated list of phase kinds/
    names. Returns the resolved list, or an 'ERROR: ...' string."""
    key = (gates or "key").strip().lower()
    if key in devteam_store.GATE_PRESETS:
        return list(devteam_store.GATE_PRESETS[key])
    explicit = [g.strip() for g in gates.split(",") if g.strip()]
    known = set(devteam_store.GATE_PRESETS["all"])
    unknown = [g for g in explicit if g not in known
               and not g.startswith("milestone-")]
    if not explicit or unknown:
        return (f"ERROR: gates must be one of "
                f"{tuple(devteam_store.GATE_PRESETS)} or a comma-separated "
                f"list of phase kinds {sorted(known)}"
                + (f" — unknown: {unknown}" if unknown else "."))
    return explicit


def _summary_line(session: dict) -> str:
    phases = session.get("phases", [])
    done = sum(1 for p in phases if p.get("status") in ("approved", "done"))
    current = session.get("current_phase", 0)
    name = phases[current]["name"] if 0 <= current < len(phases) else "?"
    return (f"{session['id']} [{session['status']}] project "
            f"'{session.get('project', '')}' — phase {done}/{len(phases)} "
            f"done, at '{name}' (created {session.get('created_at', '?')})")


# ── Start ────────────────────────────────────────────────────────────────────

def _do_devteam_start(params: dict) -> str:
    session = devteam_store.create_session(
        project=params["project"], product_plan=params["product_plan"],
        constraints=params["constraints"], context=params["context"],
        gates=params["gates"])
    job = devteam_store.queue_phase(session, 0, "start")
    gates = ", ".join(params["gates"]) or "none — fully autonomous"
    return (f"OBJECT_ID={session['id']}\n"
            f"Engagement {session['id']} started on project "
            f"'{params['project']}'. Phase 0 (requirements) is queued as "
            f"{job['id']} and runs in the background; between sign-off "
            f"gates ({gates}) the team advances on its own. You will be "
            f"notified when input or a review is needed. Track with "
            f"devteam_status('{session['id']}').")


policy.register_executor("devteam", "devteam_start", _do_devteam_start)


@mcp.tool
def devteam_start(project: str, product_plan: str,
                  constraints: list[str] | None = None, context: str = "",
                  gates: str = "key") -> str:
    """WRITE ACTION — start a software-development engagement: the
    lead-architect agent and its specialist team build the application
    described by product_plan inside the registered project directory
    ~/workspace/<project>, phase by phase in the background (requirements →
    architecture → scaffold → implementation milestones → qa → docs).
    product_plan: the full plan text, refined with the user first — what
    the app is, its features, stack preferences, and non-goals; the
    requirements phase will ask (pausing the engagement) rather than guess
    at real product decisions, so a concrete plan means faster progress.
    gates: which phases park for the user's explicit sign-off before the
    team continues — 'key' (default: requirements, architecture, docs),
    'all', 'none', or a comma-separated list of phase kinds. Ungated
    phases notify and continue automatically. Returns the engagement id.
    Preconditions: the project is already registered (project_register —
    the user creating ~/workspace/<project> by hand is the write
    authorization); a non-trivial product plan; devteam store and job
    queue mounted.
    Effects: creates the engagement and queues its requirements phase;
    runs unattended between gates (heavy model time, hours). The user is
    notified at every gate, question, milestone, and stuck state.
    Failure modes: 'ERROR: ...' on an unregistered project, an empty/thin
    plan, invalid gates, or unmounted stores. A failed phase leaves the
    engagement 'stuck' — devteam_resume, never a duplicate engagement."""
    project = project.strip()
    if not project:
        return "ERROR: project is empty."
    if get_project(project) is None:
        return (f"ERROR: project '{project}' is not registered. Create "
                f"~/workspace/{project} and register it with "
                "project_register first — the engagement writes all code "
                "and docs there.")
    if len((product_plan or "").strip()) < _MIN_PLAN_CHARS:
        return (f"ERROR: product_plan is too thin (<{_MIN_PLAN_CHARS} "
                "chars) — refine it with the user first: what the app is, "
                "its features, stack preferences, and non-goals.")
    resolved_gates = _resolve_gates(gates)
    if isinstance(resolved_gates, str):
        return resolved_gates
    if not jobs_store.available() or not devteam_store.available():
        return ("ERROR: the devteam store or agent job queue is not "
                "mounted — is mcp-tools running with its default volumes "
                "(and smolagents started)?")
    return policy.apply_policy(
        domain="devteam", tool="devteam_start", action_kind="create",
        summary=f"Start devteam engagement on '{project}': "
                f"{product_plan.strip()[:100]}",
        params={"project": project, "product_plan": product_plan,
                "constraints": constraints or [], "context": context,
                "gates": resolved_gates},
        changes=[f"New engagement on project '{project}'"],
        created_object_id_from_result=True)


# ── Read-only status ─────────────────────────────────────────────────────────

@mcp.tool
def devteam_status(engagement_id: str) -> str:
    """Status of an engagement: the phase table (with gates and revision
    counts), any open questions awaiting the user, the stop reason if
    stuck, and the liveness of the current phase's background job. Statuses:
    running (working autonomously), awaiting_input (answer with
    devteam_answer), awaiting_review (devteam_approve/devteam_revise),
    stuck (devteam_resume), concluded, cancelled."""
    session = devteam_store.get_session(engagement_id)
    if session is None:
        return f"ERROR: no engagement named '{engagement_id}'."
    lines = [_summary_line(session), "", devteam_store.render_phase_table(session)]
    if session.get("open_questions"):
        lines.append("\nQuestions for the user (answer via devteam_answer):")
        lines += [f"  ? {q}" for q in session["open_questions"]]
    if session.get("stop_reason"):
        lines.append(f"\nStop reason: {session['stop_reason']}")
    job_id = session.get("queued_job_id") or session.get("current_job_id")
    job = jobs_store.get_job(job_id) if job_id else None
    if job:
        note = ""
        if job.get("status") == "running" and job.get("heartbeat_ts"):
            note = f" (last activity {int(time.time() - job['heartbeat_ts'])}s ago)"
        lines.append(f"Current phase job {job['id']}: {job['status']}{note}")
    if session.get("status") == "awaiting_review":
        lines.append("Awaiting the user's sign-off: summarize "
                     f"devteam_result('{engagement_id}') for them, then "
                     "devteam_approve or devteam_revise per their explicit "
                     "instruction.")
    lines.append(f"Inbox: {config.MCPTOOLS_PUBLIC_URL}/inbox")
    return "\n".join(lines)


@mcp.tool
def devteam_list(status: str = "") -> str:
    """Recent engagements, newest first. status filters to one of: running,
    awaiting_input, awaiting_review, stuck, concluded, cancelled. Empty
    lists everything."""
    if not devteam_store.available():
        return "ERROR: the devteam store is not mounted."
    sessions = devteam_store.list_sessions(status=status)
    if not sessions:
        return ("No engagements"
                + (f" with status '{status}'." if status else " yet."))
    return "\n".join(_summary_line(s) for s in sessions)


@mcp.tool
def devteam_result(engagement_id: str, phase: int = -1) -> str:
    """The landed report of one engagement phase — summary, deliverables
    (file paths in the project), reviewer findings, attention items, and
    (for the architecture phase) the milestone plan. phase: a phase index
    from devteam_status, or -1 (default) for the most recently landed
    phase — at a review gate that is exactly the phase awaiting sign-off.
    Use this to summarize a gate for the user before devteam_approve /
    devteam_revise."""
    session = devteam_store.get_session(engagement_id)
    if session is None:
        return f"ERROR: no engagement named '{engagement_id}'."
    index = phase if phase >= 0 else devteam_store.latest_landed_phase(session)
    if index is None:
        return f"ERROR: no phase of '{engagement_id}' has landed a report yet."
    report = devteam_store.read_phase_report(engagement_id, index)
    if report is None:
        return (f"ERROR: phase {index} of '{engagement_id}' has no landed "
                "report (not run yet, or an invalid index).")
    p = session["phases"][index]
    lines = [f"Phase {index} '{p['name']}' [{p.get('status')}] of "
             f"{engagement_id} — report:",
             f"Status: {report.get('status')}",
             f"Summary: {report.get('summary', '')}"]
    for d in report.get("deliverables") or []:
        lines.append(f"Deliverable: {d.get('title', '?')} "
                     f"({d.get('type', '?')}) — {d.get('location', '')}")
    audit = report.get("audit") or {}
    if audit.get("performed"):
        lines.append(f"Review findings: {audit.get('findings', '(none)')}")
    for a in report.get("attention") or []:
        lines.append(f"Attention: {a}")
    for m in report.get("milestones") or []:
        lines.append(f"Planned milestone: {m.get('name', '?')} — "
                     f"{m.get('objective', '')}")
    for n in report.get("decisions") or []:
        lines.append(f"Decision: {n}")
    return "\n".join(lines)


# ── The five user-driven transitions — the narrow exceptions to "the worker
# owns every transition", mirroring the debate domain's carve-outs ───────────

def _do_devteam_answer(params: dict) -> str:
    session = devteam_store.get_session(params["engagement_id"])
    if session is None:
        return f"ERROR: no engagement named '{params['engagement_id']}'."
    if session.get("status") != "awaiting_input":
        return (f"ERROR: engagement is '{session.get('status')}', not "
                "'awaiting_input' — nothing is waiting for answers.")
    phase_index = session.get("current_phase", 0)
    session.setdefault("answers", []).append(
        {"phase": phase_index, "questions": session.get("open_questions", []),
         "answers": params["answers"],
         "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    job = devteam_store.queue_phase(session, phase_index, "answers")
    return (f"Answers recorded. Phase "
            f"'{session['phases'][phase_index]['name']}' resumes with them "
            f"as job {job['id']} — the architect is instructed to treat "
            "them as settled.")


policy.register_executor("devteam", "devteam_answer", _do_devteam_answer)


@mcp.tool
def devteam_answer(engagement_id: str, answers: str) -> str:
    """WRITE ACTION — answer the architect's open questions and resume a
    paused engagement (status awaiting_input). answers: the user's answers,
    captured faithfully — quote their words for preferences and decisions;
    cover every open question shown by devteam_status. The paused phase
    re-runs with the questions and these answers injected verbatim.
    Executes immediately (notify tier).
    Preconditions: the engagement's status is exactly 'awaiting_input'.
    Effects: records the answers and requeues the paused phase; the
    engagement returns to autonomous running.
    Failure modes: 'ERROR: ...' when the engagement is unknown or not
    awaiting input."""
    session = devteam_store.get_session(engagement_id)
    if session is None:
        return f"ERROR: no engagement named '{engagement_id}'."
    if session.get("status") != "awaiting_input":
        return (f"ERROR: engagement '{engagement_id}' is "
                f"'{session.get('status')}', not 'awaiting_input' — "
                "nothing is waiting for answers.")
    if not (answers or "").strip():
        return "ERROR: answers is empty — gather the user's answers first."
    return policy.apply_policy(
        domain="devteam", tool="devteam_answer", action_kind="update",
        target_id=engagement_id,
        summary=f"Answer questions on engagement {engagement_id}",
        params={"engagement_id": engagement_id, "answers": answers},
        changes=[f"Answered {len(session.get('open_questions', []))} open "
                 "question(s); phase resumes"])


def _do_devteam_approve(params: dict) -> str:
    session = devteam_store.get_session(params["engagement_id"])
    if session is None:
        return f"ERROR: no engagement named '{params['engagement_id']}'."
    if session.get("status") != "awaiting_review":
        return (f"ERROR: engagement is '{session.get('status')}', not "
                "'awaiting_review' — nothing is gated for approval.")
    phase_index = session.get("current_phase", 0)
    phase = session["phases"][phase_index]
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    phase["status"] = "approved"
    phase["approved_at"] = now
    if params.get("feedback"):
        session.setdefault("feedback", []).append(
            {"phase": phase_index, "verdict": "approve",
             "feedback": params["feedback"], "ts": now})
    if phase_index == len(session["phases"]) - 1:
        session["status"] = "concluded"
        session["stop_reason"] = "final delivery approved by the client"
        devteam_store.save_session(session)
        policy._notify("devteam.completed", {
            "engagement_id": session["id"],
            "project": session.get("project", ""),
            "summary": f"Engagement {session['id']} concluded — final "
                       "delivery approved."})
        return (f"Engagement {session['id']} CONCLUDED — final delivery "
                f"approved. The application lives in "
                f"~/workspace/{session.get('project', '')}.")
    job = devteam_store.queue_phase(session, phase_index + 1, "start")
    next_name = session["phases"][phase_index + 1]["name"]
    return (f"Phase '{phase['name']}' approved. Next phase '{next_name}' "
            f"is queued as {job['id']} and the team continues "
            "autonomously until the next gate, question, or stuck state.")


policy.register_executor("devteam", "devteam_approve", _do_devteam_approve)


@mcp.tool
def devteam_approve(engagement_id: str, feedback: str = "") -> str:
    """WRITE ACTION — approve the phase gated for review (status
    awaiting_review) and let the team continue; on the final phase this
    concludes the engagement. Call ONLY on the user's explicit approval —
    never approve on their behalf; summarize devteam_result for them first.
    feedback: optional non-blocking notes to record alongside the approval.
    Executes immediately (notify tier).
    Preconditions: the engagement's status is exactly 'awaiting_review',
    and the user explicitly approved.
    Effects: marks the gated phase approved; queues the next phase (or
    concludes the engagement after the final phase).
    Failure modes: 'ERROR: ...' when the engagement is unknown or nothing
    is gated. A mistaken approval is recoverable — the next gate's
    devteam_revise can send work back, or devteam_cancel stops the run."""
    session = devteam_store.get_session(engagement_id)
    if session is None:
        return f"ERROR: no engagement named '{engagement_id}'."
    if session.get("status") != "awaiting_review":
        return (f"ERROR: engagement '{engagement_id}' is "
                f"'{session.get('status')}', not 'awaiting_review' — "
                "nothing is gated for approval.")
    phase = session["phases"][session.get("current_phase", 0)]
    return policy.apply_policy(
        domain="devteam", tool="devteam_approve", action_kind="update",
        target_id=engagement_id,
        summary=f"Approve phase '{phase['name']}' of {engagement_id}",
        params={"engagement_id": engagement_id, "feedback": feedback},
        changes=[f"Phase '{phase['name']}' approved by the user"])


def _do_devteam_revise(params: dict) -> str:
    session = devteam_store.get_session(params["engagement_id"])
    if session is None:
        return f"ERROR: no engagement named '{params['engagement_id']}'."
    if session.get("status") != "awaiting_review":
        return (f"ERROR: engagement is '{session.get('status')}', not "
                "'awaiting_review' — nothing is gated for revision.")
    phase_index = session.get("current_phase", 0)
    phase = session["phases"][phase_index]
    session.setdefault("feedback", []).append(
        {"phase": phase_index, "verdict": "revise",
         "feedback": params["feedback"],
         "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    phase["revisions"] = phase.get("revisions", 0) + 1
    job = devteam_store.queue_phase(session, phase_index, "revision")
    return (f"Revision requested on phase '{phase['name']}' (revision "
            f"{phase['revisions']}), queued as job {job['id']} with the "
            "user's feedback injected verbatim. It gates for review again "
            "when done.")


policy.register_executor("devteam", "devteam_revise", _do_devteam_revise)


@mcp.tool
def devteam_revise(engagement_id: str, feedback: str) -> str:
    """WRITE ACTION — send the phase gated for review (status
    awaiting_review) back for rework instead of approving it. feedback:
    the user's requested changes, quoted faithfully and concretely — the
    architect addresses exactly this. The phase re-runs and gates for
    review again. Executes immediately (notify tier).
    Preconditions: status exactly 'awaiting_review'; non-empty feedback
    from the user.
    Effects: requeues the same phase with the feedback injected; the
    revision count increments.
    Failure modes: 'ERROR: ...' when the engagement is unknown, nothing is
    gated, or feedback is empty."""
    session = devteam_store.get_session(engagement_id)
    if session is None:
        return f"ERROR: no engagement named '{engagement_id}'."
    if session.get("status") != "awaiting_review":
        return (f"ERROR: engagement '{engagement_id}' is "
                f"'{session.get('status')}', not 'awaiting_review' — "
                "nothing is gated for revision.")
    if not (feedback or "").strip():
        return ("ERROR: feedback is empty — capture the user's requested "
                "changes first.")
    phase = session["phases"][session.get("current_phase", 0)]
    return policy.apply_policy(
        domain="devteam", tool="devteam_revise", action_kind="update",
        target_id=engagement_id,
        summary=f"Request revision of phase '{phase['name']}' of "
                f"{engagement_id}",
        params={"engagement_id": engagement_id, "feedback": feedback},
        changes=[f"Phase '{phase['name']}' sent back for rework"])


def _do_devteam_resume(params: dict) -> str:
    session = devteam_store.get_session(params["engagement_id"])
    if session is None:
        return f"ERROR: no engagement named '{params['engagement_id']}'."
    if session.get("status") != "stuck":
        return (f"ERROR: engagement is '{session.get('status')}', not "
                "'stuck' — nothing to resume.")
    phase_index = session.get("next_expected", {}).get(
        "phase_index", session.get("current_phase", 0))
    session["stop_reason"] = None
    job = devteam_store.queue_phase(session, phase_index, "resume")
    return (f"Resumed engagement {session['id']} — phase "
            f"'{session['phases'][phase_index]['name']}' re-runs as job "
            f"{job['id']}, re-verifying existing work before redoing any.")


policy.register_executor("devteam", "devteam_resume", _do_devteam_resume)


@mcp.tool
def devteam_resume(engagement_id: str) -> str:
    """WRITE ACTION — re-queue the interrupted phase of an engagement stuck
    after a crash, a failed phase, or an architecture phase that produced
    no valid milestone plan (status 'stuck' — devteam_status shows the stop
    reason). Only valid on a stuck engagement. Executes immediately (notify
    tier).
    Preconditions: the engagement's status is exactly 'stuck'.
    Effects: re-queues the interrupted phase; it resumes from its own
    working memory rather than starting over.
    Failure modes: 'ERROR: ...' when the engagement is unknown or not
    stuck."""
    session = devteam_store.get_session(engagement_id)
    if session is None:
        return f"ERROR: no engagement named '{engagement_id}'."
    if session.get("status") != "stuck":
        return (f"ERROR: engagement '{engagement_id}' is "
                f"'{session.get('status')}', not 'stuck' — nothing to "
                "resume.")
    return policy.apply_policy(
        domain="devteam", tool="devteam_resume", action_kind="update",
        target_id=engagement_id,
        summary=f"Resume stuck engagement {engagement_id}",
        params={"engagement_id": engagement_id},
        changes=["Re-queued the interrupted phase"])


def _do_devteam_cancel(params: dict) -> str:
    session = devteam_store.get_session(params["engagement_id"])
    if session is None:
        return f"ERROR: no engagement named '{params['engagement_id']}'."
    if session.get("status") in devteam_store.TERMINAL_STATUSES:
        return (f"ERROR: engagement is already {session.get('status')}.")
    cancelled_job = bool(session.get("queued_job_id")) and jobs_store.cancel_job(
        session["queued_job_id"])
    session["status"] = "cancelled"
    session["stop_reason"] = "cancelled by user"
    session["queued_job_id"] = None
    devteam_store.save_session(session)
    note = (" Its queued phase job was also cancelled." if cancelled_job else
            " If a phase is currently running it will finish and its work "
            "in the project remains, but nothing further is queued.")
    return f"Engagement '{session['id']}' cancelled.{note}"


policy.register_executor("devteam", "devteam_cancel", _do_devteam_cancel)


@mcp.tool
def devteam_cancel(engagement_id: str) -> str:
    """WRITE ACTION — stop an engagement. A still-queued phase job is
    cancelled outright; a running phase finishes (its project writes
    remain) but nothing further is queued. Work already written to the
    project directory is never deleted. Executes immediately (notify tier).
    Preconditions: the engagement exists and is not already concluded or
    cancelled.
    Effects: status -> cancelled; the engagement never advances again.
    Failure modes: 'ERROR: ...' on unknown or already-terminal
    engagements."""
    session = devteam_store.get_session(engagement_id)
    if session is None:
        return f"ERROR: no engagement named '{engagement_id}'."
    if session.get("status") in devteam_store.TERMINAL_STATUSES:
        return (f"ERROR: engagement '{engagement_id}' is already "
                f"{session.get('status')}.")
    return policy.apply_policy(
        domain="devteam", tool="devteam_cancel", action_kind="update",
        target_id=engagement_id,
        summary=f"Cancel engagement {engagement_id}",
        params={"engagement_id": engagement_id},
        changes=["status -> cancelled"])
