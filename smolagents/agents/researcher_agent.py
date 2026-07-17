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
from .citations import check_citations_fetched
from .context import with_baseline
from .model import get_model
from .thoughts import THINK_FIRST
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
    "**Patterns & leads:** <optional, at most 3 bullets: broader patterns "
    "across the findings, non-obvious connections to adjacent domains, or "
    "follow-up questions worth asking — each explicitly marked "
    "(interpretation) where it goes beyond the sourced findings>\n"
    "**Confidence & gaps:** <one short paragraph: how well-sourced this "
    "is, what conflicts you found, what you could NOT establish>\n"
    "\n"
    "Method: never answer from memory alone when your web tools are up — "
    "run at least one search per distinct question, open the most "
    "authoritative results (official docs, primary sources, established "
    "publications) rather than trusting search snippets, and prefer two "
    "independent sources for any load-bearing claim. Research is "
    "exploration into the unknown: for a broad question, you have a deep "
    "step budget — use it. Run multiple search rounds, follow promising "
    "leads into adjacent fields and related work, chase the references a "
    "good source cites, and only then synthesize; do not stop at the "
    "first page of results because it 'answers' the question. Attribute "
    "every finding to the URL you actually read. If sources conflict, "
    "report the conflict as its own finding instead of silently picking a "
    "side. If the tools are down or the question is unanswerable from "
    "public sources, say exactly that in the brief — never fabricate a "
    "source or a number. CITATIONS ARE ENFORCED BY CODE, not trust: a "
    "deterministic check rejects any brief citing a URL you did not "
    "successfully open with fetch_url during this run — search snippets "
    "are not enough, and links written from memory never pass. So fetch "
    "every page you intend to cite before writing the brief; if a page "
    "will not load or does not actually support the claim, cite a source "
    "that does or move the claim to Confidence & gaps as unverified. "
    "Depth belongs in your exploration, not your "
    "output: keep the whole brief under ~500 words; you are feeding "
    "someone else's bounded context, not writing a survey paper. The "
    "entire answer must be the plain-markdown brief above — no code, "
    "JSON, tool syntax, or commentary about your process outside the "
    "brief. Your intuitive leads are also search leads: when a hunch from "
    "your thinking is checkable, spend a search round on it before writing "
    "the brief.\n"
    "\n"
) + THINK_FIRST


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
        max_steps=config.RESEARCHER_MAX_STEPS,
        # Reject briefs citing URLs the agent never successfully fetched
        # this run — dead links and invented sources both fail closed
        # (bad links + fabricated citations reached the user, 2026-07-16).
        final_answer_checks=[check_citations_fetched],
    )
