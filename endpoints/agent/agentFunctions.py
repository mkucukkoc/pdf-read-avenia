from __future__ import annotations

from typing import Dict, List

from .baseAgent import BaseAgent
from .files_pdf import pdf_agent_functions
from .files_word import word_agent_functions
from .files_pptx import pptx_agent_functions
from .image_gemini import image_gemini_agents
from .search_google import search_google_agents
from .generate_doc import generate_doc_agents
from .generate_ppt import generate_ppt_agents
from .generate_pdf import generate_pdf_agents
from .ai_or_not import ai_or_not_agents

agentFunctions: List[BaseAgent] = [
    *image_gemini_agents,
    *pdf_agent_functions,
    *word_agent_functions,
    *pptx_agent_functions,
    *search_google_agents,
    *generate_doc_agents,
    *generate_ppt_agents,
    *generate_pdf_agents,
    *ai_or_not_agents,
]

AGENT_REGISTRY: Dict[str, BaseAgent] = {agent.name: agent for agent in agentFunctions}

__all__ = ["agentFunctions", "AGENT_REGISTRY"]

