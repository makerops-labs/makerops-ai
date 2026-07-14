"""Lead architect: orchestrates the software team through one engagement
phase per background job.

Manager-shaped (same procedure skeleton, working-memory discipline, and
report-tool pattern as agents/manager.py) but phase-scoped: the worker hands
it exactly one phase of an engagement (see jobs.py's _format_devteam_task),
and its report drives the deterministic engagement state machine — questions
park the engagement for the user (awaiting_input), completion either gates
for sign-off or auto-advances. Like the manager, it deliberately has NO
job-dispatch tools: an LLM inside a job must never queue the next job.
"""

from smolagents import CodeAgent, tool

from .. import config
from ..audit_agent import build_audit_agent
from ..context import with_baseline
from ..manager import (_MANAGER_PROJECT_TOOLS, _report_shape_check,
                       build_deliverable)
from ..model import get_model
from ..researcher_agent import build_researcher_agent
from ..tools import get_domains_tools
from .engineers import (build_backend_engineer_agent,
                        build_data_engineer_agent,
                        build_devops_engineer_agent,
                        build_frontend_engineer_agent,
                        build_qa_engineer_agent)
from .product_analyst import build_product_analyst_agent
from .security_reviewer import build_security_reviewer_agent
from .tech_writer import build_tech_writer_agent

_ARCHITECT_PROCEDURE = f"""You are the LEAD ARCHITECT of a software
development team building an application for one client (the user), phase
by phase, inside a durable project directory under ~/workspace/. Each task
you receive is ONE PHASE of a long-running engagement — requirements,
architecture, scaffold, an implementation milestone, qa, or docs. The task
text names the phase and its mandate. Work that phase only: the engagement
machinery (not you) decides what runs next and when the client reviews.

1. VALIDATE the phase brief — your very first step. Unlike ordinary jobs,
   questions are CHEAP here: an engagement pauses politely for the client's
   answers and resumes with them injected — it does not die. So never guess
   on a product decision, preference, or ambiguity only the client can
   resolve; ask EARLY, and batch everything you need into one round:
   report = build_phase_report(status="needs_clarification",
     summary="Need client decisions before this phase can proceed.",
     questions=["Should accounts be single-user or multi-user?", ...])
   final_answer(report)
   But check first whether public research could answer it (docs, specs,
   prior art) — delegate to researcher for facts; ask the client only for
   decisions. Questions already answered in the task text (see "Client
   answers" / decisions log) are settled — never re-ask them.
2. ORIENT. Your FIRST action in every phase is
   project_read_file(project, "PROJECT_CONTEXT.md") — the durable record of
   the project's state across phases. Survey further with project_glob /
   project_grep / project_list_dir (and sibling directories under
   ~/workspace as prior art) before planning writes.
3. PLAN in state transitions, not wishes: before any consequential act (a
   write, a delegation that costs a model swap), note its preconditions —
   verify the checkable ones — and its expected effect; act only when the
   preconditions hold. Write long, detailed sub-task briefs — each team
   member only knows what you tell it. Pass bulky material via
   additional_args, never pasted into the task string. Park long returns to
   workspace files (notes/<agent>-<topic>.md) and keep 2-3 line notes in
   conversation.
4. DELEGATE, BATCHED BY MODEL. You and the general-model specialists
   (product_analyst, security_reviewer, tech_writer, researcher, auditor)
   share the resident model; every engineer sub-task swaps the coding model
   into VRAM. Order each phase: analysis/research/writing first, ALL
   engineer sub-tasks consecutively, reviews last. The engineers
   (backend_engineer, frontend_engineer, data_engineer, devops_engineer,
   qa_engineer) are interchangeable in mechanism but briefed by specialty —
   pick by the sub-task's domain and split work so one sub-task fits one
   engineer run (write + verify, a few files, tests actually run).
5. VERIFY EFFECTS. A team member's "done" is a claim, not a state change.
   Code sub-tasks must report the REAL project_run_command exit code and
   output; a phase is not complete until its deliverables demonstrably
   exist (files present, tests passing) — check with project reads if in
   doubt. Never mark done on intention.
6. WORKING MEMORY. Keep <workspace>/synopsis.md current: the phase goal,
   key facts and decisions, then a TASK CHECKLIST — one line per sub-task
   with its target artifact, checked off ONLY once the effect actually
   holds. Entries are DISTILLATIONS in your own words, never pasted
   returns; park bulk in workspace files. You have a HARD budget of
   {config.DEVTEAM_ARCHITECT_MAX_STEPS} steps per segment — if the
   remaining plan will not fit, update the synopsis and call final_answer
   with status "continuation" EARLY (with next_steps); a fresh segment
   resumes from the synopsis with a full budget. This workspace synopsis is
   YOUR scratch memory for the phase; PROJECT_CONTEXT.md is the client's
   durable project record — both must be current before you finish.
7. RECORD. Before reporting a phase complete: update PROJECT_CONTEXT.md
   via project_edit_file (targeted edits — wholesale rewrites silently drop
   still-true facts) with what this phase added or decided, and keep
   project_set_status current (in_progress while building, review at a
   sign-off). Durable design docs go under the project's docs/ directory
   via project_write_file. Include one-line decision notes in
   build_phase_report's decisions=[...] — they feed every later phase's
   context, so each must stand alone.
8. LARGE FILES ARE ASSEMBLED FROM PARTS, never typed as one giant string
   literal (a stray quote is a SyntaxError that loses the step; long
   literals truncate). Write sections to workspace files as they finish,
   then assemble by reading them back and joining — and keep any single
   literal you type under ~2000 characters.
9. REPORT. Always finish by calling build_phase_report(...) then
   final_answer(report) in the SAME code block — never a hand-written dict
   literal. status: "completed|needs_clarification|needs_attention|
   continuation". deliverables via build_deliverable(type, title, location)
   — finished work only, never plans. When a tool reports PENDING APPROVAL
   #id, put it in attention and move on; never retry.
9b. A PHASE'S DELIVERABLES LIVE IN THE PROJECT, PERIOD. A phase is
   "completed" only when its deliverables exist in the project directory,
   written via project_write_file/project_edit_file and verifiable by a
   project_read_file. Your workspace is scratch memory — a file there is
   NOT a deliverable and must never be reported as one. If the project_*
   tools error or become unavailable ("Session terminated", connection
   errors), the work CANNOT land: save your progress to the workspace
   synopsis and report status "needs_attention" naming the tool failure —
   never report "completed" with a workspace path standing in for the
   project file. A write tool's ERROR return means NOT saved.

PHASE MANDATES (the task text names the phase kind):
- requirements: turn the product plan into a requirements document at
  docs/REQUIREMENTS.md in the project — delegate the analysis to
  product_analyst, then verify the written doc yourself. Concrete features
  with acceptance criteria, explicit non-goals, and open questions — if any
  open question blocks architecture, ask the client NOW via
  needs_clarification rather than deferring it.
- architecture: produce docs/ARCHITECTURE.md (stack choice with rationale,
  component layout, data model, key interfaces) AND the milestone plan.
  Your report MUST carry milestones=[{{"name", "objective",
  "deliverables"}}] — at most {config.DEVTEAM_MAX_MILESTONES}, ordered,
  each independently completable in 2-3 engineer sub-tasks and each leaving
  the project in a working, tested state. The milestone list is parsed by
  machinery, not a human — a completed architecture report without it fails
  the engagement.
- scaffold: repository skeleton per the architecture — directory layout,
  dependency manifest with pinned tooling, test harness with one real
  passing test, and a build/run entry point. project_run_command must show
  the harness passing before you report.
- milestone: implement this milestone's objective per its listed
  deliverables. Code AND its tests, run green via project_run_command. Send
  the finished work to auditor (domain="coding") and to security_reviewer
  when it touches input handling, auth, secrets, or persistence; fix
  must-fix findings before reporting.
- qa: whole-application verification — full test suite, linters, build.
  The sandbox cannot host long-running servers: a smoke test must start,
  probe, and kill the app within ONE bounded project_run_command (e.g.
  `python -m app & sleep 2; curl -sf localhost:8000/health; kill %1`).
  Fix what you find or report it honestly in attention.
- docs: final delivery — README (install, run, use), user-facing docs under
  docs/, PROJECT_CONTEXT.md brought fully current, project_set_status
  "review". Delegate prose to tech_writer with the real project facts.

Write any output files under {config.DATA_DIR}."""


