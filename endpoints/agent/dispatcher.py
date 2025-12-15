import logging
from typing import Any, Dict, List

from fastapi import HTTPException

from schemas import AgentDispatchRequest, ChatMessagePayload, ChatRequestPayload
from endpoints.chat.chat_service import chat_service
from .select_agents.use_function_calling import (
    FunctionCallingContext,
    FunctionCallingResult,
    FunctionCallingService,
)

logger = logging.getLogger("pdf_read_refresh.agent.dispatcher")
function_calling_service = FunctionCallingService()


async def determine_agent_and_run(payload: AgentDispatchRequest, user_id: str) -> Dict[str, Any]:
    effective_user = user_id or payload.user_id or ""
    logger.info(
        "Agent dispatch payload received",
        extra={
            "userId": effective_user,
            "chatId": payload.chat_id,
            "language": payload.language,
            "hasFile": bool(payload.file_url or payload.file_urls),
        },
    )

    merged_params: Dict[str, Any] = dict(payload.parameters or {})
    if payload.file_url is not None:
        merged_params.setdefault("fileUrl", payload.file_url)
    if payload.file_urls is not None:
        merged_params.setdefault("fileUrls", payload.file_urls)
    if payload.file1 is not None:
        merged_params.setdefault("file1", payload.file1)
    if payload.file2 is not None:
        merged_params.setdefault("file2", payload.file2)
    if payload.question is not None:
        merged_params.setdefault("question", payload.question)
    if payload.file_id is not None:
        merged_params.setdefault("fileId", payload.file_id)
    if payload.file_name is not None:
        merged_params.setdefault("fileName", payload.file_name)
    if payload.target_language is not None:
        merged_params.setdefault("targetLanguage", payload.target_language)
    if payload.source_language is not None:
        merged_params.setdefault("sourceLanguage", payload.source_language)

    if payload.file_url and "selectedFile" not in merged_params:
        merged_params["selectedFile"] = {
            "fileUrl": payload.file_url,
            "fileName": payload.file_name,
        }

    context = FunctionCallingContext(
        prompt=payload.prompt or "",
        conversation=payload.conversation or [],
        chat_id=payload.chat_id,
        language=payload.language,
        user_id=effective_user,
        selected_file=merged_params.get("selectedFile"),
        parameters=merged_params,
    )

    logger.info("Dispatcher invoking FunctionCallingService", extra={"chatId": payload.chat_id})
    result: FunctionCallingResult = await function_calling_service.maybe_handle_agent_functions(context)

    if not result.handled:
        logger.info(
            "FunctionCallingService returned unhandled response, forwarding to /api/v1/chat/send",
            extra={"chatId": payload.chat_id, "leftover": result.leftover_prompt},
        )
        return await _forward_to_default_chat(payload, effective_user)

    logger.info(
        "Agent handled successfully",
        extra={"agent": result.agent_name, "chatId": payload.chat_id},
    )

    if not result.agent_response:
        logger.error(
            "Agent returned empty response",
            extra={"agent": result.agent_name, "chatId": payload.chat_id},
        )
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "agent_empty_response",
                "message": "Agent geçerli bir yanıt döndürmedi.",
            },
        )

    return result.agent_response


async def _forward_to_default_chat(payload: AgentDispatchRequest, user_id: str) -> Dict[str, Any]:
    if not payload.chat_id:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "chat_id_required",
                "message": "chatId alanı gereklidir.",
            },
        )

    logger.info(
        "Dispatch fallback: building chat payload for /send",
        extra={
            "chatId": payload.chat_id,
            "conversationCount": len(payload.conversation or []),
            "promptPreview": (payload.prompt or "")[:120],
        },
    )

    fallback_messages: List[ChatMessagePayload] = []
    conversation = payload.conversation or []
    for entry in conversation:
        fallback_messages.append(
            ChatMessagePayload(
                role=entry.role,
                content=entry.content,
                timestamp=entry.timestamp,
                file_name=entry.file_name,
                file_url=entry.file_url,
            )
        )

    prompt_text = (payload.prompt or "").strip()
    if prompt_text:
        should_append_prompt = True
        if fallback_messages:
            last_msg = fallback_messages[-1]
            if last_msg.role == "user" and (last_msg.content or "").strip() == prompt_text:
                should_append_prompt = False
        if should_append_prompt:
            logger.debug(
                "Dispatch fallback: appending prompt as tail user message",
                extra={"chatId": payload.chat_id, "promptPreview": prompt_text[:200]},
            )
            fallback_messages.append(
                ChatMessagePayload(
                    role="user",
                    content=prompt_text,
                    file_name=payload.file_name,
                    file_url=payload.file_url,
                )
            )

    if not fallback_messages:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "empty_conversation",
                "message": "Gönderilecek mesaj bulunamadı.",
            },
        )

    parameters = payload.parameters or {}
    has_image = bool(
        parameters.get("hasImage")
        or payload.file_url
        or any(msg.file_url for msg in fallback_messages)
    )
    image_file_url = (
        parameters.get("imageFileUrl")
        or payload.file_url
        or (fallback_messages[-1].file_url if has_image else None)
    )

    chat_payload = ChatRequestPayload(
        messages=fallback_messages,
        chat_id=payload.chat_id,
        has_image=has_image,
        image_file_url=image_file_url,
        language=payload.language,
        stream=payload.stream,
    )

    logger.info(
        "Forwarding dispatch payload to ChatService.send_message",
        extra={
            "chatId": payload.chat_id,
            "messageCount": len(chat_payload.messages),
            "hasImage": chat_payload.has_image,
            "imageFileUrl": chat_payload.image_file_url,
        },
    )
    return await chat_service.send_message(chat_payload, user_id)

