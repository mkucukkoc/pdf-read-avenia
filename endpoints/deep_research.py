import asyncio
import logging
import os
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from core.useChatPersistence import chat_persistence
from endpoints.agent.utils import get_request_user_id
from core.websocket_manager import stream_manager
from schemas import DeepResearchRequest

logger = logging.getLogger("pdf_read_refresh.deep_research")

router = APIRouter(prefix="/api/v1/deep-research", tags=["DeepResearch"])

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_AGENT = os.getenv("GEMINI_DEEP_RESEARCH_AGENT", "deep-research-pro-preview-12-2025")
POLL_DELAY_SEC = float(os.getenv("DEEP_RESEARCH_POLL_DELAY", "4.0"))
MAX_POLL_ATTEMPTS = int(os.getenv("DEEP_RESEARCH_MAX_POLL", "6"))


async def _start_interaction(prompt: str, api_key: str, agent: str, urls: Optional[list[str]] = None) -> Dict[str, Any]:
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
    async with httpx.AsyncClient(timeout=180) as client:
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


async def _poll_interaction(interaction_id: str, api_key: str) -> Dict[str, Any]:
    url = f"{API_BASE}/interactions/{interaction_id}?key={api_key}"
    async with httpx.AsyncClient(timeout=180) as client:
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
            status = str(payload.get("status") or payload.get("state") or "").lower()

            if status in ("completed", "succeeded", "done"):
                logger.info("DeepResearch completed", extra={"interaction_id": interaction_id})
                return payload
            if status in ("failed", "error"):
                raise HTTPException(
                    status_code=500,
                    detail={"success": False, "error": "deep_research_failed", "message": payload},
                )

            await asyncio.sleep(POLL_DELAY_SEC)

    return last_payload


def _extract_text(payload: Dict[str, Any]) -> Optional[str]:
    outputs = payload.get("outputs") or []
    for item in reversed(outputs):
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("part"), dict) and isinstance(item["part"].get("text"), str):
            return item["part"]["text"]
        if isinstance(item.get("output"), dict) and isinstance(item["output"].get("text"), str):
            return item["output"]["text"]
        if isinstance(item.get("text"), str):
            return item["text"]
    return None


async def run_deep_research(payload: DeepResearchRequest, user_id: str) -> Dict[str, Any]:
    prompt = (payload.prompt or "").strip()
    if not prompt:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "prompt_required", "message": "prompt is required"},
        )

    api_key = os.getenv("GEMINI_API_KEY", "")
    agent = os.getenv("GEMINI_DEEP_RESEARCH_AGENT", DEFAULT_AGENT)
    language = normalize_language(payload.language) or "Turkish"

    logger.info(
        "Deep Research start userId=%s chatId=%s lang=%s",
        user_id,
        payload.chat_id,
        language,
    )

    start_result = await _start_interaction(prompt, api_key, agent, payload.urls)
    interaction_id = start_result["interaction_id"]
    result_payload = await _poll_interaction(interaction_id, api_key)
    text = _extract_text(result_payload)

    if not text:
        logger.error(
            "DeepResearch returned empty text",
            extra={
                "interaction_id": interaction_id,
                "payload_preview": str(result_payload)[:800],
            },
        )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "deep_research_empty", "message": "No output text from Deep Research"},
        )

    logger.info(
        "DeepResearch extracted text",
        extra={"interaction_id": interaction_id, "text_len": len(text), "text_preview": text[:400]},
    )

    message_id = f"deep_research_{interaction_id}"
    if payload.chat_id:
        try:
            chat_persistence.save_assistant_message(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=text,
                metadata={"source": "deep_research", "interactionId": interaction_id},
                message_id=message_id,
            )
        except Exception:
            logger.warning("Failed to persist deep research message chatId=%s userId=%s", payload.chat_id, user_id, exc_info=True)

        try:
            await stream_manager.emit_chunk(
                payload.chat_id,
                {
                    "chatId": payload.chat_id,
                    "messageId": message_id,
                    "tool": "deep_research",
                    "content": text,
                    "isFinal": True,
                },
            )
        except Exception:
            logger.warning("DeepResearch streaming emit failed chatId=%s", payload.chat_id, exc_info=True)

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
async def deep_research_endpoint(payload: DeepResearchRequest, request: Request) -> Dict[str, Any]:
    user_id = get_request_user_id(request) or payload.user_id or ""
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={"success": False, "error": "unauthorized", "message": "Kullanıcı kimliği gerekiyor."},
        )

    return await run_deep_research(payload, user_id)


__all__ = ["router", "run_deep_research"]

