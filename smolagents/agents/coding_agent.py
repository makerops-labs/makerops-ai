"""Coding agent: writes and runs Python for data work and document prep.

Imports are deliberately minimal — no os/subprocess/shutil. See the
Executor safety section of the service README before widening this list.
"""

from smolagents import CodeAgent

from . import config
from .model import get_model

AUTHORIZED_IMPORTS = ["json", "csv", "pathlib", "datetime", "re", "math"]


def build_coding_agent() -> CodeAgent:
    return CodeAgent(
        tools=[],
        model=get_model("coding"),
        additional_authorized_imports=AUTHORIZED_IMPORTS,
        name="coder",
        description=(
            "Writes and executes Python to transform data, draft documents, "
            "and solve programming tasks. Give it a self-contained task with "
            "any needed inputs."
        ),
        instructions=(
            f"Write any output files under {config.DATA_DIR} so they persist "
            "outside the sandbox."
        ),
        max_steps=config.MAX_STEPS,
    )
