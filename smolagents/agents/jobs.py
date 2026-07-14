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
import re
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
from .thoughts import strip_thoughts

_POLL_S = 2.0
_LOG_TAIL_CHARS = 2000
_TERMINAL = {"completed", "needs_clarification", "needs_attention",
             "failed", "cancelled"}

_jobs_dir = Path(config.JOBS_DIR)
_debates_dir = Path(config.DEBATES_DIR)
_liaison_dir = Path(config.LIAISON_DIR)
_devteam_dir = Path(config.DEVTEAM_DIR)


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
# deterministic Python, never an LLM tool call — and so is everything else
# around a turn: the worker runs the persona directly (_run_debate_turn),
# with no orchestrator LLM in between.

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


def _unwrap_fences(text: str) -> str:
    while text.startswith("```") and text.endswith("```"):
        first_newline = text.find("\n")
        if first_newline == -1:
            break
        text = text[first_newline + 1:-3].strip()
    return text


def _clean_round_text(text: str) -> str:
    """Deterministic backstop behind the personas' own output contract
    (debate/format.py): unwrap an answer the model wrapped whole in a code
    fence, so the round file and the next turn's prompt get prose, not a
    ```-block the next persona would imitate. Content inside is preserved
    verbatim — this only strips the wrapper. Also discards a leaked
    thought scratchpad (thoughts.py's marker protocol) — a scratchpad in a
    round file would poison the next turn's input. Order matters: unwrap →
    strip → unwrap covers both a fence-wrapped leak (strip first would
    orphan the closing fence) and a leak whose response part is itself
    fenced. Residual case: a thought marker with no response marker is
    unstrippable by rule — check_round_prose plus the raw path's
    corrective retry remain the net there, same as before."""
    text = _unwrap_fences((text or "").strip())
    return _unwrap_fences(strip_thoughts(text))


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
    """Task text addressed DIRECTLY to the persona taking this turn — there
    is no orchestrator LLM in a debate turn (see _run_debate_turn)."""
    debate = job["debate"]
    session_id, round_num, persona = (debate["session_id"], debate["round"],
                                      debate["persona"])
    session = _load_debate_session(session_id)
    if session is None:
        # Handled before the persona ever runs — see _run_debate_turn.
        return ""
    lines = [
        f"DEBATE TURN — round {round_num} of a structured, file-relayed "
        f"debate. YOU are the '{persona}' persona and this turn is yours: "
        "write this round's contribution per your persona instructions and "
        "your OUTPUT CONTRACT. Your entire final answer becomes this "
        "round's file, read verbatim by the other debaters next turn and "
        "by the human owner at the end.",
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
        "This is a BROAD, open-ended exploration — research where useful, "
        "consider multiple angles, and do not rush to converge."
        if session["mode"] == "broad" else
        "This is a NARROW, well-scoped question — keep your answer "
        "concrete and directly responsive; do not broaden scope.")
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
            "Write the final stand-alone report for the human owner per "
            "your SYNTHESIS MODE instructions: what was decided or "
            "learned, the strongest surviving objections, concrete next "
            "steps, and open questions — drawing on the whole manifest "
            "above. No VERDICT line.")
    elif persona == "monitor":
        lines.append(
            "\nThis is a monitor CHECKPOINT: judge the debate's progress "
            "per your instructions and END your answer with your verdict "
            "line — exactly one of 'VERDICT: continue', "
            "'VERDICT: redirect: <note>', or 'VERDICT: conclude'.")
    else:
        lines.append(
            "\nWrite your round now: open with your one-line abstract (25 "
            "words or fewer), a blank line, then your full argument in "
            "plain markdown prose.")
    return "\n".join(lines)


_PSEUDO_CALL_RE = re.compile(
    r"^final_answer\(\s*(?:\"\"\"|'''|\"|')?(.*?)(?:\"\"\"|'''|\"|')?\s*\)?\s*$",
    re.DOTALL)


def _salvage_persona_text(agent) -> str:
    """A persona that exhausted its steps often DID write a complete,
    usable round — just as plain chat text instead of an actual
    final_answer tool call (observed live with gpt-oss: every step a full
    critique, is_final_answer=False on all of them). Recover the most
    recent model output that is substantial prose. Deliberately LOOSER
    than the personas' own contract check: a salvaged round with an
    overlong first line or a typed-out pseudo final_answer("...") wrapper
    is still a good argument — only code/JSON-shaped output is rejected,
    since that would poison the next turn's input. Deterministic — no
    extra model call."""
    from .debate.format import _CODE_OPENERS

    for step in reversed(agent.memory.steps):
        candidate = _clean_round_text(getattr(step, "model_output", None) or "")
        # Unwrap a pseudo-call the model TYPED instead of making: the
        # argument inside is the round.
        m = _PSEUDO_CALL_RE.match(candidate)
        if m and m.group(1).strip():
            candidate = _clean_round_text(m.group(1))
        if len(candidate) < 300:
            continue
        first = candidate.splitlines()[0].strip()
        if any(first.startswith(tok) for tok in _CODE_OPENERS):
            continue
        return candidate
    return ""


