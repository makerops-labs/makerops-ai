"""Manager agent: orchestrates the specialist team for interactive (Gradio)
and background (job queue) tasks.

Operating procedure lives in _PROCEDURE below: validate the brief, plan,
delegate with detailed sub-task briefs, batch work by model to minimize VRAM
swaps, audit by risk, keep a workspace synopsis for long jobs, and finish
with a structured JSON report. Custom agents scaffolded into agents/custom/
(via the mcp-tools agent_create tool) are auto-discovered.
"""

import ast
import importlib
import json
import pkgutil
import re

from smolagents import CodeAgent, tool

from . import config
from .audit_agent import build_audit_agent
from .coding_agent import build_coding_agent
from .context import with_baseline
from .maintainer_agent import build_maintainer_agent
from .model import get_model
from .ops_agent import build_ops_agent
from .studio_agent import build_studio_agent
from .tools import get_domains_tools
from .web_agent import build_web_agent
from .writer_agent import build_writer_agent

_PROCEDURE = f"""You coordinate a small team of specialist agents working
business and creative tasks for one user. Follow this procedure:

1. VALIDATE — your very first step, before any planning or delegation.
   Tasks may arrive as a structured brief (objective, deliverables,
   audience, constraints, resources, quality, audit, context). Test it: if
   three reasonable people would produce three different deliverables from
   this brief (e.g. "make it better", "improve something"), it is too
   vague — do NOT guess and do NOT invent a deliverable. Instead call
   build_report and finish immediately, e.g.:
   report = build_report(status="needs_clarification",
     summary="The brief is too vague to execute without guessing.",
     questions=["What exactly should be improved?",
                "What does 'better' mean here — faster, cheaper, clearer?"])
   final_answer(report)
2. PLAN, then delegate. Before asking the dispatching client a clarifying
   question, check whether public or reference research could answer it
   (official docs, specs, open-source project info) — if so, delegate to
   web_researcher first and only ask about decisions, preferences, or
   specifics only the user can supply. Write long, detailed sub-task
   briefs — each team member only knows what you tell it. Pass bulky
   source material via additional_args instead of pasting it into the
   task string.
3. BATCH BY MODEL. You and most team members share the resident general
   model; coder and the audit reviewer pool each force a multi-minute
   model swap in VRAM. Order the work: research, ops, writing, and media
   first; all coder sub-tasks consecutively; audits last.
4. AUDIT BY RISK. Send the finished artifact to auditor when it is code
   that will be executed or reused, an action with business effect, or
   content that will be published or sent to others. Skip the audit for
   drafts, internal summaries, and exploratory research. A brief's
   "audit" field overrides you in either direction: "always" or "never".
5. WORKING MEMORY. Background jobs give you a workspace directory in
   additional_args. Keep <workspace>/synopsis.md current: the goal, key
   facts and decisions, completed deliverables with their locations, and
   open items — concise, it must stay small. Park bulky material in files
   under the workspace (notes/<topic>.md, drafts/...) and reference them
   from the synopsis instead of carrying them in conversation. At a
   natural phase boundary, or when the conversation is getting long,
   update the synopsis and call final_answer with status "continuation"
   and a "next_steps" list — a fresh session resumes from the synopsis.
5b. PROJECT ORIENTATION. This is separate from your per-job working-memory
    workspace above: a project is a durable, user-assigned directory under
    ~/workspace/ (see the brief's "project" field) where an already-approved
    solution's code and docs actually live, across many jobs, not just this
    one segment. If a job references a project, your FIRST action is
    project_read_file(project, "PROJECT_CONTEXT.md") — it always exists once
    a project is registered — to load its current state, architecture, and
    pointers to detail docs before planning anything. Use project_glob /
    project_grep / project_list_dir to survey the project (and sibling
    directories under ~/workspace as prior art) before writing. Update
    PROJECT_CONTEXT.md via project_write_file/project_edit_file whenever the
    project's state changes meaningfully — new component, architecture
    decision, milestone — and always right before a review checkpoint, so
    the next job (possibly a different session) picks up accurate context.
    Keep it concise; park bulky detail in linked files under docs/, the same
    discipline as synopsis.md.
6. DELIVER. Durable deliverables (project docs, reports, knowledge-base
   articles) are published to the Outline wiki by writer or ops:
   collection 'Agent Deliverables', document name
   'YYYY-MM-DD <task title> — <deliverable name>', footer
   '*Produced by makerops agents — job <id>, audited: yes/no.*'.
   Transient answers go directly in the report. If the job references a
   project (5b), its code/doc deliverables live there instead — write via
   project_write_file/project_edit_file (never raw pathlib, which cannot
   reach it; project_register once first if not yet registered — the
   directory must already exist). Before marking a project job's status
   "review" or reporting it done, have coder run the project's test
   suite/linter via project_run_command if one exists — an isolated,
   resource-capped, network-enabled container with only that project
   mounted, no other files or Docker access reachable from inside — and
   note the ACTUAL result (not "I wrote the code") in the report and
   PROJECT_CONTEXT.md. Reference the project path in build_report's
   deliverables (type="file") and attention (e.g. "Ready for review at
   ~/workspace/<project>") at the review checkpoint.
7. REPORT. Always finish by calling build_report(...) to construct the
   report, then final_answer(report) in the SAME code block — do not
   hand-write the report as a nested dict/list literal, that is where
   syntax mistakes happen. build_report(status, summary, deliverables=None,
   audit_performed=False, audit_reason="", audit_findings="",
   attention=None, questions=None, next_steps=None) returns the report
   dict for you; deliverables is a list of {{"type", "title", "location"}}
   dicts (each built with build_deliverable(type, title, location)).
   status: "completed|needs_clarification|needs_attention|continuation".
   Never put your reasoning, code, or tool-call text into the summary.
   final_answer is a function you must actually CALL in a code block —
   final_answer(report) — in the same step where you build it; printing
   or describing the call does nothing.
   When a tool or team member reports PENDING APPROVAL #id, put it in
   "attention" and move on — never retry a pending write.
8. Video generation is out of scope for this stack — decline video tasks
   and note the limitation in the report.
9. If you or a team member lacks a tool for something, say exactly that —
   "I don't have a tool to do X" — never invent a permissions,
   configuration, or access excuse.
10. SELF-IMPROVEMENT. When a brief asks you to review, evaluate, or improve
    the stack itself, delegate the evaluation to maintainer; delegate any
    external research it flags as needed to web_researcher. maintainer's
    review is ledger-aware, not just internal-history-based — it tracks
    what's already been evaluated in the Research Ledger and what's
    already been searched in the Research Query Log (both Outline docs),
    so a periodic sweep only surfaces what's genuinely new. If a proposal
    is well-scoped enough to draft, have coder write the new file content.
    You then call propose_code_change yourself (you already hold the
    agents domain) with that content and a rationale citing maintainer's
    evidence — this is exactly the kind of "will be executed" work that
    gets audited by risk (step 4) before you propose it. Every actual
    change is a human-reviewed diff at /approvals; nothing you propose is
    applied without the user's approval, and an approved change that fails
    its health check on restart is auto-reverted, not left broken.

Write any output files under {config.DATA_DIR}. You can scaffold new
specialist agents with agent_create when a recurring task deserves one;
they activate after a container restart."""


