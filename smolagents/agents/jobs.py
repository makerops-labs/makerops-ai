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
from smolagents.utils import AgentMaxStepsError

from . import config

_POLL_S = 2.0
_LOG_TAIL_CHARS = 2000
_TERMINAL = {"completed", "needs_clarification", "needs_attention",
             "failed", "cancelled"}

_jobs_dir = Path(config.JOBS_DIR)
_debates_dir = Path(config.DEBATES_DIR)
_liaison_dir = Path(config.LIAISON_DIR)


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


def _clean_round_text(text: str) -> str:
    """Deterministic backstop behind the personas' own output contract
    (debate/format.py): unwrap an answer the model wrapped whole in a code
    fence, so the round file and the next turn's prompt get prose, not a
    ```-block the next persona would imitate. Content inside is preserved
    verbatim — this only strips the wrapper."""
    text = (text or "").strip()
    while text.startswith("```") and text.endswith("```"):
        first_newline = text.find("\n")
        if first_newline == -1:
            break
        text = text[first_newline + 1:-3].strip()
    return text


def _write_debate_round_file(session_id: str, round_num: int, persona: str,
                             full_text: str) -> str:
    """Writes the round file (hard-capped as a backstop — persona prompts
    target ~400-700 words on their own) and returns its path relative to
    the session directory, for the manifest entry."""
    text = _clean_round_text(full_text)
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
    if debate.get("synthesis"):
        lines.append(
            f"\nSYNTHESIS MODE — the debate has ENDED "
            f"({session.get('stop_reason') or 'round cap reached'}). "
            f"YOUR JOB THIS TURN: delegate this ENTIRE turn to the "
            f"'monitor' sub-agent, telling it explicitly this is SYNTHESIS "
            f"MODE: it must write the final stand-alone report for the "
            f"human owner (what was decided or learned, the strongest "
            f"surviving objections, concrete next steps, open questions), "
            f"drawing on the whole manifest — no verdict line. Then relay "
            f"its answer verbatim via build_debate_report "
            f"(verdict='conclude') and finish.")
    else:
        lines.append(
            f"\nYOUR JOB THIS TURN: delegate this ENTIRE turn to the "
            f"'{persona}' sub-agent per your procedure steps 3-6 — pass it "
            "the goal, mode, constraints, manifest, and recent-round text "
            "above (plus any monitor redirect), call it exactly once, then "
            "relay its answer verbatim via build_debate_report and finish.")
    return "\n".join(lines)


def _new_debate_job(session_id: str, round_num: int, persona: str,
                    mode: str, goal: str, synthesis: bool = False) -> dict:
    label = "synthesis" if synthesis else f"turn {round_num}"
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
        "brief": {"objective": f"Debate {label} ({persona}, "
                               f"{mode}): {goal[:150]}",
                 "deliverables": ["final human-facing synthesis" if synthesis
                                  else "round argument text"]},
        "report": None,
        "error": None,
        "log_tail": "",
        "debate": {"session_id": session_id, "round": round_num,
                   "persona": persona, "synthesis": synthesis},
    }


def _write_debate_summary(session_id: str, text: str) -> None:
    """summary.md is the debate's single human-facing artifact — the final
    synthesis a person reads instead of the whole round history. Served by
    the debate_result MCP tool."""
    (_debates_dir / session_id / "summary.md").write_text(
        _clean_round_text(text) + "\n")


