"""Business operations agent: works the stack's services through the shared
MCP tool server — wiki, inventory, projects, automation, helpdesk, jobs,
image generation, and diagrams. Only domains that are mounted on mcp-tools
(token configured) contribute tools."""

from smolagents import ToolCallingAgent

from . import config
from .context import with_baseline
from .model import get_model
from .tools import get_domains_tools

OPS_DOMAINS = ("outline", "inventree", "plane", "n8n", "freescout",
               "triggerdev", "comfyui", "drawio", "approvals")


def build_ops_agent() -> ToolCallingAgent:
    tools = get_domains_tools(*OPS_DOMAINS)
    return ToolCallingAgent(
        tools=tools,
        model=get_model("general"),
        name="ops",
        description=(
            "Operates the business stack: searches and writes wiki docs "
            "(Outline), queries inventory (InvenTree), manages project issues "
            "(Plane), runs automations (n8n, trigger.dev), handles helpdesk "
            "conversations (FreeScout), and generates images and diagrams. "
            "Give it a concrete operational task."
        ),
        instructions=with_baseline(
            "Check live data with the read tools before answering. Use write "
            "tools only when the task explicitly asks for a change, and "
            "describe what you changed. Some writes are held for human "
            "approval — when a tool answers PENDING APPROVAL, report the "
            "pending action id and approval link to the user instead of "
            "retrying."
        ),
        max_steps=config.MAX_STEPS,
    )