_VERDICT_RE = re.compile(
    r"VERDICT:\s*(continue|redirect|conclude)\s*:?\s*(.*)", re.IGNORECASE)


def _parse_monitor_verdict(text: str) -> tuple[str, str]:
    """Deterministically extract the monitor's mandated verdict line. A
    missing/garbled verdict degrades to 'continue' — the debate proceeds
    and the monitor gets another checkpoint — rather than failing a turn
    whose prose is otherwise fine."""
    last = None
    for m in _VERDICT_RE.finditer(text):
        last = m
    if last is None:
        return "continue", ""
    return last.group(1).lower(), last.group(2).strip()


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


def _parse_report(manager, answer, salvage_task: str = _SALVAGE_TASK) -> dict:
    """Extract the manager's report dict. If the answer is unstructured,
    try one short salvage run in the same memory (small models often do
    the work but fumble the final final_answer call); only then degrade to
    a raw-text needs_attention report so the job is never lost. The
    salvage_task names the caller's report tool (build_report for manager
    jobs, build_phase_report for devteam phases)."""
    from .manager import extract_report

    report = extract_report(answer)
    if report is None:
        print("[jobs] unstructured final answer — attempting report salvage")
        try:
            report = extract_report(
                manager.run(salvage_task, reset=False, max_steps=3))
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


def _steps_exhausted(agent) -> bool:
    """True when the last run ended because the step budget ran out —
    smolagents records an AgentMaxStepsError ActionStep in memory before
    force-summarizing a final answer (which bypasses final_answer_checks)."""
    return any(isinstance(getattr(s, "error", None), AgentMaxStepsError)
               for s in agent.memory.steps)


def _exhaustion_report(job: dict, workspace: Path, segment_started: float,
                       max_steps: int = config.MANAGER_MAX_STEPS) -> dict:
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
                            f"({max_steps} steps); "
                            "auto-resuming from the workspace synopsis."),
                "next_steps": ["Resume from synopsis.md and the workspace "
                               "files (auto-continued after step-budget "
                               "exhaustion)."]}
    return {"status": "needs_attention",
            "summary": (f"Segment {job['segments']} exhausted its step "
                        f"budget ({max_steps} steps) without "
                        "writing anything to its workspace, so a fresh "
                        "segment would just repeat the same work.\n\n"
                        + (("Last synopsis:\n" + synopsis.read_text())
                           if synopsis.is_file() else "(no synopsis was ever written)")),
            "attention": ["Job stopped: step budget exhausted with no "
                          "workspace progress this segment — refine the "
                          "brief (smaller scope or explicit sub-tasks) and "
                          "re-dispatch with parent_job_id."]}


def _run_raw_persona(spec: dict, task: str) -> str:
    """One plain completion against the persona's system prompt — the audit
    reviewer pool's proven pattern for models that fumble tool-calling.
    One corrective retry when the answer violates the prose contract;
    returns the best text obtained ('' only if the model produced nothing
    usable at all)."""
    from openai import OpenAI

    from .debate.format import check_round_prose

    client = OpenAI(base_url=config.OLLAMA_API_BASE,
                    api_key=config.OLLAMA_API_KEY)
    messages = [{"role": "system", "content": spec["raw_system"]},
                {"role": "user", "content": task}]
    best = ""
    for _ in range(2):
        resp = client.chat.completions.create(model=spec["model_id"],
                                              messages=messages)
        text = _clean_round_text(resp.choices[0].message.content or "")
        if len(text) >= 200:
            best = text
        try:
            check_round_prose(text, None)
            return text
        except Exception as exc:  # noqa: BLE001 — the check raises corrective feedback
            messages += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"{exc} Rewrite your ENTIRE "
                                            "answer accordingly — do not "
                                            "reference this correction."}]
    return best


