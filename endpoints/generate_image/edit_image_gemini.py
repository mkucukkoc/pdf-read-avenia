import asyncio
import base64
import json
import logging
import os
import tempfile
import time
import uuid
from typing import Any, Dict, Optional

import firebase_admin
import requests
from firebase_admin import firestore
from fastapi import APIRouter, HTTPException, Request
from PIL import Image

from core.language_support import normalize_language, get_image_gen_message
from core.websocket_manager import stream_manager
from core.useChatPersistence import chat_persistence
from errors_response.image_errors import get_image_edit_failed_message
from errors_response.api_errors import get_api_error_message
from schemas import GeminiImageEditRequest
from endpoints.files_pdf.utils import attach_streaming_payload
from endpoints.logging.utils_logging import log_gemini_request, log_gemini_response, log_request, log_response

logger = logging.getLogger("pdf_read_refresh.gemini_image_edit")

router = APIRouter(prefix="/api/v1/image", tags=["Image"])


def _get_storage():
    from main import storage  # Local import prevents circular dependency

    return storage


def _extract_user_id(request: Request) -> str:
    payload = getattr(request.state, "token_payload", {}) or {}
    return payload.get("uid") or payload.get("userId") or payload.get("sub") or ""


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




def _extract_text_response(resp_json: Dict[str, Any]) -> Optional[str]:
    candidates = resp_json.get("candidates") or []
    if not candidates:
        return None
    parts = (candidates[0].get("content", {}) or {}).get("parts", [])
    text_parts = [part.get("text", "").strip() for part in parts if isinstance(part.get("text"), str)]
    combined = "\n".join([text for text in text_parts if text])
    return combined or None


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


