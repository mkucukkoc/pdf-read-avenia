import asyncio
import logging
import os
import re
from typing import Any, Dict, Optional, List
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from core.useChatPersistence import chat_persistence
from endpoints.agent.utils import get_request_user_id
from core.websocket_manager import stream_manager
from schemas import DeepResearchRequest
from endpoints.logging.utils_logging import log_request, log_response
from errors_response.api_errors import get_api_error_message

logger = logging.getLogger("pdf_read_refresh.deep_research")

router = APIRouter(prefix="/api/v1/deep-research", tags=["DeepResearch"])

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_AGENT = os.getenv("GEMINI_DEEP_RESEARCH_AGENT", "deep-research-pro-preview-12-2025")
POLL_DELAY_SEC = float(os.getenv("DEEP_RESEARCH_POLL_DELAY", "3.0"))
# Default ~2 minutes; can be overridden via env.
MAX_POLL_ATTEMPTS = int(os.getenv("DEEP_RESEARCH_MAX_POLL", "40"))


async def _start_interaction(
    client: httpx.AsyncClient, prompt: str, api_key: str, agent: str, urls: Optional[list[str]] = None
) -> Dict[str, Any]:
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_api_key_missing", "message": "GEMINI_API_KEY env is required"},
        )

    payload: Dict[str, Any] = {"input": prompt, "agent": agent, "background": True, "store": True}
    if urls:
        payload["context"] = {"urls": urls}

    logger.info(
        "DeepResearch start call",
        extra={
            "agent": agent,
            "has_urls": bool(urls),
            "url_count": len(urls or []),
            "prompt_preview": prompt[:200],
            "payload": payload,
        },
    )
    resp = await client.post(f"{API_BASE}/interactions?key={api_key}", json=payload)

    logger.info(
        "DeepResearch start response",
        extra={
            "status": resp.status_code,
            "body_preview": (resp.text or "")[:800],
            "headers": dict(resp.headers),
        },
    )

    if not resp.is_success:
        body_preview = (resp.text or "")[:800]
        logger.error("Deep Research start failed status=%s body=%s", resp.status_code, body_preview)
        raise HTTPException(
            status_code=resp.status_code,
            detail={"success": False, "error": "deep_research_start_failed", "message": body_preview},
        )

    data = resp.json()
    interaction_id = data.get("id") or data.get("name")
    logger.info(
        "DeepResearch start parsed",
        extra={
            "interaction_id": interaction_id,
            "raw_keys": list(data.keys()),
            "data_preview": str(data)[:500],
        },
    )
    if not interaction_id:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "missing_interaction_id", "message": "Deep Research interaction id missing"},
        )
    return {"interaction_id": interaction_id, "raw": data}


async def _poll_interaction(client: httpx.AsyncClient, interaction_id: str, api_key: str) -> Dict[str, Any]:
    url = f"{API_BASE}/interactions/{interaction_id}?key={api_key}"
    last_payload: Dict[str, Any] = {}
    for attempt in range(MAX_POLL_ATTEMPTS):
        logger.info("DeepResearch poll", extra={"interaction_id": interaction_id, "attempt": attempt + 1})
        resp = await client.get(url)
        logger.info(
            "DeepResearch poll response",
            extra={
                "status": resp.status_code,
                "body_preview": (resp.text or "")[:800],
                "headers": dict(resp.headers),
            },
        )
        if not resp.is_success:
            body_preview = (resp.text or "")[:400]
            logger.error("Deep Research poll failed id=%s status=%s body=%s", interaction_id, resp.status_code, body_preview)
            raise HTTPException(
                status_code=resp.status_code,
                detail={"success": False, "error": "deep_research_poll_failed", "message": body_preview},
            )

        payload = resp.json()
        last_payload = payload
        outputs = payload.get("outputs") or []
        status = str(payload.get("status") or payload.get("state") or "").lower()
        logger.info(
            "DeepResearch poll payload",
            extra={
                "keys": list(payload.keys()),
                "outputs_len": len(outputs),
                "first_output_preview": str(outputs[0])[:400] if outputs else None,
                "status": status,
            },
        )

        if status in ("completed", "succeeded", "done"):
            logger.info("DeepResearch completed", extra={"interaction_id": interaction_id})
            return payload
        if status in ("failed", "error"):
            raise HTTPException(
                status_code=500,
                detail={"success": False, "error": "deep_research_failed", "message": payload},
            )

        await asyncio.sleep(POLL_DELAY_SEC)

    logger.error(
        "DeepResearch poll timeout",
        extra={
            "interaction_id": interaction_id,
            "last_status": str(last_payload.get("status") or last_payload.get("state")),
            "outputs_len": len(last_payload.get("outputs") or []),
            "payload_preview": str(last_payload)[:800],
        },
    )
    last_payload = last_payload or {}
    last_payload["status"] = last_payload.get("status") or "timeout"
    last_payload["timeout"] = True
    return last_payload


