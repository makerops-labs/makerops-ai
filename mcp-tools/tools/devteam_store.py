"""Read/create access to the shared devteam engagement store (bind mount of
smolagents/data/smolagents/devteam). A fourth parallel queue alongside the
job/debate/liaison stores, same ownership rule: this side creates
session.json (status "running") plus each user-driven phase job, and may
perform exactly five transitions — answer (awaiting_input→running), approve
(awaiting_review→running or →concluded), revise (awaiting_review→running),
resume (stuck→running), cancel (any non-terminal→cancelled); the smolagents
job worker (agents/jobs.py's devteam section) owns every other transition,
including auto-advancing past ungated phases. Writes are atomic.

Layout per engagement (see devteam_domain.py for the id format):
    <id>/session.json      whole-object atomic write (the state machine)
    <id>/product_plan.md   the client's full plan text, kept out of session.json
    <id>/reports/phase-NN-<name>-r<rev>.json   every phase landing (worker-written)
    <id>/phases/<NN>-<name>/workspace/         per-phase working memory (worker-written)
"""

import json
import os
import time
import uuid
from pathlib import Path

from . import config, jobs_store

DEVTEAM_DIR = Path(config.AGENT_DEVTEAM_DIR)

TERMINAL_STATUSES = {"concluded", "cancelled"}

# Phase plan: fixed prefix and suffix; the worker inserts the milestone
# phases the architecture phase planned, before "qa".
_PHASE_PREFIX = ("requirements", "architecture", "scaffold")
_PHASE_SUFFIX = ("qa", "docs")

# gates="key" gates the client-style sign-offs: the expensive-to-redo
# decisions (requirements, architecture) plus final delivery acceptance
# (docs). Everything between auto-advances — the client chose autonomy
# over per-stage click-through.
GATE_PRESETS = {
    "key": ["requirements", "architecture", "docs"],
    "all": ["requirements", "architecture", "scaffold", "milestone",
            "qa", "docs"],
    "none": [],
}


def _session_dir(session_id: str) -> Path:
    return DEVTEAM_DIR / session_id


def _session_path(session_id: str) -> Path:
    return _session_dir(session_id) / "session.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _save_session(session: dict) -> None:
    path = _session_path(session["id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(session, indent=1, ensure_ascii=False))
    os.replace(tmp, path)


def available() -> bool:
    return DEVTEAM_DIR.is_dir()


def _phase_entry(kind: str) -> dict:
    return {"name": kind, "kind": kind, "status": "pending", "job_ids": [],
            "summary": "", "deliverables": [], "objective": "",
            "deliverables_spec": [], "revisions": 0, "approved_at": None}


def create_session(project: str, product_plan: str, constraints: list[str],
                   context: str, gates: list[str]) -> dict:
    now = _now()
    session = {
        "id": f"devteam-{int(time.time())}-{uuid.uuid4().hex[:6]}",
        "status": "running",
        "project": project,
        "constraints": constraints,
        "context": context,
        "gates": gates,
        "phases": [_phase_entry(k) for k in _PHASE_PREFIX + _PHASE_SUFFIX],
        "current_phase": 0,
        "open_questions": [],
        "answers": [],
        "feedback": [],
        "decisions": [],
        "current_job_id": None,
        "queued_job_id": None,
        "next_expected": {"phase_index": 0, "reason": "start"},
        "stop_reason": None,
        "created_at": now,
        "updated_at": now,
    }
    _session_dir(session["id"]).mkdir(parents=True, exist_ok=True)
    (_session_dir(session["id"]) / "product_plan.md").write_text(product_plan)
    _save_session(session)
    return session


def get_session(session_id: str) -> dict | None:
    try:
        return json.loads(_session_path(session_id).read_text())
    except (OSError, ValueError):
        return None


def save_session(session: dict) -> None:
    """Atomic save after one of this side's five sanctioned transitions —
    callers mutate the session dict from get_session() then hand it back."""
    session["updated_at"] = _now()
    _save_session(session)


def queue_phase(session: dict, phase_index: int, reason: str) -> dict:
    """Queue one phase job and point the (mutated, saved) session at it —
    the mcp-tools mirror of the worker's _queue_devteam_phase, used only
    for the user-driven transitions (start/answer/approve/revise/resume).
    The job record shape must stay in lockstep with the worker's
    _new_devteam_job."""
    phase = session["phases"][phase_index]
    job = jobs_store.create_job(
        brief={"objective": (f"Devteam engagement {session['id']} phase "
                             f"{phase_index} '{phase['name']}' ({reason}) — "
                             f"project '{session.get('project', '')}'"),
               "deliverables": (phase.get("deliverables_spec")
                                or [f"{phase.get('kind', '')} phase "
                                    "deliverables"]),
               "project": session.get("project", "")},
        source="devteam",
        devteam={"session_id": session["id"], "phase_index": phase_index,
                 "phase_name": phase["name"], "reason": reason})
    phase["status"] = "running"
    phase.setdefault("job_ids", []).append(job["id"])
    session["status"] = "running"
    session["current_phase"] = phase_index
    session["queued_job_id"] = job["id"]
    session["open_questions"] = []
    session["next_expected"] = {"phase_index": phase_index, "reason": reason}
    save_session(session)
    return job


def list_sessions(status: str = "", limit: int = 30) -> list[dict]:
    sessions = []
    if not DEVTEAM_DIR.is_dir():
        return sessions
    for path in DEVTEAM_DIR.glob("devteam-*/session.json"):
        try:
            session = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if status and session.get("status") != status:
            continue
        sessions.append(session)
    sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return sessions[:limit]


def render_phase_table(session: dict) -> str:
    """One line per phase: index, name, status, revision count, and the
    one-line summary once the phase has landed."""
    lines = []
    gates = session.get("gates", [])
    for i, p in enumerate(session.get("phases", [])):
        gate = " [gate]" if (p.get("kind") in gates
                             or p.get("name") in gates) else ""
        marker = "→ " if i == session.get("current_phase") else "  "
        rev = f" r{p['revisions']}" if p.get("revisions") else ""
        summary = f" — {p['summary'][:100]}" if p.get("summary") else ""
        lines.append(f"{marker}{i}. {p.get('name')} "
                     f"[{p.get('status')}]{gate}{rev}{summary}")
    return "\n".join(lines) or "(no phases)"


def read_phase_report(session_id: str, phase_index: int) -> dict | None:
    """Latest revision of one phase's landed report (worker-written)."""
    reports_dir = _session_dir(session_id) / "reports"
    session = get_session(session_id)
    if session is None or not 0 <= phase_index < len(session["phases"]):
        return None
    name = session["phases"][phase_index]["name"]
    candidates = sorted(reports_dir.glob(f"phase-{phase_index:02d}-{name}-r*.json"))
    if not candidates:
        return None
    try:
        return json.loads(candidates[-1].read_text())
    except (OSError, ValueError):
        return None


def latest_landed_phase(session: dict) -> int | None:
    """Index of the most recent phase that has landed a report — the phase
    a review or question is about."""
    for i in range(len(session.get("phases", [])) - 1, -1, -1):
        status = session["phases"][i].get("status")
        if status not in ("pending",):
            return i
    return None