def _call_gemini_edit_api(
    prompt_text: str,
    base64_image: str,
    mime_type: str,
    api_key: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_api_key_missing", "message": "GEMINI_API_KEY env is required"},
        )

    # Varsayılan olarak metin+görsel için desteklenen model; env ile özelleştirilebilir
    effective_model = model or os.getenv("GEMINI_IMAGE_EDIT_MODEL") or "gemini-2.5-flash-image"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{effective_model}:generateContent?key={api_key}"
    request_body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt_text},
                    {
                        "inlineData": {
                            "data": base64_image,
                            "mimeType": mime_type,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }

    log_gemini_request(
        logger,
        "image_edit_gemini",
        url=url,
        payload=request_body,
        model=effective_model,
    )
    logger.info(
        "Calling Gemini edit API",
        extra={"prompt_len": len(prompt_text), "prompt_preview": prompt_text[:120], "mime_type": mime_type, "model": effective_model},
    )
    resp = requests.post(url, json=request_body, timeout=120)
    response_json = resp.json() if resp.text else {}
    log_gemini_response(
        logger,
        "image_edit_gemini",
        url=url,
        status_code=resp.status_code,
        response=response_json,
    )
    logger.info("Gemini edit API response", extra={"status": resp.status_code, "body_preview": resp.text[:800]})
    if not resp.ok:
        raise HTTPException(
            status_code=resp.status_code,
            detail={"success": False, "error": "gemini_edit_failed", "message": resp.text[:500]},
        )
    return response_json


def _extract_image_data(response_json: Dict[str, Any]) -> Dict[str, str]:
    candidates = response_json.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini response missing candidates")

    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    for part in parts:
        inline_data = part.get("inlineData") or part.get("inline_data")
        if inline_data and inline_data.get("data"):
            return inline_data

    raise RuntimeError("Gemini response missing inline image data")


def _save_temp_image(image_base64: str, mime_type: str) -> str:
    ext = _guess_extension_from_mime(mime_type)
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
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
    safe_user = user_id or "anonymous"
    sanitized_name = (file_name or "gemini-image.png").replace("/", "_")
    blob_path = f"image-generations/{safe_user}/{int(time.time() * 1000)}-{sanitized_name}"
    blob = bucket.blob(blob_path)
    blob.upload_from_filename(tmp_path)
    blob.make_public()
    logger.info("Gemini image uploaded to storage", extra={"path": blob_path})
    return blob.public_url


def _find_latest_image_url(user_id: str, chat_id: str) -> Optional[str]:
    if not firebase_admin._apps:
        logger.debug("Firestore not initialized; cannot fetch previous image url")
        return None
    if not chat_id:
        return None

    db = firestore.client()
    msgs = (
        db.collection("users")
        .document(user_id or "anonymous")
        .collection("chats")
        .document(chat_id)
        .collection("messages")
        .order_by("timestamp", direction=firestore.Query.DESCENDING)
        .limit(50)
        .stream()
    )

    placeholder_patterns = ["your-image-url", "example.com/your-image-url"]

    for doc in msgs:
        data = doc.to_dict() or {}
        for key in ("imageUrl", "fileUrl"):
            url = data.get(key)
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                if any(pat in url for pat in placeholder_patterns):
                    continue
                logger.info("Found prior image URL for edit", extra={"chatId": chat_id, "sourceKey": key, "url_preview": url[:120]})
                return url
    logger.warning("No prior image URL found in chat history", extra={"chatId": chat_id})
    return None


@router.post("/gemini-edit")
async def edit_gemini_image(payload: GeminiImageEditRequest, request: Request) -> Dict[str, Any]:
    """Edit/transform an image via Google Gemini API using a prompt and (optionally) last image in chat."""
    if not payload.prompt or not payload.prompt.strip():
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "invalid_prompt", "message": "prompt is required"},
        )

    log_request(logger, "image_edit_gemini", payload)

    user_id = _extract_user_id(request)
    language = normalize_language(payload.language)
    prompt = payload.prompt.strip()
    gemini_key = os.getenv("GEMINI_API_KEY")
    effective_model = payload.model or os.getenv("GEMINI_IMAGE_EDIT_MODEL") or "gemini-2.5-flash-image"
    streaming_enabled = bool(payload.stream and payload.chat_id)
    message_id = f"image_edit_{uuid.uuid4().hex}" if streaming_enabled else None
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
            "tool": "image_edit_gemini",
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

    image_url = payload.image_url.strip() if isinstance(payload.image_url, str) else ""
    placeholder_patterns = ["your-image-url", "example.com/your-image-url"]
    if (not image_url) or any(pat in image_url for pat in placeholder_patterns):
        logger.info("Image URL missing or placeholder; attempting to fetch last image from chat", extra={"chatId": payload.chat_id, "userId": user_id})
        found_url = _find_latest_image_url(user_id, payload.chat_id or "")
        if not found_url:
            logger.info("[image_edit_gemini] NO_IMAGE_IN_CHAT", extra={"chatId": payload.chat_id})
            if payload.chat_id:
                _save_message_to_firestore(
                    user_id=user_id,
                    chat_id=payload.chat_id,
                    content="Bu sohbet içinde düzenlenebilecek bir görsel bulunamadı.",
                    image_url=None,
                metadata={"tool": "image_edit_gemini", "error": "no_image_found"},
                client_message_id=getattr(payload, "client_message_id", None),
                )
            raise HTTPException(
                status_code=400,
                detail={
                    "success": False,
                    "error": "no_image_found",
                    "message": "Bu sohbet içinde düzenlenebilecek bir görsel bulunamadı.",
                },
            )
        image_url = found_url

    tmp_file_path = None
    final_url: Optional[str] = None
    data_url: Optional[str] = None

    try:
        await emit_status(None)
        logger.info(
            "Downloading source image for edit",
            extra={
                "image_url": image_url[:200],
                "chat_id": payload.chat_id,
                "prompt_len": len(prompt),
            },
        )
        inline = _download_image_as_base64(image_url)
        logger.info(
            "Source image downloaded",
            extra={"mime_type": inline["mimeType"], "data_len": len(inline["data"])},
        )
        await emit_status(None)

        logger.info("Calling Gemini edit API...", extra={"prompt_preview": prompt[:120], "mime_type": inline["mimeType"]})
        system_message = _build_image_system_instruction(language, payload.tone_key)
        prompt_text = f"{system_message}\n\nUSER PROMPT:\n{prompt}"
        response_json = await asyncio.to_thread(
            _call_gemini_edit_api,
            prompt_text,
            inline["data"],
            inline["mimeType"],
            gemini_key,
            effective_model,
        )
        logger.info("Gemini edit API response received", extra={"has_candidates": bool(response_json.get("candidates"))})

        try:
            inline_data = _extract_image_data(response_json)
        except RuntimeError:
            text_response = _extract_text_response(response_json)
            logger.error(
                "Gemini returned text-only response for image edit request",
                extra={"text_preview": (text_response or "")[:200], "model": effective_model},
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
        logger.info("Inline data extracted (edit)", extra={"mimeType": inline_data.get("mimeType")})
        tmp_file_path = _save_temp_image(inline_data["data"], inline_data["mimeType"])
        logger.info("Temp file ready for upload (edit)", extra={"tmp_path": tmp_file_path})
        await emit_status(None)

        try:
            final_url = _upload_to_storage(tmp_file_path, user_id, payload.file_name or f"gemini-edit{_guess_extension_from_mime(inline_data['mimeType'])}")
            logger.info("Edited image uploaded to storage", extra={"final_url": final_url})
            await emit_status(None)
        except Exception as storage_exc:
            logger.warning("Firebase upload failed for edit; returning data URL", extra={"error": str(storage_exc)})
            data_url = f"data:{inline_data['mimeType']};base64,{inline_data['data']}"
            logger.info("Using data URL fallback (edit)", extra={"has_data_url": bool(data_url)})
            await emit_status(None)

        result_payload = {
            "success": True,
            "imageUrl": final_url,
            "dataUrl": data_url,
            "chatId": payload.chat_id,
            "language": language,
            "model": effective_model,
            "mimeType": inline_data["mimeType"],
        }
        final_image_link = final_url or data_url
        metadata = {
            "prompt": prompt,
            "model": effective_model,
            "tool": "image_edit_gemini",
        }
        logger.info(
            "Writing Gemini edit message to Firestore",
            extra={
                "userId": user_id or "anonymous",
                "chatId": payload.chat_id,
                "hasImageUrl": bool(final_url),
                "hasDataUrl": bool(data_url),
                "model": effective_model,
            },
        )
        response_text = _extract_text_response(response_json)
        edited_msg = response_text or get_image_gen_message(language, "edited")
        _save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id or "",
            content=edited_msg,
            image_url=final_image_link,
            metadata=metadata,
            client_message_id=getattr(payload, "client_message_id", None),
        )
        await emit_status(
            edited_msg,
            final=True,
            metadata={
                "imageUrl": final_image_link,
                "tool": "image_edit_gemini",
                "mimeType": inline_data["mimeType"],
            },
        )
        result = attach_streaming_payload(
            result_payload,
            tool="image_edit_gemini",
            content=edited_msg,
            streaming=streaming_enabled,
            message_id=message_id if streaming_enabled else None,
            extra_data={
                "imageUrl": final_url,
                "dataUrl": data_url,
                "mimeType": inline_data["mimeType"],
            },
        )
        try:
            log_response(logger, "image_edit_gemini", result)
        except Exception:
            logger.warning("Gemini edit response logging failed")
        return result
    except HTTPException as he:
        logger.error("Gemini image edit HTTPException", exc_info=he)
        key = "upstream_500"
        if he.status_code == 404: key = "upstream_404"
        elif he.status_code == 429: key = "upstream_429"
        elif he.status_code in (401, 403): key = "upstream_401"
        
        msg = get_api_error_message(key, language)
        edit_failed_msg = get_image_gen_message(language, "edit_failed")
        await emit_status(edit_failed_msg, final=True, error=key)
        
        if payload.chat_id:
            _save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id or "",
                content=msg,
                image_url=None,
                metadata={"tool": "image_edit_gemini", "error": key},
            )
        return {
            "success": True,
            "data": {
                "message": {
                    "content": msg,
                    "id": f"image_edit_error_{os.urandom(4).hex()}"
                },
                "streaming": False,
            }
        }
    except Exception as exc:
        logger.error("Gemini image edit failed", exc_info=exc)
        message = get_api_error_message("upstream_500", language)
        edit_failed_msg = get_image_gen_message(language, "edit_failed")
        await emit_status(edit_failed_msg, final=True, error="image_edit_failed")
        if payload.chat_id:
            _save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id or "",
                content=message,
                image_url=None,
                metadata={"tool": "image_edit_gemini", "error": "upstream_500"},
                client_message_id=getattr(payload, "client_message_id", None),
            )
        return {
            "success": True,
            "data": {
                "message": {
                    "content": message,
                    "id": f"image_edit_error_{os.urandom(4).hex()}"
                },
                "streaming": False,
            }
        }
    finally:
        if tmp_file_path:
            try:
                os.remove(tmp_file_path)
                logger.info("Temp file removed (edit)", extra={"path": tmp_file_path})
            except OSError:
                logger.warning("Temp file cleanup failed (edit)", extra={"path": tmp_file_path})


__all__ = ["router"]
