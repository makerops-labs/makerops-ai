"""Read/create access to the shared agent-job queue (bind mount of
smolagents/data/smolagents/jobs). Ownership rule: this side only creates
records with status "queued" and may flip queued→cancelled; the smolagents
job worker owns every other status transition. Writes are atomic."""

import json
import os
import time
import uuid
from pathlib import Path

from . import config

JOBS_DIR = Path(config.AGENT_JOBS_DIR)


def _save(job: dict) -> None:
    path = JOBS_DIR / f"{job['id']}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(job, indent=1, ensure_ascii=False))
    os.replace(tmp, path)


def available() -> bool:
    return JOBS_DIR.is_dir()


def create_job(brief: dict, source: str, parent_job_id: str = "",
              debate: dict | None = None, liaison: dict | None = None,
              devteam: dict | None = None, hardware: dict | None = None) -> dict:
    job = {
        "id": f"job-{int(time.time())}-{uuid.uuid4().hex[:6]}",
        "status": "queued",
        "source": source,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "started_at": None,
        "finished_at": None,
        "heartbeat_ts": 0,
        "parent_job_id": parent_job_id or None,
        "segments": 1,
        "brief": brief,
        "report": None,
        "error": None,
        "log_tail": "",
        "debate": debate,
        "liaison": liaison,
        "devteam": devteam,
        "hardware": hardware,
    }
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    _save(job)
    return job


def get_job(job_id: str) -> dict | None:
    path = JOBS_DIR / f"{job_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def cancel_job(job_id: str) -> bool:
    """Flip a still-queued job to cancelled — the one status transition this
    side is allowed to make on its own (see module docstring). Returns False
    (no-op) if the job doesn't exist or has already left the queued state,
    e.g. the worker already picked it up."""
    job = get_job(job_id)
    if job is None or job.get("status") != "queued":
        return False
    job["status"] = "cancelled"
    job["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _save(job)
    return True


def list_jobs(status: str = "", limit: int = 30) -> list[dict]:
    jobs = []
    for path in JOBS_DIR.glob("job-*.json"):
        try:
            job = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if status and job.get("status") != status:
            continue
        jobs.append(job)
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return jobs[:limit]


def counts() -> dict:
    tally = {"queued": 0, "running": 0}
    for job in list_jobs(limit=1000):
        st = job.get("status")
        if st in tally:
            tally[st] += 1
    return tally


def load_roster() -> list[dict] | None:
    path = JOBS_DIR / "roster.json"
    if not path.is_file():
        return None
    try:
        roster = json.loads(path.read_text())
        return roster if isinstance(roster, list) else None
    except (OSError, ValueError):
        return None
