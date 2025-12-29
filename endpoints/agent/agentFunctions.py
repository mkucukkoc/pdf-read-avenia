from __future__ import annotations

from typing import Dict, List

from .baseAgent import BaseAgent
from .files_pdf import pdf_agent_functions
from .files_word import word_agent_functions
from .files_pptx import pptx_agent_functions
from .image_gemini import image_gemini_agents

agentFunctions: List[BaseAgent] = [
    *image_gemini_agents,
    *pdf_agent_functions,
    *word_agent_functions,
    *pptx_agent_functions,
]

AGENT_REGISTRY: Dict[str, BaseAgent] = {agent.name: agent for agent in agentFunctions}

__all__ = ["agentFunctions", "AGENT_REGISTRY"]