def _run_debate_turn(agent, job: dict, workspace: Path) -> None:
    """A debate turn runs the persona DIRECTLY — there is no orchestrator
    LLM in the loop. Everything an orchestrator would have done is
    deterministic Python here: the task text is assembled by
    _format_debate_task, the persona's final answer IS the round text (its
    own final_answer_checks enforce the prose contract), the monitor's
    verdict comes from regex-parsing its mandated VERDICT line, and
    completion hands off to _advance_debate. An earlier design put a
    CodeAgent relay between the worker and the persona; it failed
    constantly by re-typing the persona's argument into giant string
    literals, and it added nothing the code above can't do reliably.
    A raw-mode persona (dict spec, see config.DEBATE_RAW_PERSONAS) is a
    single plain completion instead of an agent run."""
    debate = job["debate"]
    session = _load_debate_session(debate["session_id"])
    if session is None:
        report = {"status": "needs_attention",
                  "full_text": "session record not found",
                  "abstract": "session record not found",
                  "summary": "session record not found",
                  "verdict": "continue", "redirect_note": ""}
        job.update(status="needs_attention", report=report, finished_at=_now())
        _save(job)
        _notify("job.needs_attention", job)
        _mark_debate_stuck(job, report)
        return

    task = _format_debate_task(job, workspace)
    is_raw = isinstance(agent, dict)
    try:
        if is_raw:
            text = _run_raw_persona(agent, task)
        else:
            answer = agent.run(task, reset=True)
            text = _clean_round_text(answer if isinstance(answer, str)
                                     else str(answer))
    except Exception as exc:  # noqa: BLE001 — a failed run must land in the record
        job.update(status="failed", finished_at=_now(),
                   error=f"{type(exc).__name__}: {exc}")
        print(f"[jobs] debate turn {job['id']} failed:\n{traceback.format_exc()}")
        _save(job)
        _notify("job.failed", job)
        _mark_debate_stuck(job, {"status": "failed"})
        return

    if not is_raw and _steps_exhausted(agent):
        # The forced max-steps answer bypasses the persona's prose check —
        # don't trust it. But the persona often DID write a valid round in
        # an earlier step and only fumbled the final_answer tool call;
        # recover that deterministically before giving up on the turn.
        text = _salvage_persona_text(agent)
        if text:
            print(f"[jobs] debate turn {job['id']}: persona exhausted its "
                  "steps but a contract-valid round was salvaged from its "
                  "memory")
    if not text:
        reason = ("persona produced no usable round (raw completion)"
                  if is_raw else
                  ("persona exhausted its step budget "
                   f"({agent.max_steps} steps) with no salvageable round"
                   if _steps_exhausted(agent)
                   else "persona produced an empty answer"))
        report = {"status": "needs_attention", "full_text": "",
                  "abstract": f"(turn unusable: {reason})",
                  "summary": f"(turn unusable: {reason})",
                  "verdict": "continue", "redirect_note": ""}
    else:
        first_line = next((l.strip() for l in text.splitlines() if l.strip()),
                          "")
        verdict, redirect_note = "continue", ""
        if debate["persona"] == "monitor":
            if debate.get("synthesis"):
                verdict = "conclude"
            else:
                verdict, redirect_note = _parse_monitor_verdict(text)
                if not _VERDICT_RE.search(text):
                    print(f"[jobs] debate turn {job['id']}: monitor omitted "
                          "its VERDICT line — treating as 'continue'")
        report = {"status": "completed", "full_text": text,
                  "abstract": first_line[:200],
                  # summary alias: the generic notify webhook and /inbox
                  # card read report["summary"].
                  "summary": first_line[:200],
                  "verdict": verdict, "redirect_note": redirect_note}

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
    """Liaison-turn counterpart to _parse_report — kept
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


# ── Devteam engagement phases ────────────────────────────────────────────────
# A fourth parallel queue sharing the job-record mechanism (a phase run IS an
# ordinary job, tagged job["devteam"]) with its own durable session store
# under _devteam_dir/<id>/: session.json (the phase state machine),
# product_plan.md (the client's full plan text, kept out of session.json),
# reports/phase-NN-<name>-r<rev>.json (every phase landing, the audit
# trail), and phases/<NN>-<name>/workspace/ (per-PHASE synopsis working
# memory — persists across the revision/answer re-runs of one phase, unlike
# a per-job workspace). Ownership split mirrors the debate store: mcp-tools
# (tools/devteam_store.py) creates sessions + queued jobs and performs
# exactly the five user-driven transitions (answer, approve, revise,
# resume, cancel); this worker owns everything else — INCLUDING auto-
# queuing the next phase past an ungated completion, the same
# deterministic-Python-advances rule as _advance_debate. Gate transitions
# are the deliberate inversion: at a gated phase the worker parks the
# session (awaiting_review / awaiting_input) and notifies; only a human-
# driven mcp-tools call queues what runs next. The lead architect itself
# has no dispatch tools, same reasoning as the manager.

def _devteam_session_path(session_id: str) -> Path:
    return _devteam_dir / session_id / "session.json"


def _load_devteam_session(session_id: str) -> dict | None:
    return _load(_devteam_session_path(session_id))


def _save_devteam_session(session: dict) -> None:
    session["updated_at"] = _now()
    path = _devteam_session_path(session["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(session, indent=1, ensure_ascii=False))
    os.replace(tmp, path)


def _devteam_phase_workspace(session_id: str, phase_index: int,
                             phase_name: str) -> Path:
    return (_devteam_dir / session_id / "phases"
            / f"{phase_index:02d}-{phase_name}" / "workspace")


def _new_devteam_job(session: dict, phase_index: int, reason: str) -> dict:
    phase = session["phases"][phase_index]
    return {
        "id": f"job-{int(time.time())}-{uuid.uuid4().hex[:6]}",
        "status": "queued",
        "source": "devteam",
        "created_at": _now(),
        "started_at": None,
        "finished_at": None,
        "heartbeat_ts": 0,
        "parent_job_id": None,
        "segments": 1,
        "brief": {"objective": (f"Devteam engagement {session['id']} phase "
                                f"{phase_index} '{phase['name']}' ({reason}) "
                                f"— project '{session.get('project', '')}'"),
                  "deliverables": (phase.get("deliverables_spec")
                                   or [f"{phase.get('kind', '')} phase "
                                       "deliverables"]),
                  "project": session.get("project", "")},
        "report": None,
        "error": None,
        "log_tail": "",
        "devteam": {"session_id": session["id"], "phase_index": phase_index,
                    "phase_name": phase["name"], "reason": reason},
    }


def _queue_devteam_phase(session: dict, phase_index: int, reason: str) -> None:
    """Queue one phase job and point the session at it. Worker-side callers
    only (ungated auto-advance); the five user-driven transitions queue via
    mcp-tools' devteam_store mirror of this."""
    job = _new_devteam_job(session, phase_index, reason)
    phase = session["phases"][phase_index]
    phase["status"] = "running"
    phase.setdefault("job_ids", []).append(job["id"])
    session["status"] = "running"
    session["current_phase"] = phase_index
    session["queued_job_id"] = job["id"]
    session["open_questions"] = []
    session["next_expected"] = {"phase_index": phase_index, "reason": reason}
    _save_devteam_session(session)
    _save(job)  # picked up by the SAME poll loop within _POLL_S


