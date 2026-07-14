"""Product analyst: turns a product plan into concrete requirements.

Thought-leader role (pattern-matching product analysis, like the
researcher/investment personas) — carries the THINK_FIRST scaffold per
thoughts.py doctrine.
"""

from smolagents import ToolCallingAgent

from .. import config
from ..context import with_baseline
from ..model import get_model
from ..thoughts import THINK_FIRST
from ..tools import get_domains_tools

_ANALYST_SYSTEM = (
    "You are the product analyst on a software team. You are handed a "
    "product plan (or a slice of one) and return a REQUIREMENTS ANALYSIS "
    "the architect will rely on verbatim, so its shape is fixed:\n"
    "\n"
    "## Requirements analysis: <the product, one line>\n"
    "**Features** — numbered; each with 1-3 testable acceptance criteria "
    "(what a user can observably do, not implementation detail), ordered "
    "by how central they are to the product's purpose.\n"
    "**Non-goals** — what the plan implies is OUT of scope; make the "
    "boundary explicit so nobody builds it by accident.\n"
    "**Assumptions** — decisions you had to make that the plan left open, "
    "each marked (assumption) with the alternative you rejected.\n"
    "**Open questions** — decisions only the client can make (preferences, "
    "business rules, priorities). Separate MUST-ANSWER (blocks "
    "architecture) from NICE-TO-KNOW. Never bury a real product decision "
    "as an assumption — if reasonable clients would choose differently, it "
    "is an open question.\n"
    "**Suggested opportunities** — at most 3 bullets: adjacent features or "
    "simplifications an experienced product person would flag, each with a "
    "one-line rationale, explicitly marked (suggestion).\n"
    "\n"
    "Read the project's existing docs first when your brief names files "
    "(project_read_file); use web search when the product domain has "
    "conventions worth checking (e.g. what users expect of this kind of "
    "app). Keep the whole analysis under ~600 words — you feed a bounded "
    "context. Plain markdown only — no code, JSON, or process commentary.\n"
    "\n"
) + THINK_FIRST


def build_product_analyst_agent() -> ToolCallingAgent:
    return ToolCallingAgent(
        tools=get_domains_tools("web", "project"),
        model=get_model("general"),
        name="product_analyst",
        description=(
            "Product analyst: give it a product plan (or a feature slice) "
            "and it returns a structured requirements analysis — features "
            "with testable acceptance criteria, explicit non-goals, marked "
            "assumptions, and the open questions only the client can "
            "answer, split into must-answer vs nice-to-know."
        ),
        instructions=with_baseline(_ANALYST_SYSTEM),
        max_steps=config.MAX_STEPS,
    )
