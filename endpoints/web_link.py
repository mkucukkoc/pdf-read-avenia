import logging
import os
import re
import uuid
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from core.tone_instructions import build_tone_instruction
from core.useChatPersistence import chat_persistence
from endpoints.agent.utils import get_request_user_id
from core.websocket_manager import stream_manager
from schemas import WebSearchRequest
from endpoints.logging.utils_logging import log_gemini_request, log_gemini_response, log_request, log_response
from errors_response.api_errors import get_api_error_message

logger = logging.getLogger("pdf_read_refresh.web_link")

router = APIRouter(prefix="/api/v1/web-link", tags=["WebLink"])

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = os.getenv("GEMINI_WEB_SEARCH_MODEL", "models/gemini-2.5-flash")


async def _call_gemini_web_link(
    prompt: str,
    api_key: str,
    model: str,
    urls: Optional[list[str]] = None,
    system_instruction: Optional[str] = None,
) -> Dict[str, Any]:
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
    if system_instruction:
        payload["system_instruction"] = {"parts": [{"text": system_instruction}]}

    url = f"{API_BASE}/{model}:generateContent?key={api_key}"
    log_gemini_request(
        logger,
        "web_link",
        url=url,
        payload=payload,
        model=model,
    )
    logger.info(
        "Web link call",
        extra={
            "model": model,
            "prompt_preview": prompt[:200],
            "url_count": len(urls or []),
        },
    )
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(url, json=payload)

    body_preview = (resp.text or "")[:800]
    response_json = resp.json() if resp.text else {}
    log_gemini_response(
        logger,
        "web_link",
        url=url,
        status_code=resp.status_code,
        response=response_json,
    )
    logger.info("Web link response status=%s", resp.status_code, extra={"body_preview": body_preview})
    if not resp.is_success:
        raise HTTPException(
            status_code=resp.status_code,
            detail={"success": False, "error": "web_link_failed", "message": body_preview},
        )
    return response_json


def _extract_text(result: Dict[str, Any]) -> str:
    candidates = result.get("candidates") or []
    for cand in candidates:
        parts = (cand.get("content") or {}).get("parts") or []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                return part["text"]
    return ""


