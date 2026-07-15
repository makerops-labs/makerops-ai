"""Hardware: an embedded-architect orchestrator plus a KiCad build-plan
specialist that design a circuit in a registered ~/workspace/<project>
directory from a user-provided desired outcome.

An engagement is a durable multi-phase session (requirements → architecture
→ per-block milestones → fab-review → docs) stored under
config.HARDWARE_DIR; each phase runs as ONE manager-style background job by
the embedded architect (see jobs.py's hardware section for the state
machine and the mcp-tools hardware domain for the user-facing controls).
Only build_embedded_architect_agent is built by the worker — kicad_specialist
lives on the architect as a managed_agent, never on the general manager.

This package mirrors agents/devteam/ deliberately, as a forked (not shared)
implementation — see jobs.py's hardware section for why.
"""

from .embedded_architect import build_embedded_architect_agent

__all__ = ["build_embedded_architect_agent"]