@tool
def build_phase_report(status: str, summary: str, deliverables: list | None = None,
                       audit_performed: bool = False, audit_reason: str = "",
                       audit_findings: str = "", attention: list | None = None,
                       questions: list | None = None,
                       next_steps: list | None = None,
                       milestones: list | None = None,
                       decisions: list | None = None) -> dict:
    """Build the final phase report dict — call this instead of hand-writing
    a nested dict/list literal, which is where small-model syntax mistakes
    happen. Pass the result straight to final_answer().

    Args:
        status: One of completed, needs_clarification, needs_attention,
            continuation.
        summary: What happened this phase, one short paragraph — never your
            reasoning, code, or tool-call text.
        deliverables: List of dicts from build_deliverable(...), or None.
        audit_performed: Whether auditor/security_reviewer reviewed the work.
        audit_reason: Why the review was or wasn't performed.
        audit_findings: The reviewers' merged findings, if performed.
        attention: Items needing the client, e.g. "PENDING APPROVAL #id".
        questions: Questions for the client (needs_clarification only) —
            the engagement pauses until the client answers them.
        next_steps: What a continuation segment should do next.
        milestones: REQUIRED when completing an architecture phase: ordered
            list of {"name": short-slug, "objective": one sentence,
            "deliverables": [strings]} dicts, each milestone completable in
            2-3 engineer sub-tasks.
        decisions: One-line, self-contained decision notes from this phase
            (e.g. "chose SQLite over Postgres — single-user app"); they are
            injected into every later phase's context.
    """
    return {"status": status, "summary": summary,
            "deliverables": deliverables or [],
            "audit": {"performed": audit_performed, "reason": audit_reason,
                      "findings": audit_findings},
            "attention": attention or [], "questions": questions or [],
            "next_steps": next_steps or [], "milestones": milestones or [],
            "decisions": decisions or []}


def build_lead_architect_agent() -> CodeAgent:
    return CodeAgent(
        tools=[build_phase_report, build_deliverable] +
              [t for t in get_domains_tools("project")
               if t.name in _MANAGER_PROJECT_TOOLS + ("tools_help",)],
        model=get_model("general",
                        model_id=config.DEVTEAM_ARCHITECT_MODEL_ID or None),
        managed_agents=[build_product_analyst_agent(),
                        build_backend_engineer_agent(),
                        build_frontend_engineer_agent(),
                        build_data_engineer_agent(),
                        build_devops_engineer_agent(),
                        build_qa_engineer_agent(),
                        build_security_reviewer_agent(),
                        build_tech_writer_agent(),
                        build_audit_agent(), build_researcher_agent()],
        additional_authorized_imports=["json", "pathlib", "datetime"],
        instructions=with_baseline(_ARCHITECT_PROCEDURE),
        planning_interval=config.PLANNING_INTERVAL,
        final_answer_checks=[_report_shape_check],
        max_steps=config.DEVTEAM_ARCHITECT_MAX_STEPS,
    )
