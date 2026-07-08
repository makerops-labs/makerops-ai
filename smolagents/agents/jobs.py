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

    lines.append(
        f"Your working-memory workspace directory is {workspace} "
        "(create files with pathlib). Keep synopsis.md there current per "
        "your WORKING MEMORY procedure.")
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


def _run_job(manager, job: dict) -> None:
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

    if not getattr(manager, "_jobs_heartbeat", False):
        manager.step_callbacks.register(ActionStep, _heartbeat)
        manager.step_callbacks.register(PlanningStep, _heartbeat)
        manager._jobs_heartbeat = True

    while True:
        task = _format_task(job, workspace)
        try:
            answer = manager.run(task, reset=True,
                                 additional_args={"workspace": str(workspace)})
            report = _parse_report(manager, answer)
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
    """A record stuck in 'running' means the container died mid-job."""
    for path in _jobs_dir.glob("job-*.json"):
        job = _load(path)
        if job and job.get("status") == "running":
            job.update(status="failed", finished_at=_now(),
                       error="worker restarted mid-job")
            _save(job)
            _notify("job.failed", job)


def _worker_loop() -> None:
    # Deferred import: manager needs mcp-tools reachable for tool loading.
    from .manager import build_manager_agent

    _jobs_dir.mkdir(parents=True, exist_ok=True)
    _recover_stale()
    manager = build_manager_agent()  # built once; reused with reset=True
    _write_roster(manager)
    print(f"[jobs] worker ready — polling {_jobs_dir} every {_POLL_S}s")
    while True:
        try:
            for job in _queued_jobs():
                # Re-read in case mcp-tools cancelled it meanwhile.
                current = _load(_job_path(job["id"]))
                if current and current.get("status") == "queued":
                    _run_job(manager, current)
        except Exception:  # noqa: BLE001 — the worker must survive anything
            print(f"[jobs] worker loop error:\n{traceback.format_exc()}")
        time.sleep(_POLL_S)


def start_job_worker() -> threading.Thread:
    thread = threading.Thread(target=_worker_loop, name="job-worker",
                              daemon=True)
    thread.start()
    return thread
