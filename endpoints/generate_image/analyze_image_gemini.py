import base64
import logging
import os
import uuid
from typing import Any, Dict, Optional

import requests
from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from core.websocket_manager import stream_manager
from core.useChatPersistence import chat_persistence
from schemas import GeminiImageAnalyzeRequest
from endpoints.files_pdf.utils import attach_streaming_payload

logger = logging.getLogger("pdf_read_refresh.gemini_image_analyze")

router = APIRouter(prefix="/api/v1/image", tags=["Image"])


def _extract_user_id(request: Request) -> str:
    payload = getattr(request.state, "token_payload", {}) or {}
    return payload.get("uid") or payload.get("userId") or payload.get("sub") or ""


def _detect_mime_from_headers(headers: Dict[str, str]) -> Optional[str]:
    content_type = headers.get("Content-Type") or headers.get("content-type")
    if content_type:
        return content_type.split(";")[0].strip()
    return None


def _download_image_as_base64(image_url: str) -> Dict[str, str]:
    if not image_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "invalid_image_url", "message": "imageUrl must be an http/https URL"},
        )

    resp = requests.get(image_url, timeout=60)
    if not resp.ok:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "image_download_failed", "message": f"Failed to download image: {resp.status_code}"},
        )

    mime_type = _detect_mime_from_headers(resp.headers) or "image/png"
    content = resp.content
    if not content or len(content) < 500:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "image_download_failed",
                "message": "Downloaded image is empty or too small",
            },
        )

    logger.info("Image downloaded for analysis", extra={"mime_type": mime_type, "size_bytes": len(content)})
    b64 = base64.b64encode(content).decode("utf-8")
    return {"data": b64, "mimeType": mime_type}


def _extract_text(response_json: Dict[str, Any]) -> str:
    candidates = response_json.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini response missing candidates")

    parts = (candidates[0].get("content") or {}).get("parts") or []
    for part in parts:
        text = part.get("text")
        if text:
            return text
    raise RuntimeError("Gemini response missing text content")


@router.post("/gemini-analyze")
async def analyze_gemini_image(payload: GeminiImageAnalyzeRequest, request: Request) -> Dict[str, Any]:
    """Analyze an image via Google Gemini API and return a text summary."""
    logger.info(
        "Gemini analyze endpoint called",
        extra={
            "chat_id": payload.chat_id,
            "language_raw": payload.language,
            "image_url": (payload.image_url or "")[:200],
            "prompt_len": len(payload.prompt or ""),
            "prompt_preview": (payload.prompt or "")[:120],
            "model_override": payload.model,
        },
    )

    user_id = _extract_user_id(request)
    language = normalize_language(payload.language)
    prompt = (payload.prompt or "Lütfen görseli detaylı analiz et.").strip()
    gemini_key = os.getenv("GEMINI_API_KEY")
    model = payload.model or os.getenv("GEMINI_IMAGE_ANALYZE_MODEL") or "gemini-1.5-flash"
    streaming_enabled = bool(payload.stream and payload.chat_id)
    message_id = f"image_analyze_{uuid.uuid4().hex}" if streaming_enabled else None
    status_lines: list[str] = []

    async def emit_status(
        message: Optional[str] = None,
        *,
        final: bool = False,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not streaming_enabled:
            return
        if message:
            status_lines.append(message)
        chunk_payload: Dict[str, Any] = {
            "chatId": payload.chat_id,
            "messageId": message_id,
            "tool": "analyze_image_gemini",
            "content": "\n".join(status_lines),
            "isFinal": final,
        }
        if message:
            chunk_payload["delta"] = message + ("\n" if not message.endswith("\n") else "")
        if metadata:
            chunk_payload["metadata"] = metadata
        if error:
            chunk_payload["error"] = error
        await stream_manager.emit_chunk(payload.chat_id, chunk_payload)

    if not gemini_key:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_api_key_missing", "message": "GEMINI_API_KEY env is required"},
        )

    inline = _download_image_as_base64(payload.image_url)
    await emit_status("Görsel indirildi, Gemini analizine gönderiliyor...")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
    request_body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "data": inline["data"],
                            "mimeType": inline["mimeType"],
                        }
                    },
                ],
            }
        ]
    }

    logger.info(
        "Calling Gemini analyze API",
        extra={
            "prompt_len": len(prompt),
            "prompt_preview": prompt[:120],
            "mime_type": inline["mimeType"],
            "model": model,
        },
    )
    resp = requests.post(url, json=request_body, timeout=120)
    logger.info(
        "Gemini analyze API response",
        extra={"status": resp.status_code, "body_preview": (resp.text or "")[:800]},
    )
    if not resp.ok:
        await emit_status("Analiz başarısız.", final=True, error="gemini_analyze_failed")
        raise HTTPException(
            status_code=resp.status_code,
            detail={"success": False, "error": "gemini_analyze_failed", "message": resp.text[:500]},
        )

    try:
        response_json = resp.json()
    except Exception as exc:
        logger.error("Failed to parse Gemini analyze response", exc_info=exc)
        await emit_status("Analiz cevabı parse edilemedi.", final=True, error="gemini_analyze_parse_failed")
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_analyze_parse_failed", "message": str(exc)},
        ) from exc

    try:
        analysis_text = _extract_text(response_json)
    except Exception as exc:
        logger.error("Failed to extract text from Gemini response", exc_info=exc)
        await emit_status("Analiz cevabında metin bulunamadı.", final=True, error="gemini_analyze_no_text")
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_analyze_no_text", "message": str(exc)},
        ) from exc

    logger.info(
        "Gemini analyze completed",
        extra={
            "chat_id": payload.chat_id,
            "user_id": user_id,
            "model": model,
            "analysis_preview": analysis_text[:200],
        },
    )

    result_payload = {
        "success": True,
        "analysis": analysis_text,
        "chatId": payload.chat_id,
        "language": language,
        "model": model,
        "imageUrl": payload.image_url,
    }

    metadata = {
        "prompt": prompt,
        "model": model,
        "tool": "analyze_image_gemini",
        "imageUrl": payload.image_url,
    }

    if payload.chat_id:
        try:
            chat_persistence.save_assistant_message(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=analysis_text,
                file_url=payload.image_url,
                metadata=metadata,
            )
            logger.info(
                "Analysis message saved to Firestore",
                extra={"chatId": payload.chat_id, "userId": user_id},
            )
        except RuntimeError:
            logger.debug("Skipping Firestore save; firebase app not initialized")
        except Exception as exc:  # pragma: no cover
            logger.exception("Firestore save failed", extra={"error": str(exc), "chatId": payload.chat_id})

    await emit_status(
        "Analiz tamamlandı.",
        final=True,
        metadata={"tool": "analyze_image_gemini", "analysis": analysis_text[:500]},
    )

    result = attach_streaming_payload(
        result_payload,
        tool="analyze_image_gemini",
        content=analysis_text,
        streaming=streaming_enabled,
        message_id=message_id if streaming_enabled else None,
        extra_data={"analysis": analysis_text},
    )

    logger.info(
        "Gemini analyze response ready",
        extra={"chatId": payload.chat_id, "streaming": streaming_enabled},
    )
    return result


__all__ = ["router", "analyze_gemini_image"]

