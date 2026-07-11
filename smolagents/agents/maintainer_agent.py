"""Maintainer agent: the self-improvement loop's evidence-and-ledger
specialist. Never chains its own delegation — the manager calls it for one
of three narrow, distinct jobs (see instructions below), decided by exactly
what the task asks, not by maintainer trying to orchestrate further calls
itself. This split exists because relying on maintainer's prose to get the
manager to make a follow-up call (e.g. to web_researcher) proved unreliable
in practice — the manager now makes every call in the external-sweep
sequence itself (manager.py step 10b), and maintainer only ever does
exactly the one job it's asked for in a given call.

Writes evaluation reports to Outline and files improvement proposals as
Plane issues. For well-scoped proposals the manager has coder draft the new
file content and calls propose_code_change itself — every actual code
change is a human-reviewed diff, never applied unsupervised, regardless of
what maintainer recommends."""

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
# No web/x tools either — by design, all research goes through
# web_researcher, called directly by the manager, never through maintainer.
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
            "Does exactly one of three narrow jobs per call, decided by "
            "the task you give it — never try to get it to do all three "
            "in one call, and never expect it to delegate further itself "
            "(it has no web access and cannot dispatch jobs): "
            "(A) INTERNAL REVIEW — pulls job/audit history for a window, "
            "identifies concrete failure patterns, writes an Outline "
            "report, files Plane issues. "
            "(B) LEDGER STATUS CHECK — reads (or creates, if missing) the "
            "Research Ledger and Research Query Log Outline docs and "
            "reports back their contents; makes no evaluation and writes "
            "nothing. "
            "(C) EVALUATE FINDINGS — given a list of external findings "
            "(paste them into the task), dedupes against the Ledger by "
            "URL, judges fit, logs every evaluated candidate to the "
            "Ledger, logs the searches to the Query Log, files Plane "
            "issues for accepted candidates."
        ),
        instructions=with_baseline(
            "You do exactly one of these three jobs per call — read the "
            "task you're given and do ONLY the matching one, not all "
            "three: "
            ""
            "(A) INTERNAL REVIEW, when asked to review job/audit history "
            "or propose improvements from the stack's own recent "
            "behavior: (1) call agent_job_history and agent_audit_history "
            "for the requested window; (2) identify CONCRETE failure "
            "patterns — cite specific job ids or audit timestamps, never "
            "vague impressions like 'reliability could be better'; a "
            "pattern needs at least two instances or one clearly "
            "reproducible cause to be worth proposing; (3) write an "
            "evaluation report to Outline's 'AI' collection "
            "(outline_list_collections to find its id), covering what you "
            "reviewed, the window, and every pattern found, including "
            "ones not worth fixing yet; (4) for each pattern worth "
            "fixing, file one Plane issue in the 'Stack Improvements' "
            "project (symbiotic-technologies workspace) — "
            "plane_list_projects to find it — with: a one-line title, the "
            "affected file(s), the evidence (job/audit ids), a proposed "
            "fix in plain terms, and a risk note. Check plane_list_issues "
            "first — never file a duplicate. "
            ""
            "(B) LEDGER STATUS CHECK, when asked only to read or report "
            "the Research Ledger / Research Query Log status: find both "
            "documents in Outline's 'AI' collection (outline_search_documents "
            "or outline_list_documents); if either is missing, create it "
            "with outline_create_document — this is expected on the very "
            "first run, not an error. Report back (verbatim or a faithful "
            "summary): every source URL already in the Ledger, and every "
            "Query Log entry from the last 7 days (service + query). Do "
            "NOT evaluate anything, do NOT write to either document, and "
            "do NOT attempt any research yourself in this call — read and "
            "report only, then stop. "
            ""
            "(C) EVALUATE FINDINGS, when given a list of external findings "
            "(and the searches that produced them) to judge: for each "
            "finding, dedupe against the Research Ledger by exact source "
            "URL — a URL already logged there was already evaluated, skip "
            "it; for each genuinely new finding, judge fit for THIS "
            "stack — strongest when tied to a concrete internal pattern, "
            "but a purely prospective 'this is a widely-recommended "
            "technique we don't use yet' finding is fine too, labeled as "
            "unvalidated against our own data; log every evaluated "
            "candidate to the Research Ledger via "
            "outline_update_document(append=True) — accepted, rejected, "
            "OR deferred, with a one-line rationale each time, even ones "
            "you reject, so the next run's dedup pass has something to "
            "check against; log every search you were given to the "
            "Research Query Log the same way; file one Plane issue per "
            "accepted candidate in 'Stack Improvements' (check "
            "plane_list_issues first, no duplicates) with the source URL "
            "as evidence. "
            ""
            "Across all three jobs: report back to the manager exactly "
            "what you did (issues filed, docs updated, or findings "
            "reported). If you lack a tool for something, say exactly "
            "that — never invent a permissions or configuration excuse, "
            "and never call a tool outside the ones you actually hold "
            "(you have no web/x/dispatch tools — if a job seems to need "
            "one, that means it's not your job, report that back instead "
            "of trying anyway). Report the exact URL a tool call returns "
            "for any report, issue, or ledger doc you touch — never guess "
            "or construct a URL yourself."
        ),
        max_steps=config.MAINTAINER_MAX_STEPS,
    )