def _notify_devteam(event: str, session: dict, summary: str = "",
                    questions: list | None = None) -> None:
    """Fire-and-forget webhook for engagement-level events, mirroring
    _notify_debate. devteam.needs_input carries the questions themselves so
    the n8n fan-out (email/push) can show the client what is being asked
    without a round-trip to the inbox."""
    if not config.NOTIFY_WEBHOOK:
        return
    phases = session.get("phases", [])
    current = session.get("current_phase", 0)
    phase_name = (phases[current]["name"]
                  if 0 <= current < len(phases) else "")
    payload = {"event": event, "engagement_id": session["id"],
               "project": session.get("project", ""),
               "phase": phase_name,
               "phase_progress": f"{sum(1 for p in phases if p.get('status') in ('approved', 'done'))}/{len(phases)}",
               "status": session.get("status"),
               "stop_reason": session.get("stop_reason") or "",
               "questions": questions or [],
               "summary": summary[:500],
               "inbox_url": f"{config.MCP_TOOLS_PUBLIC_URL}/inbox"}
    try:
        httpx.post(config.NOTIFY_WEBHOOK, json=payload, timeout=10)
    except httpx.HTTPError as exc:
        print(f"[jobs] devteam notify webhook failed for {session['id']}: {exc}")


_MILESTONE_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _extract_milestones(report: dict) -> list[dict] | None:
    """Deterministically validate the architecture report's milestone plan.
    Returns normalized phase entries, or None when the list is missing or
    malformed — the caller marks the session stuck rather than guessing
    (an invalid plan must go back to the architect, never be repaired by
    code)."""
    raw = report.get("milestones")
    if not isinstance(raw, list) or not raw:
        return None
    entries = []
    for i, m in enumerate(raw[:config.DEVTEAM_MAX_MILESTONES]):
        if not isinstance(m, dict):
            return None
        name = str(m.get("name", "")).strip().lower()
        objective = str(m.get("objective", "")).strip()
        if not name or not objective:
            return None
        slug = _MILESTONE_SLUG_RE.sub("-", name).strip("-")[:40] or f"m{i + 1}"
        deliverables = m.get("deliverables")
        if isinstance(deliverables, str):
            deliverables = [deliverables]
        if not isinstance(deliverables, list):
            deliverables = []
        entries.append({"name": f"milestone-{i + 1}-{slug}",
                        "kind": "milestone", "status": "pending",
                        "objective": objective,
                        "deliverables_spec": [str(d) for d in deliverables],
                        "job_ids": [], "summary": "", "deliverables": [],
                        "revisions": 0, "approved_at": None})
    return entries


