import asyncio
import base64
import logging
import json
import os
import tempfile
import time
import uuid
from typing import Any, Dict, Optional

import requests
from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language, get_image_gen_message
from core.firebase import db
from core.websocket_manager import stream_manager
from core.useChatPersistence import chat_persistence
from errors_response.image_errors import get_no_image_generate_message
from errors_response.api_errors import get_api_error_message
from schemas import GeminiImageEditRequest, GeminiImageRequest
from endpoints.files_pdf.utils import attach_streaming_payload
from endpoints.logging.utils_logging import log_gemini_request, log_gemini_response, log_request, log_response
from usage_tracking import build_base_event, finalize_event, extract_gemini_usage_metadata, enqueue_usage_update

logger = logging.getLogger("pdf_read_refresh.gemini_image")

router = APIRouter(prefix="/api/v1/image", tags=["Image"])


def _get_storage():
    from main import storage  # Local import prevents circular dependency

    return storage


def _extract_user_id(request: Request) -> str:
    payload = getattr(request.state, "token_payload", {}) or {}
    return payload.get("uid") or payload.get("userId") or payload.get("sub") or ""


def _build_usage_context(
    request: Request,
    user_id: str,
    endpoint: str,
    model: str,
    payload: Any,
) -> Dict[str, Any]:
    token_payload = getattr(request.state, "token_payload", {}) or {}
    request_id = (
        getattr(payload, "client_message_id", None)
        or request.headers.get("x-request-id")
        or request.headers.get("x-requestid")
        or f"req_{uuid.uuid4().hex}"
    )
    event = build_base_event(
        request_id=request_id,
        user_id=user_id,
        endpoint=endpoint,
        provider="gemini",
        model=model,
        token_payload=token_payload,
        request=request,
    )
    logger.info(
        "UsageTracking image endpoint built base event",
        extra={
            "requestId": event.get("requestId"),
            "userId": event.get("userId"),
            "endpoint": endpoint,
            "model": model,
            "action": event.get("action"),
        },
    )
    return event


def _enqueue_usage_event(
    usage_context: Optional[Dict[str, Any]],
    usage_data: Dict[str, Any],
    latency_ms: int,
    *,
    status: str,
    error_code: Optional[str],
) -> None:
    if not usage_context or not db:
        logger.info(
            "UsageTracking image endpoint skipped enqueue (missing context or db)",
            extra={"hasContext": bool(usage_context), "hasDb": bool(db)},
        )
        return
    try:
        logger.info(
            "UsageTracking image endpoint finalize_event start",
            extra={
                "requestId": usage_context.get("requestId"),
                "userId": usage_context.get("userId"),
                "endpoint": usage_context.get("endpoint"),
                "status": status,
                "errorCode": error_code,
                "latencyMs": latency_ms,
            },
        )
        event = finalize_event(
            usage_context,
            raw_usage=usage_data or None,
            latency_ms=latency_ms,
            status=status,
            error_code=error_code,
        )
        logger.info(
            "UsageTracking image endpoint enqueue_usage_update",
            extra={
                "requestId": event.get("requestId"),
                "userId": event.get("userId"),
                "endpoint": event.get("endpoint"),
                "payload": event,
            },
        )
        enqueue_usage_update(db, event)
    except Exception:
        logger.warning("Usage tracking failed for image endpoint", exc_info=True)


def _save_message_to_firestore(
    user_id: str,
    chat_id: str,
    content: str,
    image_url: Optional[str],
    metadata: Optional[Dict[str, Any]] = None,
    client_message_id: Optional[str] = None,
) -> None:
    if not chat_id:
        logger.debug("Skipping Firestore save; chat_id missing")
        return

    try:
        chat_persistence.save_assistant_message(
            user_id=user_id,
            chat_id=chat_id,
            content=content,
            file_url=image_url,
            metadata=metadata or {},
            client_message_id=client_message_id,
        )
    except RuntimeError:
        logger.debug("Skipping Firestore save; firebase app not initialized")
    except Exception as exc:  # pragma: no cover
        logger.exception("Firestore save failed", extra={"error": str(exc), "chatId": chat_id})


def _build_storage_path(user_id: str, file_name: Optional[str]) -> str:
    safe_user = user_id or "anonymous"
    sanitized_name = (file_name or "gemini-image.png").replace("/", "_")
    timestamp = int(time.time() * 1000)
    return f"image-generations/{safe_user}/{timestamp}-{sanitized_name}"


def _detect_mime_from_headers(headers: Dict[str, str]) -> Optional[str]:
    content_type = headers.get("Content-Type") or headers.get("content-type")
    if content_type:
        return content_type.split(";")[0].strip()
    return None


