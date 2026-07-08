# sandbox — Docker-socket-scoped sandboxed command execution

The second (and only other) service in this stack with Docker socket
access, alongside [redeploy](../redeploy/). Exists so agents can run shell
commands — test runners, linters, builds, `git`, package installs —
confined to exactly one registered project directory
(`mcp-tools`'s `project` domain, see [mcp-tools/README.md](../mcp-tools/README.md)
"Project workspaces"), without any ability to touch anything outside it or
affect other system/Docker resources.

## Why a separate service

A container with the Docker socket mounted can generally do far more than
"launch one scoped, resource-capped throwaway container" — create
privileged containers, mount arbitrary host paths, etc. Isolating that
capability into one small, auditable service — whose only job is spinning
up an ephemeral, resource-capped container with exactly one project
directory mounted, then tearing it down — keeps the blast radius of a bug
or a bad prompt to "one throwaway container that can only see the project
it was scoped to," not "arbitrary Docker control." mcp-tools itself never
touches Docker; it only ever calls this one narrow endpoint.

**Hard rule, never relax**: the ephemeral containers this service launches
never receive the Docker socket themselves. A sandboxed command has no path
to nested Docker control.

## Containment model

- **Filesystem**: exactly one bind mount, `<WORKSPACES_ROOT>/<project>` →
  `/workspace` (read-write, the container's working directory). Nothing
  else is reachable — no other project, no host paths, no Docker socket.
  **Trust boundary worth knowing**: this service has no filesystem view of
  `~/workspace` (by design — see the DooD note above), so it cannot verify
  a project's directory already exists before mounting it; Docker's own
  bind-mount semantics silently create an empty (root-owned) directory at
  that path if it's missing. `project_run_command` on the mcp-tools side
  always checks the project registry first, so this is never reachable
  from an agent in normal use — it only matters if something calls `/run`
  directly with an unregistered name, bypassing mcp-tools entirely.
- **Resources**: memory (`SANDBOX_MEM_LIMIT`, default `2g`), CPU
  (`SANDBOX_CPUS`, default `2`), and process count (`SANDBOX_PIDS_LIMIT`,
  default `256`) are all capped per container — a memory hog gets
  OOM-killed, a fork bomb hits the PID cap, rather than degrading the host.
- **Privilege**: `cap_drop=["ALL"]`, `no-new-privileges`, runs as a
  non-root UID/GID (`SANDBOX_RUN_UID`/`GID`, default matching a typical
  host user) — files it creates in the project directory aren't
  root-owned.
- **Network**: standard Docker bridge networking (deliberate — package
  installs, `git clone`/`push`, and real test suites need it). This is
  orthogonal to filesystem/process containment: network access doesn't let
  a command reach other files or other containers on the host.
- **Lifetime**: every request gets a brand-new container, torn down
  (`remove(force=True)`) when the command finishes, times out, or errors —
  no container survives past one request.
- **No command allowlist**: containment here is structural (the box
  itself), not a list of permitted command strings — this matches the
  rest of the `project` domain's philosophy (notify-tier, no per-action
  approval friction; the sandbox is the safety boundary).

## API

- `POST /run` — body `{"project": str, "command": str, "timeout_s": int = 120}`,
  header `X-Sandbox-Token: <SANDBOX_TOKEN>`. Runs `command` via `sh -c` in a
  fresh container scoped to `project`'s directory, waits up to `timeout_s`
  (killing and reporting `timed_out: true` if exceeded), and returns
  `{"exit_code", "stdout", "stderr", "timed_out", "duration_s"}` — stdout
  and stderr are each truncated to `SANDBOX_MAX_OUTPUT_CHARS`. Synchronous:
  the caller (mcp-tools) blocks for the command's duration, unlike
  redeploy's fire-and-forget `/restart` — this service never restarts the
  caller, so there's nothing to lose by waiting.
- `GET /healthz` — liveness.

Not for long-running processes (dev servers, daemons) — commands must run
to completion and return within `timeout_s` (capped by
`SANDBOX_MAX_TIMEOUT_S` on the mcp-tools side).

## Setup

`./start.sh` builds the ephemeral-container runtime image
(`runtime.Dockerfile` → `makerops-sandbox-runtime:latest`, git/curl/Python/
Node/build-essential on `debian:bookworm-slim`) and generates a random
`SANDBOX_TOKEN` on first run — copy that value into `mcp-tools/.env`'s
`SANDBOX_TOKEN` (must match on both sides) and recreate mcp-tools
(`docker compose -p mcp-tools up -d`). Also set `WORKSPACES_ROOT` in this
directory's `.env` to the **same** absolute host path as `mcp-tools/.env`'s
— see the Docker-out-of-Docker note in `main.py`'s module docstring for
why this value is a plain string here rather than a mount.

## Known limitation (v1)

If the `sandbox` service process itself crashes mid-request, its own
ephemeral container could be orphaned (the `finally: container.remove()`
never runs). There's no automatic reconciliation sweep yet — find and
remove any survivors with
`docker ps -a --filter label=managed-by=makerops-sandbox`.

## Swapping the runtime image

Set `SANDBOX_RUNTIME_IMAGE` in `.env` to any image name (build it yourself
or pull one) if the default toolchain doesn't fit a project — no code
change needed.
