"""Project domain: durable, user-assigned directories for implementing an
already-approved solution's code and docs. Distinct from a job's own
ephemeral working-memory workspace (see jobs.py) — a project lives at
~/workspace/<name> (a sibling of ~/workspace/makerops/, never inside it) and
persists across many jobs.

Read tools (project_read_file, project_list_dir, project_glob, project_grep)
work anywhere under the ~/workspace mount, including directories nobody has
registered yet — this is deliberate, so agents can browse sibling projects
(or this stack's own source) as prior art without any setup. Write tools
(project_write_file, project_edit_file) are confined to one project the user
has registered with project_register, which requires the directory to
already exist — the user creating it by hand is the authorization. Writes
execute immediately (notify tier; see APPROVAL_GATE_EXEMPT=project in
.env.example) since that authorization already happened.
"""

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastmcp import FastMCP

from . import config, policy

mcp = FastMCP(
    "project",
    instructions=(
        "Durable project directories under ~/workspace/, distinct from your "
        "own per-job working-memory workspace. Read tools (project_read_file, "
        "project_list_dir, project_glob, project_grep) work anywhere under "
        "~/workspace, including directories nobody registered yet — use them "
        "to survey sibling projects or this stack's own source as prior art. "
        "Write tools (project_write_file, project_edit_file) only work inside "
        "a project you've registered with project_register, and only once "
        "the user has created that directory by hand. Every registered "
        "project has a PROJECT_CONTEXT.md at its root — read it first, and "
        "keep it current as the project's state changes."))
required_env = None  # writes to the bind mount, no token

_LOCK = threading.Lock()
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv"}
_STATUSES = ("proposed", "assigned", "in_progress", "review", "done")
_GLOB_LIMIT = 500
_GREP_LIMIT = 200

PROJECTS_FILE = config.DATA_DIR / "projects.json"

