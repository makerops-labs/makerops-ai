"""Background job worker: runs manager-agent jobs dispatched by mcp-tools.

The queue is a shared directory (config.JOBS_DIR, bind-mounted into
mcp-tools as /agent-jobs): one JSON record per job plus a per-job workspace
tree the manager uses as working memory. Ownership rule: mcp-tools only
creates records with status "queued" (and may flip queued→cancelled);
this worker owns every other transition. Writes are atomic (tmp+rename).

Long jobs run in segments: when the manager answers status "continuation",
the next run starts fresh from the brief plus the workspace synopsis —
bounded context over an arbitrarily large task (see manager.py PROCEDURE
step 5).
"""

import json
import os
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from smolagents.memory import ActionStep, PlanningStep

from . import config

_POLL_S = 2.0
_LOG_TAIL_CHARS = 2000
_TERMINAL = {"completed", "needs_clarification", "needs_attention",
             "failed", "cancelled"}

_jobs_dir = Path(config.JOBS_DIR)
_debates_dir = Path(config.DEBATES_DIR)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _job_path(job_id: str) -> Path:
    return _jobs_dir / f"{job_id}.json"


def _save(job: dict) -> None:
    """Atomic write so mcp-tools never reads a half-written record."""
    path = _job_path(job["id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(job, indent=1, ensure_ascii=False))
    os.replace(tmp, path)


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _queued_jobs() -> list[dict]:
    jobs = [j for p in _jobs_dir.glob("job-*.json")
            if (j := _load(p)) and j.get("status") == "queued"]
    return sorted(jobs, key=lambda j: j.get("created_at", ""))


def _notify(event: str, job: dict) -> None:
    """Fire-and-forget webhook (n8n) on job completion/attention events."""
    if not config.NOTIFY_WEBHOOK:
        return
    payload = {"event": event, "job_id": job["id"],
               "objective": job.get("brief", {}).get("objective", ""),
               "summary": job.get("report", {}).get("summary",
                                                    job.get("error") or ""),
               "inbox_url": f"{config.MCP_TOOLS_PUBLIC_URL}/inbox"}
    try:
        httpx.post(config.NOTIFY_WEBHOOK, json=payload, timeout=10)
    except httpx.HTTPError as exc:
        print(f"[jobs] notify webhook failed for {job['id']}: {exc}")


def _write_roster(manager) -> None:
    """Live roster consumed by the mcp-tools agent_list tool."""
    roster = [{"name": "manager",
               "description": "Orchestrator: refines briefs, plans, "
                              "delegates to the team, audits by risk, and "
                              "reports. Background jobs always run through "
                              "the manager."}]
    roster += [{"name": name, "description": agent.description}
               for name, agent in manager.managed_agents.items()]
    _jobs_dir.mkdir(parents=True, exist_ok=True)
    tmp = _jobs_dir / "roster.json.tmp"
    tmp.write_text(json.dumps(roster, indent=1, ensure_ascii=False))
    os.replace(tmp, _jobs_dir / "roster.json")


def _format_task(job: dict, workspace: Path) -> str:
    brief = job.get("brief", {})
    lines = [
        f"Background job {job['id']} (segment {job.get('segments', 1)}).",
        f"Objective: {brief.get('objective', '')}",
        "Deliverables: " + "; ".join(brief.get("deliverables", []) or ["(unspecified)"]),
    ]
    for key in ("audience", "quality", "audit", "urgency"):
        if brief.get(key):
            lines.append(f"{key.capitalize()}: {brief[key]}")
    if brief.get("constraints"):
        lines.append("Constraints: " + "; ".join(brief["constraints"]))
    if brief.get("resources"):
        lines.append("Resources: " + "; ".join(brief["resources"]))
    if brief.get("context"):
        lines.append(f"Context from the user:\n{brief['context']}")
    if job.get("parent_job_id"):
        lines.append(f"This continues clarified job {job['parent_job_id']}.")

    if brief.get("project"):
        lines.append(
            f"This job implements an already-approved solution in project "
            f"'{brief['project']}' (a durable directory under ~/workspace/, "
            f"NOT the per-job working-memory workspace below). FIRST call "
            f"project_read_file('{brief['project']}', 'PROJECT_CONTEXT.md') "
            f"to orient yourself — it always exists once a project is "
            f"registered. Survey further with project_glob/project_grep/"
            f"project_list_dir/project_read_file (including sibling "
            f"directories under ~/workspace for prior art) before writing. "
            f"Write via project_write_file/project_edit_file, and update "
            f"PROJECT_CONTEXT.md and project_set_status as you progress.")

    lines.append(
        f"Your working-memory workspace directory is {workspace} "
        "(create files with pathlib). Keep synopsis.md there current per "
        "your WORKING MEMORY procedure. This is separate from the project "
        "directory above, if any — synopsis.md is your own scratch memory "
        "for this job, PROJECT_CONTEXT.md is the durable project record.")
    lines.append(
        "FIRST apply your VALIDATE step: if this brief is too vague to "
        "execute without guessing, answer needs_clarification immediately. "
        "Always finish with build_report(...) and final_answer(report) — "
        "no hand-written dict literals, no other text.")

    synopsis = workspace / "synopsis.md"
    if synopsis.is_file():
        listing = ", ".join(sorted(
            str(p.relative_to(workspace))
            for p in workspace.rglob("*") if p.is_file())) or "(empty)"
        lines.append(
            "A previous segment already worked this job. Resume from its "
            f"synopsis below; workspace files: {listing}\n\n--- synopsis.md ---\n"
            + synopsis.read_text())
    return "\n".join(lines)


# ── Debate turns ─────────────────────────────────────────────────────────────
# A second, parallel queue sharing this same job-record mechanism (a debate
# turn IS an ordinary job, tagged job["debate"]) but with its own durable
# session store under _debates_dir: session.json (status/round/next_expected),
# manifest.jsonl (one line per completed round, append-only — matches
# mcp-tools' audit.jsonl pattern so a half-written last line is trivially
# skippable), and rounds/round-NNN-<persona>.md. Turn advancement below is
# deterministic Python, never an LLM tool call — see debate_manager.py's
# module docstring for why.

def _debate_session_path(session_id: str) -> Path:
    return _debates_dir / session_id / "session.json"


def _debate_manifest_path(session_id: str) -> Path:
    return _debates_dir / session_id / "manifest.jsonl"


def _debate_rounds_dir(session_id: str) -> Path:
    return _debates_dir / session_id / "rounds"


def _load_debate_session(session_id: str) -> dict | None:
    return _load(_debate_session_path(session_id))


def _save_debate_session(session: dict) -> None:
    path = _debate_session_path(session["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(session, indent=1, ensure_ascii=False))
    os.replace(tmp, path)


def _load_debate_manifest(session_id: str) -> list[dict]:
    entries = []
    try:
        lines = _debate_manifest_path(session_id).read_text().splitlines()
    except OSError:
        return entries
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def _append_debate_manifest_entry(session_id: str, entry: dict) -> None:
    path = _debate_manifest_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _render_debate_manifest(session_id: str, limit: int) -> str:
    """Compact, bounded index rendered oldest-to-newest (reading order);
    older entries collapse once the count exceeds limit, so a turn's task
    prompt stays flat regardless of how long the debate runs."""
    entries = _load_debate_manifest(session_id)
    if not entries:
        return "(no rounds yet)"
    shown = entries[-limit:] if limit and len(entries) > limit else entries
    omitted = len(entries) - len(shown)
    lines = []
    if omitted > 0:
        lines.append(f"... [{omitted} earlier round(s) omitted; read one "
                     "with pathlib if its description looks relevant]")
    for e in shown:
        lines.append(f"R{e.get('round')} [{e.get('persona')}] "
                     f"{e.get('word_count', '?')}w — {e.get('description', '')} "
                     f"({e.get('path', '')})")
    return "\n".join(lines)


def _write_debate_round_file(session_id: str, round_num: int, persona: str,
                             full_text: str) -> str:
    """Writes the round file (hard-capped as a backstop — persona prompts
    target ~400-700 words on their own) and returns its path relative to
    the session directory, for the manifest entry."""
    text = full_text.strip()
    if len(text) > config.DEBATE_ROUND_MAX_CHARS:
        text = (text[:config.DEBATE_ROUND_MAX_CHARS]
               + f"\n\n... [truncated at {config.DEBATE_ROUND_MAX_CHARS} chars]")
    rounds_dir = _debate_rounds_dir(session_id)
    rounds_dir.mkdir(parents=True, exist_ok=True)
    filename = f"round-{round_num:03d}-{persona}.md"
    (rounds_dir / filename).write_text(f"# Round {round_num} — {persona}\n\n{text}\n")
    return f"rounds/{filename}"


def _recent_debate_round_texts(session_id: str, count: int) -> str:
    """Full text of only the most recent `count` rounds — older rounds are
    manifest-only, readable on demand via pathlib (see _DEBATE_PROCEDURE)."""
    entries = _load_debate_manifest(session_id)
    if not entries or count <= 0:
        return ""
    sections = []
    for e in entries[-count:]:
        path = _debates_dir / session_id / e["path"]
        try:
            text = path.read_text()
        except OSError:
            continue
        sections.append(f"### Round {e.get('round')} — {e.get('persona')}\n\n{text}")
    return "\n\n".join(sections)


def _next_debate_persona(next_round: int, monitor_every_n: int) -> str:
    """Fixed cadence, e.g. monitor_every_n=2: entrepreneur, critic,
    entrepreneur, critic, monitor, entrepreneur, ... — deterministic so the
    worker never has to parse a model-chosen speaker name."""
    cycle_len = 2 * monitor_every_n + 1
    pos = ((next_round - 1) % cycle_len) + 1
    if pos == cycle_len:
        return "monitor"
    return "entrepreneur" if pos % 2 == 1 else "critic"


def _format_debate_task(job: dict, workspace: Path) -> str:
    debate = job["debate"]
    session_id, round_num, persona = (debate["session_id"], debate["round"],
                                      debate["persona"])
    session = _load_debate_session(session_id)
    if session is None:
        return (f"DEBATE TURN — session {session_id} round {round_num} "
               f"persona '{persona}'. ERROR: session.json is missing for "
               "this debate. Skip delegating to a persona; instead call "
               "build_debate_report(status='needs_attention', "
               "full_text='session record not found', abstract='session "
               "record not found') and finish.")
    session_dir = _debates_dir / session_id
    lines = [
        f"DEBATE TURN — session {session_id}, round {round_num}, persona "
        f"'{persona}'. Session directory (for any pathlib look-back): "
        f"{session_dir}",
        f"Debate goal ({session['mode']}): {session['goal']}",
    ]
    if session.get("deliverables"):
        lines.append("What a good debate should ultimately produce: "
                     + "; ".join(session["deliverables"]))
    if session.get("constraints"):
        lines.append("Constraints: " + "; ".join(session["constraints"]))
    if session.get("resources"):
        lines.append("Resources: " + "; ".join(session["resources"]))
    if session.get("context"):
        lines.append(f"Background context:\n{session['context']}")
    lines.append(
        "This is a BROAD, open-ended exploration — the persona may use web "
        "research, consider multiple angles, and should not rush to "
        "converge." if session["mode"] == "broad" else
        "This is a NARROW, well-scoped question — keep the persona's "
        "answer concrete and directly responsive; do not broaden scope.")
    if session.get("pending_redirect"):
        lines.append(
            f"MONITOR REDIRECT (from round {session['current_round']}): "
            f"{session['pending_redirect']}\nAddress this before anything "
            "else.")
    lines.append("\n--- Manifest of all rounds so far ---\n"
                 + _render_debate_manifest(session_id, config.DEBATE_MANIFEST_RENDER_LIMIT))
    recent = _recent_debate_round_texts(session_id, config.DEBATE_RECENT_ROUNDS_FULL)
    if recent:
        lines.append("\n--- Full text of the most recent round(s) ---\n" + recent)
    lines.append(
        f"\nYOUR JOB THIS TURN: delegate this ENTIRE turn to the '{persona}' "
        "sub-agent per your procedure steps 3-6 — pass it the goal, mode, "
        "constraints, manifest, and recent-round text above (plus any "
        "monitor redirect), call it exactly once, then relay its answer "
        "verbatim via build_debate_report and finish.")
    return "\n".join(lines)


def _new_debate_job(session_id: str, round_num: int, persona: str,
                    mode: str, goal: str) -> dict:
    return {
        "id": f"job-{int(time.time())}-{uuid.uuid4().hex[:6]}",
        "status": "queued",
        "source": "debate",
        "created_at": _now(),
        "started_at": None,
        "finished_at": None,
        "heartbeat_ts": 0,
        "parent_job_id": None,
        "segments": 1,
        "brief": {"objective": f"Debate turn {round_num} ({persona}, "
                               f"{mode}): {goal[:150]}",
                 "deliverables": ["round argument text"]},
        "report": None,
        "error": None,
        "log_tail": "",
        "debate": {"session_id": session_id, "round": round_num, "persona": persona},
    }


def _notify_debate(event: str, session: dict) -> None:
    """Fire-and-forget webhook, mirrors _notify but for session-level
    events (concluded/stuck) rather than per-job ones."""
    if not config.NOTIFY_WEBHOOK:
        return
    payload = {"event": event, "session_id": session["id"],
              "goal": session.get("goal", ""), "status": session.get("status"),
              "stop_reason": session.get("stop_reason") or "",
              "inbox_url": f"{config.MCP_TOOLS_PUBLIC_URL}/inbox"}
    try:
        httpx.post(config.NOTIFY_WEBHOOK, json=payload, timeout=10)
    except httpx.HTTPError as exc:
        print(f"[jobs] debate notify webhook failed for {session['id']}: {exc}")


def _advance_debate(job: dict, report: dict) -> None:
    """Deterministic turn advancement, run only after a debate-turn job
    reaches status 'completed' (see _run_job) — this, not an LLM tool call,
    is what makes 'reliably start the next turn' actually reliable."""
    debate = job["debate"]
    session_id, round_num, persona = (debate["session_id"], debate["round"],
                                      debate["persona"])
    session = _load_debate_session(session_id)
    if session is None:
        print(f"[jobs] debate {session_id}: session.json missing — cannot "
             f"advance turn {round_num}")
        return

    full_text = (report.get("full_text") or "").strip()
    abstract = (report.get("abstract") or full_text[:120] or "(empty)").strip()
    rel_path = _write_debate_round_file(session_id, round_num, persona, full_text)
    _append_debate_manifest_entry(session_id, {
        "seq": round_num, "round": round_num, "persona": persona,
        "path": rel_path, "description": abstract[:200],
        "word_count": len(full_text.split()), "created_at": _now()})

    session["current_round"] = round_num
    session["last_persona"] = persona
    session["current_job_id"] = job["id"]

    if session.get("status") == "cancelled":
        # Let this turn's output land, but a cancelled debate never queues
        # another turn regardless of what the monitor's verdict said.
        _save_debate_session(session)
        return

    verdict = report.get("verdict", "continue")
    if verdict not in ("continue", "redirect", "conclude"):
        print(f"[jobs] debate {session_id}: unexpected verdict {verdict!r}, "
             "treating as 'continue'")
        verdict = "continue"

    if verdict == "conclude" or round_num >= session["max_rounds"]:
        session["status"] = "concluded"
        session["stop_reason"] = (
            "monitor concluded the debate" if verdict == "conclude"
            else f"max_rounds ({session['max_rounds']}) reached")
        _save_debate_session(session)
        _notify_debate("debate.concluded", session)
        return

    session["pending_redirect"] = ((report.get("redirect_note") or "").strip()
                                   if verdict == "redirect" else None)
    next_persona = _next_debate_persona(round_num + 1, session["monitor_every_n"])
    next_job = _new_debate_job(session_id, round_num + 1, next_persona,
                               session["mode"], session["goal"])
    session["status"] = "active"
    session["queued_job_id"] = next_job["id"]
    session["next_expected"] = {"round": round_num + 1, "persona": next_persona}
    _save_debate_session(session)
    _save(next_job)  # picked up by the SAME poll loop within _POLL_S


def _mark_debate_stuck(job: dict, report: dict) -> None:
    """Any non-completed terminal status, or a worker restart mid-turn
    (_recover_stale), halts auto-advancement instead of silently stalling
    or queuing garbage into the next turn's context."""
    debate = job.get("debate")
    if not debate:
        return
    session = _load_debate_session(debate["session_id"])
    if session is None:
        return
    session["status"] = "stuck"
    session["stop_reason"] = (
        f"turn {debate['round']} ({debate['persona']}) ended "
        f"'{report.get('status', 'failed')}' — see job {job['id']}. Resume "
        "with debate_resume once fixed, or debate_cancel to give up.")
    session["current_job_id"] = job["id"]
    session["next_expected"] = {"round": debate["round"], "persona": debate["persona"]}
    _save_debate_session(session)
    _notify_debate("debate.stuck", session)


_SALVAGE_TASK = (
    "Your previous answer was not the required report dict. The work you "
    "already did above still counts — do not redo it. In ONE code block: "
    "call build_report(...) describing that work (put any text "
    "deliverables you produced, e.g. drafted copy, into a "
    'build_deliverable(type="text", title=..., location="<the full '
    'text>")), then actually call final_answer(report). Nothing else — no '
    "hand-written dict literals.")


def _parse_report(manager, answer) -> dict:
    """Extract the manager's report dict. If the answer is unstructured,
    try one short salvage run in the same memory (small models often do
    the work but fumble the final final_answer call); only then degrade to
    a raw-text needs_attention report so the job is never lost."""
    from .manager import extract_report

    report = extract_report(answer)
    if report is None:
        print("[jobs] unstructured final answer — attempting report salvage")
        try:
            report = extract_report(
                manager.run(_SALVAGE_TASK, reset=False, max_steps=3))
        except Exception as exc:  # noqa: BLE001 — salvage is best-effort
            print(f"[jobs] salvage run failed: {type(exc).__name__}: {exc}")
            report = None
    if report is None:
        text = (answer if isinstance(answer, str) else str(answer)).strip()
        report = {"status": "needs_attention",
                  "summary": "The manager did not produce a structured "
                             "report; raw answer follows.\n\n" + text[:4000],
                  "attention": ["Report was unstructured — review the raw "
                                "answer and the job log."]}
    if report.get("status") not in _TERMINAL | {"continuation"}:
        report["status"] = "completed"
    return report


_DEBATE_SALVAGE_TASK = (
    "Your previous answer was not the required report dict. The work you "
    "already did above still counts — do not redo it. In ONE code block: "
    "call build_debate_report(...) with the persona's answer you already "
    "obtained (status='completed', full_text=<the persona's full verbatim "
    "answer>, abstract=<its one-line abstract>), then actually call "
    "final_answer(report). Nothing else — no hand-written dict literals.")


def _parse_debate_report(agent, answer) -> dict:
    """Debate-turn counterpart to _parse_report — kept separate since a
    debate report's shape (full_text/abstract/verdict) differs from the
    general job report and the two should never be cross-parsed."""
    from .debate_manager import extract_debate_report

    report = extract_debate_report(answer)
    if report is None:
        print("[jobs] debate turn: unstructured final answer — attempting "
             "report salvage")
        try:
            report = extract_debate_report(
                agent.run(_DEBATE_SALVAGE_TASK, reset=False, max_steps=3))
        except Exception as exc:  # noqa: BLE001 — salvage is best-effort
            print(f"[jobs] debate salvage run failed: {type(exc).__name__}: {exc}")
            report = None
    if report is None:
        text = (answer if isinstance(answer, str) else str(answer)).strip()
        report = {"status": "needs_attention",
                  "full_text": "The debate turn did not produce a "
                               "structured report; raw answer follows.\n\n"
                               + text[:4000],
                  "abstract": "(unstructured answer — see full_text)",
                  "verdict": "continue", "redirect_note": ""}
    if report.get("status") not in ("completed", "needs_attention"):
        report["status"] = "completed"
    # Alias so the generic job-notify webhook and the /inbox card (which
    # both read report.get("summary")) show something useful without
    # needing to know about debate-specific report fields.
    report.setdefault("summary", report.get("abstract", ""))
    return report


def _run_debate_turn(agent, job: dict, workspace: Path) -> None:
    """A debate turn is 'delegate once, relay verbatim' — no continuation
    segments, and completion hands off to deterministic turn-advancement
    (_advance_debate) instead of looping like the general job below."""
    task = _format_debate_task(job, workspace)
    try:
        answer = agent.run(task, reset=True,
                           additional_args={"workspace": str(workspace)})
        report = _parse_debate_report(agent, answer)
    except Exception as exc:  # noqa: BLE001 — a failed run must land in the record
        job.update(status="failed", finished_at=_now(),
                   error=f"{type(exc).__name__}: {exc}")
        print(f"[jobs] debate turn {job['id']} failed:\n{traceback.format_exc()}")
        _save(job)
        _notify("job.failed", job)
        _mark_debate_stuck(job, {"status": "failed"})
        return

    job.update(status=report["status"], report=report, finished_at=_now())
    _save(job)
    _notify(f"job.{report['status']}", job)
    if report["status"] == "completed":
        _advance_debate(job, report)
    else:
        _mark_debate_stuck(job, report)


def _run_job(agents: dict, job: dict) -> None:
    is_debate = bool(job.get("debate"))
    agent = agents["debate_manager"] if is_debate else agents["manager"]
    workspace = _jobs_dir / job["id"] / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    job.update(status="running", started_at=_now(),
               segments=job.get("segments", 1))
    _save(job)

    log_tail: list[str] = [""]

    def _heartbeat(step, agent=None):
        job["heartbeat_ts"] = time.time()
        try:
            log_tail[0] = (log_tail[0] + "\n" + str(step)[-500:])[-_LOG_TAIL_CHARS:]
        except Exception:  # noqa: BLE001 — logging must never kill a job
            pass
        job["log_tail"] = log_tail[0]
        _save(job)

    if not getattr(agent, "_jobs_heartbeat", False):
        agent.step_callbacks.register(ActionStep, _heartbeat)
        agent.step_callbacks.register(PlanningStep, _heartbeat)
        agent._jobs_heartbeat = True

    if is_debate:
        _run_debate_turn(agent, job, workspace)
        return

    while True:
        task = _format_task(job, workspace)
        try:
            answer = agent.run(task, reset=True,
                               additional_args={"workspace": str(workspace)})
            report = _parse_report(agent, answer)
        except Exception as exc:  # noqa: BLE001 — a failed run must land in the record
            job.update(status="failed", finished_at=_now(),
                       error=f"{type(exc).__name__}: {exc}")
            print(f"[jobs] job {job['id']} failed:\n{traceback.format_exc()}")
            _save(job)
            _notify("job.failed", job)
            return

        # A segment that hit max_steps produces whatever final answer the
        # model managed; continuation is only honored below the segment cap.
        if report["status"] == "continuation":
            if job["segments"] >= config.MAX_SEGMENTS:
                synopsis = workspace / "synopsis.md"
                report = {
                    "status": "needs_attention",
                    "summary": ("Segment cap reached "
                                f"({config.MAX_SEGMENTS}). Progress so far:\n"
                                + (synopsis.read_text()
                                   if synopsis.is_file() else report["summary"])),
                    "attention": ["Job stopped at the segment cap — review "
                                  "the synopsis and re-dispatch the remainder."],
                }
            else:
                job["segments"] += 1
                job["report"] = report
                _save(job)
                continue

        job.update(status=report["status"], report=report, finished_at=_now())
        _save(job)
        _notify(f"job.{report['status']}", job)
        return


def _recover_stale() -> None:
    """A record stuck in 'running' means the container died mid-job. For a
    debate turn, this also halts auto-advancement (status -> stuck) rather
    than leaving the session silently waiting on a turn that will never
    finish — the ordinary job queue has no such follow-on step to get
    stuck, so this only matters for debates."""
    for path in _jobs_dir.glob("job-*.json"):
        job = _load(path)
        if job and job.get("status") == "running":
            job.update(status="failed", finished_at=_now(),
                       error="worker restarted mid-job")
            _save(job)
            _notify("job.failed", job)
            if job.get("debate"):
                _mark_debate_stuck(job, {"status": "failed"})


def _worker_loop() -> None:
    # Deferred import: both agents need mcp-tools reachable for tool loading.
    from .debate_manager import build_debate_manager_agent
    from .manager import build_manager_agent

    _jobs_dir.mkdir(parents=True, exist_ok=True)
    _debates_dir.mkdir(parents=True, exist_ok=True)
    _recover_stale()
    manager = build_manager_agent()  # built once; reused with reset=True
    debate_manager = build_debate_manager_agent()  # same, for debate turns
    agents = {"manager": manager, "debate_manager": debate_manager}
    _write_roster(manager)
    print(f"[jobs] worker ready — polling {_jobs_dir} every {_POLL_S}s")
    while True:
        try:
            for job in _queued_jobs():
                # Re-read in case mcp-tools cancelled it meanwhile.
                current = _load(_job_path(job["id"]))
                if current and current.get("status") == "queued":
                    _run_job(agents, current)
        except Exception:  # noqa: BLE001 — the worker must survive anything
            print(f"[jobs] worker loop error:\n{traceback.format_exc()}")
        time.sleep(_POLL_S)


def start_job_worker() -> threading.Thread:
    thread = threading.Thread(target=_worker_loop, name="job-worker",
                              daemon=True)
    thread.start()
    return thread
