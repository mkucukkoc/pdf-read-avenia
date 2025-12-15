from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from core.openai_client import get_client
from endpoints.agent.agentFunctions import agentFunctions
from endpoints.agent.baseAgent import BaseAgent

logger = logging.getLogger("pdf_read_refresh.agent.use_chat_agents")

DEFAULT_ROUTER_MODEL = "gpt-4o-mini"


def build_system_prompt(context: Optional[Dict[str, Any]]) -> str:
    available_tools = "\n".join([f"- {agent.name}: {agent.description}" for agent in agentFunctions])
    lines = [
        "You are an orchestrator that decides whether the assistant should call a function (tool).",
        "If none of the tools are relevant, respond normally without calling a tool.",
        "Only call a single tool when it is clearly required to fulfil the user request.",
        "Always prefer structured data in function arguments. Leave out fields the user did not provide.",
        "",
        "IMPORTANT routing rules:",
        "- If the user requests to analyze an image, and the message contains any URL (including Turkish placeholder like \"[Dosya Bağlantısı]: <url>\"), you MUST call the detect_ai_image tool.",
        "- When calling detect_ai_image, set arguments.imageFileUrl to the URL found in the latest user message (extract the first http/https URL).",
        "- CRITICAL: If the user explicitly asks to check if the image is AI-generated, AI-created, or asks \"AI mı?\", \"yapay zeka mı?\", \"bu AI tarafından mı üretildi?\", set arguments.checkAi = true.",
        "- If the user just wants to analyze/describe/explain the image WITHOUT asking about AI generation, do NOT set checkAi or set it to false.",
        "- If the user wants to modify/edit/retouch an existing image, call the image_edit_gemini tool with the latest available image URL.",
        "- If the user explicitly asks for multi-step image editing on the same image, prefer image_edit_gemini_multi.",
        "- CRITICAL FILE ROUTING: If a file is attached and the user asks to summarize/analyze/explain/extract content from the file, you MUST call summarize_file_flow.",
        "- create_pptx/create_docx/generate_excel are ONLY for creating new documents/presentations/spreadsheets, not summarizing uploaded files.",
        "- When calling summarize_file_flow with an attached file, pass the user prompt and selected file metadata. Include chatId when available.",
        "",
        "Available tools:",
        available_tools,
    ]

    chat_id = context.get("chatId") if context else None
    if chat_id:
        lines.append("")
        lines.append(f"Current chat id: {chat_id}")

    if context:
        file_name = context.get("selectedFileName")
        if file_name:
            lines.append("")
            lines.append("Currently attached file:")
            lines.append(f"- name: {file_name}")
            mime = context.get("selectedFileMimeType")
            if mime:
                lines.append(f"- mimeType: {mime}")
            size_mb = context.get("selectedFileSizeMb")
            if size_mb is not None:
                lines.append(f"- sizeMb: {size_mb}")

    return "\n".join(filter(None, lines))


def serialize_conversation(conversation: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    if not conversation:
        return []
    normalized = []
    for entry in conversation[-8:]:
        content = (entry.get("content") or "").strip()
        role = entry.get("role")
        if not content:
            continue
        normalized.append(
            {
                "role": "assistant" if role == "assistant" else "user",
                "content": content,
            }
        )
    return normalized


def build_tool_definitions() -> List[Dict[str, Any]]:
    tools = []
    for agent in agentFunctions:
        logger.debug(
            "Registering agent tool %s schemaKeys=%s",
            agent.name,
            list(agent.parameters.get("properties", {}).keys()),
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": agent.name,
                    "description": agent.description,
                    "parameters": agent.parameters or {},
                },
            }
        )
    return tools


class ChatAgentRouter:
    def __init__(self, model: str = DEFAULT_ROUTER_MODEL) -> None:
        self.client = get_client()
        self.model = model

    async def detect_agent(
        self,
        *,
        prompt: str,
        conversation: Optional[List[Dict[str, str]]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        prompt = (prompt or "").strip()
        if not prompt:
            return None

        system_prompt = build_system_prompt(context)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(serialize_conversation(conversation))
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "tool_choice": "auto",
            "tools": build_tool_definitions(),
        }

        logger.debug("Agent router request prepared model=%s", self.model)
        response = await asyncio.to_thread(self.client.chat.completions.create, **payload)
        choice = (response.choices or [None])[0]
        if not choice:
            return None

        tool_call = None
        if choice.message and choice.message.tool_calls:
            tool_call = choice.message.tool_calls[0]
        function_call = tool_call.function if tool_call else getattr(choice.message, "function_call", None)
        if not function_call or not function_call.name:
            return None

        target_agent = next((agent for agent in agentFunctions if agent.name == function_call.name), None)
        if not target_agent:
            logger.warning("No agent found for router result functionName=%s", function_call.name)
            return None

        raw_args = function_call.arguments or "{}"
        if isinstance(raw_args, dict):
            parsed_args = raw_args
            raw_arguments = json.dumps(raw_args)
        else:
            raw_arguments = raw_args
            try:
                parsed_args = json.loads(raw_args or "{}")
            except json.JSONDecodeError as exc:
                logger.warning(
                    "Failed to parse function arguments JSON rawArgs=%s error=%s",
                    raw_args,
                    str(exc),
                )
                parsed_args = {}

        if not parsed_args:
            logger.warning(
                "Agent selected but no arguments provided agent=%s",
                target_agent.name,
            )

        logger.debug(
            "Agent router selected tool agent=%s rawArgs=%s",
            target_agent.name,
            raw_arguments,
        )

        return {
            "agent": target_agent,
            "arguments": parsed_args,
            "raw_arguments": raw_arguments,
        }


__all__ = ["ChatAgentRouter"]