CONTEXT_FILENAME = "PROJECT_CONTEXT.md"
_CONTEXT_TEMPLATE = """# Project context

Status: assigned, no work started yet.

## Architecture

(not yet known)

## Further reading

(none yet — as the project grows, link detail docs here, e.g. under docs/,
and keep this file itself concise.)
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Registry ────────────────────────────────────────────────────────────────

def _load_registry() -> dict:
    try:
        return json.loads(PROJECTS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save_registry(data: dict) -> None:
    PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROJECTS_FILE.write_text(json.dumps(data, indent=1))


def _get_project(project: str) -> dict | None:
    return _load_registry().get(project)


# ── Path resolution ─────────────────────────────────────────────────────────
# Two deliberately different scopes: reads are broad (anywhere under the
# ~/workspace mount, no registration needed — prior-art browsing is the
# point); writes are narrow (confined to one registered project's own root).

def _is_env_file(path: Path) -> bool:
    return path.name == ".env" or path.name.startswith(".env.")


def _has_control_chars(path_str: str) -> bool:
    """Catches a model passing content where a path was expected (e.g.
    swapped arguments) — a real failure mode observed in testing. Still
    fully contained either way; this is hygiene against garbled filenames,
    not a security boundary."""
    return any(ord(c) < 0x20 for c in path_str)


def _resolve_read_path(relative_path: str) -> Path | str:
    if _has_control_chars(relative_path):
        return "ERROR: relative_path contains control characters (newline/tab/etc) — that looks like content, not a path."
    root = config.PROJECTS_ROOT.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return "ERROR: path escapes ~/workspace."
    if _is_env_file(candidate):
        return "ERROR: .env files are off-limits — they hold live secrets."
    return candidate


def _resolve_project_path(project: str, file_path: str) -> Path | str:
    if not _NAME_RE.match(project):
        return "ERROR: invalid project name."
    if _has_control_chars(file_path):
        return "ERROR: file_path contains control characters (newline/tab/etc) — that looks like content, not a path."
    if _get_project(project) is None:
        return (f"ERROR: '{project}' is not a registered project — call "
                f"project_register first (the directory must already exist).")
    root = (config.PROJECTS_ROOT / project).resolve()
    candidate = (root / file_path).resolve()
    try:
        rel_parts = candidate.relative_to(root).parts
    except ValueError:
        return f"ERROR: file_path escapes the '{project}' project directory."
    if ".git" in rel_parts[:-1]:
        return "ERROR: paths under .git/ are off-limits (VCS content, not source)."
    return candidate


def _read_text_or_error(path: Path) -> str:
    if not path.is_file():
        return f"ERROR: no such file: {path.name}"
    try:
        return path.read_text()
    except UnicodeDecodeError:
        return "ERROR: file is not valid UTF-8 text (binary)."


# ── Read tools — broad, no registration required ────────────────────────────

@mcp.tool
def project_read_file(relative_path: str, offset: int = 0, limit: int = 0) -> str:
    """Read a file anywhere under ~/workspace, given a path relative to that
    root (e.g. 'other-project/README.md' or
    'makerops/makerops-ai/README.md') — works even for directories nobody
    has registered, for prior-art research. offset/limit select a 0-indexed
    line range (both 0 = whole file). .env files are off-limits everywhere."""
    resolved = _resolve_read_path(relative_path)
    if isinstance(resolved, str):
        return resolved
    text = _read_text_or_error(resolved)
    if text.startswith("ERROR:"):
        return text
    if not offset and not limit:
        return text
    lines = text.splitlines()
    end = (offset + limit) if limit else len(lines)
    return "\n".join(lines[offset:end])


@mcp.tool
def project_list_dir(relative_path: str = "") -> str:
    """Non-recursive directory listing under ~/workspace. Empty
    relative_path lists the top-level project directories themselves."""
    resolved = _resolve_read_path(relative_path)
    if isinstance(resolved, str):
        return resolved
    if not resolved.is_dir():
        return f"ERROR: not a directory: {relative_path or '(root)'}"
    entries = []
    for p in sorted(resolved.iterdir()):
        if p.name in _SKIP_DIRS:
            continue
        if p.is_dir():
            entries.append(f"{p.name}/ (dir)")
        else:
            entries.append(f"{p.name} (file, {p.stat().st_size}b)")
    return "\n".join(entries) if entries else "(empty)"


@mcp.tool
def project_glob(pattern: str, relative_path: str = "") -> str:
    """Recursive filename pattern match (e.g. '*.py' or '**/*.md') under
    ~/workspace or a subdirectory. Skips .git, node_modules, __pycache__,
    .venv. Results capped at 500 matches."""
    resolved = _resolve_read_path(relative_path)
    if isinstance(resolved, str):
        return resolved
    if not resolved.is_dir():
        return f"ERROR: not a directory: {relative_path or '(root)'}"
    root = config.PROJECTS_ROOT.resolve()
    matches = []
    for p in resolved.rglob(pattern):
        if not p.is_file() or _SKIP_DIRS & set(p.relative_to(root).parts):
            continue
        matches.append(str(p.relative_to(root)))
        if len(matches) >= _GLOB_LIMIT:
            matches.append(f"... [truncated at {_GLOB_LIMIT} matches]")
            break
    return "\n".join(matches) if matches else "(no matches)"


@mcp.tool
def project_grep(pattern: str, relative_path: str = "", file_glob: str = "*") -> str:
    """Text search (regular expression) across files under ~/workspace or a
    subdirectory, matching filenames against file_glob (e.g. '*.py'). Skips
    .git, node_modules, __pycache__, .venv, binary files, and .env files.
    Results capped at 200 matches, each shown as 'path:line: text'."""
    resolved = _resolve_read_path(relative_path)
    if isinstance(resolved, str):
        return resolved
    if not resolved.is_dir():
        return f"ERROR: not a directory: {relative_path or '(root)'}"
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"ERROR: invalid regular expression: {exc}"
    root = config.PROJECTS_ROOT.resolve()
    matches = []
    for p in sorted(resolved.rglob(file_glob)):
        if not p.is_file() or _SKIP_DIRS & set(p.relative_to(root).parts) or _is_env_file(p):
            continue
        try:
            text = p.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append(f"{p.relative_to(root)}:{i}: {line.strip()[:200]}")
                if len(matches) >= _GREP_LIMIT:
                    matches.append(f"... [truncated at {_GREP_LIMIT} matches]")
                    return "\n".join(matches)
    return "\n".join(matches) if matches else "(no matches)"


# ── Registry listing ─────────────────────────────────────────────────────────

@mcp.tool
def project_list() -> str:
    """List registered projects: name, status, path, description, and when
    each was created/last updated."""
    registry = _load_registry()
    if not registry:
        return "No projects registered yet."
    lines = []
    for name, entry in sorted(registry.items()):
        lines.append(
            f"{name} [{entry.get('status', '?')}] {entry.get('path', '')} — "
            f"{entry.get('description', '')} (created {entry.get('created_at', '?')}, "
            f"updated {entry.get('updated_at', '?')})")
    return "\n".join(lines)


# ── Write tools — narrow, confined to one registered project ────────────────

def _seed_context_doc(root: Path) -> None:
    context_path = root / CONTEXT_FILENAME
    if not context_path.is_file():
        context_path.write_text(_CONTEXT_TEMPLATE)


def _do_project_register(params: dict) -> str:
    project = params["project"]
    root = config.PROJECTS_ROOT / project
    with _LOCK:
        registry = _load_registry()
        now = _now_iso()
        entry = registry.get(project, {"created_at": now})
        entry.update(path=str(root), description=params["description"],
                     status="assigned", updated_at=now)
        registry[project] = entry
        _save_registry(registry)
    _seed_context_doc(root)
    return (f"OBJECT_ID={project}\n"
            f"Registered project '{project}' at {root}. "
            f"{CONTEXT_FILENAME} is present at its root — read it first in "
            f"any job targeting this project.")


policy.register_executor("project", "project_register", _do_project_register)


@mcp.tool
def project_register(project: str, description: str = "") -> str:
    """WRITE ACTION — register an existing directory under ~/workspace as a
    project you can write to. project: the directory's own name (e.g.
    'my-app' for ~/workspace/my-app), no slashes — the directory must
    already exist; the user creating it by hand is the authorization to
    write there. Never registers 'makerops' (governed by
    propose_code_change/redeploy instead). Seeds a starter
    PROJECT_CONTEXT.md at the project root if one isn't already there."""
    if not _NAME_RE.match(project):
        return "ERROR: project must be a bare directory name (letters, digits, _, - only, no slashes)."
    if project == "makerops":
        return "ERROR: 'makerops' is off-limits — governed by propose_code_change/redeploy, not this domain."
    root = config.PROJECTS_ROOT / project
    if not root.is_dir():
        return (f"ERROR: {root} does not exist — create the directory "
                f"yourself first (that's the authorization signal); this "
                f"tool never creates it for you.")
    return policy.apply_policy(
        domain="project", tool="project_register", action_kind="create",
        summary=f"Register project '{project}'" +
                (f": {description[:100]}" if description else ""),
        params={"project": project, "description": description},
        changes=[f"Registered project directory {root}"],
        created_object_id_from_result=True)


