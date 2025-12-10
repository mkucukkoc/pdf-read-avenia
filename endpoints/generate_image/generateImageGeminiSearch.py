import asyncio
import base64
import logging
import os
import tempfile
import time
from typing import Any, Dict, Optional

import firebase_admin
import requests
from firebase_admin import firestore
from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from errors_response.image_errors import get_no_image_generate_message
from schemas import GeminiImageRequest

logger = logging.getLogger("pdf_read_refresh.gemini_image_search")

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


def _call_gemini_api(
    prompt: str,
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

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateImage?key={api_key}"
    payload: Dict[str, Any] = {
        "prompt": prompt,
    }
    if use_google_search:
        payload["use_google_search"] = True
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio

    logger.info(
        "Gemini Image API call start (search)",
        extra={
            "prompt_preview": prompt[:120],
            "prompt_len": len(prompt),
            "model": model,
            "use_google_search": use_google_search,
            "aspect_ratio": aspect_ratio,
        },
    )

    resp = requests.post(url, json=payload, timeout=120)
    logger.info(
        "Gemini Image API response (search)",
        extra={"status": resp.status_code, "body_preview": resp.text[:800], "use_google_search": use_google_search},
    )

    if not resp.ok:
        logger.error("Gemini API failed (search)", extra={"status": resp.status_code, "body": resp.text[:800]})
        raise HTTPException(
            status_code=resp.status_code,
            detail={"success": False, "error": "gemini_image_search_failed", "message": resp.text[:500]},
        )

    data = resp.json()
    return data


def _extract_image_data(response_json: Dict[str, Any]) -> Dict[str, str]:
    images = response_json.get("images") or response_json.get("candidates") or []
    if not images:
        raise RuntimeError("Gemini search response did not contain any images")

    first = images[0]
    inline_data = first.get("inlineData") or first.get("inline_data") or {}
    if not inline_data.get("data"):
        raise RuntimeError("Gemini search response missing inline image data")
    return inline_data


def _save_temp_image(image_base64: str, mime_type: str) -> str:
    ext = _guess_extension_from_mime(mime_type)
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    tmp_file.write(base64.b64decode(image_base64))
    tmp_file_path = tmp_file.name
    tmp_file.close()
    logger.info("Temp image saved", extra={"path": tmp_file_path, "mime_type": mime_type, "size_bytes": os.path.getsize(tmp_file_path)})
    return tmp_file_path


def _upload_to_storage(tmp_path: str, user_id: str, file_name: Optional[str]) -> str:
    firebase_storage = _get_storage()
    if firebase_storage is None:
        raise RuntimeError("Firebase storage is not initialized")

    logger.info("Uploading image (search) to storage", extra={"user_id": user_id, "file_name": file_name, "tmp_path": tmp_path})
    bucket = firebase_storage.bucket()
    safe_user = user_id or "anonymous"
    sanitized_name = (file_name or "gemini-image.png").replace("/", "_")
    blob_path = f"image-generations/{safe_user}/{int(time.time() * 1000)}-{sanitized_name}"
    blob = bucket.blob(blob_path)
    blob.upload_from_filename(tmp_path)
    blob.make_public()
    logger.info("Gemini image (search) uploaded to storage", extra={"path": blob_path})
    return blob.public_url


def _save_message_to_firestore(
    user_id: str,
    chat_id: str,
    content: str,
    image_url: Optional[str],
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    if not firebase_admin._apps:
        logger.debug("Skipping Firestore save; firebase app not initialized")
        return
    if not chat_id:
        logger.debug("Skipping Firestore save; chat_id missing")
        return

    db = firestore.client()
    data: Dict[str, Any] = {
        "role": "assistant",
        "content": content,
        "timestamp": firestore.SERVER_TIMESTAMP,
        "metadata": metadata or {},
    }
    if image_url:
        data["imageUrl"] = image_url

    try:
        logger.info(
            "Saving assistant message to Firestore (search)",
            extra={
                "userId": user_id or "anonymous",
                "chatId": chat_id,
                "hasImage": bool(image_url),
                "metadata": metadata or {},
            },
        )
        db.collection("users").document(user_id or "anonymous") \
            .collection("chats").document(chat_id) \
            .collection("messages").add(data)
        logger.info("Firestore message saved (search)", extra={"chatId": chat_id, "hasImage": bool(image_url)})
    except Exception as exc:  # pragma: no cover
        logger.exception("Firestore save failed (search)", extra={"error": str(exc), "chatId": chat_id})


@router.post("/gemini-search")
async def generate_gemini_image_with_search(payload: GeminiImageRequest, request: Request) -> Dict[str, Any]:
    """
    Generate an image via Gemini with optional Google Search grounding.
    """
    if not payload.prompt or not payload.prompt.strip():
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "invalid_prompt", "message": "prompt is required"},
        )

    logger.info(
        "Gemini search endpoint called",
        extra={
          "chat_id": payload.chat_id,
          "language_raw": payload.language,
          "file_name": payload.file_name,
          "prompt_len": len(payload.prompt or ""),
          "prompt_preview": (payload.prompt or "")[:120],
          "aspect_ratio": payload.aspect_ratio,
        },
    )

    user_id = _extract_user_id(request)
    language = normalize_language(payload.language)
    prompt = payload.prompt.strip()
    gemini_key = os.getenv("GEMINI_API_KEY")

    tmp_file_path = None
    final_url: Optional[str] = None
    data_url: Optional[str] = None

    try:
        use_google_search = True
        aspect_ratio = payload.aspect_ratio
        model = payload.model or "gemini-2.5-flash-image"

        logger.info(
            "Gemini search generation request",
            extra={
                "userId": user_id,
                "chatId": payload.chat_id,
                "language": language,
                "useGoogleSearch": use_google_search,
                "aspectRatio": aspect_ratio,
                "model": model,
            },
        )

        response_json = await asyncio.to_thread(
            _call_gemini_api,
            prompt,
            gemini_key,
            model,
            use_google_search,
            aspect_ratio,
        )
        logger.info(
            "Gemini API response received (search)",
            extra={"has_images": bool(response_json.get("images") or response_json.get("candidates")), "model": model},
        )

        inline_data = _extract_image_data(response_json)
        logger.info("Inline data extracted (search)", extra={"mimeType": inline_data.get("mimeType")})
        tmp_file_path = _save_temp_image(inline_data["data"], inline_data["mimeType"])

        try:
            final_url = _upload_to_storage(tmp_file_path, user_id, payload.file_name)
            logger.info("Image (search) uploaded to storage", extra={"final_url": final_url})
        except Exception as storage_exc:
            logger.warning("Firebase upload failed (search); returning data URL", extra={"error": str(storage_exc)})
            data_url = f"data:{inline_data['mimeType']};base64,{inline_data['data']}"
            logger.info("Using data URL fallback (search)", extra={"has_data_url": bool(data_url)})

        result = {
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
            "tool": "generate_image_gemini_search",
        }
        logger.info(
            "Writing Gemini search message to Firestore",
            extra={
                "userId": user_id or "anonymous",
                "chatId": payload.chat_id,
                "hasImageUrl": bool(final_url),
                "hasDataUrl": bool(data_url),
                "model": model,
            },
        )
        _save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id or "",
            content="Görsel hazır!",
            image_url=final_image_link,
            metadata=metadata,
        )
        logger.info("Gemini search response ready", extra={"imageUrl": final_url, "hasDataUrl": bool(data_url), "chatId": payload.chat_id})
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Gemini image search failed", exc_info=exc)
        message = get_no_image_generate_message(payload.language)
        if firebase_admin._apps and payload.chat_id:
            _save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id or "",
                content=message,
                image_url=None,
                metadata={"tool": "generate_image_gemini_search", "error": "no_image_generate"},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "no_image_generate", "message": message},
        ) from exc
    finally:
        if tmp_file_path:
            try:
                os.remove(tmp_file_path)
                logger.info("Temp file removed (search)", extra={"path": tmp_file_path})
            except OSError:
                logger.warning("Temp file cleanup failed (search)", extra={"path": tmp_file_path})


__all__ = ["router"]


