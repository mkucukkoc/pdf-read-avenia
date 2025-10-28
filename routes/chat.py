import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from ..schemas import (
    ChatRequestPayload,
    CreateChatRequest,
    TextToSpeechRequest,
)
from ..services import chat_service

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


@router.post("/send")
async def send_chat_message(payload: ChatRequestPayload, request: Request) -> Dict[str, Any]:
    user_id = _extract_user_id(request)
    try:
        return await chat_service.send_message(payload, user_id)
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
        return await chat_service.text_to_speech(payload.messages)
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
        return await chat_service.get_chat_messages(user_id, chat_id)
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
        return await chat_service.create_chat(user_id, payload.title)
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


__all__ = ["router"]
