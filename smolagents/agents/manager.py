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

from smolagents import CodeAgent

from . import config
from .audit_agent import build_audit_agent
from .coding_agent import build_coding_agent
from .context import with_baseline
from .model import get_model
from .ops_agent import build_ops_agent
from .studio_agent import build_studio_agent
from .tools import get_domain_tools
from .web_agent import build_web_agent
from .writer_agent import build_writer_agent

_PROCEDURE = f"""You coordinate a small team of specialist agents working
business and creative tasks for one user. Follow this procedure:

1. VALIDATE — your very first step, before any planning or delegation.
   Tasks may arrive as a structured brief (objective, deliverables,
   audience, constraints, resources, quality, audit, context). Test it: if
   three reasonable people would produce three different deliverables from
   this brief (e.g. "make it better", "improve something"), it is too
   vague — do NOT guess and do NOT invent a deliverable. Instead build a
   plain Python dict and finish immediately, e.g.:
   report = {{"status": "needs_clarification",
     "summary": "The brief is too vague to execute without guessing.",
     "deliverables": [], "audit": {{"performed": False}},
     "attention": [], "next_steps": [],
     "questions": ["What exactly should be improved?",
                   "What does 'better' mean here — faster, cheaper, clearer?"]}}
   final_answer(report)
2. PLAN, then delegate. Write long, detailed sub-task briefs — each team
   member only knows what you tell it. Pass bulky source material via
   additional_args instead of pasting it into the task string.
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
6. DELIVER. Durable deliverables (project docs, reports, knowledge-base
   articles) are published to the Outline wiki by writer or ops:
   collection 'Agent Deliverables', document name
   'YYYY-MM-DD <task title> — <deliverable name>', footer
   '*Produced by makerops agents — job <id>, audited: yes/no.*'.
   Transient answers go directly in the report.
7. REPORT. Always finish by building the report as a plain Python dict in
   your code and calling final_answer(report) — the dict IS the report; do
   not wrap it in json.dumps, markdown, or any prose. Keys:
   {{"status": "completed|needs_clarification|needs_attention|continuation",
     "summary": "<what happened, one short paragraph>",
     "deliverables": [{{"type": "outline_doc|file|text|image_url|audio_url",
                        "title": "...", "location": "..."}}],
     "audit": {{"performed": True/False, "reason": "...", "findings": "..."}},
     "attention": ["<items needing the user, e.g. PENDING APPROVAL #id>"],
     "questions": [], "next_steps": []}}
   Never put your reasoning, code, or tool-call text into the summary.
   final_answer is a function you must actually CALL in a code block —
   final_answer(report) — in the same step where you build the dict;
   printing or describing the call does nothing.
   When a tool or team member reports PENDING APPROVAL #id, put it in
   "attention" and move on — never retry a pending write.
8. Video generation is out of scope for this stack — decline video tasks
   and note the limitation in the report.

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
        "build report = {...} in code and call final_answer(report). Do "
        "not include any other text.")


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


# The manager gets the agents domain for scaffolding/introspection, but not
# the job-dispatch tools — a job's manager queueing further jobs would loop
# the worker. Dispatch belongs to outside clients (Open WebUI).
_MANAGER_AGENT_TOOLS = ("agent_list", "agent_read", "agent_create",
                        "tools_help")


def build_manager_agent() -> CodeAgent:
    return CodeAgent(
        tools=[t for t in get_domain_tools("agents")
               if t.name in _MANAGER_AGENT_TOOLS],
        model=get_model("general"),
        managed_agents=[build_web_agent(), build_coding_agent(),
                        build_ops_agent(), build_writer_agent(),
                        build_studio_agent(), build_audit_agent(),
                        *_build_custom_agents()],
        additional_authorized_imports=["json", "pathlib", "datetime"],
        instructions=with_baseline(_PROCEDURE),
        planning_interval=config.PLANNING_INTERVAL,
        final_answer_checks=[_report_shape_check],
        max_steps=config.MANAGER_MAX_STEPS,
    )
