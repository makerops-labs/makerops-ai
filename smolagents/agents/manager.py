"""Manager agent: plans tasks and delegates to the specialist agents.

This is the orchestrator the Gradio UI serves. It handles planning and
document preparation itself and hands research to web_researcher, code work
to coder, and service operations to ops. Custom agents scaffolded into
agents/custom/ (via the mcp-tools agent_create tool) are auto-discovered.
"""

import importlib
import pkgutil

from smolagents import CodeAgent

from . import config
from .audit_agent import build_audit_agent
from .coding_agent import build_coding_agent
from .model import get_model
from .ops_agent import build_ops_agent
from .tools import get_domain_tools
from .web_agent import build_web_agent


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


def build_manager_agent() -> CodeAgent:
    return CodeAgent(
        # The agents domain lets the manager scaffold new custom agents.
        tools=get_domain_tools("agents"),
        model=get_model("general"),
        managed_agents=[build_web_agent(), build_coding_agent(),
                        build_ops_agent(), build_audit_agent(),
                        *_build_custom_agents()],
        additional_authorized_imports=["json", "pathlib", "datetime"],
        instructions=(
            "You coordinate work for a small business operations team. "
            "Break large tasks into steps, delegate web research to "
            "web_researcher, programming or data tasks to coder, and tasks "
            "touching business services (wiki, inventory, projects, "
            "automation, helpdesk, images, diagrams) to ops. When the user "
            "asks for a review, verification, or second opinion on finished "
            "work, hand the task and the complete artifact to auditor. "
            f"Write any output files under {config.DATA_DIR}. You can "
            "scaffold new specialist agents with agent_create when a "
            "recurring task deserves one; they activate after a container "
            "restart."
        ),
        max_steps=config.MAX_STEPS,
    )
