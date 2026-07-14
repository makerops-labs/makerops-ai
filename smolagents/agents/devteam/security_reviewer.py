"""Security reviewer: read-only security review of project code.

Reviewer role — carries the DRAFT_AND_EVALUATE scaffold per thoughts.py
doctrine. Deliberately gets only the project READ tools: a reviewer that
can edit what it reviews stops being an independent check, and its findings
go back through the architect to an implementing engineer anyway.
"""

from smolagents import ToolCallingAgent

from .. import config
from ..context import with_baseline
from ..model import get_model
from ..thoughts import DRAFT_AND_EVALUATE
from ..tools import get_domains_tools

_PROJECT_READ_TOOLS = ("project_list", "project_read_file",
                       "project_list_dir", "project_glob", "project_grep",
                       "tools_help", "current_datetime")

_SECURITY_SYSTEM = (
    "You are the security reviewer on a software team. You are handed a "
    "scope — a project name plus the files or feature to review — and you "
    "return numbered findings ordered by severity. Read the actual code "
    "with your project tools (project_grep for dangerous patterns, "
    "project_read_file for the flows in scope); never review from the "
    "description alone. Hunt for: injection (SQL/command/template/path), "
    "missing or broken authentication and authorization checks, secrets or "
    "credentials in code or config, unsafe deserialization or eval, "
    "missing input validation at trust boundaries, sensitive data leaking "
    "into logs or error messages, and insecure defaults. Every finding "
    "must name the file, the concrete attack or failure scenario (what "
    "input or state exploits it), and a one-line remediation — a vague "
    "'consider hardening X' is not a finding and must be omitted. Rate "
    "each finding MUST-FIX (exploitable or data-loss) or HARDENING "
    "(defense in depth). Do not rewrite the code — your findings go to the "
    "architect, who assigns fixes. If you find nothing significant in "
    "scope, say so explicitly.\n"
    "\n"
) + DRAFT_AND_EVALUATE


def build_security_reviewer_agent() -> ToolCallingAgent:
    return ToolCallingAgent(
        tools=[t for t in get_domains_tools("project")
               if t.name in _PROJECT_READ_TOOLS],
        model=get_model("general"),
        name="security_reviewer",
        description=(
            "Read-only security review of project code. Give it the "
            "project name, the files or feature in scope, and what the "
            "code is supposed to protect; it returns severity-ordered "
            "findings, each with the concrete attack scenario and a "
            "one-line remediation, rated MUST-FIX or HARDENING."
        ),
        instructions=with_baseline(_SECURITY_SYSTEM),
        max_steps=config.MAX_STEPS,
    )
