import logging
import os
import re
import uuid
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request

from core.gemini_prompt import build_system_message, merge_parts_with_system
from core.language_support import normalize_language
from core.firebase import db
from core.useChatPersistence import chat_persistence
from endpoints.agent.utils import get_request_user_id
from core.websocket_manager import stream_manager
from schemas import WebSearchRequest
from endpoints.logging.utils_logging import log_gemini_request, log_gemini_response, log_request, log_response
from errors_response.api_errors import get_api_error_message
from usage_tracking import build_base_event, finalize_event, parse_gemini_usage, enqueue_usage_update

logger = logging.getLogger("pdf_read_refresh.web_search")

router = APIRouter(prefix="/api/v1/web-search", tags=["WebSearch"])

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = os.getenv("GEMINI_WEB_SEARCH_MODEL", "models/gemini-2.5-flash")


def _build_usage_context(
    payload: WebSearchRequest,
    user_id: str,
    model: str,
    request: Optional[Request],
) -> Optional[Dict[str, Any]]:
    if not user_id:
        return None
    token_payload = getattr(request.state, "token_payload", {}) if request else {}
    request_id = (
        getattr(payload, "client_message_id", None)
        or (request.headers.get("x-request-id") if request else None)
        or (request.headers.get("x-requestid") if request else None)
        or f"req_{uuid.uuid4().hex}"
    )
    return build_base_event(
        request_id=request_id,
        user_id=user_id,
        endpoint="web_search",
        provider="gemini",
        model=model,
        token_payload=token_payload,
        request=request,
    )


def _enqueue_usage_event(
    usage_context: Optional[Dict[str, Any]],
    usage_data: Dict[str, int],
    latency_ms: int,
    *,
    status: str,
    error_code: Optional[str],
) -> None:
    if not usage_context or not db:
        return
    try:
        event = finalize_event(
            usage_context,
            input_tokens=usage_data.get("inputTokens", 0),
            output_tokens=usage_data.get("outputTokens", 0),
            latency_ms=latency_ms,
            status=status,
            error_code=error_code,
        )
        enqueue_usage_update(db, event)
    except Exception:
        logger.warning("Usage tracking failed for web_search", exc_info=True)


