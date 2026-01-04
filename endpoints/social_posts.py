import logging
import os
from typing import Any, Dict

import httpx
from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from core.useChatPersistence import chat_persistence
from core.websocket_manager import stream_manager
from endpoints.agent.utils import get_request_user_id
from schemas import SocialPostRequest

logger = logging.getLogger("pdf_read_refresh.social_posts")

router = APIRouter(prefix="/api/v1/social-posts", tags=["SocialPosts"])

GEMINI_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-1.5-pro")
API_BASE = "https://generativelanguage.googleapis.com/v1beta"


async def _call_gemini(prompt: str, api_key: str, model: str) -> str:
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_api_key_missing", "message": "GEMINI_API_KEY env is required"},
        )

    payload: Dict[str, Any] = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                ]
            }
        ]
    }

    logger.info("SocialPosts Gemini API call", extra={"model": model})
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{API_BASE}/models/{model}:generateContent?key={api_key}", json=payload)

    logger.info(
        "SocialPosts Gemini API response",
        extra={"status": resp.status_code, "body_preview": (resp.text or "")[:800]},
    )

    if not resp.is_success:
        body_preview = (resp.text or "")[:400]
        raise HTTPException(
            status_code=resp.status_code,
            detail={"success": False, "error": "social_posts_failed", "message": body_preview},
        )

    data = resp.json()
    candidates = data.get("candidates") or []
    for cand in candidates:
        content = cand.get("content") or {}
        parts = content.get("parts") or []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                return part["text"]
    raise HTTPException(
        status_code=500,
        detail={"success": False, "error": "social_posts_empty", "message": "No text generated for social post"},
    )


async def run_social_posts(payload: SocialPostRequest, user_id: str) -> Dict[str, Any]:
    prompt = (payload.prompt or "").strip()
    if not prompt:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "prompt_required", "message": "prompt is required"},
        )

    api_key = os.getenv("GEMINI_API_KEY", "")
    model = GEMINI_MODEL
    language = normalize_language(payload.language) or "Turkish"

    styled_prompt = f"""Write an engaging, emoji-rich social media post for the topic below.
- Keep it friendly and inspiring.
- Add a call-to-action and 8-12 relevant hashtags.
- Language: {language}

Topic:
{prompt}
"""

    logger.info("SocialPosts start", extra={"userId": user_id, "chatId": payload.chat_id, "lang": language})
    text = await _call_gemini(styled_prompt, api_key, model)

    message_id = f"social_posts_{hash(prompt)}"
    if payload.chat_id:
        try:
            chat_persistence.save_assistant_message(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=text,
                metadata={"source": "social_posts"},
                message_id=message_id,
            )
        except Exception:
            logger.warning("SocialPosts persist failed chatId=%s userId=%s", payload.chat_id, user_id, exc_info=True)

        try:
            await stream_manager.emit_chunk(
                payload.chat_id,
                {
                    "chatId": payload.chat_id,
                    "messageId": message_id,
                    "tool": "social_posts",
                    "content": text,
                    "isFinal": True,
                },
            )
        except Exception:
            logger.warning("SocialPosts streaming emit failed chatId=%s", payload.chat_id, exc_info=True)

    return {
        "success": True,
        "data": {
            "message": {
                "content": text,
                "id": message_id,
            },
            "streaming": True,
        },
    }


@router.post("")
async def social_posts_endpoint(payload: SocialPostRequest, request: Request) -> Dict[str, Any]:
    user_id = get_request_user_id(request) or payload.user_id or ""
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={"success": False, "error": "unauthorized", "message": "Kullanıcı kimliği gerekiyor."},
        )
    return await run_social_posts(payload, user_id)


__all__ = ["router", "run_social_posts"]

