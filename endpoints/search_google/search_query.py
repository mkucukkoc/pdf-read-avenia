import asyncio
import logging
import os
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException, Request

from core.language_support import normalize_language
from core.tone_instructions import build_tone_instruction
from endpoints.agent.utils import get_request_user_id
from endpoints.files_pdf.utils import (
    attach_streaming_payload,
    extract_text_response,
    log_full_payload,
    save_message_to_firestore,
)
from endpoints.logging.utils_logging import log_request, log_response
from schemas import SearchQueryRequest
from errors_response.api_errors import get_api_error_message

logger = logging.getLogger("pdf_read_refresh.search_google.search_query")


def _effective_search_model(model: Optional[str]) -> str:
    """
    Preferred order: payload > env > default flash.
    """
    effective = model or os.getenv("GEMINI_SEARCH_MODEL") or "models/gemini-2.5-flash"
    if not effective.startswith("models/"):
        effective = f"models/{effective}"
    return effective


async def _call_gemini_search(
    *,
    parts: list[Dict[str, Any]],
    api_key: str,
    model: str,
    urls: Optional[list[str]] = None,
    system_instruction: Optional[str] = None,
) -> Dict[str, Any]:
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "gemini_api_key_missing",
                "message": "GEMINI_API_KEY env is required",
            },
        )

    url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={api_key}"
    tools: list[Dict[str, Any]] = [{"google_search": {}}]
    if urls:
        tools.append({"url_context": {}})

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "tools": tools,
    }
    if system_instruction:
        payload["system_instruction"] = {"parts": [{"text": system_instruction}]}

    logger.info(
        "Gemini search-query http call prepared",
        extra={
            "model": model,
            "tools": [list(t.keys())[0] for t in tools],
            "has_urls": bool(urls),
            "url_count": len(urls or []),
            "part_count": len(parts),
        },
    )

    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(url, json=payload)

    body_preview = (resp.text or "")[:800]
    logger.info(
        "Gemini search-query request",
        extra={"status": resp.status_code, "model": model, "body_preview": body_preview},
    )
    if not resp.ok:
        raise HTTPException(
            status_code=resp.status_code,
            detail={
                "success": False,
                "error": "gemini_search_failed",
                "message": body_preview,
            },
        )
    return resp.json()


