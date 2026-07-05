"""Agent scaffolding: lets an LLM create new smolagents agents from a fixed
template. Writes land only in smolagents/agents/custom/ on the host (via
the rw bind mount), so they are git-visible and revertible. The LLM supplies
parameters, never raw Python."""

import re
import string
from datetime import date

from fastmcp import FastMCP

from . import config, policy

mcp = FastMCP(
    "agents",
    instructions="Scaffold, list, and read custom smolagents specialist agents.")
required_env = None  # writes to the bind mount, no token

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
_VALID_DOMAINS = ("web", "outline", "inventree", "plane", "n8n", "comfyui",
                  "freescout", "drawio", "triggerdev")
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
    """List the smolagents agents: built-ins and custom agents created via
    agent_create."""
    lines = ["Built-in agents: manager, web_researcher, coder, ops"]
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
    drawio, triggerdev). model_role: 'general' or 'coding'. The file is
    created in the repo working tree for the user to review; the user is
    notified with a summary."""
    if not _NAME_RE.match(name):
        return "ERROR: name must match ^[a-z][a-z0-9_]{2,30}$ (snake_case)."
    if name in ("manager", "web_researcher", "coder", "ops", "custom"):
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
