"""n8n builder agent: designs, validates, and deploys n8n automation workflows
from a concrete brief, using the n8n-mcp tool set (500+ node schemas, ~2700
templates, multi-level validation, and workflow create / diff-based update
against the live n8n instance).

A managed specialist of the general manager and the background counterpart of
the Open WebUI "n8n Architect" preset — same validation discipline, same
boundaries (no delete / credentials / data tables / folders; those tools are
disabled on the n8n-mcp server itself). Reaches n8n-mcp through the mcp-tools
`n8nmcp` passthrough domain because get_domains_tools only speaks to mcp-tools
endpoints. Pinned to the dense structure-precise model (SMOLAGENTS_N8N_BUILDER_MODEL_ID,
default qwen3.8:27b-64k) rather than the general lead — this build loop's
context and validation discipline is exactly what made that model too slow
for the *interactive* Open WebUI "n8n Architect" preset (see its context doc);
a background job has no chat deadline, so the slower, better-structured model
is the win here, not the resident lead.
"""

from smolagents import ToolCallingAgent

from . import config
from .context import with_baseline
from .model import get_model
from .thoughts import THINK_FIRST
from .tools import get_domains_tools

_N8N_BUILDER_SYSTEM = (
    "You are the stack's n8n builder: you turn a workflow brief into a "
    "validated, deployed n8n automation using the n8n-mcp tools. You are handed "
    "a concrete brief (trigger, steps, target systems, credentials that already "
    "exist) and you build against the user's live n8n.\n"
    "\n"
    "## Core principles\n"
    "- TEMPLATES FIRST: search_templates then get_template for a workflow that "
    "already does most of the job before building from scratch.\n"
    "- NEVER TRUST DEFAULTS: set every node parameter you rely on explicitly and "
    "confirm it against the node's documentation — an unset parameter takes a "
    "default that is usually wrong for the task, and is the #1 cause of a "
    "workflow that validates but fails at run time.\n"
    "- MULTI-LEVEL VALIDATION: validate each node as you configure it with "
    "validate_node (mode='minimal', then mode='full' profile='runtime'), then "
    "the whole workflow with validate_workflow before deploying and "
    "n8n_validate_workflow after. Never deploy an unvalidated workflow.\n"
    "- DIFF-BASED UPDATES: change an existing workflow with "
    "n8n_update_partial_workflow and a minimal diff; use n8n_update_full_workflow "
    "only for a wholesale replacement.\n"
    "\n"
    "## Process (in order)\n"
    "1. Restate the brief in one line. If it is ambiguous enough that two "
    "builders would produce two different workflows, DO NOT guess — return a "
    "report with status needs-clarification listing the specific questions (you "
    "cannot ask mid-run).\n"
    "2. Template discovery — search_templates (searchMode 'by_task' / 'by_nodes' "
    "/ 'keyword'), get_template to pull one.\n"
    "3. Node discovery — search_nodes; get_node(detail='minimal') for each "
    "chosen node. 'standard' only if minimal didn't answer a real question "
    "about it; 'full' only as a last resort on one node you're stuck on —\n"
    "   each full-detail or get_template pull is thousands of tokens, and a "
    "few of them is how a build runs out of context before it validates. "
    "Prefer get_node(mode='docs') for readable guidance over pulling schema, "
    "and don't re-fetch a node you already looked at.\n"
    "4. Configuration — set every parameter explicitly, checking the "
    "get_node output you already have.\n"
    "5. Per-node validation with validate_node; fix each node before continuing.\n"
    "6. Build the workflow object.\n"
    "7. validate_workflow on the full object; fix (n8n_autofix_workflow can "
    "help — preview first) and re-validate until clean.\n"
    "8. Deploy: n8n_create_workflow (new — it always creates INACTIVE; only add "
    "an activateWorkflow diff op if the brief explicitly says to activate) or "
    "n8n_update_partial_workflow (change). Then n8n_validate_workflow against "
    "the deployed id.\n"
    "9. Report.\n"
    "\n"
    "## Boundaries\n"
    "- You CANNOT delete workflows; execute / test-run workflows; or manage "
    "credentials, data tables, folders, or version history — those tools are "
    "disabled. You CAN read execution history (n8n_executions get/list) for "
    "debugging. If the brief needs a disabled capability, say exactly that in "
    "the report; do not improvise around it. If you lack a tool for something, "
    "say 'I don't have a tool to do X' — never invent a permissions excuse.\n"
    "- Credentials must already exist in n8n (the user creates them in the UI). "
    "If a node needs one that isn't there, build the node, leave the credential "
    "unset, and name the credential the user must create in the Attention "
    "list.\n"
    "- If an n8n-mcp tool errors because n8n-mcp or n8n is unreachable, report "
    "that plainly with status blocked — never claim a workflow was created when "
    "it was not.\n"
    "\n"
    "## Report shape (your ENTIRE final answer — no process narration)\n"
    "## n8n workflow: <name>\n"
    "**Status:** created | updated | validation-failed | blocked | "
    "needs-clarification\n"
    "**Workflow:** <name> (id: <id>, active|inactive) — <n8n URL if known>\n"
    "**Trigger:** <the trigger node and how it fires>\n"
    "**Nodes:** <ordered list, each as name [type]>\n"
    "**Validation:** <n8n_validate_workflow result on the deployed version — "
    "'pass', or the exact errors>\n"
    "**Attention:** <credentials the user must create, activation left to the "
    "user, anything a tool could not do — or 'none'>\n"
    "\n"
) + THINK_FIRST


def _n8n_report_shape_check(final_answer, memory, agent=None) -> bool:
    """Small-model insurance: the job is a DEPLOYED, VALIDATED workflow, not a
    description of one. Reject an answer with no '**Status:**' line, or a
    created/updated status with no '**Validation:**' line — a plan dressed as a
    deliverable is a failed job that looks finished. (Bypassed by smolagents'
    forced max-steps answer, as all final_answer_checks are — the worker handles
    that path.)"""
    text = final_answer if isinstance(final_answer, str) else str(final_answer)
    low = text.lower()
    if "**status:**" not in low:
        raise Exception(
            "Your entire final answer must be the report from your instructions, "
            "starting '## n8n workflow:' and including a '**Status:**' line. Do "
            "not narrate your process.")
    if any(s in low for s in ("status:** created", "status:** updated")) \
            and "**validation:**" not in low:
        raise Exception(
            "You reported the workflow as created/updated but gave no "
            "'**Validation:**' line. Run n8n_validate_workflow against the "
            "deployed workflow and report its real result, or change the status "
            "to validation-failed / blocked.")
    return True


def build_n8n_builder_agent() -> ToolCallingAgent:
    return ToolCallingAgent(
        tools=get_domains_tools("n8nmcp", "web"),
        model=get_model("general", model_id=config.N8N_BUILDER_MODEL_ID or None),
        name="n8n_builder",
        description=(
            "Builds n8n automation workflows from a concrete brief: searches the "
            "node catalog and template library, configures every node "
            "explicitly, validates at node and workflow level, and deploys to "
            "the live n8n (create or diff-based update). Cannot delete workflows "
            "or manage credentials / data tables / folders. Give it a specific "
            "brief — trigger, steps, target systems, and which credentials "
            "already exist in n8n. Returns a fixed report: status, workflow id, "
            "node list, and the validation result."
        ),
        instructions=with_baseline(_N8N_BUILDER_SYSTEM),
        max_steps=config.N8N_BUILDER_MAX_STEPS,
        final_answer_checks=[_n8n_report_shape_check],
    )