def _extract_text(payload: Dict[str, Any]) -> Optional[str]:
    """Try to extract assistant text from various Deep Research output shapes."""
    outputs = payload.get("outputs") or []

    def from_parts(parts: Any) -> Optional[str]:
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, dict) and isinstance(part.get("text"), str) and part["text"].strip():
                    return part["text"]
        return None

    for item in reversed(outputs):
        if not isinstance(item, dict):
            continue

        part = item.get("part")
        if isinstance(part, dict):
            if isinstance(part.get("text"), str) and part["text"].strip():
                return part["text"]
            if part.get("content"):
                text = from_parts(part.get("content"))
                if text:
                    return text

        output = item.get("output")
        if isinstance(output, dict):
            if isinstance(output.get("text"), str) and output["text"].strip():
                return output["text"]
            content = output.get("content")
            if isinstance(content, list):
                for content_item in content:
                    if isinstance(content_item, dict):
                        text = from_parts(content_item.get("parts"))
                        if text:
                            return text
        # Variant: content directly on item
        content = item.get("content")
        if isinstance(content, dict):
            text = from_parts(content.get("parts"))
            if text:
                return text

        if isinstance(item.get("text"), str) and item["text"].strip():
            return item["text"]

    # Fallbacks: response.candidates[].content.parts[].text
    resp = payload.get("response")
    if isinstance(resp, dict):
        t_direct = resp.get("output_text") or resp.get("text")
        if isinstance(t_direct, str) and t_direct.strip():
            return t_direct
        candidates = resp.get("candidates")
        if isinstance(candidates, list):
            for cand in candidates:
                if isinstance(cand, dict):
                    content = cand.get("content")
                    if isinstance(content, dict):
                        text = from_parts(content.get("parts"))
                        if text:
                            return text

    # Fallback: candidates at top level
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        for cand in candidates:
            if isinstance(cand, dict):
                content = cand.get("content")
                if isinstance(content, dict):
                    text = from_parts(content.get("parts"))
                    if text:
                        return text

    return None


def _parse_citations(raw: str) -> Dict[str, Any]:
    """
    Parse Deep Research markdown-ish output into cleaned body text and a citations array.
    Converts [cite: n] -> (n) and extracts Sources list into structured links.
    """
    body = raw.strip()
    citations: List[Dict[str, Any]] = []

    # Split out Sources block (markdown bold "Sources:")
    parts = re.split(r"\n\s*\*\*Sources?:\*\*\s*\n", raw, maxsplit=1)
    if len(parts) == 2:
        body = parts[0].strip()
        sources_block = parts[1]
    else:
        sources_block = ""

    # Parse sources: lines like "1. [label](url)" or "1. url"
    for m in re.finditer(r"(?m)^\s*(\d+)\.\s*(?:\[(.+?)\]\((.+?)\)|(.+))$", sources_block):
        sid = int(m.group(1))
        label = (m.group(2) or m.group(4) or "").strip()
        url_raw = (m.group(3) or m.group(4) or "").strip()
        url_match = re.search(r"https?://\S+", url_raw)
        url = url_match.group(0) if url_match else url_raw
        title = label or url
        try:
            domain = urlparse(url).netloc
            if domain and "vertexaisearch.cloud.google.com" not in domain:
                title = domain
        except Exception:
            pass
        citations.append({"id": sid, "title": title, "url": url})

    # Replace [cite: 1,2] with (1, 2)
    def cite_repl(match: re.Match) -> str:
        nums = match.group(1)
        nums = re.sub(r"\s*,\s*", ", ", nums.strip())
        return f"({nums})"

    body = re.sub(r"\[cite:\s*([0-9,\s]+)\]", cite_repl, body)

    return {"content": body, "citations": citations}


