import logging
import uuid
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from schemas import (
    ChatRequestPayload,
    CreateChatRequest,
    TextToSpeechRequest,
)
from .chat_service import chat_service

logger = logging.getLogger("pdf_read_refresh.chat_routes")

router = APIRouter(prefix="/api/v1/chat", tags=["Chat"])


def _extract_user_id(request: Request) -> str:
    payload = getattr(request.state, "token_payload", {}) or {}
    return (
        payload.get("uid")
        or payload.get("userId")
        or payload.get("sub")
        or ""
    )


def _build_usage_request(payload: ChatRequestPayload, request: Request) -> Dict[str, Any]:
    token_payload = getattr(request.state, "token_payload", {}) or {}
    request_id = (
        getattr(payload, "client_message_id", None)
        or request.headers.get("x-request-id")
        or request.headers.get("x-requestid")
        or f"req_{uuid.uuid4().hex}"
    )
    return {
        "request": request,
        "token_payload": token_payload,
        "request_id": request_id,
    }


@router.post("/send")
async def send_chat_message(payload: ChatRequestPayload, request: Request) -> Dict[str, Any]:
    user_id = _extract_user_id(request)
    try:
        logger.info(
            "Chat send request received",
            extra={"userId": user_id, "payload": payload.model_dump()},
        )
        usage_request = _build_usage_request(payload, request)
        result = await chat_service.send_message(payload, user_id, usage_request=usage_request)
        logger.debug("Chat send response payload", extra={"userId": user_id, "response": result})
        return result
    except ValueError as exc:
        logger.warning("Invalid chat send request: %s", exc)
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "invalid_request",
                "message": str(exc),
            },
        ) from exc
    except RuntimeError as exc:
        logger.error("Chat send runtime error: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "chat_processing_failed",
                "message": str(exc),
            },
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Unexpected error while sending chat message")
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "internal_server_error",
                "message": "Failed to process chat message",
            },
        ) from exc


@router.post("/tts")
async def text_to_speech_endpoint(payload: TextToSpeechRequest, request: Request) -> Dict[str, Any]:
    _ = _extract_user_id(request)  # Ensure token validation occurs
    try:
        logger.info(
            "Text-to-speech request received",
            extra={"messageCount": len(payload.messages)},
        )
        result = await chat_service.text_to_speech(payload.messages)
        logger.debug("Text-to-speech response payload", extra={"response": result})
        return result
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Failed to convert text to speech")
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "internal_server_error",
                "message": "Failed to convert text to speech",
            },
        ) from exc


@router.get("/messages/{chat_id}")
async def get_chat_messages(chat_id: str, request: Request) -> Dict[str, Any]:
    user_id = _extract_user_id(request)
    try:
        logger.info(
            "Get chat messages request received",
            extra={"userId": user_id, "chatId": chat_id},
        )
        result = await chat_service.get_chat_messages(user_id, chat_id)
        logger.debug("Get chat messages response payload", extra={"userId": user_id, "response": result})
        return result
    except ValueError as exc:
        logger.warning("Invalid get messages request: %s", exc)
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "invalid_request",
                "message": str(exc),
            },
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Failed to retrieve chat messages")
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "internal_server_error",
                "message": "Failed to retrieve chat messages",
            },
        ) from exc


@router.post("/create")
async def create_chat_endpoint(payload: CreateChatRequest, request: Request) -> Dict[str, Any]:
    user_id = _extract_user_id(request)
    try:
        logger.info(
            "Create chat request received",
            extra={"userId": user_id, "title": payload.title},
        )
        result = await chat_service.create_chat(user_id, payload.title)
        logger.debug("Create chat response payload", extra={"userId": user_id, "response": result})
        return result
    except ValueError as exc:
        logger.warning("Invalid create chat request: %s", exc)
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "invalid_request",
                "message": str(exc),
            },
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Failed to create chat")
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "internal_server_error",
                "message": "Failed to create chat",
            },
        ) from exc


__all__ = ["router", "chat_service"]









