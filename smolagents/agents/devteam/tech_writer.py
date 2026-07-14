"""Tech writer: project documentation from real project facts.

Direction-follower doc production (like the general writer agent) — no TPO
scaffold. Distinct from writer_agent: scoped to the engagement's project
docs (README, docs/, PROJECT_CONTEXT.md) and required to read the actual
code before describing it.
"""

from smolagents import ToolCallingAgent

from ..context import with_baseline
from ..model import get_model
from ..tools import get_domains_tools


def build_tech_writer_agent() -> ToolCallingAgent:
    return ToolCallingAgent(
        tools=get_domains_tools("project", "outline"),
        model=get_model("general"),
        name="tech_writer",
        description=(
            "Writes project documentation: README, user/developer docs "
            "under docs/, and PROJECT_CONTEXT.md updates. Give it the "
            "project name, the audience, what to document, and any facts "
            "not visible in the code; it reads the actual project before "
            "writing and reports the real file paths it wrote."
        ),
        instructions=with_baseline(
            "You document a real project directory under "
            "~/workspace/<project>, reachable ONLY through the project_* "
            "tools. Never document from the brief alone: read the actual "
            "code, configs, and tests in scope (project_read_file/"
            "project_glob/project_grep) so every command, path, option, and "
            "behavior you state is verifiably true — a doc that says what "
            "the code should do instead of what it does is worse than no "
            "doc. Write docs into the project via project_write_file (new "
            "files) or project_edit_file (targeted updates to existing "
            "docs — re-read first and preserve sections that still hold; "
            "never blind-overwrite). A README covers: what the app is, "
            "install, run, use, test — with the exact commands that work "
            "in this project. Deliver FINISHED documentation with real "
            "content, never outlines, placeholders, or 'will be written' "
            "text. Keep PROJECT_CONTEXT.md entries distilled — atomic "
            "facts and their implications, bulk parked under docs/. Only "
            "publish to the Outline wiki when your brief explicitly asks "
            "for it. Report the exact file paths you actually wrote — "
            "never guessed ones. When a write tool answers PENDING "
            "APPROVAL, report the pending id and stop — never retry. If "
            "you lack a tool for something, say exactly that."
        ),
        max_steps=8,
    )