async def run_deep_research(payload: DeepResearchRequest, user_id: str) -> Dict[str, Any]:
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
        message_id = client_message_id or f"deep_research_error_{os.urandom(4).hex()}"
        try:
            chat_persistence.save_assistant_message(
                user_id=user_id,
                chat_id=chat_id or "",
                content=msg,
                metadata={"source": "deep_research", "error": key, "detail": detail},
                message_id=message_id,
                client_message_id=client_message_id or message_id,
            )
        except Exception:
            logger.warning("DeepResearch error persist failed chatId=%s userId=%s", chat_id, user_id, exc_info=True)

        response_payload = {
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
            log_response(logger, "deep_research_error", response_payload)
        except Exception:
            logger.warning("DeepResearch error response logging failed")
        return response_payload

    log_request(logger, "deep_research", payload)
    user_prompt = (payload.prompt or "").strip()
    language = normalize_language(payload.language) or "Turkish"
    if not user_prompt:
        return _error_response(language, payload.chat_id, user_id, 400, "prompt_required")

    try:
        api_key = os.getenv("GEMINI_API_KEY", "")
        agent = os.getenv("GEMINI_DEEP_RESEARCH_AGENT", DEFAULT_AGENT)
        structured_prompt = f"""
Derin araştırma yap.
- En fazla 5 kaynak
- Maddeler halinde
- En fazla 300 kelime
Yanıt dili: {language}

Konu:
{user_prompt}
""".strip()

        logger.info(
            "Deep Research start userId=%s chatId=%s lang=%s",
            user_id,
            payload.chat_id,
            language,
        )

        async with httpx.AsyncClient(timeout=180) as client:
            start_result = await _start_interaction(client, structured_prompt, api_key, agent, payload.urls)
            interaction_id = start_result["interaction_id"]
            result_payload = await _poll_interaction(client, interaction_id, api_key)
        text = _extract_text(result_payload)

        timed_out = bool(result_payload.get("timeout"))
        if not text:
            logger.warning(
                "DeepResearch returned empty text; responding with graceful fallback",
                extra={
                    "interaction_id": interaction_id,
                    "payload_keys": list(result_payload.keys()),
                    "outputs_len": len(result_payload.get("outputs") or []),
                    "payload_preview": str(result_payload)[:1200],
                    "timed_out": timed_out,
                },
            )
            fallback_text = (
                "Derin araştırma tamamlandı ancak metin gelmedi veya süre doldu. "
                "Lütfen yeniden deneyin ya da Web Search ile devam edin."
            )
            message_id = client_message_id or f"deep_research_{interaction_id}"
            return {
                "success": True,
                "data": {
                    "message": {"content": fallback_text, "id": message_id},
                    "streaming": False,
                },
            }

        parsed = _parse_citations(text)
        body = parsed["content"]
        citations = parsed.get("citations") or []

        logger.info(
            "DeepResearch extracted text",
            extra={
                "interaction_id": interaction_id,
                "text_len": len(body),
                "text_preview": body[:400],
                "citations_len": len(citations),
            },
        )

        message_id = client_message_id or f"deep_research_{interaction_id}"
        streaming_enabled = bool(payload.chat_id)
        if payload.chat_id:
            try:
                chat_persistence.save_assistant_message(
                    user_id=user_id,
                    chat_id=payload.chat_id,
                    content=body,
                    metadata={"source": "deep_research", "interactionId": interaction_id, "citations": citations},
                    message_id=message_id,
                    client_message_id=client_message_id or message_id,
                )
            except Exception:
                logger.warning("Failed to persist deep research message chatId=%s userId=%s", payload.chat_id, user_id, exc_info=True)

            if streaming_enabled:
                try:
                    await stream_manager.emit_chunk(
                        payload.chat_id,
                        {
                            "chatId": payload.chat_id,
                            "messageId": message_id,
                            "tool": "deep_research",
                            "content": body,
                            "citations": citations,
                            "isFinal": True,
                        },
                    )
                except Exception:
                    logger.warning("DeepResearch streaming emit failed chatId=%s", payload.chat_id, exc_info=True)

        response_payload = {
            "success": True,
            "data": {
                "message": {
                    "content": body,
                    "id": message_id,
                    "citations": citations,
                },
                "streaming": streaming_enabled,
            },
        }
        try:
            log_response(logger, "deep_research", response_payload)
        except Exception:
            logger.warning("DeepResearch response logging failed")
        return response_payload
    except HTTPException as he:
        logger.error("DeepResearch HTTPException", exc_info=he)
        return _error_response(language, payload.chat_id, user_id, he.status_code, he.detail)
    except Exception as exc:
        logger.exception("DeepResearch unexpected error")
        return _error_response(language, payload.chat_id, user_id, 500, str(exc))


@router.post("")
async def deep_research_endpoint(payload: DeepResearchRequest, request: Request) -> Dict[str, Any]:
    user_id = get_request_user_id(request) or payload.user_id or ""
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={"success": False, "error": "unauthorized", "message": "Kullanıcı kimliği gerekiyor."},
        )

    return await run_deep_research(payload, user_id)


__all__ = ["router", "run_deep_research"]

