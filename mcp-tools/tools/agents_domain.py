"""Agent workforce domain: dispatch background jobs to the local smolagents
team (manager + specialists), track their status/results, and scaffold new
custom agents from a fixed template. Scaffold writes land only in
smolagents/agents/custom/ on the host (via the rw bind mount), so they are
git-visible and revertible. The LLM supplies parameters, never raw Python."""

import json
import re
import string
import time
from datetime import date

from fastmcp import FastMCP

from . import config, jobs_store, policy

mcp = FastMCP(
    "agents",
    instructions=(
        "Agent workforce: list the local smolagents team, dispatch "
        "background jobs to it, check job status/results, and scaffold new "
        "specialist agents."))
required_env = None  # writes to the bind mount, no token

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
_VALID_DOMAINS = ("web", "outline", "inventree", "plane", "n8n", "comfyui",
                  "freescout", "drawio", "triggerdev", "speech", "approvals")
_CUSTOM_DIR = config.SMOLAGENTS_AGENTS_DIR / "custom"

_TEMPLATE = string.Template('''"""$description

Custom agent scaffolded by mcp-tools on $created. Safe to edit by hand.
Picked up by the manager after: docker compose -p smolagents restart
"""

from smolagents import ToolCallingAgent

from ..context import with_baseline
from ..model import get_model
from ..tools import get_domains_tools


def build_${name}_agent() -> ToolCallingAgent:
    tools = get_domains_tools(*$domains)
    return ToolCallingAgent(
        name="$name",
        description="$description",
        model=get_model("$model_role"),
        tools=tools,
        instructions=with_baseline(
            $instructions
        ),
        max_steps=12,
    )
''')


@mcp.tool
def agent_list() -> str:
    """List the smolagents agent team (live roster with descriptions) plus
    any custom agents created via agent_create. Dispatch work to the team
    with agent_dispatch."""
    roster = jobs_store.load_roster()
    if roster:
        lines = [f"- {a.get('name')}: {a.get('description', '').strip()}"
                 for a in roster]
    else:
        lines = ["Built-in agents: manager, web_researcher, coder, ops, "
                 "writer, studio, auditor (live roster unavailable — is "
                 "smolagents running?)"]
    if _CUSTOM_DIR.is_dir():
        customs = sorted(p.stem for p in _CUSTOM_DIR.glob("*.py")
                         if p.stem != "__init__")
        lines.append("Custom agents: " + (", ".join(customs) if customs else "(none)"))
    else:
        lines.append("Custom agents: (none)")
    return "\n".join(lines)


@mcp.tool
def agent_read(name: str) -> str:
    """Return the source code of a custom agent for review."""
    if not _NAME_RE.match(name):
        return "ERROR: invalid agent name."
    path = _CUSTOM_DIR / f"{name}.py"
    if not path.is_file():
        return f"ERROR: no custom agent named '{name}'."
    return path.read_text()


def _do_agent_create(params: dict) -> str:
    _CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    init = _CUSTOM_DIR / "__init__.py"
    if not init.exists():
        init.write_text('"""Custom agents scaffolded via mcp-tools agent_create."""\n')

    path = _CUSTOM_DIR / f"{params['name']}.py"
    if path.exists():
        return (f"ERROR: custom agent '{params['name']}' already exists — "
                f"choose another name (overwriting is not allowed).")

    instructions_literal = repr(params["instructions"] or
                                f"You are the {params['name']} agent. "
                                f"{params['description']}")
    source = _TEMPLATE.substitute(
        name=params["name"],
        description=params["description"].replace('"', "'"),
        domains=repr(list(params["tool_domains"])),
        model_role=params["model_role"],
        instructions=instructions_literal,
        created=date.today().isoformat(),
    )
    path.write_text(source)
    return (f"OBJECT_ID={params['name']}\n"
            f"Created custom agent '{params['name']}' at agents/custom/{params['name']}.py "
            f"with tool domains {params['tool_domains']}. It becomes available "
            f"after the smolagents container restarts: "
            f"docker compose -p smolagents restart")


policy.register_executor("agents", "agent_create", _do_agent_create)


@mcp.tool
def agent_create(name: str, description: str, tool_domains: list[str],
                 model_role: str = "general", instructions: str = "") -> str:
    """WRITE ACTION — scaffolds a new smolagents agent module from a fixed
    template. name: snake_case, 3-31 chars. tool_domains: which MCP tool
    domains it gets (web, outline, inventree, plane, n8n, comfyui, freescout,
    drawio, triggerdev, speech, approvals). model_role: 'general' or
    'coding'. The file is created in the repo working tree for the user to
    review; the user is notified with a summary."""
    if not _NAME_RE.match(name):
        return "ERROR: name must match ^[a-z][a-z0-9_]{2,30}$ (snake_case)."
    if name in ("manager", "web_researcher", "coder", "ops", "writer",
                "studio", "auditor", "custom"):
        return f"ERROR: '{name}' is reserved."
    bad = [d for d in tool_domains if d not in _VALID_DOMAINS]
    if bad:
        return f"ERROR: unknown tool domains {bad}; valid: {list(_VALID_DOMAINS)}."
    if model_role not in ("general", "coding"):
        return "ERROR: model_role must be 'general' or 'coding'."
    if not config.SMOLAGENTS_AGENTS_DIR.is_dir():
        return ("ERROR: the smolagents agents directory is not mounted — "
                "is mcp-tools running with its default volumes?")
    return policy.apply_policy(
        domain="agents", tool="agent_create", action_kind="create",
        summary=f"Scaffold new smolagents agent '{name}' ({model_role}) "
                f"with domains {tool_domains}",
        params={"name": name, "description": description,
                "tool_domains": tool_domains, "model_role": model_role,
                "instructions": instructions},
        changes=[f"New file smolagents/agents/custom/{name}.py"],
        created_object_id_from_result=True)


