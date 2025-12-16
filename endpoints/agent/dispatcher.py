import logging
from typing import Any, Dict, List

from fastapi import HTTPException

from schemas import AgentDispatchRequest, ChatMessagePayload, ChatRequestPayload
from endpoints.chat.chat_service import chat_service
from core.useChatPersistence import chat_persistence
from functools import partial
import asyncio
from .select_agents.use_function_calling import (
    FunctionCallingContext,
    FunctionCallingResult,
    FunctionCallingService,
)
from core.usage_limits import increment_usage

logger = logging.getLogger("pdf_read_refresh.agent.dispatcher")
function_calling_service = FunctionCallingService()


async def determine_agent_and_run(payload: AgentDispatchRequest, user_id: str) -> Dict[str, Any]:
    effective_user = user_id or payload.user_id or ""
    logger.info(
        "Agent dispatch payload received userId=%s chatId=%s language=%s hasFile=%s",
        effective_user,
        payload.chat_id,
        payload.language,
        bool(payload.file_url or payload.file_urls),
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
    if payload.stream is not None:
        merged_params.setdefault("stream", payload.stream)

    if payload.file_url and "selectedFile" not in merged_params:
        merged_params["selectedFile"] = {
            "fileUrl": payload.file_url,
            "fileName": payload.file_name,
        }

    # Usage increment (backend-enforced)
    try:
        increment_usage(effective_user, is_premium=bool(merged_params.get("isPremiumUser") or merged_params.get("premium")))
    except Exception:
        logger.warning("Usage increment failed userId=%s", effective_user)

    # Kullanıcı mesajını (temp olmayan) Firestore'a yaz; agent flow'da da kaçmasın
    try:
        latest_user = None
        for msg in reversed(payload.conversation or []):
            if msg.role == "user":
                latest_user = msg
                break
        if not latest_user and payload.prompt:
            latest_user = ChatMessagePayload(
                role="user",
                content=payload.prompt,
                file_name=payload.file_name,
                file_url=payload.file_url,
                metadata=None,
                message_id=None,
            )
        if latest_user:
            await asyncio.to_thread(
                partial(
                    chat_persistence.save_user_message,
                    user_id=effective_user,
                    chat_id=payload.chat_id or "",
                    content=latest_user.content or "",
                    file_name=getattr(latest_user, "file_name", None),
                    file_url=getattr(latest_user, "file_url", None),
                    metadata=getattr(latest_user, "metadata", None),
                )
            )
    except Exception:
        logger.warning("Failed to persist user message in dispatcher", exc_info=True)

    context = FunctionCallingContext(
        prompt=payload.prompt or "",
        conversation=payload.conversation or [],
        chat_id=payload.chat_id,
        language=payload.language,
        user_id=effective_user,
        selected_file=merged_params.get("selectedFile"),
        parameters=merged_params,
    )

    logger.info("Dispatcher invoking FunctionCallingService chatId=%s", payload.chat_id)
    result: FunctionCallingResult = await function_calling_service.maybe_handle_agent_functions(context)

    if not result.handled:
        logger.info(
            "FunctionCallingService returned unhandled response chatId=%s leftoverLen=%s -> forwarding to /api/v1/chat/send",
            payload.chat_id,
            len(result.leftover_prompt or ""),
        )
        return await _forward_to_default_chat(payload, effective_user)

    logger.info(
        "Agent handled successfully agent=%s chatId=%s",
        result.agent_name,
        payload.chat_id,
    )

    if not result.agent_response:
        logger.error(
            "Agent returned empty response agent=%s chatId=%s",
            result.agent_name,
            payload.chat_id,
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
        "Dispatch fallback building chat payload chatId=%s conversationCount=%s promptPreview=%s",
        payload.chat_id,
        len(payload.conversation or []),
        (payload.prompt or "")[:120],
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
                metadata=getattr(entry, "metadata", None),
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
                "Dispatch fallback appending prompt chatId=%s promptPreview=%s",
                payload.chat_id,
                prompt_text[:200],
            )
            fallback_messages.append(
                ChatMessagePayload(
                    role="user",
                    content=prompt_text,
                    file_name=payload.file_name,
                    file_url=payload.file_url,
                    metadata=None,
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
        "Forwarding dispatch payload to ChatService chatId=%s messageCount=%s hasImage=%s imageFileUrl=%s",
        payload.chat_id,
        len(chat_payload.messages),
        chat_payload.has_image,
        chat_payload.image_file_url,
    )
    return await chat_service.send_message(chat_payload, user_id)