def _guess_extension_from_mime(mime_type: str) -> str:
    if not mime_type:
        return ".png"
    if "jpeg" in mime_type or "jpg" in mime_type:
        return ".jpg"
    if "webp" in mime_type:
        return ".webp"
    if "gif" in mime_type:
        return ".gif"
    return ".png"


def _build_image_system_instruction(language: Optional[str], tone_key: Optional[str]) -> str:
    tone_line = ""
    if tone_key:
        tone_line = f"\nTONE: {tone_key}. Apply this tone to the visual style (mood/colors/composition)."
    lang = language or "en"
    return (
        "System: You are an IMAGE generation model inside an app named Avenia.\n"
        "Task: Generate an IMAGE result. Do NOT answer with only text.\n"
        "Return the image as inline_data (base64) in the response parts.\n"
        f"If any text is returned, it must be in {lang}.\n"
        "Do NOT ask follow-up questions."
        f"{tone_line}"
    )


async def _call_gemini_api(
    prompt_text: str,
    api_key: str,
    model: str,
    use_google_search: bool = False,
    aspect_ratio: Optional[str] = None,
) -> Dict[str, Any]:
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_api_key_missing", "message": "GEMINI_API_KEY env is required"},
        )

    logger.info(
        "Gemini API call start",
        extra={
            "prompt_preview": prompt_text[:120],
            "prompt_len": len(prompt_text),
            "model": model,
            "use_google_search": use_google_search,
            "aspect_ratio": aspect_ratio,
        },
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload: Dict[str, Any] = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt_text,
                    }
                ],
            }
        ],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }

    if use_google_search:
        payload["tools"] = [{"google_search": {}}]
    if aspect_ratio:
        logger.info("Aspect ratio requested but not applied to Gemini payload", extra={"aspect_ratio": aspect_ratio})

    log_gemini_request(
        logger,
        "generate_image_gemini",
        url=url,
        payload=payload,
        model=model,
    )
    response = await asyncio.to_thread(requests.post, url, json=payload, timeout=120)
    response_json = response.json() if response.text else {}
    log_gemini_response(
        logger,
        "generate_image_gemini",
        url=url,
        status_code=response.status_code,
        response=response_json,
    )
    logger.info(
        "Gemini image request completed",
        extra={
            "status": response.status_code,
            "body_preview": (response.text or "")[:400],
            "content_length": len(response.text or ""),
        },
    )

    if not response.ok:
        logger.error("Gemini image generation failed", extra={"status": response.status_code, "body": response.text})
        raise HTTPException(
            status_code=502,
            detail={
                "success": False,
                "error": "gemini_generation_failed",
                "message": response.text[:500],
            },
        )

    return response_json


async def _call_gemini_edit_api(
    prompt_text: str,
    image_base64: str,
    mime_type: str,
    api_key: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_api_key_missing", "message": "GEMINI_API_KEY env is required"},
        )

    logger.info(
        "Gemini edit API call start",
        extra={"prompt_preview": prompt_text[:120], "prompt_len": len(prompt_text), "mime_type": mime_type},
    )

    effective_model = model or os.getenv("GEMINI_IMAGE_EDIT_MODEL") or "gemini-2.5-flash-image"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{effective_model}:generateContent?key={api_key}"

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt_text},
                    {
                        "inline_data": {
                            "mime_type": mime_type or "image/png",
                            "data": image_base64,
                        }
                    },
                ]
            }
        ]
    }

    log_gemini_request(
        logger,
        "image_edit_gemini",
        url=url,
        payload=payload,
        model=effective_model,
    )
    response = await asyncio.to_thread(requests.post, url, json=payload, timeout=180)
    response_json = response.json() if response.text else {}
    log_gemini_response(
        logger,
        "image_edit_gemini",
        url=url,
        status_code=response.status_code,
        response=response_json,
    )
    logger.info("Gemini edit image request completed", extra={"status": response.status_code})

    if not response.ok:
        logger.error("Gemini edit image generation failed", extra={"status": response.status_code, "body": response.text})
        raise HTTPException(
            status_code=502,
            detail={
                "success": False,
                "error": "gemini_edit_generation_failed",
                "message": response.text[:500],
            },
        )

    return response_json


def _extract_image_data(resp_json: Dict[str, Any]) -> Dict[str, str]:
    candidates = resp_json.get("candidates") or []
    logger.info("Parsing Gemini response", extra={"candidate_count": len(candidates)})
    if not candidates:
        raise ValueError("No candidates in Gemini response")

    parts = (candidates[0].get("content", {}) or {}).get("parts", [])
    for part in parts:
        inline = part.get("inline_data") or part.get("inlineData")
        if inline and inline.get("data"):
            logger.info(
                "Inline data found",
                extra={"mimeType": inline.get("mimeType") or "image/png", "data_len": len(inline.get("data", ""))},
            )
            return {
                "data": inline["data"],
                "mimeType": inline.get("mimeType") or "image/png",
            }

    raise ValueError("No inlineData found in Gemini response")