async def _call_gemini_web_search(
    prompt: str,
    api_key: str,
    model: str,
    urls: Optional[list[str]] = None,
    system_message: Optional[str] = None,
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

    effective_parts = merge_parts_with_system(parts, system_message)
    payload = {
        "contents": [{"parts": effective_parts}],
        "tools": [{"google_search": {}}],
    }

    url = f"{API_BASE}/{model}:generateContent?key={api_key}"
    log_gemini_request(
        logger,
        "web_search",
        url=url,
        payload=payload,
        model=model,
    )
    logger.info(
        "Web search call",
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
        "web_search",
        url=url,
        status_code=resp.status_code,
        response=response_json,
    )
    logger.info("Web search response status=%s", resp.status_code, extra={"body_preview": body_preview})
    if not resp.is_success:
        raise HTTPException(
            status_code=resp.status_code,
            detail={"success": False, "error": "web_search_failed", "message": body_preview},
        )
    return response_json


def _extract_text(result: Dict[str, Any]) -> str:
    candidates = result.get("candidates") or []
    for cand in candidates:
        parts = (cand.get("content") or {}).get("parts") or []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                return part["text"]
    # fallback
    return ""


def _strip_markdown_stars(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\*", "", text)


async def _emit_streaming_text(chat_id: str, message_id: str, tool: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> None:
    """
    Best-effort chunked emit to mimic streaming for chat UI.
    Splits text and sends incremental content + delta over websocket.
    """
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

    # final
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


async def run_web_search(payload: WebSearchRequest, user_id: str, request: Optional[Request] = None) -> Dict[str, Any]:
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
        message_id = client_message_id or f"web_search_error_{os.urandom(4).hex()}"
        try:
            chat_persistence.save_assistant_message(
                user_id=user_id,
                chat_id=chat_id or "",
                content=msg,
                metadata={"source": "web_search", "error": key, "detail": detail},
                message_id=message_id,
                client_message_id=client_message_id or message_id,
            )
        except Exception:
            logger.warning("WebSearch error persist failed chatId=%s userId=%s", chat_id, user_id, exc_info=True)

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
            log_response(logger, "web_search_error", payload)
        except Exception:
            logger.warning("WebSearch error response logging failed")
        return payload

    log_request(logger, "web_search", payload)
    prompt = (payload.prompt or "").strip()
    language = normalize_language(payload.language) or "Turkish"
    if not prompt:
        return _error_response(language, payload.chat_id, user_id, 400, "prompt_required")

    model = DEFAULT_MODEL if DEFAULT_MODEL.startswith("models/") else f"models/{DEFAULT_MODEL}"
    usage_context = _build_usage_context(payload, user_id, model, request)
    usage_data: Dict[str, int] = {}
    start_time = time.monotonic()
    status = "success"
    error_code = None

    try:
        api_key = os.getenv("GEMINI_API_KEY", "")

        logger.info(
            "WebSearch start userId=%s chatId=%s lang=%s urls=%s",
            user_id,
            payload.chat_id,
            language,
            len(payload.urls or []),
        )

        system_message = build_system_message(
            language=language,
            tone_key=payload.tone_key,
            response_style=payload.response_style,
            include_followup=True,
            followup_language=language,
        )
        result = await _call_gemini_web_search(prompt, api_key, model, payload.urls, system_message)
        usage_data = parse_gemini_usage(result)
        text = _strip_markdown_stars(_extract_text(result))
        if not text:
            logger.error(
                "Web search returned empty text",
                extra={"payload_preview": str(result)[:800]},
            )
            return _error_response(language, payload.chat_id, user_id, 500, "web_search_empty")

        logger.info("Web search extracted text", extra={"text_len": len(text), "text_preview": text[:400]})

        message_id = client_message_id or f"web_search_{result.get('id') or uuid.uuid4().hex}"
        streaming_enabled = bool(payload.chat_id)
        if payload.chat_id:
            try:
                chat_persistence.save_assistant_message(
                    user_id=user_id,
                    chat_id=payload.chat_id,
                    content=text,
                    metadata={"source": "web_search", "model": model},
                    message_id=message_id,
                    client_message_id=client_message_id or message_id,
                )
            except Exception:
                logger.warning("Failed to persist web search message chatId=%s userId=%s", payload.chat_id, user_id, exc_info=True)

            try:
                await _emit_streaming_text(
                    chat_id=payload.chat_id,
                    message_id=message_id,
                    tool="web_search",
                    text=text,
                    metadata={"model": model},
                )
            except Exception:
                logger.warning("WebSearch streaming emit failed chatId=%s", payload.chat_id, exc_info=True)

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
            log_response(logger, "web_search", response_payload)
        except Exception:
            logger.warning("WebSearch response logging failed")
        return response_payload
    except HTTPException as he:
        status = "error"
        if isinstance(he.detail, dict):
            error_code = he.detail.get("error")
        error_code = error_code or _map_error_key(he.status_code)
        logger.error("WebSearch HTTPException", exc_info=he)
        return _error_response(language, payload.chat_id, user_id, he.status_code, he.detail)
    except Exception as exc:
        status = "error"
        error_code = "web_search_failed"
        logger.exception("WebSearch unexpected error")
        return _error_response(language, payload.chat_id, user_id, 500, str(exc))
    finally:
        _enqueue_usage_event(
            usage_context,
            usage_data,
            int((time.monotonic() - start_time) * 1000),
            status=status,
            error_code=error_code,
        )


@router.post("")
async def web_search_endpoint(payload: WebSearchRequest, request: Request) -> Dict[str, Any]:
    user_id = get_request_user_id(request) or payload.user_id or ""
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={"success": False, "error": "unauthorized", "message": "Kullanıcı kimliği gerekiyor."},
        )

    return await run_web_search(payload, user_id, request)


__all__ = ["router", "run_web_search"]
