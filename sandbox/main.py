"""Sandbox-runner: the second (and only other) service in this stack with
Docker socket access, alongside redeploy. Runs agent-issued shell commands
(tests, linters, builds, git, package installs) inside a throwaway,
resource-capped container with exactly one registered project directory
mounted read-write — nothing else, no host access, no other containers.

Hard rule, never relax without equally careful review: the ephemeral
containers this service launches NEVER receive the Docker socket
themselves — only this service holds it, to launch them. A sandboxed
command has no path to nested Docker control.

Containment here is structural (isolated container, single mount, resource
limits, no socket inside), not a command allowlist and not human-approval
gating — mcp-tools' project_run_command tool always executes immediately
(notify tier); the sandbox is the safety boundary, not a review step.
"""

import os
import re
import secrets
import time

import docker
from docker.errors import NotFound
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

SANDBOX_TOKEN = os.environ.get("SANDBOX_TOKEN", "")

# Absolute HOST path (e.g. /home/scher/workspace) — the same value backing
# mcp-tools' WORKSPACES_ROOT. Deliberately NOT mounted into this container:
# Docker's daemon resolves bind-mount sources against the HOST filesystem
# regardless of which container's process asked for them (this service
# only ever talks to the daemon via the socket), so this string is used
# purely for concatenation, never for a filesystem call from in here.
# There is no safe default — fail fast if it's missing.
WORKSPACES_ROOT = os.environ["WORKSPACES_ROOT"].rstrip("/")

RUNTIME_IMAGE = os.environ.get("SANDBOX_RUNTIME_IMAGE", "makerops-sandbox-runtime:latest")
MEM_LIMIT = os.environ.get("SANDBOX_MEM_LIMIT", "2g")
NANO_CPUS = int(float(os.environ.get("SANDBOX_CPUS", "2")) * 1_000_000_000)
PIDS_LIMIT = int(os.environ.get("SANDBOX_PIDS_LIMIT", "256"))
RUN_UID = os.environ.get("SANDBOX_RUN_UID", "1000")
RUN_GID = os.environ.get("SANDBOX_RUN_GID", "1000")
MAX_OUTPUT_CHARS = int(os.environ.get("SANDBOX_MAX_OUTPUT_CHARS", "8000"))

# This service has no filesystem view of ~/workspace at all (see above) —
# so unlike mcp-tools' project.py (which containment-checks a resolved
# Path), this regex on the project NAME STRING is the entire containment
# guarantee at this layer. No slashes, no leading dot, no "..": every
# match is necessarily a single path segment directly under
# WORKSPACES_ROOT. Do not loosen this without equally careful review.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

app = FastAPI(title="sandbox")
_docker = docker.from_env()


class RunRequest(BaseModel):
    project: str
    command: str
    timeout_s: int = 120


class RunResponse(BaseModel):
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float


def _check_auth(x_sandbox_token: str | None) -> None:
    if SANDBOX_TOKEN and x_sandbox_token != SANDBOX_TOKEN:
        raise HTTPException(401, "invalid or missing X-Sandbox-Token")


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n... [truncated at {MAX_OUTPUT_CHARS} chars]"


def _run_ephemeral(project: str, command: str, timeout_s: int) -> RunResponse:
    host_path = f"{WORKSPACES_ROOT}/{project}"
    started = time.monotonic()
    container = _docker.containers.run(
        RUNTIME_IMAGE,
        ["sh", "-c", command],
        name=f"sandbox-run-{secrets.token_hex(6)}",
        # The one and only mount: this project's own directory, read-write,
        # as the working directory. Nothing else is reachable from inside —
        # in particular, never list the Docker socket here.
        volumes={host_path: {"bind": "/workspace", "mode": "rw"}},
        working_dir="/workspace",
        user=f"{RUN_UID}:{RUN_GID}",
        environment={
            # A numeric UID has no /etc/passwd entry inside the container,
            # so give tools an env-visible $HOME that isn't the project dir.
            "HOME": "/tmp",
            # This is an isolated, throwaway container with no system
            # Python to protect — Debian's PEP 668 "externally-managed"
            # guard would otherwise reject plain `pip install` and force
            # every agent to rediscover --break-system-packages/venvs.
            "PIP_BREAK_SYSTEM_PACKAGES": "1",
        },
        mem_limit=MEM_LIMIT,
        nano_cpus=NANO_CPUS,
        pids_limit=PIDS_LIMIT,
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
        network_mode="bridge",
        # WSL2 quirk (same as every other service in this repo): the host
        # resolver is unreachable from the default bridge network, which
        # breaks DNS for any package install/git clone without this.
        dns=["8.8.8.8", "1.1.1.1"],
        detach=True,
        labels={"managed-by": "makerops-sandbox"},
    )
    timed_out = False
    try:
        try:
            result = container.wait(timeout=timeout_s)
            exit_code = result.get("StatusCode")
        except Exception:
            timed_out = True
            exit_code = None
            try:
                container.stop(timeout=5)
            except NotFound:
                pass
        stdout = container.logs(stdout=True, stderr=False).decode(errors="replace")
        stderr = container.logs(stdout=False, stderr=True).decode(errors="replace")
    finally:
        # No leaked containers on any exit path, including exceptions above.
        try:
            container.remove(force=True)
        except NotFound:
            pass
    return RunResponse(
        exit_code=exit_code, stdout=_truncate(stdout), stderr=_truncate(stderr),
        timed_out=timed_out, duration_s=time.monotonic() - started)


@app.post("/run", response_model=RunResponse)
def run(req: RunRequest, x_sandbox_token: str | None = Header(default=None)):
    _check_auth(x_sandbox_token)
    if not _NAME_RE.match(req.project):
        raise HTTPException(400, "invalid project name")
    if not req.command.strip():
        raise HTTPException(400, "command is empty")
    if req.timeout_s <= 0:
        raise HTTPException(400, "timeout_s must be positive")
    return _run_ephemeral(req.project, req.command, req.timeout_s)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
