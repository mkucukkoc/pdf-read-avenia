import logging
import os
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from core.useChatPersistence import chat_persistence
from endpoints.agent.utils import get_request_user_id
from core.websocket_manager import stream_manager
from schemas import WebSearchRequest

logger = logging.getLogger("pdf_read_refresh.web_search")

router = APIRouter(prefix="/api/v1/web-search", tags=["WebSearch"])

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = os.getenv("GEMINI_WEB_SEARCH_MODEL", "models/gemini-2.5-flash")


async def _call_gemini_web_search(prompt: str, api_key: str, model: str, urls: Optional[list[str]] = None) -> Dict[str, Any]:
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_api_key_missing", "message": "GEMINI_API_KEY env is required"},
        )

    parts: list[Dict[str, Any]] = [{"text": prompt}]
    if urls:
        url_lines = "\n".join(urls)
        parts.append({"text": f"Context URLs:\n{url_lines}"})

    payload = {
        "contents": [{"parts": parts}],
        "tools": [{"google_search": {}}],
    }

    url = f"{API_BASE}/{model}:generateContent?key={api_key}"
    logger.info("Web search call", extra={"model": model, "prompt_preview": prompt[:120], "url_count": len(urls or [])})
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(url, json=payload)

    body_preview = (resp.text or "")[:800]
    logger.info("Web search response status=%s", resp.status_code, extra={"body_preview": body_preview})
    if not resp.is_success:
        raise HTTPException(
            status_code=resp.status_code,
            detail={"success": False, "error": "web_search_failed", "message": body_preview},
        )
    return resp.json()


def _extract_text(result: Dict[str, Any]) -> str:
    candidates = result.get("candidates") or []
    for cand in candidates:
        parts = (cand.get("content") or {}).get("parts") or []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                return part["text"]
    # fallback
    return ""


async def run_web_search(payload: WebSearchRequest, user_id: str) -> Dict[str, Any]:
    prompt = (payload.prompt or "").strip()
    if not prompt:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "prompt_required", "message": "prompt is required"},
        )

    api_key = os.getenv("GEMINI_API_KEY", "")
    model = DEFAULT_MODEL if DEFAULT_MODEL.startswith("models/") else f"models/{DEFAULT_MODEL}"
    language = normalize_language(payload.language) or "Turkish"

    logger.info(
        "WebSearch start userId=%s chatId=%s lang=%s urls=%s",
        user_id,
        payload.chat_id,
        language,
        len(payload.urls or []),
    )

    result = await _call_gemini_web_search(prompt, api_key, model, payload.urls)
    text = _extract_text(result)
    if not text:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "web_search_empty", "message": "No text returned from web search"},
        )

    message_id = f"web_search_{result.get('id') or ''}"
    if payload.chat_id:
        try:
            chat_persistence.save_assistant_message(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=text,
                metadata={"source": "web_search", "model": model},
                message_id=message_id,
            )
        except Exception:
            logger.warning("Failed to persist web search message chatId=%s userId=%s", payload.chat_id, user_id, exc_info=True)

        try:
            await stream_manager.emit_chunk(
                payload.chat_id,
                {
                    "chatId": payload.chat_id,
                    "messageId": message_id,
                    "tool": "web_search",
                    "content": text,
                    "isFinal": True,
                },
            )
        except Exception:
            logger.warning("WebSearch streaming emit failed chatId=%s", payload.chat_id, exc_info=True)

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
async def web_search_endpoint(payload: WebSearchRequest, request: Request) -> Dict[str, Any]:
    user_id = get_request_user_id(request) or payload.user_id or ""
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={"success": False, "error": "unauthorized", "message": "Kullanıcı kimliği gerekiyor."},
        )

    return await run_web_search(payload, user_id)


__all__ = ["router", "run_web_search"]

