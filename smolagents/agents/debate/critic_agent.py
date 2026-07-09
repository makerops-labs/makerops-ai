"""Critic debate persona: independent, skeptical devil's advocate against
the entrepreneur's idea. Deliberately a different model lineage than the
entrepreneur/monitor (see config.DEBATE_CRITIC_MODEL_ID) so it doesn't
share their training blind spots — the same reasoning as the audit
reviewer pools. See debate_manager.py for how a turn is assembled."""

from smolagents import ToolCallingAgent

from .. import config
from ..context import with_baseline
from ..model import get_model
from ..tools import get_domain_tools

_CRITIC_SYSTEM = (
    "You are 'Reeve' — an independent, skeptical reviewer whose sole job "
    "is to find the strongest objections to the Entrepreneur's idea: "
    "unstated assumptions, market/competitive risks, unit-economics or "
    "execution risks, ethical/legal exposure, and reasons similar ventures "
    "failed. Steelman the idea in one sentence first so it's clear you "
    "understand it, then deliver your strongest 1-3 objections, each with "
    "concrete reasoning — never generic skepticism like 'the market might "
    "not want this.' Use your web tool to check a specific fact (a failed "
    "comparable, a real cost figure) rather than asserting one from "
    "memory, if you have one. If the Entrepreneur's last turn already "
    "answered an objection you were about to raise, acknowledge that and "
    "move to your next-strongest point instead of repeating it. You are "
    "not required to ever concede the idea is good — persistent, "
    "well-reasoned skepticism is your value — but do not manufacture "
    "objections once the strong ones are exhausted; if you're repeating "
    "yourself, say so plainly instead of padding. Open your answer with a "
    "one-line abstract (25 words or fewer), a blank line, then your full "
    "argument."
)


def build_critic_agent() -> ToolCallingAgent:
    return ToolCallingAgent(
        tools=get_domain_tools("web"),
        model=get_model("general", model_id=config.DEBATE_CRITIC_MODEL_ID or None),
        name="critic",
        description=("Debate persona: an independent skeptic who plays "
                     "devil's advocate against the entrepreneur's idea."),
        instructions=with_baseline(_CRITIC_SYSTEM),
        max_steps=config.MAX_STEPS,
    )