def _extract_text_response(resp_json: Dict[str, Any]) -> Optional[str]:
    candidates = resp_json.get("candidates") or []
    if not candidates:
        return None
    parts = (candidates[0].get("content", {}) or {}).get("parts", [])
    text_parts = [part.get("text", "").strip() for part in parts if isinstance(part.get("text"), str)]
    combined = "\n".join([text for text in text_parts if text])
    return combined or None


def _save_temp_image(image_base64: str, mime_type: str) -> str:
    extension = ".png"
    if "jpeg" in mime_type or "jpg" in mime_type:
        extension = ".jpg"
    elif "webp" in mime_type:
        extension = ".webp"

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=extension)
    tmp_file.write(base64.b64decode(image_base64))
    tmp_file_path = tmp_file.name
    tmp_file.close()
    logger.info("Temp image saved", extra={"path": tmp_file_path, "mime_type": mime_type, "size_bytes": os.path.getsize(tmp_file_path)})
    return tmp_file_path


def _download_image_as_base64(image_url: str) -> Dict[str, str]:
    if not image_url.startswith("http://") and not image_url.startswith("https://"):
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
          detail={"success": False, "error": "image_download_failed", "message": "Downloaded image is empty or too small"},
        )

    logger.info("Image downloaded for edit", extra={"mime_type": mime_type, "size_bytes": len(content)})
    b64 = base64.b64encode(content).decode("utf-8")
    return {"data": b64, "mimeType": mime_type}


def _upload_to_storage(tmp_path: str, user_id: str, file_name: Optional[str]) -> str:
    firebase_storage = _get_storage()
    if firebase_storage is None:
        raise RuntimeError("Firebase storage is not initialized")

    logger.info("Uploading image to storage", extra={"user_id": user_id, "file_name": file_name, "tmp_path": tmp_path})
    bucket = firebase_storage.bucket()
    blob_path = _build_storage_path(user_id, file_name)
    blob = bucket.blob(blob_path)
    blob.upload_from_filename(tmp_path)
    blob.make_public()
    logger.info("Gemini image uploaded to storage", extra={"path": blob_path})
    return blob.public_url


