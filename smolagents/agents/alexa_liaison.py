"""Alexa liaison: owns one turn of a voice conversation coming through the
alexa-bridge service. A separate, dedicated CodeAgent from the general
manager.py — its own instructions target spoken, turn-by-turn dialogue
(answer or delegate ONCE, then stop and wait for the next thing the user
says) rather than the manager's multi-phase VALIDATE/PLAN/BATCH/AUDIT/
DELIVER procedure.

Built once at worker startup (agents/jobs.py) alongside the manager, and
reused across turns with reset=True — prior turns are
folded into the task text by jobs.py's _format_liaison_task, not carried in
the agent's own live memory, since a voice session must survive the bridge
being a stateless HTTP handler invoked fresh per Alexa turn.

Deterministic voice commands ("end session", "confirm/deny a pending
approval", "check status", "start over") are intercepted by the alexa-bridge
itself and never reach this agent — see its module docs. If a turn's task
text looks like one of those, something upstream was misrouted; the
procedure below tells the model to say so rather than guess.

Delegation is capped at ONE sub-agent (or one agent_dispatch background job)
per turn — smolagents' managed_agents already makes a single delegation
synchronous/blocking (the sub-agent's full answer lands back in this
agent's own reasoning before it continues), which is the return-of-control
primitive the alexa-bridge relies on; capping it at one keeps a turn
inside Alexa's ~8s response budget."""

from smolagents import CodeAgent, tool

from . import config
from .context import with_baseline
from .model import get_model
from .ops_agent import build_ops_agent
from .tools import get_domains_tools
from .web_agent import build_web_agent

_LIAISON_PROCEDURE = """You are the spoken-voice liaison for one turn of a
conversation coming from an Amazon Alexa device. You are invoked once per
turn and do not keep your own memory between turns — the task text below
already contains a bounded window of the recent conversation (oldest first)
plus the newest thing the user just said. Follow this procedure:

1. Read the recent-turns window and the new utterance together — the
   conversation may already be mid-way through disambiguating something.
2. If the new utterance is genuinely ambiguous (three reasonable people
   would do three different things with it), ask exactly ONE short,
   concrete clarifying question and stop — do not guess and do not ask more
   than one question in the same turn. Use build_liaison_turn(status=
   "needs_clarification", ...).
3. If you can answer directly from what you already know (general
   knowledge, or something already established earlier in this
   conversation), just answer — do not delegate for something you can
   already say correctly and concisely.
4. If the request needs a live lookup or a small, fast action, delegate to
   EXACTLY ONE of your two managed agents (web_researcher or ops) with a
   clear, self-contained task string, then relay its answer in your own
   spoken words (concise — do not read its full answer verbatim, this is
   voice, not text). Never call more than one managed agent in the same
   turn, and never call the same one twice.
5. If the request is a substantial task (something that would take minutes,
   not seconds — a multi-step change, a long-running lookup, anything the
   ops/web agents are not scoped for) call agent_dispatch yourself with a
   proper brief (objective, deliverables, any context this conversation
   already established), tell the user briefly you're on it, and use
   build_liaison_turn(status="deferred", job_id=<the id agent_dispatch
   returned>, ...). Do not also try to answer the substance yourself in the
   same turn — dispatch and hand back.
6. If a tool or managed agent reports 'PENDING APPROVAL #id', copy that id
   VERBATIM into build_liaison_turn's pending_action_id parameter — do not
   summarize or paraphrase it away, the user's next 'confirm' or 'deny'
   depends on that exact id surviving into your report untouched. Tell the
   user in your speech that the action needs their approval.
7. The phrases 'end session', 'goodbye', 'confirm', 'approve', 'deny',
   'reject', 'what's the status', 'start over' are handled by the bridge
   BEFORE it ever calls you — you will never see them as your new
   utterance. If the task text below looks like one of those anyway, say
   "Sorry, I didn't catch that — can you say that again?" via
   build_liaison_turn(status="needs_clarification", ...) rather than
   guessing what was meant.
8. Speech is SPOKEN, not read: 1-3 short sentences, no markdown, no bullet
   lists, no code, no URLs read aloud character-by-character. If something
   genuinely needs a list, summarize the count and offer to say more
   ("there are 4 open items, the first is...").
9. Always finish by calling build_liaison_turn(...) then final_answer(...)
   with its result, in the SAME code block — never hand-write the report
   dict, never leave speech empty, never call final_answer with a bare
   string."""


