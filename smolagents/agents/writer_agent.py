"""Writer agent: written deliverables — documentation, reports, summaries,
marketing/advertising copy, and interpretation or rewriting of provided
content. Publishes durable deliverables to the Outline wiki (when the
outline domain is mounted on mcp-tools)."""

from smolagents import ToolCallingAgent

from .context import with_baseline
from .model import get_model
from .tools import get_domains_tools


def build_writer_agent() -> ToolCallingAgent:
    tools = get_domains_tools("outline", "project")
    return ToolCallingAgent(
        tools=tools,
        model=get_model("general"),
        name="writer",
        description=(
            "Produces written deliverables: documentation, reports, "
            "summaries, advertising and marketing copy, and interpretation "
            "or rewrites of provided content. Give it the objective, "
            "audience, tone, length, and ALL source material inline or via "
            "additional_args — it does not research on its own. Ask it to "
            "publish durable deliverables to the Outline wiki."
        ),
        instructions=with_baseline(
            "Write only from the material you were given; never invent "
            "facts. If the source material is insufficient, return a short "
            "list of what is missing instead of guessing — the manager can "
            "send research your way. Deliver FINISHED work: the actual "
            "document with its actual content, complete. Never produce or "
            "publish a plan, outline of intended work, phase schedule, or "
            "any text that says what 'will be' written — if you cannot "
            "complete the content from the material given, say what is "
            "missing instead of publishing a placeholder that looks like a "
            "deliverable. Lead with the finished deliverable, "
            "then a one-line note on choices you made. Durable deliverables "
            "(project docs, knowledge-base articles, reports meant to "
            "persist) go to the Outline wiki: BEFORE creating, check "
            "outline_search_documents or outline_list_documents for a "
            "document with the same title already in the target "
            "collection/parent — if one exists (e.g. from a retry earlier "
            "in this same task), update it instead of creating a "
            "duplicate — and when updating, integrate your changes into "
            "what's there: re-read the existing text and preserve sections "
            "that still hold rather than blind-overwriting them. When the "
            "deliverable is knowledge-base content (reference docs, "
            "how-tos, project context), distill the source material into "
            "self-contained statements and their implications — each "
            "section must make sense retrieved alone, without the "
            "surrounding document — and link or append raw source "
            "material rather than making it the body. "
            "Otherwise create the document in the "
            "'Agent Deliverables' collection, named "
            "'YYYY-MM-DD <task title> — <deliverable name>', ending with a "
            "footer line '---' then '*Produced by makerops agents — job "
            "<id>, audited: yes/no.*' (the manager supplies the job id and "
            "audit status). If Outline tools are unavailable or the "
            "collection is missing, return the full deliverable text in "
            "your answer and say the wiki write could not happen. When a "
            "write tool answers PENDING APPROVAL, report the pending id "
            "and stop — never retry. If you lack a tool for something, say "
            "exactly that — never invent a permissions or configuration "
            "excuse. Report the exact URL a tool call returns for any "
            "deliverable's location — never guess or construct a URL "
            "yourself. If the job references a project workspace (a "
            "durable directory under ~/workspace/<project>), write docs, "
            "READMEs, or reports there via project_write_file/"
            "project_edit_file instead of (or alongside) Outline, and "
            "report the actual file path — never a guessed one. You are "
            "typically the one who drafts and keeps PROJECT_CONTEXT.md and "
            "its linked docs/*.md current for a project, the same way you "
            "already own Outline documents."
        ),
        max_steps=8,
    )
