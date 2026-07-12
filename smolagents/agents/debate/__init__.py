"""The three fixed debate personas — entrepreneur, critic, monitor. Run
DIRECTLY by the job worker, one persona per debate-turn job (see jobs.py's
_run_debate_turn) — never registered on the general manager, and no
orchestrator LLM sits between the worker and a persona.

A persona can run in either of two modes (config.DEBATE_RAW_PERSONAS):
as a ToolCallingAgent (web research mid-turn, tool-called final answer),
or as a RAW completion — one plain generation against the persona's system
prompt, the same proven pattern the audit reviewer pool uses. Raw mode
exists because some models (observed live: gpt-oss) write excellent
arguments but persistently fumble the tool-calling protocol — plain-text
answers, typed-out pseudo final_answer() calls — burning their whole step
budget on submission mechanics. PERSONA_SYSTEM_PROMPTS feeds raw mode."""

from .critic_agent import _CRITIC_SYSTEM, build_critic_agent
from .entrepreneur_agent import _ENTREPRENEUR_SYSTEM, build_entrepreneur_agent
from .monitor_agent import _MONITOR_SYSTEM, build_monitor_agent

PERSONA_SYSTEM_PROMPTS = {
    "entrepreneur": _ENTREPRENEUR_SYSTEM,
    "critic": _CRITIC_SYSTEM,
    "monitor": _MONITOR_SYSTEM,
}

__all__ = ["build_entrepreneur_agent", "build_critic_agent",
           "build_monitor_agent", "PERSONA_SYSTEM_PROMPTS"]
