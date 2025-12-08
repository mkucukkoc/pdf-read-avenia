"""Backend agent registry (mirrors frontend agentFunctions).

These definitions are data-only and can be used for server-side routing/tools.
Frontend files remain intact; no behavior change is introduced by this module.
"""

from .registry import AGENTS, get_agent_by_name, get_agent_definitions

__all__ = ["AGENTS", "get_agent_definitions", "get_agent_by_name"]


