"""Redeploy service: the only thing in this stack with Docker socket access.

Owns the full apply-a-code-change lifecycle for approved propose_code_change
actions: write the file, restart the affected container, poll its health,
and if it doesn't come back healthy, revert the file and restart again.
Reports the outcome itself (audit log + notify webhook) rather than relying
on the caller (mcp-tools) still being alive to hear the answer — restarting
mcp-tools' own container is exactly the case where that caller can't wait
around for a response.

mcp-tools never touches Docker directly; it only ever calls this one narrow
endpoint. Expanding ALLOWED_SERVICES is itself a code change to this file,
so even loosening this boundary goes through the same gated review this
service exists to support.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import docker
import httpx
from docker.errors import NotFound
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

ALLOWED_SERVICES = {"smolagents", "mcp-tools"}
HEALTH_POLL_S = 2
HEALTH_TIMEOUT_S = 30
# A container that crash-loops can show "running" for a brief window right
# after each restart attempt (process spawns, then dies on import/startup
# error, then Docker's own restart policy cycles it again) — a single
# point-in-time check can sample right into that window and report a false
# healthy. Require several consecutive stable checks, and treat a changed
# StartedAt as an immediate failure — it means Docker's restart policy
# intervened again since redeploy's own restart, i.e. it crashed on its own.
REQUIRED_STABLE_CHECKS = 3

REDEPLOY_TOKEN = os.environ.get("REDEPLOY_TOKEN", "")
NOTIFY_WEBHOOK = os.environ.get("APPROVAL_NOTIFY_WEBHOOK", "")
MCPTOOLS_PUBLIC_URL = os.environ.get("MCPTOOLS_PUBLIC_URL", "http://mcp.localhost")
# Same file mcp-tools/tools/policy.py writes to — shared bind mount — so
# redeploy's own audit entries show up in /approvals "Recent activity" with
# no changes needed to that page's rendering code.
AUDIT_LOG = Path(os.environ.get("AUDIT_LOG_PATH", "/mcp-data/audit.jsonl"))
REPO_ROOT = Path(os.environ.get("REPO_ROOT", "/repo"))

app = FastAPI(title="redeploy")
_docker = docker.from_env()


class RestartRequest(BaseModel):
    service: str
    file_path: str = ""
    new_content: str = ""
    old_content: str = ""


def _check_auth(x_redeploy_token: str | None) -> None:
    if REDEPLOY_TOKEN and x_redeploy_token != REDEPLOY_TOKEN:
        raise HTTPException(401, "invalid or missing X-Redeploy-Token")


def _resolve_path(file_path: str) -> Path:
    resolved = (REPO_ROOT / file_path).resolve()
    if not resolved.is_relative_to(REPO_ROOT.resolve()):
        raise HTTPException(400, "file_path escapes the repository root")
    return resolved


def _audit(event: str, summary: str) -> None:
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "event": event, "domain": "agents", "tool": "propose_code_change",
             "summary": summary}
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError as exc:
        print(f"[redeploy] failed to write audit log: {exc}")


def _notify(event: str, summary: str) -> None:
    if not NOTIFY_WEBHOOK:
        return
    body = {"event": event, "summary": summary,
            "approvals_url": f"{MCPTOOLS_PUBLIC_URL}/approvals"}
    try:
        httpx.post(NOTIFY_WEBHOOK, json=body, timeout=5.0)
    except httpx.HTTPError as exc:
        print(f"[redeploy] notify webhook failed: {exc}")


def _container_healthy(name: str, expected_started_at: str) -> bool:
    try:
        container = _docker.containers.get(name)
    except NotFound:
        return False
    container.reload()
    state = container.attrs.get("State", {}) or {}
    if state.get("StartedAt") != expected_started_at:
        # Docker's own restart policy cycled the container again since we
        # restarted it — it crashed on its own, even if it looks "running"
        # again right now.
        return False
    if container.status != "running":
        return False
    health = state.get("Health")
    if health is None:
        # No healthcheck defined (e.g. smolagents) — running-and-stable is
        # the only signal available.
        return True
    return health.get("Status") == "healthy"


def _restart_and_wait(service: str) -> bool:
    container = _docker.containers.get(service)
    container.restart(timeout=10)
    container.reload()
    expected_started_at = container.attrs.get("State", {}).get("StartedAt", "")

    deadline = time.time() + HEALTH_TIMEOUT_S
    stable_checks = 0
    while time.time() < deadline:
        time.sleep(HEALTH_POLL_S)
        if _container_healthy(service, expected_started_at):
            stable_checks += 1
            if stable_checks >= REQUIRED_STABLE_CHECKS:
                return True
        else:
            stable_checks = 0
    return False


def _apply(req: RestartRequest) -> None:
    """Runs in a background thread so the HTTP response can return
    immediately — the caller (mcp-tools) may be the very container about to
    restart and won't be around to read a response that arrives later."""
    target = _resolve_path(req.file_path) if req.file_path else None
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(req.new_content)

    if req.service not in ALLOWED_SERVICES:
        _audit("redeploy.skipped",
               f"{req.file_path or '(no file)'} written; '{req.service}' is "
               f"not restartable by redeploy — no automatic redeploy for "
               f"this path.")
        return

    try:
        healthy = _restart_and_wait(req.service)
    except NotFound:
        _audit("redeploy.failed", f"no running container named '{req.service}'")
        _notify("redeploy.failed", f"no running container named '{req.service}'")
        return

    if healthy:
        _audit("redeploy.completed", f"{req.service} restarted and is healthy "
               f"(file: {req.file_path or 'n/a'})")
        _notify("redeploy.completed", f"{req.service} restarted successfully "
               f"after a code change to {req.file_path}.")
        return

    # Unhealthy — revert and restart again onto the known-good version.
    if target is not None:
        target.write_text(req.old_content)
    reverted_ok = False
    try:
        reverted_ok = _restart_and_wait(req.service)
    except NotFound:
        pass
    summary = (f"{req.service} failed its health check after the change to "
              f"{req.file_path} — reverted to the previous version and "
              f"restarted{'  successfully' if reverted_ok else ' (still unhealthy — needs attention)'}.")
    _audit("redeploy.reverted", summary)
    _notify("redeploy.reverted", summary)


@app.post("/restart")
def restart(req: RestartRequest, x_redeploy_token: str | None = Header(default=None)):
    _check_auth(x_redeploy_token)
    if req.file_path:
        _resolve_path(req.file_path)  # validate before accepting
    threading.Thread(target=_apply, args=(req,), daemon=True).start()
    return {"accepted": True,
            "message": f"Applying change and restarting '{req.service}' in "
                       f"the background; outcome will appear in /approvals "
                       f"and via notification."}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
