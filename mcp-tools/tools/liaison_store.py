"""Read/create access to the shared Alexa-liaison session store (bind mount
of smolagents/data/smolagents/liaison). One JSON file per Alexa userId —
not the ephemeral per-invocation Alexa sessionId, so a conversation
survives Alexa's own ~8s-silence session timeout across separate HTTP
turns. Ownership rule, same split as debate_store.py alongside
jobs_store.py: this side appends the user's new utterance and creates that
turn's queued job; the smolagents job worker (agents/jobs.py) appends the
liaison's own answer and updates the pending job/action pointers once the
turn actually runs. Writes are atomic.

Layout: <user_id>.json — whole-object atomic write, holding a bounded
turn history plus pending_job_id/pending_action_id pointers the
alexa-bridge polls for its deterministic 'status'/'confirm'/'deny' voice
commands.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import config

LIAISON_DIR = Path(config.AGENT_LIAISON_DIR)

# Bounds how many turns a session file keeps on disk — independent of
# agents/config.py's SMOLAGENTS_LIAISON_HISTORY_TURNS, which bounds how many
# of these get folded into a turn's task text; kept as a separate constant
# since these are different services/processes (same reasoning as the
# debate manifest render limit, see this module's config.py neighbor).
_HISTORY_MAX_ENTRIES = 80


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _session_path(user_id: str) -> Path:
    return LIAISON_DIR / f"{user_id}.json"


def _save_session(session: dict) -> None:
    path = _session_path(session["user_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(session, indent=1, ensure_ascii=False))
    os.replace(tmp, path)


def available() -> bool:
    return LIAISON_DIR.is_dir()


def get_session(user_id: str) -> dict | None:
    try:
        return json.loads(_session_path(user_id).read_text())
    except (OSError, ValueError):
        return None


def get_or_create_session(user_id: str) -> dict:
    session = get_session(user_id)
    if session is not None:
        return session
    now = _now_iso()
    session = {
        "user_id": user_id,
        "history": [],
        # last_job_id: the most recently dispatched turn's job id, set at
        # dispatch time and left alone once the turn finishes — the
        # deterministic 'status' phrase's fallback so a turn the bridge
        # itself gave up waiting on (its own poll timed out) can still be
        # read back later even though it isn't 'deferred'.
        "last_job_id": "",
        # pending_job_id: ONLY a 'deferred' turn's separate background
        # manager-job id (see agents/jobs.py's _finish_liaison_turn) —
        # narrower than last_job_id, cleared once the turn that reported it
        # finishes being the most recent one.
        "pending_job_id": "",
        "pending_action_id": "",
        "created_at": now,
        "updated_at": now,
    }
    _save_session(session)
    return session


def append_turn(user_id: str, role: str, text: str) -> dict:
    """Appends one turn (role: 'user' or 'liaison') and saves. Returns the
    updated session."""
    session = get_or_create_session(user_id)
    session["history"].append({"role": role, "text": text, "ts": _now_iso()})
    if len(session["history"]) > _HISTORY_MAX_ENTRIES:
        session["history"] = session["history"][-_HISTORY_MAX_ENTRIES:]
    session["updated_at"] = _now_iso()
    _save_session(session)
    return session


def update_session(user_id: str, **fields) -> dict | None:
    session = get_session(user_id)
    if session is None:
        return None
    session.update(fields)
    session["updated_at"] = _now_iso()
    _save_session(session)
    return session


def reset_session(user_id: str) -> dict:
    """Clears history and pending pointers but keeps the same user_id record
    — backs the 'start over' deterministic voice command."""
    session = get_or_create_session(user_id)
    session["history"] = []
    session["pending_job_id"] = ""
    session["pending_action_id"] = ""
    session["updated_at"] = _now_iso()
    _save_session(session)
    return session