@router.post("/gemini")
async def generate_gemini_image(payload: GeminiImageRequest, request: Request) -> Dict[str, Any]:
    """Generate an image via Google Gemini API and optionally store it in Firebase."""
    if not payload.prompt or not payload.prompt.strip():
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "invalid_prompt", "message": "prompt is required"},
        )

    log_request(logger, "generate_image_gemini", payload)

    user_id = _extract_user_id(request)
    language = normalize_language(payload.language)
    prompt = payload.prompt.strip()
    gemini_key = os.getenv("GEMINI_API_KEY")
    streaming_enabled = bool(payload.stream and payload.chat_id)
    message_id = f"image_{uuid.uuid4().hex}" if streaming_enabled else None
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
            "tool": "generate_image_gemini",
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

    tmp_file_path = None
    final_url: Optional[str] = None
    data_url: Optional[str] = None

    try:
        await emit_status(None)
        use_google_search = False  # default endpoint: no search grounding
        aspect_ratio = payload.aspect_ratio
        model = payload.model or os.getenv("GEMINI_IMAGE_MODEL") or "gemini-2.5-flash-image"
        usage_context = _build_usage_context(request, user_id, "createImages", model, payload)
        usage_data: Dict[str, Any] = {}
        usage_status = "success"
        usage_error_code: Optional[str] = None
        start_time = time.monotonic()

        logger.info(
            "Gemini image generation request",
            extra={
                "userId": user_id,
                "chatId": payload.chat_id,
                "language": language,
                "useGoogleSearch": use_google_search,
                "aspectRatio": aspect_ratio,
                "model": model,
            },
        )

        await emit_status(None)
        system_message = _build_image_system_instruction(language, payload.tone_key)
        prompt_text = f"{system_message}\n\nUSER PROMPT:\n{prompt}"
        try:
            response_json = await _call_gemini_api(
                prompt_text,
                gemini_key,
                model,
                use_google_search,
                aspect_ratio,
            )
            usage_data = extract_gemini_usage_metadata(response_json)
        except Exception:
            usage_status = "error"
            usage_error_code = "gemini_image_failed"
            raise
        finally:
            _enqueue_usage_event(
                usage_context,
                usage_data,
                int((time.monotonic() - start_time) * 1000),
                status=usage_status,
                error_code=usage_error_code,
            )
        logger.info(
            "Gemini API response received",
            extra={"has_candidates": bool(response_json.get("candidates")), "model": model, "useGoogleSearch": use_google_search},
        )
        try:
            inline_data = _extract_image_data(response_json)
        except ValueError:
            text_response = _extract_text_response(response_json)
            logger.error(
                "Gemini returned text-only response for image request",
                extra={"text_preview": (text_response or "")[:200], "model": model},
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "success": False,
                    "error": "gemini_no_image",
                    "message": "Gemini did not return image data (inlineData).",
                    "textPreview": (text_response or "")[:200] or None,
                },
            )
        logger.info("Inline data extracted", extra={"mimeType": inline_data.get("mimeType")})
        tmp_file_path = _save_temp_image(inline_data["data"], inline_data["mimeType"])
        await emit_status(None)

        try:
            final_url = _upload_to_storage(tmp_file_path, user_id, payload.file_name)
            logger.info("Image uploaded to storage", extra={"final_url": final_url})
            await emit_status(None)
        except Exception as storage_exc:
            logger.warning("Firebase upload failed; returning data URL", extra={"error": str(storage_exc)})
            data_url = f"data:{inline_data['mimeType']};base64,{inline_data['data']}"
            logger.info("Using data URL fallback", extra={"has_data_url": bool(data_url)})
            await emit_status(None)

        result_payload = {
            "success": True,
            "imageUrl": final_url,
            "dataUrl": data_url,
            "chatId": payload.chat_id,
            "language": language,
            "model": model,
            "mimeType": inline_data["mimeType"],
        }
        final_image_link = final_url or data_url
        metadata = {
            "prompt": prompt,
            "model": model,
            "useGoogleSearch": use_google_search,
            "aspectRatio": aspect_ratio,
            "tool": "generate_image_gemini",
        }
        logger.info(
            "Writing Gemini generate message to Firestore",
            extra={
                "userId": user_id or "anonymous",
                "chatId": payload.chat_id,
                "hasImageUrl": bool(final_url),
                "hasDataUrl": bool(data_url),
                "model": model,
            },
        )
        response_text = _extract_text_response(response_json)
        ready_msg = response_text or get_image_gen_message(language, "ready")
        _save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id or "",
            content=ready_msg,
            image_url=final_image_link,
            metadata=metadata,
            client_message_id=getattr(payload, "client_message_id", None),
        )
        result = attach_streaming_payload(
            result_payload,
            tool="generate_image_gemini",
            content=ready_msg,
            streaming=streaming_enabled,
            message_id=message_id if streaming_enabled else None,
            extra_data={
                "imageUrl": final_url,
                "dataUrl": data_url,
                "mimeType": inline_data["mimeType"],
            },
        )
        try:
            log_response(logger, "generate_image_gemini", result)
        except Exception:
            logger.warning("Gemini image response logging failed")
        return result
    except HTTPException as he:
        logger.error("Gemini image generation HTTPException", exc_info=he)
        key = "upstream_500"
        if he.status_code == 404: key = "upstream_404"
        elif he.status_code == 429: key = "upstream_429"
        elif he.status_code in (401, 403): key = "upstream_401"
        
        msg = get_api_error_message(key, language)
        failed_msg = get_image_gen_message(language, "failed")
        await emit_status(failed_msg, final=True, error=key)
        
        if payload.chat_id:
            _save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id or "",
                content=msg,
                image_url=None,
                metadata={"tool": "generate_image_gemini", "error": key},
                client_message_id=getattr(payload, "client_message_id", None),
            )
        return {
            "success": True,
            "data": {
                "message": {
                    "content": msg,
                    "id": f"image_error_{os.urandom(4).hex()}"
                },
                "streaming": False,
            }
        }
    except Exception as exc:
        logger.error("Gemini image generation failed", exc_info=exc)
        message = get_api_error_message("upstream_500", language)
        failed_msg = get_image_gen_message(language, "failed")
        await emit_status(failed_msg, final=True, error="image_generation_failed")
        if payload.chat_id:
            _save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id or "",
                content=message,
                image_url=None,
                metadata={"tool": "generate_image_gemini", "error": "upstream_500"},
                client_message_id=getattr(payload, "client_message_id", None),
            )
        return {
            "success": True,
            "data": {
                "message": {
                    "content": message,
                    "id": f"image_error_{os.urandom(4).hex()}"
                },
                "streaming": False,
            }
        }
    finally:
        if tmp_file_path:
            try:
                os.remove(tmp_file_path)
                logger.info("Temp file removed", extra={"path": tmp_file_path})
            except OSError:
                logger.warning("Temp file cleanup failed", extra={"path": tmp_file_path})


## Edit endpoint moved to endpoints/generate_image/edit_image_gemini.py
