"""The three fixed debate personas — entrepreneur, critic, monitor. Only
ever run as managed_agents of debate_manager.py's dedicated orchestrator,
never registered on the general manager (see debate_manager.py)."""

from .critic_agent import build_critic_agent
from .entrepreneur_agent import build_entrepreneur_agent
from .monitor_agent import build_monitor_agent

__all__ = ["build_entrepreneur_agent", "build_critic_agent", "build_monitor_agent"]