@tool
def build_liaison_turn(status: str, speech: str, reprompt: str = "",
                       job_id: str = "", pending_action_id: str = "",
                       delegated_to: str = "") -> dict:
    """Build this turn's report — call this instead of hand-writing a dict
    literal, then pass the result straight to final_answer().

    Args:
        status: One of completed (answered, nothing pending), needs_clarification
            (you asked a follow-up question), deferred (you called
            agent_dispatch and a background job is now running), or
            needs_attention (something went wrong — a tool errored, a
            managed agent's answer was unusable).
        speech: What Alexa should say out loud — short, spoken sentences,
            never markdown/lists/code/URLs.
        reprompt: What Alexa should say if the user doesn't respond in
            time — usually a short restatement of speech's question.
            Required (non-empty) when status is needs_clarification; may be
            left empty otherwise.
        job_id: The agent_dispatch job id, only when status is deferred.
        pending_action_id: The exact id from a 'PENDING APPROVAL #id'
            string, copied verbatim, only when a tool or managed agent hit
            the write-approval gate this turn.
        delegated_to: Name of the managed agent you called this turn
            (web_researcher or ops), if any; leave empty if you answered
            directly or used agent_dispatch instead.
    """
    return {"status": status, "speech": speech, "reprompt": reprompt,
            "job_id": job_id, "pending_action_id": pending_action_id,
            "delegated_to": delegated_to}


def extract_liaison_turn(answer) -> dict | None:
    """First dict in the answer with status+speech keys — mirrors
    manager.py's extract_report, kept separate since a liaison turn's
    report shape differs and the two should never be cross-parsed."""
    import ast
    import json
    import re

    if isinstance(answer, dict):
        return answer if "status" in answer and "speech" in answer else None
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
                and "speech" in candidate):
            return candidate
    return None


def _liaison_report_shape_check(final_answer, memory, agent=None) -> bool:
    """Insurance for small models, mirrors manager.py's _report_shape_check."""
    if extract_liaison_turn(final_answer) is not None:
        return True
    raise Exception(
        "Final answer must be the report dict with at least the keys "
        '"status" and "speech" — call build_liaison_turn(...) and '
        "final_answer(report). Do not hand-write the report as a dict "
        "literal; that is where syntax mistakes happen. Do not include any "
        "other text.")


# Same access agent_dispatch/agent_job_status gives any outside client
# (Open WebUI, the deterministic status trigger phrase) — safe here even
# though manager.py deliberately withholds these tools from itself (a job's
# own manager queueing further jobs would loop the worker), because a
# liaison TURN and a manager JOB are different job "kinds" in the same
# queue; the liaison dispatching a manager job is not self-referential.
_LIAISON_AGENT_TOOLS = ("agent_dispatch", "agent_job_status", "tools_help")


def build_alexa_liaison_agent() -> CodeAgent:
    return CodeAgent(
        tools=[build_liaison_turn] +
              [t for t in get_domains_tools("agents") if t.name in _LIAISON_AGENT_TOOLS],
        model=get_model("general"),
        managed_agents=[build_web_agent(), build_ops_agent()],
        instructions=with_baseline(_LIAISON_PROCEDURE),
        planning_interval=config.PLANNING_INTERVAL,
        final_answer_checks=[_liaison_report_shape_check],
        max_steps=config.LIAISON_MAX_STEPS,
    )