def _insert_milestone_phases(session: dict, milestones: list[dict]) -> None:
    """Replace any previously planned milestone phases (an architecture
    revision re-plans them — none can have started, the architecture gate
    precedes them) and insert the new ones before the qa phase."""
    phases = [p for p in session["phases"] if p.get("kind") != "milestone"]
    insert_at = next((i for i, p in enumerate(phases)
                      if p.get("kind") == "qa"), len(phases))
    session["phases"] = (phases[:insert_at] + milestones + phases[insert_at:])


def _write_devteam_phase_report(session: dict, phase_index: int, phase: dict,
                                report: dict) -> None:
    """Full report of every phase landing, for the inbox card, the
    devteam_result tool, and the audit trail. Re-runs of the same revision
    (answer resumes) overwrite — latest landing wins."""
    reports_dir = _devteam_dir / session["id"] / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = (reports_dir / f"phase-{phase_index:02d}-{phase['name']}"
                          f"-r{phase.get('revisions', 0)}.json")
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=1, ensure_ascii=False))
    os.replace(tmp, path)


def _format_devteam_task(job: dict, workspace: Path) -> str:
    """One phase's task text for the lead architect: the phase mandate
    pointer, the product plan (inline early, by project-docs pointer
    later), bounded prior-phase summaries + the decisions log (flat context
    regardless of engagement length), and the reason-specific block —
    client answers verbatim, revision feedback, or an interruption note."""
    devteam = job["devteam"]
    session = _load_devteam_session(devteam["session_id"])
    if session is None:
        # Guarded before the run in _run_job; belt and suspenders.
        return ""
    phase_index = devteam["phase_index"]
    phase = session["phases"][phase_index]
    reason = devteam.get("reason", "start")
    project = session.get("project", "")
    lines = [
        f"DEVTEAM ENGAGEMENT {session['id']} — phase {phase_index} "
        f"'{phase['name']}' (kind: {phase['kind']}), "
        f"segment {job.get('segments', 1)}.",
        f"Project: '{project}' — a registered durable directory under "
        f"~/workspace/. Work ONLY this phase; your PHASE MANDATES section "
        f"says what a '{phase['kind']}' phase must produce.",
    ]
    if phase["kind"] == "milestone":
        lines.append(f"Milestone objective: {phase.get('objective', '')}")
        if phase.get("deliverables_spec"):
            lines.append("Milestone deliverables: "
                         + "; ".join(phase["deliverables_spec"]))
    if session.get("constraints"):
        lines.append("Engagement constraints: "
                     + "; ".join(session["constraints"]))
    if session.get("context"):
        lines.append(f"Context from the client:\n{session['context']}")

    if phase["kind"] in ("requirements", "architecture"):
        try:
            plan_text = (_devteam_dir / session["id"]
                         / "product_plan.md").read_text()
            lines.append("--- Product plan (from the client) ---\n"
                         + plan_text)
        except OSError:
            lines.append("The engagement's product_plan.md is missing — "
                         "report needs_attention immediately instead of "
                         "working without it.")
    else:
        lines.append("The requirements and architecture from earlier "
                     "phases live in the project's docs/ — read what this "
                     "phase needs (docs/REQUIREMENTS.md, "
                     "docs/ARCHITECTURE.md).")

    prior = [(i, p) for i, p in enumerate(session["phases"])
             if i < phase_index and p.get("summary")]
    if prior:
        lines.append("--- Prior phases (already done — build on them) ---")
        lines += [f"[{p['name']}] {p['summary']}" for _, p in prior]
    if session.get("decisions"):
        lines.append("--- Decisions log (settled with the client; never "
                     "revisit or re-ask) ---")
        lines += [f"- {d.get('note', '')}" for d in session["decisions"]]

    if reason == "answers" and session.get("answers"):
        last = session["answers"][-1]
        lines.append("--- CLIENT ANSWERS — this phase previously paused "
                     "with questions; these settle them. Resolve and "
                     "proceed; do NOT re-ask. ---")
        lines += [f"Q: {q}" for q in last.get("questions", [])]
        lines.append(f"A: {last.get('answers', '')}")
    elif reason == "revision" and session.get("feedback"):
        last = session["feedback"][-1]
        lines.append("--- REVISION REQUESTED — the client reviewed this "
                     "phase's previous result and wants changes. Re-read "
                     "what already exists before rewriting; address "
                     "exactly this: ---\n" + str(last.get("feedback", "")))
    elif reason == "resume":
        lines.append("A previous run of this phase was interrupted (worker "
                     "restart or failure). Re-verify what already exists — "
                     "in the project and in your workspace below — before "
                     "redoing any work.")

    lines.append(
        f"Your working-memory workspace directory is {workspace} (create "
        "files with pathlib). Keep synopsis.md there current per your "
        "WORKING MEMORY procedure — it persists across this phase's "
        "segments AND across revision/answer re-runs of this same phase. "
        "It is your own scratch memory; PROJECT_CONTEXT.md is the durable "
        "project record.")
    lines.append(
        "FIRST apply your VALIDATE step (questions pause the engagement "
        "politely — ask early, batched, rather than guessing), then ORIENT "
        f"via project_read_file('{project}', 'PROJECT_CONTEXT.md'). Always "
        "finish with build_phase_report(...) and final_answer(report) in "
        "the SAME code block — no hand-written dict literals, no other "
        "text.")

    synopsis = workspace / "synopsis.md"
    if synopsis.is_file():
        listing = ", ".join(sorted(
            str(p.relative_to(workspace))
            for p in workspace.rglob("*") if p.is_file())) or "(empty)"
        lines.append(
            "A previous segment or run already worked this phase. Resume "
            f"from its synopsis below; workspace files: {listing}\n\n"
            "--- synopsis.md ---\n" + synopsis.read_text())
    return "\n".join(lines)


