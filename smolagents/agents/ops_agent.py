"""Business operations agent: works the stack's services through the shared
MCP tool server — wiki, inventory, projects, automation, helpdesk, and jobs.
Media creation (images, diagrams, audio) belongs to the studio agent. Only
domains that are mounted on mcp-tools (token configured) contribute tools."""

from . import config
from .context import with_baseline
from .model import get_model
from .tool_filter import ToolFilteringAgent, ToolSelector
from .tools import get_domain_tools, get_domains_tools

OPS_DOMAINS = ("outline", "inventree", "plane", "n8n", "freescout",
               "triggerdev", "approvals")
# Never filtered out: approval status must always be reportable.
OPS_ALWAYS_DOMAINS = ("approvals",)


def _ops_selector(tools: list) -> ToolSelector | None:
    """Per-task tool filter (SMOLAGENTS_OPS_TOOL_FILTER), or None when off.
    Shared helpers that every domain endpoint carries (tools_help,
    current_datetime) and the always-on domains stay visible."""
    mode = config.OPS_TOOL_FILTER
    if mode == "off":
        return None
    if mode not in ("domain", "topk"):
        print(f"[ops] unknown SMOLAGENTS_OPS_TOOL_FILTER={mode!r}; filtering off.")
        return None
    per_domain = {d: get_domain_tools(d) for d in OPS_DOMAINS if d not in OPS_ALWAYS_DOMAINS}
    counts: dict[str, int] = {}
    for d_tools in per_domain.values():
        for t in d_tools:
            counts[t.name] = counts.get(t.name, 0) + 1
    shared = {n for n, c in counts.items() if c > 1}
    always_names = shared | {t.name for d in OPS_ALWAYS_DOMAINS for t in get_domain_tools(d)}
    always = [t for t in tools if t.name in always_names or t.name == "current_datetime"]
    always_set = {t.name for t in always}
    per_domain = {d: [t for t in ts if t.name not in always_set] for d, ts in per_domain.items()}
    return ToolSelector(per_domain, always=always, mode=mode, k=config.OPS_TOOL_FILTER_K)


def build_ops_agent() -> ToolFilteringAgent:
    tools = get_domains_tools(*OPS_DOMAINS)
    return ToolFilteringAgent(
        selector=_ops_selector(tools) if tools else None,
        tools=tools,
        model=get_model("general"),
        name="ops",
        description=(
            "Operates the business stack: searches and writes wiki docs "
            "(Outline), queries inventory (InvenTree), manages project issues "
            "(Plane), runs automations (n8n, trigger.dev), and handles "
            "helpdesk conversations (FreeScout). Give it a concrete "
            "operational task. Media creation belongs to studio."
        ),
        instructions=with_baseline(
            "Check live data with the read tools before answering. Use write "
            "tools only when the task explicitly asks for a change, and "
            "describe what you changed. Some writes are held for human "
            "approval — when a tool answers PENDING APPROVAL, report the "
            "pending action id and approval link to the user instead of "
            "retrying. If you lack a tool for something, say exactly that "
            "— never invent a permissions or configuration excuse."
        ),
        max_steps=config.MAX_STEPS,
    )