def _do_project_write_file(params: dict) -> str:
    resolved = _resolve_project_path(params["project"], params["file_path"])
    if isinstance(resolved, str):
        return resolved
    resolved.parent.mkdir(parents=True, exist_ok=True)
    existed = resolved.is_file()
    resolved.write_text(params["content"])
    with _LOCK:
        registry = _load_registry()
        if params["project"] in registry:
            registry[params["project"]]["updated_at"] = _now_iso()
            _save_registry(registry)
    return (f"{'Overwrote' if existed else 'Created'} "
            f"{params['project']}/{params['file_path']} "
            f"({len(params['content'])} bytes).")


policy.register_executor("project", "project_write_file", _do_project_write_file)


@mcp.tool
def project_write_file(project: str, file_path: str, content: str) -> str:
    """WRITE ACTION — create or fully overwrite a file inside a registered
    project. project: name passed to project_register. file_path: relative
    to that project's own root (not ~/workspace). content: the FULL file
    content, not a patch — for incremental changes to an existing file,
    prefer project_edit_file. Executes immediately (notify tier) once
    registered; the user is notified with a summary."""
    if "\x00" in content:
        return "ERROR: content contains a null byte — binary content is not supported."
    resolved = _resolve_project_path(project, file_path)
    if isinstance(resolved, str):
        return resolved
    return policy.apply_policy(
        domain="project", tool="project_write_file", action_kind="update",
        target_id=f"{project}/{file_path}",
        summary=f"Write {project}/{file_path}",
        params={"project": project, "file_path": file_path, "content": content},
        changes=[f"{'Overwrote' if resolved.is_file() else 'Created'} {file_path}"])


def _do_project_edit_file(params: dict) -> str:
    resolved = _resolve_project_path(params["project"], params["file_path"])
    if isinstance(resolved, str):
        return resolved
    text = _read_text_or_error(resolved)
    if text.startswith("ERROR:"):
        return text
    old_string, new_string = params["old_string"], params["new_string"]
    count = text.count(old_string)
    if count == 0:
        return f"ERROR: old_string not found in {params['file_path']}."
    if count > 1 and not params["replace_all"]:
        return (f"ERROR: old_string appears {count} times in "
                f"{params['file_path']} — pass replace_all=True or include "
                f"more surrounding context to make it unique.")
    new_text = text.replace(old_string, new_string,
                            -1 if params["replace_all"] else 1)
    resolved.write_text(new_text)
    with _LOCK:
        registry = _load_registry()
        if params["project"] in registry:
            registry[params["project"]]["updated_at"] = _now_iso()
            _save_registry(registry)
    return (f"Edited {params['project']}/{params['file_path']} "
            f"({count} replacement{'s' if count != 1 else ''}).")


policy.register_executor("project", "project_edit_file", _do_project_edit_file)


