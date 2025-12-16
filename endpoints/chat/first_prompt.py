from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core.auth import get_request_user_id  # type: ignore[attr-defined]
from core.useChatPersistence import chat_persistence


logger = logging.getLogger("pdf_read_refresh.chat.first_prompt")

router = APIRouter(prefix="/api/v1/chat", tags=["ChatFirstPrompt"])


class FirstPromptRequest(BaseModel):
    chat_id: str = Field(alias="chatId")
    content: str
    language: Optional[str] = None
    file_name: Optional[str] = Field(default=None, alias="fileName")
    file_url: Optional[str] = Field(default=None, alias="fileUrl")
    metadata: Optional[Dict[str, Any]] = None

    model_config = {"populate_by_name": True}


@router.post("/first_prompt")
async def save_first_prompt(payload: FirstPromptRequest, request: Request) -> Dict[str, Any]:
    user_id = get_request_user_id(request)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={"success": False, "error": "unauthorized", "message": "Auth gerekli"},
        )

    content = (payload.content or "").strip()
    if not content:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "invalid_content", "message": "content zorunlu"},
        )

    try:
        message_id = await chat_persistence.save_user_message(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=content,
            file_name=payload.file_name,
            file_url=payload.file_url,
            metadata={**(payload.metadata or {}), "source": "first_prompt"},
        )
        logger.info(
            "First prompt saved userId=%s chatId=%s messageId=%s",
            user_id,
            payload.chat_id,
            message_id,
        )
        return {"success": True, "data": {"messageId": message_id}}
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to save first prompt chatId=%s", payload.chat_id)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "internal_error", "message": "İlk prompt kaydedilemedi"},
        ) from exc


__all__ = ["router"]

