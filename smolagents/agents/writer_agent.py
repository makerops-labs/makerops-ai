"""Writer agent: written deliverables — documentation, reports, summaries,
marketing/advertising copy, and interpretation or rewriting of provided
content. Publishes durable deliverables to the Outline wiki (when the
outline domain is mounted on mcp-tools)."""

from smolagents import ToolCallingAgent

from .context import with_baseline
from .model import get_model
from .tools import get_domains_tools


def build_writer_agent() -> ToolCallingAgent:
    tools = get_domains_tools("outline")
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
            "send research your way. Lead with the finished deliverable, "
            "then a one-line note on choices you made. Durable deliverables "
            "(project docs, knowledge-base articles, reports meant to "
            "persist) go to the Outline wiki: create the document in the "
            "'Agent Deliverables' collection, named "
            "'YYYY-MM-DD <task title> — <deliverable name>', ending with a "
            "footer line '---' then '*Produced by makerops agents — job "
            "<id>, audited: yes/no.*' (the manager supplies the job id and "
            "audit status). If Outline tools are unavailable or the "
            "collection is missing, return the full deliverable text in "
            "your answer and say the wiki write could not happen. When a "
            "write tool answers PENDING APPROVAL, report the pending id "
            "and stop — never retry."
        ),
        max_steps=8,
    )
