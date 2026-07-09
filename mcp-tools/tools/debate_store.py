"""Read/create access to the shared debate session store (bind mount of
smolagents/data/smolagents/debates). A second, parallel queue alongside
jobs_store.py's job queue, same ownership rule: this side creates
session.json (status "active") and the first turn's queued job, and may
flip stuck->active (debate_resume) or any non-terminal status->cancelled
(debate_cancel); the smolagents job worker (agents/jobs.py) owns every
other transition, including advancing to the next turn. Writes are atomic.

Layout per session (see debate_domain.py for the id format):
    <session_id>/session.json    whole-object atomic write
    <session_id>/manifest.jsonl  one JSON line per completed round, append-only
    <session_id>/rounds/round-NNN-<persona>.md
"""

import json
import os
import time
import uuid
from pathlib import Path

from . import config

DEBATES_DIR = Path(config.AGENT_DEBATES_DIR)

_TERMINAL_STATUSES = {"concluded", "cancelled"}


def _session_dir(session_id: str) -> Path:
    return DEBATES_DIR / session_id


def _session_path(session_id: str) -> Path:
    return _session_dir(session_id) / "session.json"


def _manifest_path(session_id: str) -> Path:
    return _session_dir(session_id) / "manifest.jsonl"


def _save_session(session: dict) -> None:
    path = _session_path(session["id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(session, indent=1, ensure_ascii=False))
    os.replace(tmp, path)


def available() -> bool:
    return DEBATES_DIR.is_dir()


def create_session(goal: str, deliverables: list[str], mode: str,
                   max_rounds: int, monitor_every_n: int,
                   constraints: list[str], resources: list[str],
                   context: str) -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    session = {
        "id": f"debate-{int(time.time())}-{uuid.uuid4().hex[:6]}",
        "status": "active",
        "mode": mode,
        "goal": goal,
        "deliverables": deliverables,
        "constraints": constraints,
        "resources": resources,
        "context": context,
        "max_rounds": max_rounds,
        "monitor_every_n": monitor_every_n,
        "current_round": 0,
        "last_persona": None,
        "pending_redirect": None,
        "current_job_id": None,
        "queued_job_id": None,
        "next_expected": {"round": 1, "persona": "entrepreneur"},
        "stop_reason": None,
        "created_at": now,
        "updated_at": now,
    }
    (_session_dir(session["id"]) / "rounds").mkdir(parents=True, exist_ok=True)
    _manifest_path(session["id"]).touch()
    _save_session(session)
    return session


def get_session(session_id: str) -> dict | None:
    try:
        return json.loads(_session_path(session_id).read_text())
    except (OSError, ValueError):
        return None


def update_session(session_id: str, **fields) -> dict | None:
    """Merge fields into a session and atomically save it. Returns the
    updated session, or None if it doesn't exist. Used for this side's
    narrow, explicitly-scoped updates (recording the first turn's job id,
    debate_resume, debate_cancel) — the worker owns every other transition,
    including the status field on every ordinary turn advancement."""
    session = get_session(session_id)
    if session is None:
        return None
    session.update(fields)
    session["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _save_session(session)
    return session


def list_sessions(status: str = "", limit: int = 30) -> list[dict]:
    sessions = []
    if not DEBATES_DIR.is_dir():
        return sessions
    for path in DEBATES_DIR.glob("debate-*/session.json"):
        try:
            session = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if status and session.get("status") != status:
            continue
        sessions.append(session)
    sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return sessions[:limit]


def load_manifest(session_id: str) -> list[dict]:
    """Every parseable line, oldest first. A half-written last line (a crash
    mid-append) is silently skipped rather than corrupting the whole read."""
    entries = []
    try:
        lines = _manifest_path(session_id).read_text().splitlines()
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


def render_manifest(session_id: str, limit: int) -> str:
    """Compact, bounded view of the manifest for a human or a turn's task
    prompt: newest context first is NOT what we want here — rounds render
    oldest-to-newest (reading order), with older entries collapsed once the
    count exceeds limit."""
    entries = load_manifest(session_id)
    if not entries:
        return "(no rounds yet)"
    shown = entries[-limit:] if limit and len(entries) > limit else entries
    omitted = len(entries) - len(shown)
    lines = []
    if omitted > 0:
        lines.append(f"... [{omitted} earlier round(s) omitted; read one "
                     "with debate_read_round if its description looks "
                     "relevant]")
    for e in shown:
        lines.append(f"R{e.get('round')} [{e.get('persona')}] "
                     f"{e.get('word_count', '?')}w — {e.get('description', '')} "
                     f"({e.get('path', '')})")
    return "\n".join(lines)


def read_round(session_id: str, round_num: int) -> str | None:
    """Full text of one round file, looked up via the manifest (not a
    filename guess, so it stays correct even if a round was re-run after a
    stuck/resume cycle)."""
    for entry in load_manifest(session_id):
        if entry.get("round") == round_num:
            path = _session_dir(session_id) / entry["path"]
            try:
                return path.read_text()
            except OSError:
                return None
    return None