_DEVTEAM_SALVAGE_TASK = (
    "Your previous answer was not the required report dict. The work you "
    "already did above still counts — do not redo it. In ONE code block: "
    "call build_phase_report(...) describing that work (put any text "
    "deliverables you produced into a "
    'build_deliverable(type="text", title=..., location="<the full '
    'text>")), then actually call final_answer(report). Nothing else — no '
    "hand-written dict literals.")


def _advance_devteam(job: dict, report: dict) -> None:
    """Deterministic engagement advancement, run after a devteam phase job
    lands its terminal report (see _run_job). Every path either parks the
    session for the user (awaiting_review / awaiting_input / stuck) with a
    webhook, or — for an ungated completed phase — auto-queues the next
    phase, the debate-advance pattern. No LLM decides any of this."""
    devteam = job["devteam"]
    session = _load_devteam_session(devteam["session_id"])
    if session is None:
        print(f"[jobs] devteam {devteam['session_id']}: session.json "
              f"missing — cannot advance phase {devteam['phase_index']}")
        return
    phase_index = devteam["phase_index"]
    if not 0 <= phase_index < len(session["phases"]):
        print(f"[jobs] devteam {session['id']}: job {job['id']} names "
              f"phase {phase_index} outside the plan — ignoring")
        return
    phase = session["phases"][phase_index]
    session["current_phase"] = phase_index
    session["current_job_id"] = job["id"]
    session["queued_job_id"] = None
    _write_devteam_phase_report(session, phase_index, phase, report)

    if session.get("status") == "cancelled":
        # Let the landing be recorded, but a cancelled engagement never
        # advances or re-parks — the user's cancel wins.
        _save_devteam_session(session)
        return

    status = report.get("status")
    if status == "needs_clarification":
        questions = [str(q) for q in (report.get("questions") or []) if q]
        if not questions:
            questions = ["(the architect paused for clarification but "
                         f"listed no questions — see job {job['id']})"]
        session["open_questions"] = questions
        session["status"] = "awaiting_input"
        phase["status"] = "awaiting_input"
        session["next_expected"] = {"phase_index": phase_index,
                                    "reason": "answers"}
        _save_devteam_session(session)
        _notify_devteam("devteam.needs_input", session,
                        summary=report.get("summary", ""),
                        questions=questions)
        return

    if status != "completed":
        _mark_devteam_stuck(job, report)
        return

    phase["summary"] = str(report.get("summary", ""))[:1000]
    phase["deliverables"] = report.get("deliverables") or []
    for note in report.get("decisions") or []:
        if str(note).strip():
            session.setdefault("decisions", []).append(
                {"phase": phase_index, "note": str(note)[:300], "ts": _now()})

    if phase["kind"] == "architecture":
        milestones = _extract_milestones(report)
        if milestones is None:
            phase["status"] = "stuck"
            session["status"] = "stuck"
            session["stop_reason"] = (
                "architecture phase completed WITHOUT a valid milestones "
                "list (report must carry milestones=[{name, objective, "
                "deliverables}, ...]) — devteam_resume re-runs the phase, "
                "or devteam_cancel to give up. See job " + job["id"] + ".")
            session["next_expected"] = {"phase_index": phase_index,
                                        "reason": "resume"}
            _save_devteam_session(session)
            _notify_devteam("devteam.stuck", session,
                            summary=report.get("summary", ""))
            return
        _insert_milestone_phases(session, milestones)
        phase = session["phases"][phase_index]  # list rebuilt above

    gates = session.get("gates", [])
    gated = phase.get("kind") in gates or phase.get("name") in gates
    is_last = phase_index == len(session["phases"]) - 1
    summary = report.get("summary", "")

    if gated:
        phase["status"] = "awaiting_review"
        session["status"] = "awaiting_review"
        session["next_expected"] = {"phase_index": phase_index,
                                    "reason": "review"}
        _save_devteam_session(session)
        _notify_devteam("devteam.milestone", session, summary=summary)
        return

    phase["status"] = "done"
    if is_last:
        session["status"] = "concluded"
        session["stop_reason"] = "all phases completed"
        _save_devteam_session(session)
        _notify_devteam("devteam.completed", session, summary=summary)
        return
    # Informational milestone note, then straight on to the next phase —
    # the client asked for autonomy between sign-offs.
    _notify_devteam("devteam.milestone", session, summary=summary)
    _queue_devteam_phase(session, phase_index + 1, "start")