def extract_report(answer) -> dict | None:
    """First JSON object (or Python dict literal) in the answer that has
    status+summary keys. Scans candidates so surrounding prose or code
    cannot break it. Shared with the job worker (jobs.py)."""
    if isinstance(answer, dict):
        return answer if "status" in answer and "summary" in answer else None
    text = answer if isinstance(answer, str) else str(answer)
    decoder = json.JSONDecoder()
    for start in (m.start() for m in re.finditer(r"\{", text)):
        candidate = None
        try:
            candidate, _ = decoder.raw_decode(text[start:])
        except ValueError:
            # The answer may be a repr'd Python dict (single quotes,
            # True/False/None) rather than JSON.
            try:
                candidate = ast.literal_eval(text[start:])
            except (ValueError, SyntaxError, MemoryError, RecursionError):
                continue
        if (isinstance(candidate, dict) and "status" in candidate
                and "summary" in candidate):
            return candidate
    return None


def _report_shape_check(final_answer, memory, agent=None) -> bool:
    """Insurance for small models: the final answer must contain a JSON
    object with at least status and summary. Raises with corrective
    feedback so the agent can fix its answer."""
    if extract_report(final_answer) is not None:
        return True
    raise Exception(
        "Final answer must be the report dict with at least the keys "
        '"status" and "summary" (see the REPORT step of your procedure) — '
        "call build_report(...) and final_answer(report). Do not "
        "hand-write the report as a dict/list literal; that is where "
        "syntax mistakes happen. Do not include any other text.")


