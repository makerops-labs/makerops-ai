"""Debate turn orchestrator: runs exactly ONE turn of a multi-round,
file-relayed debate between three fixed personas (entrepreneur, critic,
monitor). A separate, dedicated CodeAgent from the general manager.py —
its own instructions avoid fighting that manager's VALIDATE/PLAN/BATCH-BY-
MODEL/AUDIT/DELIVER procedure (which actively conflicts with "delegate this
turn to exactly one persona and relay verbatim"), and its own small tool/
team list avoids handing a local model the full specialist roster for a
task that only ever needs one of three fixed names.

Built once at worker startup (agents/jobs.py) alongside the general
manager and reused across turns with reset=True, same as that manager.
Turn advancement itself — deciding whether to queue another turn and who
speaks next — is deterministic Python in jobs.py's _advance_debate, never
an LLM tool call (see that module's docstring for why)."""

from smolagents import CodeAgent, tool

from . import config
from .context import with_baseline
from .debate import build_critic_agent, build_entrepreneur_agent, build_monitor_agent
from .model import get_model

_DEBATE_PROCEDURE = """You orchestrate ONE turn of a structured, file-relayed
debate between three personas: entrepreneur, critic, and monitor. You are
invoked once per turn and do not see the whole debate history directly — the
task text below already contains the compact manifest of prior rounds plus
the full text of the most recent round(s). Follow this procedure:

1. The task text names which ONE persona ('entrepreneur', 'critic', or
   'monitor') owns this turn, and gives you the debate goal, mode,
   constraints, manifest, and recent round text to pass along.
2. If the manifest's short descriptions suggest an EARLIER round (not
   already given to you in full) is directly relevant to this turn, you may
   read it with pathlib — Path(<its 'path' from the manifest>), resolved
   under the debate directory named in the task text. Do not read every
   round; that defeats the point of the manifest.
3. Call the named persona sub-agent EXACTLY ONCE with a task string
   containing everything relevant (goal, mode, constraints, manifest,
   recent rounds, any excerpt from step 2, any monitor redirect note). Do
   not write the persona's argument yourself and do not call any other
   sub-agent.
4. Relay the persona's answer back VERBATIM via build_debate_report — never
   summarize, edit, correct, or add commentary. The persona's answer must
   open with a one-line abstract (25 words or fewer), a blank line, then
   its full argument; put the abstract in build_debate_report's abstract
   parameter and the whole answer in full_text.
5. Only for the 'monitor' persona: its answer must end with a line exactly
   'VERDICT: continue', 'VERDICT: redirect: <note>', or 'VERDICT: conclude'.
   Copy the verdict word ('continue', 'redirect', or 'conclude') into
   build_debate_report's verdict parameter and any redirect note into
   redirect_note. For entrepreneur/critic turns leave verdict as the
   default 'continue'.
6. Always finish with build_debate_report(...) then final_answer(report) in
   the SAME code block. If the persona errors or answers something
   unusable, set status to 'needs_attention' and explain in full_text —
   never invent an answer on its behalf."""


@tool
def build_debate_report(status: str, full_text: str, abstract: str,
                        verdict: str = "continue", redirect_note: str = "") -> dict:
    """Build the debate turn's report — call this instead of hand-writing a
    dict literal, then pass the result straight to final_answer().

    Args:
        status: 'completed' if the persona produced a usable answer,
            'needs_attention' otherwise.
        full_text: The persona's complete verbatim answer (abstract + blank
            line + argument) — never summarized or edited.
        abstract: Its one-line (25 words or fewer) abstract, copied verbatim.
        verdict: 'continue', 'redirect', or 'conclude' — only meaningful for
            the monitor persona; leave 'continue' for entrepreneur/critic.
        redirect_note: The monitor's note on what to refocus on, only when
            verdict is 'redirect'.
    """
    return {"status": status, "full_text": full_text, "abstract": abstract,
            "verdict": verdict, "redirect_note": redirect_note}


def extract_debate_report(answer) -> dict | None:
    """First dict in the answer with status+full_text keys — mirrors
    manager.py's extract_report, kept separate since a debate turn's report
    shape (full_text/abstract/verdict) differs from the general job report
    (summary/deliverables/...) and the two should never be cross-parsed."""
    import ast
    import json
    import re

    if isinstance(answer, dict):
        return answer if "status" in answer and "full_text" in answer else None
    text = answer if isinstance(answer, str) else str(answer)
    decoder = json.JSONDecoder()
    for start in (m.start() for m in re.finditer(r"\{", text)):
        candidate = None
        try:
            candidate, _ = decoder.raw_decode(text[start:])
        except ValueError:
            try:
                candidate = ast.literal_eval(text[start:])
            except (ValueError, SyntaxError, MemoryError, RecursionError):
                continue
        if (isinstance(candidate, dict) and "status" in candidate
                and "full_text" in candidate):
            return candidate
    return None


def _debate_report_shape_check(final_answer, memory, agent=None) -> bool:
    """Insurance for small models, mirrors manager.py's _report_shape_check."""
    if extract_debate_report(final_answer) is not None:
        return True
    raise Exception(
        "Final answer must be the report dict with at least the keys "
        '"status" and "full_text" — call build_debate_report(...) and '
        "final_answer(report). Do not hand-write the report as a dict "
        "literal; that is where syntax mistakes happen. Do not include any "
        "other text.")


def build_debate_manager_agent() -> CodeAgent:
    return CodeAgent(
        tools=[build_debate_report],
        model=get_model("general"),
        managed_agents=[build_entrepreneur_agent(), build_critic_agent(),
                        build_monitor_agent()],
        additional_authorized_imports=["pathlib"],
        instructions=with_baseline(_DEBATE_PROCEDURE),
        planning_interval=config.PLANNING_INTERVAL,
        final_answer_checks=[_debate_report_shape_check],
        max_steps=config.DEBATE_MANAGER_MAX_STEPS,
    )
