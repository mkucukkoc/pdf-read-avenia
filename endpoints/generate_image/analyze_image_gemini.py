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
    # Model sırası: payload > env > önerilen fallback listesi
    # Öncelikli model: gemini-2.5-flash (isteğe göre), sonra env/payload ve fallback'ler
    model_candidates = [
        "gemini-2.5-flash",
        payload.model,
        os.getenv("GEMINI_IMAGE_ANALYZE_MODEL"),
        "gemini-1.5-flash-001",
        "gemini-1.5-flash-8b-001",
        "gemini-1.5-pro-001",
    ]
    # None ve tekrarları temizle, sıralı tut
    seen = set()
    candidate_models: list[str] = []
    for m in model_candidates:
        if not m:
            continue
        if m in seen:
            continue
        seen.add(m)
        candidate_models.append(m)

    # UI'de geçici mesajları göstermek istemiyoruz; streaming'i kapat.
    streaming_enabled = False
    message_id = None
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

    response_json = None
    last_error: Optional[HTTPException] = None
    selected_model: Optional[str] = None

    for idx, model in enumerate(candidate_models):
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
                "attempt": idx + 1,
                "prompt_len": len(prompt),
                "prompt_preview": prompt[:120],
                "mime_type": inline["mimeType"],
                "model": model,
            },
        )
        resp = requests.post(url, json=request_body, timeout=120)
        logger.info(
            "Gemini analyze API response",
            extra={"attempt": idx + 1, "status": resp.status_code, "body_preview": (resp.text or "")[:800]},
        )
        if not resp.ok:
            last_error = HTTPException(
                status_code=resp.status_code,
                detail={"success": False, "error": "gemini_analyze_failed", "message": resp.text[:500]},
            )
            continue

        try:
            response_json = resp.json()
            selected_model = model
            break
        except Exception as exc:
            logger.error("Failed to parse Gemini analyze response", exc_info=exc, extra={"attempt": idx + 1, "model": model})
            last_error = HTTPException(
                status_code=500,
                detail={"success": False, "error": "gemini_analyze_parse_failed", "message": str(exc)},
            )
            continue

    if response_json is None or selected_model is None:
        await emit_status("Analiz başarısız.", final=True, error="gemini_analyze_failed")
        if last_error:
            raise last_error
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "gemini_analyze_failed",
                "message": "All model attempts failed",
                "attemptedModels": candidate_models,
            },
        )

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
        "model": selected_model,
        "imageUrl": payload.image_url,
    }

    metadata = {
        "prompt": prompt,
        "model": selected_model,
        "tool": "analyze_image_gemini",
        "imageUrl": payload.image_url,
    }

    if payload.chat_id:
        try:
            # Kullanıcı mesajı zaten görsel URL'sini içeriyor; asistanda tekrar görsel ekleme.
            chat_persistence.save_assistant_message(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=analysis_text,
                file_url=None,
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

