"""Maintainer agent: the self-improvement loop. Reviews recent job/audit
history for concrete failure patterns, researches fixes (via the manager
delegating to web_researcher), writes evaluation reports to Outline, and
files improvement proposals as Plane issues. For well-scoped proposals the
manager has coder draft the new file content and calls propose_code_change
itself — every actual code change is a human-reviewed diff, never applied
unsupervised, regardless of what maintainer recommends."""

from smolagents import ToolCallingAgent

from . import config
from .context import with_baseline
from .model import get_model
from .tools import get_domains_tools

# maintainer gets read-only introspection from the agents domain only —
# never agent_dispatch (a job dispatching more jobs would loop the worker,
# same reason the manager itself doesn't hold it) and never
# propose_code_change (the manager calls that itself, per its own
# procedure, so every code change traces back to one place) or agent_create.
_MAINTAINER_AGENT_TOOLS = ("agent_job_history", "agent_list", "agent_read",
                          "tools_help")


def build_maintainer_agent() -> ToolCallingAgent:
    agents_tools = [t for t in get_domains_tools("agents")
                    if t.name in _MAINTAINER_AGENT_TOOLS]
    seen = {t.name for t in agents_tools}
    tools = agents_tools + [t for t in get_domains_tools("approvals", "outline", "plane")
                            if t.name not in seen]
    return ToolCallingAgent(
        tools=tools,
        model=get_model("general"),
        name="maintainer",
        description=(
            "Reviews the stack's own recent performance and proposes "
            "improvements: pulls job/audit history, researches fixes "
            "(ask the manager to delegate research to web_researcher), "
            "writes an evaluation report to Outline, and files one Plane "
            "issue per proposed improvement. Give it a time window (e.g. "
            "'the last 7 days') or leave it open for 'review everything "
            "recent'. It does not write code itself — the manager has "
            "coder draft any proposed file content and applies it via "
            "propose_code_change, always gated on human approval."
        ),
        instructions=with_baseline(
            "Procedure: (1) call agent_job_history and agent_audit_history "
            "for the requested window; (2) identify CONCRETE failure "
            "patterns — cite specific job ids or audit timestamps, never "
            "vague impressions like 'reliability could be better'; a "
            "pattern needs at least two instances or one clearly "
            "reproducible cause to be worth proposing; (3) for each "
            "pattern, if you need to know how other projects solve this "
            "kind of problem, say so explicitly in your findings so the "
            "manager can delegate that research to web_researcher — you "
            "do not have web access yourself; (4) write an evaluation "
            "report to Outline's 'AI' collection (outline_list_collections "
            "to find its id), covering what you reviewed, the window, and "
            "every pattern found, including ones not worth fixing yet; "
            "(5) for each pattern worth fixing, file one Plane issue in "
            "the 'Stack Improvements' project (symbiotic-technologies "
            "workspace) — plane_list_projects to find it — with: a "
            "one-line title, the affected file(s), the evidence (job/audit "
            "ids), a proposed fix in plain terms, and a risk note (what "
            "could this change break?). Do not create duplicate issues — "
            "check plane_list_issues first. Report back to the manager "
            "which issues you filed and which patterns you judged NOT "
            "worth fixing (and why) so nothing gets silently dropped. If "
            "you lack a tool for something, say exactly that — never "
            "invent a permissions or configuration excuse. Report the "
            "exact URL a tool call returns for any report or issue you "
            "file — never guess or construct a URL yourself."
        ),
        max_steps=config.MAX_STEPS,
    )
