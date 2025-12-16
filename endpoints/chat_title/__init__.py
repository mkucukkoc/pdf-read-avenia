from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .service import generate_chat_title


logger = logging.getLogger("pdf_read_refresh.chat_title_router")

router = APIRouter(prefix="/api/v1/chat", tags=["ChatTitle"])


class ChatTitleRequest(BaseModel):
    text: str
    language: Optional[str] = None
    chat_id: Optional[str] = Field(default=None, alias="chatId")

    class Config:
        populate_by_name = True


@router.post("/title")
async def create_chat_title(payload: ChatTitleRequest) -> Dict[str, Any]:
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "invalid_text", "message": "text is required"},
        )
    title = await generate_chat_title(text, payload.language)
    if not title:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "title_generation_failed", "message": "Başlık üretilemedi"},
        )
    logger.info(
        "Chat title generated",
        extra={"chatId": payload.chat_id, "language": payload.language, "title": title},
    )
    return {"success": True, "data": {"title": title}}


__all__ = ["router", "generate_chat_title"]

