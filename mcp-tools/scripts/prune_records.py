#!/usr/bin/env python3
"""Prune old terminal-state records from the job/debate/devteam/hardware
stores under smolagents/data/smolagents/ (bind-mounted into mcp-tools as
/agent-jobs, /agent-debates, /agent-devteam, /agent-hardware — see
mcp-tools/docker-compose.yml). These accumulate one file/dir per job or
session forever; nothing in the codebase currently deletes them, and the
/inbox page + /healthz job listing re-read every file on every request, so
old records cost both disk and per-request work as the count grows.

Runs directly against the host paths — no container/Docker needed. Never
touches non-terminal records regardless of age: for the job queue that's
the exact _TERMINAL set from smolagents/agents/jobs.py (queued/running
left alone); for debate/devteam/hardware sessions that's each store's own
TERMINAL_STATUSES (active/awaiting_input/awaiting_review/stuck left alone
— a stuck session is parked for a deliberate human resume, not dead).
Liaison is excluded on purpose: liaison_store.py already self-bounds each
user's file to its last 80 turns, so it doesn't need this.

Dry-run by default — pass --yes to actually delete. --keep-min protects
the N most-recent terminal records per store from deletion even if older
than --days, so there's always recent history to look back at.
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SMOLAGENTS_DATA = REPO_ROOT / "smolagents" / "data" / "smolagents"

JOB_TERMINAL = {"completed", "needs_clarification", "needs_attention", "failed", "cancelled"}
SESSION_TERMINAL = {"concluded", "cancelled"}


def _dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _age_days(iso_ts: str | None, now: float) -> float | None:
    if not iso_ts:
        return None
    try:
        # Handles both "+0500" and "+05:00" / "Z" offset styles used across stores.
        ts = iso_ts.replace("Z", "+00:00")
        if len(ts) >= 5 and ts[-5] in "+-" and ts[-3] != ":":
            ts = ts[:-2] + ":" + ts[-2:]
        parsed = time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
        epoch = time.mktime(parsed)
    except (ValueError, IndexError):
        return None
    return (now - epoch) / 86400.0


def _scan_jobs(jobs_dir: Path, now: float):
    candidates = []
    if not jobs_dir.is_dir():
        return candidates
    for path in jobs_dir.glob("job-*.json"):
        try:
            job = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        status = job.get("status")
        if status not in JOB_TERMINAL:
            continue
        age = _age_days(job.get("finished_at") or job.get("created_at"), now)
        workspace_dir = jobs_dir / job["id"]
        paths = [path] + ([workspace_dir] if workspace_dir.is_dir() else [])
        size = sum(_dir_size(p) for p in paths)
        candidates.append({"id": job["id"], "kind": "job", "status": status,
                           "age_days": age, "size": size, "paths": paths})
    return candidates


def _scan_sessions(store_dir: Path, kind: str, now: float):
    candidates = []
    if not store_dir.is_dir():
        return candidates
    for session_dir in store_dir.iterdir():
        if not session_dir.is_dir():
            continue
        session_path = session_dir / "session.json"
        if not session_path.is_file():
            continue
        try:
            session = json.loads(session_path.read_text())
        except (OSError, ValueError):
            continue
        status = session.get("status")
        if status not in SESSION_TERMINAL:
            continue
        age = _age_days(session.get("updated_at") or session.get("created_at"), now)
        candidates.append({"id": session_dir.name, "kind": kind, "status": status,
                           "age_days": age, "size": _dir_size(session_dir),
                           "paths": [session_dir]})
    return candidates


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=float, default=14,
                    help="Delete terminal records older than this many days (default: 14).")
    ap.add_argument("--keep-min", type=int, default=5,
                    help="Always keep this many most-recent terminal records per store, "
                         "even if older than --days (default: 5).")
    ap.add_argument("--yes", action="store_true",
                    help="Actually delete. Without this, only prints what would be deleted.")
    ap.add_argument("--data-dir", type=Path, default=SMOLAGENTS_DATA,
                    help=f"Path to smolagents/data/smolagents (default: {SMOLAGENTS_DATA}).")
    args = ap.parse_args()

    now = time.time()
    stores = [
        ("jobs", _scan_jobs(args.data_dir / "jobs", now)),
        ("debates", _scan_sessions(args.data_dir / "debates", "debate", now)),
        ("devteam", _scan_sessions(args.data_dir / "devteam", "devteam", now)),
        ("hardware", _scan_sessions(args.data_dir / "hardware", "hardware", now)),
    ]

    to_delete = []
    total_size = 0
    for store_name, candidates in stores:
        # Newest first; age=None (unparseable timestamp) sorts as oldest so it
        # is never silently protected by --keep-min.
        candidates.sort(key=lambda c: c["age_days"] if c["age_days"] is not None else float("inf"))
        protected = candidates[:args.keep_min]
        eligible = candidates[args.keep_min:]
        store_deletes = [c for c in eligible
                        if c["age_days"] is not None and c["age_days"] >= args.days]
        print(f"{store_name}: {len(candidates)} terminal record(s), "
              f"{len(protected)} protected by --keep-min, "
              f"{len(store_deletes)} eligible for deletion")
        to_delete.extend(store_deletes)

    if not to_delete:
        print("\nNothing to delete.")
        return

    print(f"\n{'Would delete' if not args.yes else 'Deleting'} {len(to_delete)} record(s):")
    for c in sorted(to_delete, key=lambda c: c["age_days"], reverse=True):
        total_size += c["size"]
        print(f"  {c['kind']:8s} {c['id']:32s} {c['status']:20s} "
              f"{c['age_days']:6.1f}d  {c['size'] / 1024:8.1f} KiB")
    print(f"\nTotal: {total_size / 1024 / 1024:.2f} MiB")

    if not args.yes:
        print("\nDry run — rerun with --yes to actually delete.")
        return

    for c in to_delete:
        for p in c["paths"]:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink(missing_ok=True)
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
