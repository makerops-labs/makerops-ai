"""Devteam: a lead-architect orchestrator plus a specialist software team
that builds an application in a registered ~/workspace/<project> directory
from a user-provided product plan.

An engagement is a durable multi-phase session (requirements → architecture
→ scaffold → milestones → qa → docs) stored under config.DEVTEAM_DIR; each
phase runs as ONE manager-style background job by the lead architect (see
jobs.py's devteam section for the state machine and the mcp-tools devteam
domain for the user-facing controls). Only build_lead_architect_agent is
built by the worker — the specialists live on the architect as
managed_agents, never on the general manager.
"""

from .lead_architect import build_lead_architect_agent

__all__ = ["build_lead_architect_agent"]