# ── Background job dispatch ────────────────────────────────────────────────────

_ENUMS = {"quality": ("standard", "high"),
          "audit": ("auto", "always", "never"),
          "urgency": ("low", "normal", "high")}


def _do_agent_dispatch(params: dict) -> str:
    job = jobs_store.create_job(params["brief"], source=params["source"],
                                parent_job_id=params.get("parent_job_id", ""))
    return (f"OBJECT_ID={job['id']}\n"
            f"JOB #{job['id']} queued. It runs in the background (typically "
            f"minutes; long jobs run in segments). Check progress with "
            f"agent_job_status('{job['id']}'); the finished report and any "
            f"needs-attention items appear in the task inbox at "
            f"{config.MCPTOOLS_PUBLIC_URL}/inbox and trigger a notification.")


policy.register_executor("agents", "agent_dispatch", _do_agent_dispatch)


@mcp.tool
def agent_dispatch(objective: str, deliverables: list[str],
                   audience: str = "", constraints: list[str] | None = None,
                   resources: list[str] | None = None,
                   quality: str = "standard", audit: str = "auto",
                   urgency: str = "normal", context: str = "",
                   parent_job_id: str = "") -> str:
    """WRITE ACTION — queue a background task for the local agent team
    (manager + specialists: research, coding, business ops, writing, media
    creation). Returns 'JOB #<id> queued' immediately; the job runs for
    minutes and its report lands in the task inbox. Refine the task with
    the user FIRST — a good brief has a concrete objective, explicit
    deliverables, the audience, constraints, and all needed source material
    in context/resources (the team cannot ask the user questions mid-run).
    audit: 'auto' (manager audits high-stakes outputs), 'always', or
    'never'. quality: 'standard' or 'high'. If the job later reports
    needs_clarification, answer its questions and dispatch a NEW job with
    parent_job_id set to the old id. The user is notified with a summary."""
    if not objective.strip():
        return "ERROR: objective is empty — refine the task with the user first."
    deliverables = [d for d in (deliverables or []) if d.strip()]
    if not deliverables:
        return ("ERROR: at least one explicit deliverable is required "
                "(what artifact should exist when the job is done?).")
    for field, value in (("quality", quality), ("audit", audit),
                         ("urgency", urgency)):
        if value not in _ENUMS[field]:
            return f"ERROR: {field} must be one of {_ENUMS[field]}."
    if not jobs_store.available():
        return ("ERROR: the agent job queue is not mounted — is mcp-tools "
                "running with its default volumes (and smolagents started)?")
    brief = {"objective": objective, "deliverables": deliverables,
             "audience": audience, "constraints": constraints or [],
             "resources": resources or [], "quality": quality,
             "audit": audit, "urgency": urgency, "context": context}
    return policy.apply_policy(
        domain="agents", tool="agent_dispatch", action_kind="create",
        summary=f"Dispatch agent job: {objective[:100]}",
        params={"brief": brief, "source": "mcp",
                "parent_job_id": parent_job_id},
        changes=[f"New background agent job: {objective[:100]}"],
        created_object_id_from_result=True)


def _job_summary_line(job: dict) -> str:
    brief = job.get("brief", {})
    return (f"{job['id']} [{job.get('status')}] "
            f"{brief.get('objective', '')[:80]} "
            f"(created {job.get('created_at')}, segments {job.get('segments', 1)})")


@mcp.tool
def agent_job_status(job_id: str) -> str:
    """Status of a background agent job: queued, running (with liveness),
    or its outcome. If the status is needs_clarification, relay the
    questions to the user and dispatch a new job with parent_job_id."""
    job = jobs_store.get_job(job_id)
    if job is None:
        return f"ERROR: no job named '{job_id}'."
    lines = [_job_summary_line(job)]
    report = job.get("report") or {}
    if job.get("status") == "running" and job.get("heartbeat_ts"):
        lines.append(f"Last activity {int(time.time() - job['heartbeat_ts'])}s ago.")
    if report.get("summary"):
        lines.append(f"Summary: {report['summary'][:500]}")
    if report.get("questions"):
        lines.append("Questions for the user: " + "; ".join(report["questions"]))
    if job.get("error"):
        lines.append(f"Error: {job['error']}")
    lines.append(f"Full report: agent_job_result('{job_id}') · inbox: "
                 f"{config.MCPTOOLS_PUBLIC_URL}/inbox")
    return "\n".join(lines)


@mcp.tool
def agent_job_result(job_id: str) -> str:
    """Full report of a finished background agent job: summary,
    deliverables with locations, audit record, attention items."""
    job = jobs_store.get_job(job_id)
    if job is None:
        return f"ERROR: no job named '{job_id}'."
    if job.get("status") in ("queued", "running"):
        return (f"Job {job_id} is still {job['status']} — check back with "
                f"agent_job_status('{job_id}').")
    report = job.get("report") or {"summary": job.get("error", "(no report)")}
    return json.dumps({"id": job["id"], "status": job["status"],
                       "segments": job.get("segments", 1),
                       "report": report, "error": job.get("error")},
                      indent=1, ensure_ascii=False)


@mcp.tool
def agent_jobs_list(status: str = "") -> str:
    """Recent background agent jobs, newest first. status filters to one of:
    queued, running, completed, needs_clarification, needs_attention,
    failed, cancelled. Empty lists everything."""
    if not jobs_store.available():
        return "ERROR: the agent job queue is not mounted."
    jobs = jobs_store.list_jobs(status=status)
    if not jobs:
        return "No jobs" + (f" with status '{status}'." if status else " yet.")
    return "\n".join(_job_summary_line(j) for j in jobs)
