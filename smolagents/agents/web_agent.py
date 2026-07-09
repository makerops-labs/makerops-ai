"""Web research agent: searches the web and reads pages.

Preferred tools come from the mcp-tools web domain (SearXNG-backed search +
content-type-aware fetch, matching Open WebUI's search backend), plus the
x domain (X/Twitter recent search) when a paid API token is configured —
SearXNG has no Twitter/X engine, and this is the only source that reaches
it. If the MCP server is unreachable it falls back to the stock DuckDuckGo
tools (x is never part of that fallback — no free equivalent exists).
"""

from smolagents import ToolCallingAgent, VisitWebpageTool, WebSearchTool

from . import config
from .context import with_baseline
from .model import get_model
from .tools import get_domains_tools


def build_web_agent() -> ToolCallingAgent:
    tools = (get_domains_tools("web", "x")
            or [WebSearchTool(), VisitWebpageTool()])
    return ToolCallingAgent(
        tools=tools,
        model=get_model("general"),
        name="web_researcher",
        description=(
            "Searches the web and reads pages. Give it a research question "
            "and it returns a sourced summary of what it found."
        ),
        instructions=with_baseline(
            "x_search_recent (X/Twitter, last 7 days only) COSTS REAL "
            "MONEY per call (~$0.005-0.01/read, no free tier) — use it "
            "only when specifically asked to check X/Twitter, e.g. during "
            "the self-improvement research sweep, never for routine "
            "research the free engines (web_search covers arxiv, github, "
            "scholar, stackoverflow, and general web) can answer. Before "
            "calling it, check the Research Query Log (Outline, AI "
            "collection) for the same or a similar query already run "
            "against X within the last 7 days — that call would just "
            "re-fetch data already paid for; vary the query or skip it "
            "instead. When you do call it, always request the max "
            "(100 results) since cost is per-read regardless of call "
            "count."
        ),
        max_steps=config.MAX_STEPS,
    )
