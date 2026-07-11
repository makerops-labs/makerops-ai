"""Dedicated researcher agent: structured, multi-source research briefs.

Distinct from web_researcher (a quick sourced-lookup agent): the researcher
follows a fixed research procedure and always returns the same brief shape,
so its output can be consumed sight-unseen by whoever delegated — the
general manager, the debate orchestrator (a persona's turn can be grounded
with a brief before the persona argues), or a human reading it directly.
Runs on the resident general model by default so delegating to it costs no
VRAM swap (override with SMOLAGENTS_RESEARCHER_MODEL_ID).
"""

from smolagents import ToolCallingAgent, VisitWebpageTool, WebSearchTool

from . import config
from .context import with_baseline
from .model import get_model
from .tools import get_domains_tools

_RESEARCHER_SYSTEM = (
    "You are the stack's dedicated researcher. You are handed a research "
    "question (or a short list of them) and return a RESEARCH BRIEF that "
    "someone who cannot see your work will rely on verbatim — an agent "
    "mid-task or the human owner — so its shape is fixed:\n"
    "\n"
    "## Research brief: <the question, restated in one line>\n"
    "1. <finding, 1-3 sentences> — <source URL>\n"
    "2. <finding> — <source URL>\n"
    "...\n"
    "**Confidence & gaps:** <one short paragraph: how well-sourced this "
    "is, what conflicts you found, what you could NOT establish>\n"
    "\n"
    "Method: never answer from memory alone when your web tools are up — "
    "run at least one search per distinct question, open the most "
    "authoritative results (official docs, primary sources, established "
    "publications) rather than trusting search snippets, and prefer two "
    "independent sources for any load-bearing claim. Attribute every "
    "finding to the URL you actually read. If sources conflict, report "
    "the conflict as its own finding instead of silently picking a side. "
    "If the tools are down or the question is unanswerable from public "
    "sources, say exactly that in the brief — never fabricate a source or "
    "a number. Keep the whole brief under ~500 words; you are feeding "
    "someone else's bounded context, not writing a survey paper. The "
    "entire answer must be the plain-markdown brief above — no code, "
    "JSON, tool syntax, or commentary about your process outside the "
    "brief."
)


def build_researcher_agent() -> ToolCallingAgent:
    tools = get_domains_tools("web") or [WebSearchTool(), VisitWebpageTool()]
    return ToolCallingAgent(
        tools=tools,
        model=get_model("general", model_id=config.RESEARCHER_MODEL_ID or None),
        name="researcher",
        description=(
            "Dedicated researcher: give it one or more specific research "
            "questions and it returns a structured research brief — "
            "numbered findings each attributed to a source URL, plus a "
            "confidence-and-gaps note. Use it when a decision or argument "
            "needs grounded facts; use web_researcher instead for a quick "
            "one-off lookup."
        ),
        instructions=with_baseline(_RESEARCHER_SYSTEM),
        max_steps=config.MAX_STEPS,
    )
