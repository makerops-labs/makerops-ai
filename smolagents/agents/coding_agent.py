"""Coding agent: writes and runs Python for data work and document prep.

Imports are deliberately minimal — no os/subprocess/shutil. See the
Executor safety section of the service README before widening this list.
"""

from smolagents import CodeAgent

from . import config
from .context import with_baseline
from .model import get_model
from .tools import get_domains_tools

AUTHORIZED_IMPORTS = ["json", "csv", "pathlib", "datetime", "re", "math"]


def build_coding_agent() -> CodeAgent:
    return CodeAgent(
        tools=get_domains_tools("project"),
        model=get_model("coding"),
        additional_authorized_imports=AUTHORIZED_IMPORTS,
        name="coder",
        description=(
            "Writes and executes Python to transform data, draft documents, "
            "and solve programming tasks. Give it a self-contained task with "
            "any needed inputs."
        ),
        instructions=with_baseline(
            f"Write any output files under {config.DATA_DIR} so they persist "
            "outside the sandbox — that's your own ephemeral scratch space, "
            "fine via pathlib. A durable project directory under "
            "~/workspace/<project> is a different thing entirely: reach it "
            "ONLY through project_read_file/project_list_dir/project_glob/"
            "project_grep/project_write_file/project_edit_file — pathlib/"
            "open() cannot see it at all, it is not mounted into this "
            "container. Use project_glob/project_grep to survey an existing "
            "project or a sibling directory (prior art) before editing, "
            "instead of trying to enumerate files via pathlib. After "
            "writing or changing code in a project, use project_run_command "
            "to actually run its test suite/linter/build (if one exists) "
            "before reporting done — it runs in its own isolated, "
            "resource-capped container with only that project mounted, "
            "network access included for installs. Don't just assume the "
            "code works; report the real exit code and output."
        ),
        max_steps=config.MAX_STEPS,
    )
