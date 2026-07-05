"""Web research agent: searches the web and reads pages.

Preferred tools come from the mcp-tools web domain (SearXNG-backed search +
content-type-aware fetch, matching Open WebUI's search backend). If the MCP
server is unreachable it falls back to the stock DuckDuckGo tools.
"""

from smolagents import ToolCallingAgent, VisitWebpageTool, WebSearchTool

from . import config
from .context import with_baseline
from .model import get_model
from .tools import get_domain_tools


def build_web_agent() -> ToolCallingAgent:
    tools = get_domain_tools("web") or [WebSearchTool(), VisitWebpageTool()]
    return ToolCallingAgent(
        tools=tools,
        model=get_model("general"),
        name="web_researcher",
        description=(
            "Searches the web and reads pages. Give it a research question "
            "and it returns a sourced summary of what it found."
        ),
        instructions=with_baseline(None),
        max_steps=config.MAX_STEPS,
    )