@mcp.tool
def project_edit_file(project: str, file_path: str, old_string: str,
                      new_string: str, replace_all: bool = False) -> str:
    """WRITE ACTION — targeted exact-string replacement in an existing file
    inside a registered project, mirroring an editor's find/replace. Errors
    if old_string isn't found, or (unless replace_all=True) isn't unique —
    include enough surrounding context to make it unique rather than
    setting replace_all unless you really mean every occurrence. Cheaper
    and safer than project_write_file for incremental changes. Executes
    immediately (notify tier) once registered."""
    if old_string == new_string:
        return "ERROR: old_string and new_string are identical — nothing to do."
    resolved = _resolve_project_path(project, file_path)
    if isinstance(resolved, str):
        return resolved
    if not resolved.is_file():
        return f"ERROR: no such file: {file_path}"
    return policy.apply_policy(
        domain="project", tool="project_edit_file", action_kind="update",
        target_id=f"{project}/{file_path}",
        summary=f"Edit {project}/{file_path}",
        params={"project": project, "file_path": file_path,
                "old_string": old_string, "new_string": new_string,
                "replace_all": replace_all},
        changes=[f"Replaced text in {file_path}"])


def _do_project_set_status(params: dict) -> str:
    with _LOCK:
        registry = _load_registry()
        if params["project"] not in registry:
            return f"ERROR: '{params['project']}' is not registered."
        registry[params["project"]]["status"] = params["status"]
        registry[params["project"]]["updated_at"] = _now_iso()
        _save_registry(registry)
    return f"Project '{params['project']}' status set to '{params['status']}'."


policy.register_executor("project", "project_set_status", _do_project_set_status)


@mcp.tool
def project_set_status(project: str, status: str) -> str:
    """WRITE ACTION — update a registered project's status for human
    visibility: one of proposed, assigned, in_progress, review, done.
    Purely informational bookkeeping — it does not itself notify the user
    (finish background jobs with build_report for that)."""
    if status not in _STATUSES:
        return f"ERROR: status must be one of {_STATUSES}."
    if _get_project(project) is None:
        return f"ERROR: '{project}' is not registered."
    return policy.apply_policy(
        domain="project", tool="project_set_status", action_kind="update",
        target_id=f"{project}:status",
        summary=f"Set project '{project}' status to '{status}'",
        params={"project": project, "status": status},
        changes=[f"status -> {status}"])


# ── Sandboxed command execution ──────────────────────────────────────────────
# Delegates to the sandbox service (Docker-socket access, resource-capped
# ephemeral containers, one project directory mounted — nothing else, and
# never the socket itself). This is the one project_* tool that actually
# runs code rather than reading/writing files; containment lives entirely
# in sandbox/, not here — see sandbox/README.md.

def _do_project_run_command(params: dict) -> str:
    try:
        resp = httpx.post(
            f"{config.SANDBOX_URL}/run",
            json={"project": params["project"], "command": params["command"],
                  "timeout_s": params["timeout_s"]},
            headers={"X-Sandbox-Token": config.SANDBOX_TOKEN},
            timeout=params["timeout_s"] + 30.0)
    except httpx.HTTPError as exc:
        return (f"ERROR: could not reach the sandbox service ({exc}) — "
                f"is sandbox/start.sh running?")
    if resp.status_code >= 400:
        return f"ERROR: sandbox service returned {resp.status_code}: {resp.text[:300]}"
    body = resp.json()
    status = "TIMED OUT" if body["timed_out"] else f"exit code {body['exit_code']}"
    return (f"Command finished ({status}) in {body['duration_s']:.1f}s.\n"
            f"--- stdout ---\n{body['stdout']}\n"
            f"--- stderr ---\n{body['stderr']}")


policy.register_executor("project", "project_run_command", _do_project_run_command)


@mcp.tool
def project_run_command(project: str, command: str, timeout_s: int = 120) -> str:
    """WRITE ACTION — run a shell command (test runner, linter, build, git,
    package install) inside an isolated, resource-capped, ephemeral
    container with exactly one registered project's directory mounted
    read-write as its working directory. No other files, no other
    containers, and no Docker access are reachable from inside it. Not for
    long-running daemons/dev servers — the command must run to completion
    and return within timeout_s (max SANDBOX_MAX_TIMEOUT_S, default 600s).
    Executes immediately (notify tier); the user is notified with a
    summary."""
    if _get_project(project) is None:
        return f"ERROR: '{project}' is not a registered project — call project_register first."
    if not command.strip():
        return "ERROR: command is empty."
    if timeout_s <= 0 or timeout_s > config.SANDBOX_MAX_TIMEOUT_S:
        return f"ERROR: timeout_s must be between 1 and {config.SANDBOX_MAX_TIMEOUT_S}."
    return policy.apply_policy(
        domain="project", tool="project_run_command", action_kind="create",
        summary=f"Run command in project '{project}': {command[:100]}",
        params={"project": project, "command": command, "timeout_s": timeout_s},
        changes=[f"Ran: {command[:200]}"])