def _mark_devteam_stuck(job: dict, report: dict) -> None:
    """Any non-completed terminal landing, or a worker restart mid-phase
    (_recover_stale), parks the engagement for a human instead of silently
    stalling — devteam_resume re-queues the interrupted phase."""
    devteam = job.get("devteam")
    if not devteam:
        return
    session = _load_devteam_session(devteam["session_id"])
    if session is None:
        return
    if session.get("status") in ("cancelled", "concluded"):
        return
    phase_index = devteam["phase_index"]
    if 0 <= phase_index < len(session["phases"]):
        session["phases"][phase_index]["status"] = "stuck"
    session["status"] = "stuck"
    session["stop_reason"] = (
        f"phase {phase_index} ({devteam.get('phase_name', '?')}) ended "
        f"'{report.get('status', 'failed')}' — see job {job['id']}. "
        "devteam_resume re-runs the phase once fixed, or devteam_cancel "
        "to give up.")
    session["current_job_id"] = job["id"]
    session["queued_job_id"] = None
    session["next_expected"] = {"phase_index": phase_index,
                                "reason": "resume"}
    _save_devteam_session(session)
    _notify_devteam("devteam.stuck", session,
                    summary=report.get("summary", "") or job.get("error", ""))


def _run_report_segments(agent, job: dict, workspace: Path, format_task,
                         salvage_task: str = _SALVAGE_TASK) -> dict | None:
    """The manager-style segment loop shared by ordinary manager jobs and
    devteam phase jobs: run the agent, convert step exhaustion into a
    deterministic continuation (or needs_attention) report, honor
    "continuation" up to the segment cap, then land the terminal report in
    the job record and fire the per-job webhook. Returns the terminal
    report, or None when the run raised (the record already holds
    status=failed and the failure webhook already fired)."""
    while True:
        task = format_task(job, workspace)
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
                report = _exhaustion_report(job, workspace, segment_started,
                                            max_steps=agent.max_steps)
            else:
                report = _parse_report(agent, answer, salvage_task)
        except Exception as exc:  # noqa: BLE001 — a failed run must land in the record
            job.update(status="failed", finished_at=_now(),
                       error=f"{type(exc).__name__}: {exc}")
            print(f"[jobs] job {job['id']} failed:\n{traceback.format_exc()}")
            _save(job)
            _notify("job.failed", job)
            return None

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
        return report


