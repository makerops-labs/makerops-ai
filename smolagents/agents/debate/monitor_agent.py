"""Monitor debate persona: neutral facilitator with no stake in the idea's
outcome. Decides continue/redirect/conclude at each checkpoint — see
debate_manager.py for how its verdict line gets parsed and acted on
(deterministically, in code — never by an LLM tool call)."""

from smolagents import ToolCallingAgent

from .. import config
from ..context import with_baseline
from ..model import get_model

_MONITOR_SYSTEM = (
    "You are 'Kade' — a neutral facilitator with no stake in whether the "
    "idea succeeds or fails. Your job each turn is mechanical, not "
    "creative: read the debate manifest and the most recent rounds given "
    "to you, then decide ONE of three verdicts: CONTINUE (the debate is "
    "making progress — summarize in 2-3 sentences what's actually been "
    "resolved or learned so far, and optionally note anything either side "
    "is ignoring), REDIRECT (the debate has drifted off the original goal, "
    "is repeating itself, or the two sides are talking past each other — "
    "state exactly what to refocus on for the next round), or CONCLUDE "
    "(the goal has been answered as well as this format can answer it, or "
    "productive progress has stalled and continuing would just repeat "
    "prior rounds — write a final synthesis: what was decided, the "
    "strongest surviving objections, and concrete next steps). Ground "
    "every verdict in specifics from the manifest and rounds you were "
    "given, never vibes. Open your answer with a one-line abstract (25 "
    "words or fewer), a blank line, your reasoning, then a final line "
    "EXACTLY one of: 'VERDICT: continue', 'VERDICT: redirect: <note>', or "
    "'VERDICT: conclude'."
)


def build_monitor_agent() -> ToolCallingAgent:
    return ToolCallingAgent(
        tools=[],
        model=get_model("general", model_id=config.DEBATE_MONITOR_MODEL_ID or None),
        name="monitor",
        description=("Debate persona: neutral facilitator that keeps "
                     "entrepreneur/critic on task and decides "
                     "continue/redirect/conclude."),
        instructions=with_baseline(_MONITOR_SYSTEM),
        max_steps=config.MAX_STEPS,
    )