def _strip_markdown_stars(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\*", "", text)


async def _emit_streaming_text(chat_id: str, message_id: str, tool: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> None:
    if not chat_id:
        return
    chunk_size = 600
    accumulated = ""
    total = len(text)
    for start in range(0, total, chunk_size):
        chunk = text[start : start + chunk_size]
        accumulated += chunk
        payload: Dict[str, Any] = {
            "chatId": chat_id,
            "messageId": message_id,
            "tool": tool,
            "delta": chunk,
            "content": accumulated,
            "isFinal": False,
        }
        if metadata:
            payload["metadata"] = metadata
        await stream_manager.emit_chunk(chat_id, payload)

    final_payload: Dict[str, Any] = {
        "chatId": chat_id,
        "messageId": message_id,
        "tool": tool,
        "content": accumulated,
        "delta": None,
        "isFinal": True,
    }
    if metadata:
        final_payload["metadata"] = metadata
    await stream_manager.emit_chunk(chat_id, final_payload)


async def run_web_link(payload: WebSearchRequest, user_id: str) -> Dict[str, Any]:
    client_message_id = getattr(payload, "client_message_id", None)
    def _map_error_key(status_code: int) -> str:
        if status_code == 404:
            return "upstream_404"
        if status_code == 429:
            return "upstream_429"
        if status_code in (401, 403):
            return "upstream_401"
        if status_code == 408:
            return "upstream_timeout"
        if status_code >= 500:
            return "upstream_500"
        return "unknown_error"

    def _error_response(language: str, chat_id: Optional[str], user_id: str, status_code: int, detail: Any) -> Dict[str, Any]:
        key = _map_error_key(status_code)
        msg = get_api_error_message(key, language)
        message_id = client_message_id or f"web_link_error_{os.urandom(4).hex()}"
        try:
            chat_persistence.save_assistant_message(
                user_id=user_id,
                chat_id=chat_id or "",
                content=msg,
                metadata={"source": "web_link", "error": key, "detail": detail},
                message_id=message_id,
                client_message_id=client_message_id or message_id,
            )
        except Exception:
            logger.warning("WebLink error persist failed chatId=%s userId=%s", chat_id, user_id, exc_info=True)

        payload = {
            "success": True,
            "data": {
                "message": {
                    "content": msg,
                    "id": message_id,
                },
                "streaming": False,
            },
        }
        try:
            log_response(logger, "web_link_error", payload)
        except Exception:
            logger.warning("WebLink error response logging failed")
        return payload

    log_request(logger, "web_link", payload)
    prompt = (payload.prompt or "").strip()
    language = normalize_language(payload.language) or "Turkish"
    if not prompt:
        return _error_response(language, payload.chat_id, user_id, 400, "prompt_required")
    followup_instruction = (
        f"Always end your response with a concise, relevant follow-up question to the user, in {language}."
    )
    prompt_with_followup = f"{prompt}\n\n{followup_instruction}"

    try:
        api_key = os.getenv("GEMINI_API_KEY", "")
        model = DEFAULT_MODEL if DEFAULT_MODEL.startswith("models/") else f"models/{DEFAULT_MODEL}"

        logger.info(
            "WebLink start userId=%s chatId=%s lang=%s urls=%s",
            user_id,
            payload.chat_id,
            language,
            len(payload.urls or []),
        )

        tone_instruction = build_tone_instruction(payload.tone_key, language)
        result = await _call_gemini_web_link(
            prompt_with_followup,
            api_key,
            model,
            payload.urls,
            system_instruction=tone_instruction,
        )
        text = _strip_markdown_stars(_extract_text(result))
        if not text:
            logger.error(
                "Web link returned empty text",
                extra={"payload_preview": str(result)[:800]},
            )
            return _error_response(language, payload.chat_id, user_id, 500, "web_link_empty")

        logger.info("Web link extracted text", extra={"text_len": len(text), "text_preview": text[:400]})

        message_id = client_message_id or f"web_link_{result.get('id') or uuid.uuid4().hex}"
        streaming_enabled = bool(payload.chat_id)
        if payload.chat_id:
            try:
                chat_persistence.save_assistant_message(
                    user_id=user_id,
                    chat_id=payload.chat_id,
                    content=text,
                    metadata={"source": "web_link", "model": model},
                    message_id=message_id,
                    client_message_id=client_message_id or message_id,
                )
            except Exception:
                logger.warning("Failed to persist web link message chatId=%s userId=%s", payload.chat_id, user_id, exc_info=True)

            try:
                await _emit_streaming_text(
                    chat_id=payload.chat_id,
                    message_id=message_id,
                    tool="web_link",
                    text=text,
                    metadata={"model": model},
                )
            except Exception:
                logger.warning("WebLink streaming emit failed chatId=%s", payload.chat_id, exc_info=True)

        response_payload = {
            "success": True,
            "data": {
                "message": {
                    "content": text,
                    "id": message_id,
                },
                "streaming": streaming_enabled,
            },
        }
        try:
            log_response(logger, "web_link", response_payload)
        except Exception:
            logger.warning("WebLink response logging failed")
        return response_payload
    except HTTPException as he:
        logger.error("WebLink HTTPException", exc_info=he)
        return _error_response(language, payload.chat_id, user_id, he.status_code, he.detail)
    except Exception as exc:
        logger.exception("WebLink unexpected error")
        return _error_response(language, payload.chat_id, user_id, 500, str(exc))


@router.post("")
async def web_link_endpoint(payload: WebSearchRequest, request: Request) -> Dict[str, Any]:
    user_id = get_request_user_id(request) or payload.user_id or ""
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={"success": False, "error": "unauthorized", "message": "Kullanıcı kimliği gerekiyor."},
        )

    return await run_web_link(payload, user_id)


__all__ = ["router", "run_web_link"]