async def generate_search_queries(payload: SearchQueryRequest, request: Request) -> Dict[str, Any]:
    """
    Kullanıcının doğal dil sorgusunu Google araması için optimize eder.
    """
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

    def _error_response(language: str, chat_id: Optional[str], user_id: Optional[str], status_code: int, detail: Any) -> Dict[str, Any]:
        key = _map_error_key(status_code)
        msg = get_api_error_message(key, language)
        metadata = {
            "tool": "search_query_agent",
            "error": key,
            "detail": detail,
            "model": None,
            "language": language,
            "google_search_tool": True,
            "sources": [],
            "search_overlay": "",
            "url_context_metadata": {},
        }
        try:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=chat_id or "",
                content=msg,
                metadata=metadata,
            )
        except Exception:
            logger.warning("search_query error persist failed chatId=%s userId=%s", chat_id, user_id, exc_info=True)

        result = {
            "success": True,
            "chatId": chat_id,
            "optimizedQuery": msg,
            "language": language,
            "model": metadata["model"],
            "sources": [],
            "search_overlay": "",
            "url_context_metadata": {},
        }
        result = attach_streaming_payload(
            result,
            tool="search_query_agent",
            content=msg,
            streaming=False,
            message_id=None,
            extra_data={"optimizedQuery": msg, **metadata},
        )
        try:
            log_response(logger, "search_query_error", result)
        except Exception:
            logger.warning("search_query error response logging failed")
        return result

    user_id = get_request_user_id(request)
    language = normalize_language(payload.language) or "Turkish"

    log_full_payload(logger, "search_query", payload)
    log_request(logger, "search_query", payload)

    raw_query = (payload.query or "").strip()
    if not raw_query:
        return _error_response(language, payload.chat_id, user_id, 400, "query_required")

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        model = _effective_search_model(payload.model)

        instruction = (
            "You are a search query optimization agent. Rewrite the user's request into 1-3 concise Google-ready "
            "search queries that maximize relevant results. Include key entities, dates, locations, and specific nouns. "
            "Remove ambiguity. Output ONLY the optimized queries, one per line, no bullets or extra text."
        )

        depth_hint = (
            f"Search depth preference: {payload.search_depth}"
            if payload.search_depth
            else "Search depth preference: balanced"
        )

        url_lines = "\n".join(payload.urls or [])

        parts = [
            {"text": instruction},
            {"text": f"Language: {language}"},
            {"text": f"User query: {raw_query}"},
            {"text": depth_hint},
        ]
        if url_lines:
            parts.append({"text": f"Context URLs:\n{url_lines}"})

        logger.info(
            "search_query agent - composed prompt parts",
            extra={
                "userId": user_id,
                "chatId": payload.chat_id,
                "language": language,
                "model": model,
                "searchDepth": payload.search_depth,
                "urlCount": len(payload.urls or []),
                "rawQueryPreview": raw_query[:200],
            },
        )

        tone_instruction = build_tone_instruction(payload.tone_key, language)
        response_json = await _call_gemini_search(
            parts=parts,
            api_key=api_key,
            model=model,
            urls=payload.urls,
            system_instruction=tone_instruction,
        )

        optimized = extract_text_response(response_json)
        if not optimized:
            logger.error("Gemini search-query empty response", extra={"model": model})
            return _error_response(language, payload.chat_id, user_id, 500, "empty_response")

        grounding_data = (
            (response_json.get("candidates") or [{}])[0].get("groundingMetadata") or {}
        )
        sources = grounding_data.get("groundingChunks", [])
        search_entry_point = (
            grounding_data.get("searchEntryPoint", {}) or {}
        ).get("htmlContent", "")
        url_context_metadata = (
            (response_json.get("candidates") or [{}])[0].get("urlContextMetadata") or {}
        )

        logger.info(
            "search_query agent - grounding extracted",
            extra={
                "source_count": len(sources or []),
                "has_search_overlay": bool(search_entry_point),
                "url_context_urls": len((url_context_metadata.get("urlMetadata") or [])),
            },
        )

        metadata = {
            "tool": "search_query_agent",
            "model": model,
            "language": language,
            "google_search_tool": True,
            "sources": sources,
            "search_overlay": search_entry_point,
            "url_context_metadata": url_context_metadata,
        }

        result = {
            "success": True,
            "chatId": payload.chat_id,
            "optimizedQuery": optimized,
            "language": language,
            "model": model,
            "sources": sources,
            "search_overlay": search_entry_point,
            "url_context_metadata": url_context_metadata,
        }

        result = attach_streaming_payload(
            result,
            tool="search_query_agent",
            content=optimized,
            streaming=False,
            message_id=None,
            extra_data={"optimizedQuery": optimized, **metadata},
        )

        save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id or "",
            content=optimized,
            metadata=metadata,
        )

        logger.info(
            "search_query agent - completed",
            extra={
                "chatId": payload.chat_id,
                "userId": user_id,
                "model": model,
                "optimized_len": len(optimized or ""),
                "source_count": len(sources or []),
            },
        )
        log_response(logger, "search_query", result)

        return result
    except HTTPException as he:
        logger.error("search_query HTTPException", exc_info=he)
        return _error_response(language, payload.chat_id, user_id, he.status_code, he.detail)
    except Exception as exc:
        logger.exception("search_query unexpected error")
        return _error_response(language, payload.chat_id, user_id, 500, str(exc))


async def _call_async(
    parts: list[Dict[str, Any]],
    api_key: str,
    model: str,
    system_instruction: Optional[str] = None,
) -> Dict[str, Any]:
    # Fallback async wrapper if no app loop is set
    return await asyncio.to_thread(
        lambda: _call_gemini_search(
            parts=parts,
            api_key=api_key,
            model=model,
            system_instruction=system_instruction,
        )
    )


__all__ = ["generate_search_queries"]