def _notify_debate(event: str, session: dict, summary: str = "") -> None:
    """Fire-and-forget webhook, mirrors _notify but for session-level
    events (concluded/stuck) rather than per-job ones."""
    if not config.NOTIFY_WEBHOOK:
        return
    payload = {"event": event, "session_id": session["id"],
              "goal": session.get("goal", ""), "status": session.get("status"),
              "stop_reason": session.get("stop_reason") or "",
              "summary": summary[:500],
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

    full_text = _clean_round_text(report.get("full_text") or "")
    abstract = _clean_round_text(report.get("abstract") or "").splitlines()
    abstract = (abstract[0] if abstract else "") or full_text[:120] or "(empty)"
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
        # another turn (nor concludes) regardless of what the turn said —
        # the user's cancel wins even over an in-flight synthesis.
        _save_debate_session(session)
        return

    if debate.get("synthesis"):
        # The closing report just landed — the debate is over regardless of
        # any verdict field. Its text becomes the human-facing summary.md.
        _write_debate_summary(session_id, full_text)
        session["status"] = "concluded"
        session["stop_reason"] = session.get("stop_reason") or "debate ended"
        _save_debate_session(session)
        _notify_debate("debate.concluded", session, summary=full_text)
        return

    verdict = report.get("verdict", "continue")
    if verdict not in ("continue", "redirect", "conclude"):
        print(f"[jobs] debate {session_id}: unexpected verdict {verdict!r}, "
             "treating as 'continue'")
        verdict = "continue"

    if verdict == "conclude" or round_num >= session["max_rounds"]:
        # The debate is over, but it must always end with ONE final
        # human-facing synthesis (summary.md) — never leave the human to
        # reconstruct the outcome from raw rounds. One extra monitor turn
        # is queued for that report; it runs past max_rounds by design
        # (it's the closing report, not more debating).
        session["stop_reason"] = (
            "monitor concluded the debate" if verdict == "conclude"
            else f"max_rounds ({session['max_rounds']}) reached")
        session["pending_redirect"] = None
        next_job = _new_debate_job(session_id, round_num + 1, "monitor",
                                   session["mode"], session["goal"],
                                   synthesis=True)
        session["status"] = "concluding"
        session["queued_job_id"] = next_job["id"]
        session["next_expected"] = {"round": round_num + 1,
                                    "persona": "monitor", "synthesis": True}
        _save_debate_session(session)
        _save(next_job)
        return

    session["pending_redirect"] = ((report.get("redirect_note") or "").strip()
                                   if verdict == "redirect" else None)
    next_persona = _next_debate_persona(round_num + 1, session["monitor_every_n"])
    next_job = _new_debate_job(session_id, round_num + 1, next_persona,
                               session["mode"], session["goal"])
    session["status"] = "active"
    session["queued_job_id"] = next_job["id"]
    session["next_expected"] = {"round": round_num + 1, "persona": next_persona,
                                "synthesis": False}
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
        f"turn {debate['round']} ({debate['persona']}"
        f"{', synthesis' if debate.get('synthesis') else ''}) ended "
        f"'{report.get('status', 'failed')}' — see job {job['id']}. Resume "
        "with debate_resume once fixed, or debate_cancel to give up.")
    session["current_job_id"] = job["id"]
    session["next_expected"] = {"round": debate["round"],
                                "persona": debate["persona"],
                                "synthesis": bool(debate.get("synthesis"))}
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


def _steps_exhausted(agent) -> bool:
    """True when the last run ended because the step budget ran out —
    smolagents records an AgentMaxStepsError ActionStep in memory before
    force-summarizing a final answer (which bypasses final_answer_checks)."""
    return any(isinstance(getattr(s, "error", None), AgentMaxStepsError)
               for s in agent.memory.steps)


def _exhaustion_report(job: dict, workspace: Path, segment_started: float) -> dict:
    """Deterministic report for a step-exhausted segment: continue when this
    segment demonstrably made progress — ANY workspace file (synopsis, notes,
    drafts) written since the segment began; the resume block hands the next
    segment the synopsis plus a listing of all workspace files, so file
    progress without synopsis bookkeeping still resumes meaningfully. A
    segment that produced NO file at all would just repeat itself, so it is
    surfaced for a human instead. The caller's continuation block still
    enforces the MAX_SEGMENTS cap on top of this."""
    synopsis = workspace / "synopsis.md"
    made_progress = any(p.stat().st_mtime > segment_started
                        for p in workspace.rglob("*") if p.is_file())
    if made_progress:
        print(f"[jobs] job {job['id']} segment {job['segments']} exhausted "
              "its step budget — auto-continuing from the workspace")
        return {"status": "continuation",
                "summary": (f"Segment {job['segments']} hit the step cap "
                            f"({config.MANAGER_MAX_STEPS} steps); "
                            "auto-resuming from the workspace synopsis."),
                "next_steps": ["Resume from synopsis.md and the workspace "
                               "files (auto-continued after step-budget "
                               "exhaustion)."]}
    return {"status": "needs_attention",
            "summary": (f"Segment {job['segments']} exhausted its step "
                        f"budget ({config.MANAGER_MAX_STEPS} steps) without "
                        "writing anything to its workspace, so a fresh "
                        "segment would just repeat the same work.\n\n"
                        + (("Last synopsis:\n" + synopsis.read_text())
                           if synopsis.is_file() else "(no synopsis was ever written)")),
            "attention": ["Job stopped: step budget exhausted with no "
                          "workspace progress this segment — refine the "
                          "brief (smaller scope or explicit sub-tasks) and "
                          "re-dispatch with parent_job_id."]}


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