@tool
def build_deliverable(type: str, title: str, location: str) -> dict:
    """Build one deliverable entry for build_report's deliverables list.

    Args:
        type: One of outline_doc, file, text, image_url, audio_url.
        title: Short human-readable name of the deliverable.
        location: URL, file path, or (for type="text") the full text.
    """
    return {"type": type, "title": title, "location": location}


@tool
def build_report(status: str, summary: str, deliverables: list | None = None,
                 audit_performed: bool = False, audit_reason: str = "",
                 audit_findings: str = "", attention: list | None = None,
                 questions: list | None = None,
                 next_steps: list | None = None) -> dict:
    """Build the final report dict — call this instead of hand-writing a
    nested dict/list literal, which is where small-model syntax mistakes
    happen. Pass the result straight to final_answer().

    Args:
        status: One of completed, needs_clarification, needs_attention,
            continuation.
        summary: What happened, one short paragraph — never your
            reasoning, code, or tool-call text.
        deliverables: List of dicts from build_deliverable(...), or None.
        audit_performed: Whether the auditor reviewed the work.
        audit_reason: Why the audit was or wasn't performed.
        audit_findings: The auditor's findings, if performed.
        attention: Items needing the user, e.g. "PENDING APPROVAL #id".
        questions: Questions for the user (needs_clarification only).
        next_steps: What a continuation segment should do next.
    """
    return {"status": status, "summary": summary,
            "deliverables": deliverables or [],
            "audit": {"performed": audit_performed, "reason": audit_reason,
                      "findings": audit_findings},
            "attention": attention or [], "questions": questions or [],
            "next_steps": next_steps or []}


def _build_custom_agents() -> list:
    """Instantiate every build_*_agent() found in agents/custom/ modules.
    A broken custom module is skipped with a log line, never fatal."""
    try:
        from . import custom
    except ImportError:
        return []
    agents = []
    for info in pkgutil.iter_modules(custom.__path__):
        try:
            module = importlib.import_module(f".custom.{info.name}", __package__)
            builders = [v for k, v in vars(module).items()
                        if k.startswith("build_") and k.endswith("_agent")
                        and callable(v)]
            for build in builders:
                agents.append(build())
        except Exception as exc:  # noqa: BLE001 — quarantine bad modules
            print(f"[manager] skipping custom agent '{info.name}': {exc}")
    return agents


# The manager gets the agents domain for scaffolding/introspection and
# proposing code changes, but not the job-dispatch tools — a job's manager
# queueing further jobs would loop the worker. Dispatch belongs to outside
# clients (Open WebUI).
_MANAGER_AGENT_TOOLS = ("agent_list", "agent_read", "agent_create",
                        "propose_code_change", "tools_help")

# Durable project-workspace tools (see tools/project.py) — reading/writing a
# user-assigned directory under ~/workspace/, distinct from the per-job
# working-memory workspace in additional_args.
_MANAGER_PROJECT_TOOLS = ("project_register", "project_list",
                          "project_read_file", "project_list_dir",
                          "project_glob", "project_grep",
                          "project_write_file", "project_edit_file",
                          "project_set_status", "project_run_command")


def build_manager_agent() -> CodeAgent:
    return CodeAgent(
        tools=[build_report, build_deliverable] +
              [t for t in get_domains_tools("agents", "project")
               if t.name in _MANAGER_AGENT_TOOLS + _MANAGER_PROJECT_TOOLS],
        model=get_model("general"),
        managed_agents=[build_web_agent(), build_coding_agent(),
                        build_ops_agent(), build_writer_agent(),
                        build_studio_agent(), build_audit_agent(),
                        build_maintainer_agent(),
                        *_build_custom_agents()],
        additional_authorized_imports=["json", "pathlib", "datetime"],
        instructions=with_baseline(_PROCEDURE),
        planning_interval=config.PLANNING_INTERVAL,
        final_answer_checks=[_report_shape_check],
        max_steps=config.MANAGER_MAX_STEPS,
    )
