from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from schemas import ChatMessagePayload
from endpoints.agent.baseAgent import BaseAgent
from .use_chat_agents import ChatAgentRouter

logger = logging.getLogger("pdf_read_refresh.agent.use_function_calling")


class FunctionCallingContext(BaseModel):
    prompt: str
    conversation: List[ChatMessagePayload] = Field(default_factory=list)
    chat_id: Optional[str] = Field(default=None, alias="chatId")
    language: Optional[str] = None
    user_id: Optional[str] = Field(default=None, alias="userId")
    selected_file: Optional[Dict[str, Any]] = Field(default=None, alias="selectedFile")
    parameters: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class FunctionCallingResult(BaseModel):
    handled: bool = False
    leftover_prompt: str = Field("", alias="leftoverPrompt")
    agent_name: Optional[str] = Field(default=None, alias="agentName")
    agent_response: Optional[Dict[str, Any]] = Field(default=None, alias="agentResponse")

    model_config = {"populate_by_name": True}


class FunctionCallingService:
    def __init__(self, router: Optional[ChatAgentRouter] = None) -> None:
        self.router = router or ChatAgentRouter()

    @staticmethod
    def _serialize_conversation(conversation: List[ChatMessagePayload]) -> List[Dict[str, str]]:
        serialized: List[Dict[str, str]] = []
        for entry in conversation[-8:]:
            content = (entry.content or "").strip()
            if not content:
                continue
            serialized.append(
                {
                    "role": "assistant" if entry.role == "assistant" else "user",
                    "content": content,
                }
            )
        return serialized

    async def maybe_handle_agent_functions(self, ctx: FunctionCallingContext) -> FunctionCallingResult:
        prompt = (ctx.prompt or "").strip()
        if not prompt:
            logger.debug("FunctionCallingService: empty prompt, skipping")
            return FunctionCallingResult(handled=False, leftover_prompt="")

        conversation_payload = self._serialize_conversation(ctx.conversation or [])
        context_info = {
            "chatId": ctx.chat_id,
            "selectedFileName": ctx.selected_file.get("name") if ctx.selected_file else None,
            "selectedFileMimeType": ctx.selected_file.get("mimeType") if ctx.selected_file else None,
            "selectedFileSizeMb": ctx.selected_file.get("sizeMb") if ctx.selected_file else None,
        }

        logger.info(
            "FunctionCallingService detecting agent chatId=%s hasConversation=%s promptPreview=%s",
            ctx.chat_id,
            bool(conversation_payload),
            prompt[:120],
        )
        detection = await self.router.detect_agent(
            prompt=prompt,
            conversation=conversation_payload,
            context=context_info,
        )

        if not detection:
            logger.warning(
                "FunctionCallingService router returned no agent chatId=%s leftoverPromptPreview=%s",
                ctx.chat_id,
                prompt[:120],
            )
            return FunctionCallingResult(handled=False, leftover_prompt=prompt)

        target_agent: BaseAgent = detection["agent"]
        agent_args = detection.get("arguments", {}) or {}

        execute_args: Dict[str, Any] = {}
        execute_args.update(agent_args)
        execute_args.setdefault("prompt", prompt)
        execute_args.setdefault("chatId", ctx.chat_id)
        execute_args.setdefault("language", ctx.language)

        for key, value in ctx.parameters.items():
            execute_args.setdefault(key, value)

        if ctx.selected_file:
            execute_args.setdefault("selectedFile", ctx.selected_file)

        execute_args.setdefault("userId", ctx.user_id)

        logger.info(
            "FunctionCallingService dispatching agent=%s chatId=%s",
            target_agent.name,
            ctx.chat_id,
        )
        response = await target_agent.execute(execute_args, ctx.user_id or "")
        logger.info(
            "FunctionCallingService agent execution finished agent=%s chatId=%s success=%s",
            target_agent.name,
            ctx.chat_id,
            response.get("success", True),
        )

        return FunctionCallingResult(
            handled=True,
            leftover_prompt="",
            agent_name=target_agent.name,
            agent_response=response,
        )


__all__ = ["FunctionCallingService", "FunctionCallingContext", "FunctionCallingResult"]