def _run_job(agents: dict, job: dict) -> None:
    is_debate = bool(job.get("debate"))
    is_liaison = bool(job.get("liaison"))
    is_devteam = bool(job.get("devteam"))
    if is_debate:
        persona = job["debate"].get("persona", "")
        agent = agents["debate_personas"].get(persona)
        if agent is None:
            job.update(status="failed", finished_at=_now(),
                       error=f"unknown debate persona '{persona}'")
            _save(job)
            _notify("job.failed", job)
            _mark_debate_stuck(job, {"status": "failed"})
            return
    elif is_liaison:
        agent = agents["alexa_liaison"]
    elif is_devteam:
        agent = agents["lead_architect"]
        if _load_devteam_session(job["devteam"]["session_id"]) is None:
            job.update(status="failed", finished_at=_now(),
                       error="devteam session record not found")
            _save(job)
            _notify("job.failed", job)
            return
    else:
        agent = agents["manager"]
    if is_devteam:
        # Per-PHASE persistent workspace under the engagement dir, not the
        # per-job one: synopsis.md working memory must survive the
        # revision/answer re-runs of the same phase, which are new jobs.
        devteam = job["devteam"]
        workspace = _devteam_phase_workspace(
            devteam["session_id"], devteam["phase_index"],
            devteam["phase_name"])
    else:
        workspace = _jobs_dir / job["id"] / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    job.update(status="running", started_at=_now(),
               heartbeat_ts=time.time(),
               segments=job.get("segments", 1))
    _save(job)

    # The heartbeat callback is registered ONCE per (long-lived) agent, so
    # it must not close over this call's job — it reads the current job off
    # the agent, which we re-point here on every run. (Closing over `job`
    # was a real bug: every job after an agent's first heartbeat into the
    # first job's finished record.) Raw-mode debate personas are plain dict
    # specs with no step machinery — a single completion needs no
    # heartbeat beyond the running-state save above.
    if not isinstance(agent, dict):
        agent._jobs_current = {"job": job, "tail": ""}

        def _heartbeat(step, agent=agent):
            cur = getattr(agent, "_jobs_current", None)
            if not cur:
                return
            cur["job"]["heartbeat_ts"] = time.time()
            try:
                cur["tail"] = (cur["tail"] + "\n" + str(step)[-500:])[-_LOG_TAIL_CHARS:]
            except Exception:  # noqa: BLE001 — logging must never kill a job
                pass
            cur["job"]["log_tail"] = cur["tail"]
            _save(cur["job"])

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
    if is_devteam:
        report = _run_report_segments(agent, job, workspace,
                                      _format_devteam_task,
                                      _DEVTEAM_SALVAGE_TASK)
        if report is None:
            _mark_devteam_stuck(job, {"status": "failed"})
        else:
            _advance_devteam(job, report)
        return

    _run_report_segments(agent, job, workspace, _format_task)


def _recover_stale() -> None:
    """A record stuck in 'running' means the container died mid-job. For a
    debate turn or a devteam phase, this also halts auto-advancement
    (session status -> stuck) rather than leaving the session silently
    waiting on a run that will never finish — the ordinary job queue has no
    such follow-on step to get stuck, so this only matters for the
    session-backed queues."""
    for path in _jobs_dir.glob("job-*.json"):
        job = _load(path)
        if job and job.get("status") == "running":
            job.update(status="failed", finished_at=_now(),
                       error="worker restarted mid-job")
            _save(job)
            _notify("job.failed", job)
            if job.get("debate"):
                _mark_debate_stuck(job, {"status": "failed"})
            if job.get("devteam"):
                _mark_devteam_stuck(job, {"status": "failed"})


def _persona_model_id(name: str) -> str:
    override = {"entrepreneur": config.DEBATE_ENTREPRENEUR_MODEL_ID,
                "critic": config.DEBATE_CRITIC_MODEL_ID,
                "monitor": config.DEBATE_MONITOR_MODEL_ID}.get(name, "")
    return override or config.GENERAL_MODEL_ID


def _worker_loop() -> None:
    # Deferred import: all of these need mcp-tools reachable for tool loading.
    from .alexa_liaison import build_alexa_liaison_agent
    from .debate import (PERSONA_SYSTEM_PROMPTS, build_critic_agent,
                         build_entrepreneur_agent, build_monitor_agent)
    from .devteam import build_lead_architect_agent
    from .manager import build_manager_agent

    _jobs_dir.mkdir(parents=True, exist_ok=True)
    _debates_dir.mkdir(parents=True, exist_ok=True)
    _liaison_dir.mkdir(parents=True, exist_ok=True)
    _devteam_dir.mkdir(parents=True, exist_ok=True)
    _recover_stale()
    manager = build_manager_agent()  # built once; reused with reset=True
    alexa_liaison = build_alexa_liaison_agent()  # same, for liaison turns
    lead_architect = build_lead_architect_agent()  # same, for devteam phases
    # Debate personas are run DIRECTLY by _run_debate_turn — no orchestrator
    # LLM sits between the worker and a persona (see that function's
    # docstring for the failed-relay history). A persona in
    # config.DEBATE_RAW_PERSONAS runs as a raw completion (dict spec)
    # instead of a ToolCallingAgent — see config for why.
    builders = {"entrepreneur": build_entrepreneur_agent,
                "critic": build_critic_agent,
                "monitor": build_monitor_agent}
    from .debate.format import RAW_MODE_NOTE
    debate_personas = {
        name: ({"raw_system": PERSONA_SYSTEM_PROMPTS[name] + " " + RAW_MODE_NOTE,
                "model_id": _persona_model_id(name)}
               if name in config.DEBATE_RAW_PERSONAS else build())
        for name, build in builders.items()}
    agents = {"manager": manager, "debate_personas": debate_personas,
              "alexa_liaison": alexa_liaison,
              "lead_architect": lead_architect}
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