# ── Alexa liaison turns ─────────────────────────────────────────────────────
# A third, parallel queue sharing the same job-record mechanism (a liaison
# turn IS an ordinary job, tagged job["liaison"]) but with its own durable
# session store under _liaison_dir: one session.json per Alexa userId (not
# the ephemeral per-invocation Alexa sessionId, so continuity survives
# Alexa's own ~8s-silence session timeout), holding a bounded turn history
# plus pending job/action pointers the alexa-bridge polls for its
# deterministic 'status'/'confirm'/'deny' voice commands. Unlike a debate
# turn, a liaison turn never auto-queues the next one — the NEXT turn is
# triggered externally by the user's next utterance (mcp-tools' liaison_turn
# call), not by anything in this worker.

def _liaison_session_path(user_id: str) -> Path:
    return _liaison_dir / f"{user_id}.json"


def _load_liaison_session(user_id: str) -> dict | None:
    return _load(_liaison_session_path(user_id))


def _save_liaison_session(session: dict) -> None:
    path = _liaison_session_path(session["user_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(session, indent=1, ensure_ascii=False))
    os.replace(tmp, path)


def _format_liaison_task(job: dict, workspace: Path) -> str:
    user_id = job["liaison"]["user_id"]
    session = _load_liaison_session(user_id)
    if session is None or not session.get("history"):
        return (f"LIAISON TURN — user {user_id}. ERROR: no session/turn "
               "record found for this user. Skip any delegation; instead "
               "call build_liaison_turn(status='needs_attention', "
               "speech=\"Sorry, I didn't catch that — can you try again?\") "
               "and finish.")
    history = session["history"]
    new_turn = history[-1]
    prior = history[:-1]
    # Staleness: a big gap since the previous turn means this is effectively
    # a fresh conversation even though it shares a userId — drop prior turns
    # rather than silently reinjecting context from days ago into what the
    # user experiences as a brand new exchange.
    if prior:
        try:
            prev_ts = datetime.fromisoformat(prior[-1]["ts"])
            new_ts = datetime.fromisoformat(new_turn["ts"])
            if ((new_ts - prev_ts).total_seconds()
                    > config.LIAISON_SESSION_STALE_HOURS * 3600):
                prior = []
        except (KeyError, ValueError):
            pass
    window = prior[-(config.LIAISON_HISTORY_TURNS * 2):]
    lines = [f"LIAISON TURN — user {user_id}."]
    if window:
        lines.append("--- Recent conversation (oldest first) ---")
        for turn in window:
            speaker = "User" if turn.get("role") == "user" else "You (liaison)"
            lines.append(f"{speaker}: {turn.get('text', '')}")
    else:
        lines.append("(Start of a new conversation — no prior turns, or "
                     "the previous one was too long ago to still be "
                     "relevant.)")
    lines.append(f"\nThe user just said: {new_turn.get('text', '')}")
    if session.get("pending_action_id"):
        lines.append(
            f"\nNote: action #{session['pending_action_id']} from earlier "
            "in this conversation is still pending the user's approval — "
            "only mention this if directly relevant to what they just "
            "said.")
    lines.append(
        "\nYOUR JOB THIS TURN: follow your procedure — answer directly, ask "
        "ONE clarifying question, delegate to exactly one managed agent, or "
        "call agent_dispatch for a substantial task — then finish with "
        "build_liaison_turn(...) and final_answer(report) in the SAME code "
        "block.")
    return "\n".join(lines)


_LIAISON_SALVAGE_TASK = (
    "Your previous answer was not the required report dict. The work you "
    "already did above still counts — do not redo it. In ONE code block: "
    "call build_liaison_turn(...) describing what you already decided "
    "(status, speech, and any job_id/pending_action_id/delegated_to you "
    "already have), then actually call final_answer(report). Nothing else "
    "— no hand-written dict literals.")


def _parse_liaison_turn(agent, answer) -> dict:
    """Liaison-turn counterpart to _parse_report/_parse_debate_report — kept
    separate since a liaison turn's report shape (speech/reprompt/job_id/
    pending_action_id/delegated_to) differs from both and the three should
    never be cross-parsed."""
    from .alexa_liaison import extract_liaison_turn

    report = extract_liaison_turn(answer)
    if report is None:
        print("[jobs] liaison turn: unstructured final answer — attempting "
             "report salvage")
        try:
            report = extract_liaison_turn(
                agent.run(_LIAISON_SALVAGE_TASK, reset=False, max_steps=3))
        except Exception as exc:  # noqa: BLE001 — salvage is best-effort
            print(f"[jobs] liaison salvage run failed: {type(exc).__name__}: {exc}")
            report = None
    if report is None:
        text = (answer if isinstance(answer, str) else str(answer)).strip()
        print(f"[jobs] liaison turn produced no usable report; raw answer: "
             f"{text[:2000]}")
        report = {"status": "needs_attention",
                  "speech": "Sorry, something went wrong on my end — try "
                           "that again in a moment."}
    if report.get("status") not in ("completed", "needs_clarification",
                                    "deferred", "needs_attention"):
        report["status"] = "completed"
    for key in ("reprompt", "job_id", "pending_action_id", "delegated_to"):
        report.setdefault(key, "")
    return report


def _finish_liaison_turn(user_id: str, report: dict) -> None:
    """Folds this turn's outcome back into the session the alexa-bridge
    polls: the liaison's own reply joins the history, pending_job_id tracks
    a 'deferred' background job (cleared otherwise), and pending_action_id
    is overwritten only when this turn actually surfaced one — clearing it
    on every other turn would erase a still-pending approval id from an
    earlier turn the user hasn't resolved yet."""
    session = _load_liaison_session(user_id)
    if session is None:
        print(f"[jobs] liaison turn for {user_id}: session.json missing — "
             "reply computed but could not be recorded")
        return
    session.setdefault("history", []).append(
        {"role": "liaison", "text": report.get("speech", ""), "ts": _now()})
    session["pending_job_id"] = (report.get("job_id", "")
                                 if report.get("status") == "deferred" else "")
    if report.get("pending_action_id"):
        session["pending_action_id"] = report["pending_action_id"]
    session["updated_at"] = _now()
    _save_liaison_session(session)


def _run_liaison_turn(agent, job: dict, workspace: Path) -> None:
    """A liaison turn is 'answer or delegate once, reply' — no continuation
    segments, and no auto-advance (see module section docstring above)."""
    user_id = job["liaison"]["user_id"]
    task = _format_liaison_task(job, workspace)
    try:
        answer = agent.run(task, reset=True,
                           additional_args={"workspace": str(workspace)})
        report = _parse_liaison_turn(agent, answer)
    except Exception as exc:  # noqa: BLE001 — a failed run must land in the record
        job.update(status="failed", finished_at=_now(),
                   error=f"{type(exc).__name__}: {exc}")
        print(f"[jobs] liaison turn {job['id']} failed:\n{traceback.format_exc()}")
        _save(job)
        _finish_liaison_turn(user_id, {
            "status": "failed",
            "speech": "Sorry, something went wrong on my end — try that "
                     "again in a moment."})
        return

    job.update(status=report["status"], report=report, finished_at=_now())
    _save(job)
    # Deliberately no _notify() call — unlike a background job or debate
    # turn, the user is live on the line waiting for this reply; a push
    # notification for every ordinary voice exchange would be noise. A
    # 'deferred' turn's underlying agent_dispatch job still notifies on its
    # own completion through the normal job path above.
    _finish_liaison_turn(user_id, report)


def _run_job(agents: dict, job: dict) -> None:
    is_debate = bool(job.get("debate"))
    is_liaison = bool(job.get("liaison"))
    if is_debate:
        agent = agents["debate_manager"]
    elif is_liaison:
        agent = agents["alexa_liaison"]
    else:
        agent = agents["manager"]
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
    if is_liaison:
        _run_liaison_turn(agent, job, workspace)
        return

    while True:
        task = _format_task(job, workspace)
        segment_started = time.time()
        try:
            answer = agent.run(task, reset=True,
                               additional_args={"workspace": str(workspace)})
            # A segment that exhausted its step budget got its final answer
            # from smolagents' forced max-steps summarization, which
            # BYPASSES final_answer_checks — that answer is untrusted, and
            # re-feeding the blown-out memory to the salvage run just fails
            # again. Convert exhaustion into a continuation segment
            # deterministically instead (the model never volunteers
            # continuation before dying; this is the code-level trigger,
            # same philosophy as debate turn-advancement).
            if _steps_exhausted(agent):
                report = _exhaustion_report(job, workspace, segment_started)
            else:
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
    # Deferred import: all three need mcp-tools reachable for tool loading.
    from .alexa_liaison import build_alexa_liaison_agent
    from .debate_manager import build_debate_manager_agent
    from .manager import build_manager_agent

    _jobs_dir.mkdir(parents=True, exist_ok=True)
    _debates_dir.mkdir(parents=True, exist_ok=True)
    _liaison_dir.mkdir(parents=True, exist_ok=True)
    _recover_stale()
    manager = build_manager_agent()  # built once; reused with reset=True
    debate_manager = build_debate_manager_agent()  # same, for debate turns
    alexa_liaison = build_alexa_liaison_agent()  # same, for liaison turns
    agents = {"manager": manager, "debate_manager": debate_manager,
              "alexa_liaison": alexa_liaison}
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
