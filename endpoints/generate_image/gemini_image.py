import asyncio
import base64
import logging
import os
import tempfile
import time
from typing import Any, Dict, Optional

import requests
import firebase_admin
from firebase_admin import firestore
from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from schemas import GeminiImageEditRequest, GeminiImageRequest

logger = logging.getLogger("pdf_read_refresh.gemini_image")

router = APIRouter(prefix="/api/v1/image", tags=["Image"])


def _get_storage():
    from main import storage  # Local import prevents circular dependency

    return storage


def _extract_user_id(request: Request) -> str:
    payload = getattr(request.state, "token_payload", {}) or {}
    return payload.get("uid") or payload.get("userId") or payload.get("sub") or ""


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
            "Saving assistant message to Firestore",
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
        logger.info("Firestore message saved", extra={"chatId": chat_id, "hasImage": bool(image_url)})
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


async def _call_gemini_api(
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

    logger.info(
        "Gemini API call start",
        extra={
            "prompt_preview": prompt[:120],
            "prompt_len": len(prompt),
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
                        "text": prompt,
                    }
                ],
            }
        ]
    }

    if use_google_search:
        payload["tools"] = [{"google_search": {}}]
        payload["response_modalities"] = ["TEXT", "IMAGE"]
        if aspect_ratio:
            payload["image_config"] = {"aspect_ratio": aspect_ratio}

    response = await asyncio.to_thread(requests.post, url, json=payload, timeout=120)
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

    return response.json()


async def _call_gemini_edit_api(prompt: str, image_base64: str, mime_type: str, api_key: str) -> Dict[str, Any]:
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_api_key_missing", "message": "GEMINI_API_KEY env is required"},
        )

    logger.info(
        "Gemini edit API call start",
        extra={"prompt_preview": prompt[:120], "prompt_len": len(prompt), "mime_type": mime_type},
    )

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.5-flash-image:generateContent"
        f"?key={api_key}"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
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

    response = await asyncio.to_thread(requests.post, url, json=payload, timeout=180)
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

    return response.json()


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

    logger.info(
        "Gemini endpoint called",
        extra={
          "chat_id": payload.chat_id,
          "language_raw": payload.language,
          "file_name": payload.file_name,
          "prompt_len": len(payload.prompt or ""),
          "prompt_preview": (payload.prompt or "")[:120],
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
        use_google_search = False  # default endpoint: no search grounding
        aspect_ratio = payload.aspect_ratio
        model = payload.model or "gemini-2.5-flash-image"

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

        response_json = await _call_gemini_api(prompt, gemini_key, model, use_google_search, aspect_ratio)
        logger.info(
            "Gemini API response received",
            extra={"has_candidates": bool(response_json.get("candidates")), "model": model, "useGoogleSearch": use_google_search},
        )
        inline_data = _extract_image_data(response_json)
        logger.info("Inline data extracted", extra={"mimeType": inline_data.get("mimeType")})
        tmp_file_path = _save_temp_image(inline_data["data"], inline_data["mimeType"])

        try:
            final_url = _upload_to_storage(tmp_file_path, user_id, payload.file_name)
            logger.info("Image uploaded to storage", extra={"final_url": final_url})
        except Exception as storage_exc:
            logger.warning("Firebase upload failed; returning data URL", extra={"error": str(storage_exc)})
            data_url = f"data:{inline_data['mimeType']};base64,{inline_data['data']}"
            logger.info("Using data URL fallback", extra={"has_data_url": bool(data_url)})

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
        _save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id or "",
            content="Görsel hazır!",
            image_url=final_image_link,
            metadata=metadata,
        )
        logger.info("Gemini image response ready", extra={"imageUrl": final_url, "hasDataUrl": bool(data_url), "chatId": payload.chat_id})
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Gemini image generation failed", exc_info=exc)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_image_error", "message": str(exc)},
        ) from exc
    finally:
        if tmp_file_path:
            try:
                os.remove(tmp_file_path)
                logger.info("Temp file removed", extra={"path": tmp_file_path})
            except OSError:
                logger.warning("Temp file cleanup failed", extra={"path": tmp_file_path})


@router.post("/gemini-search")
async def generate_gemini_image_with_search(payload: GeminiImageRequest, request: Request) -> Dict[str, Any]:
    """
    Generate an image via Gemini with optional Google Search grounding.
    This endpoint allows use_google_search and aspect_ratio to be configured.
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
          "use_google_search": payload.use_google_search,
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
        use_google_search = bool(payload.use_google_search)
        aspect_ratio = payload.aspect_ratio
        model = payload.model or "gemini-2.5-flash-image"

        logger.info(
            "Gemini search image generation request",
            extra={
                "userId": user_id,
                "chatId": payload.chat_id,
                "language": language,
                "useGoogleSearch": use_google_search,
                "aspectRatio": aspect_ratio,
                "model": model,
            },
        )

        response_json = await _call_gemini_api(prompt, gemini_key, model, use_google_search, aspect_ratio)
        logger.info(
            "Gemini search API response received",
            extra={"has_candidates": bool(response_json.get("candidates")), "model": model, "useGoogleSearch": use_google_search},
        )
        inline_data = _extract_image_data(response_json)
        logger.info("Inline data extracted (search)", extra={"mimeType": inline_data.get("mimeType")})
        tmp_file_path = _save_temp_image(inline_data["data"], inline_data["mimeType"])
        logger.info("Temp file ready for upload (search)", extra={"tmp_path": tmp_file_path})

        try:
            final_url = _upload_to_storage(tmp_file_path, user_id, payload.file_name)
            logger.info("Image uploaded to storage (search)", extra={"final_url": final_url})
        except Exception as storage_exc:
            logger.warning("Firebase upload failed; returning data URL", extra={"error": str(storage_exc)})
            data_url = f"data:{inline_data['mimeType']};base64,{inline_data['data']}"
            logger.info("Using data URL fallback", extra={"has_data_url": bool(data_url)})

        result = {
            "success": True,
            "imageUrl": final_url,
            "dataUrl": data_url,
            "chatId": payload.chat_id,
            "language": language,
            "model": model,
            "mimeType": inline_data["mimeType"],
        }
        logger.info("Gemini search response ready", extra={"imageUrl": final_url, "hasDataUrl": bool(data_url), "chatId": payload.chat_id})
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Gemini search image generation failed", exc_info=exc)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_search_generation_error", "message": str(exc)},
        ) from exc
    finally:
        if tmp_file_path:
            try:
                os.remove(tmp_file_path)
                logger.info("Temp file removed", extra={"path": tmp_file_path})
            except OSError:
                logger.warning("Temp file cleanup failed", extra={"path": tmp_file_path})


@router.post("/gemini-edit")
async def edit_gemini_image(payload: GeminiImageEditRequest, request: Request) -> Dict[str, Any]:
    """Edit/transform an image via Google Gemini API using a prompt and an input image URL."""
    if not payload.prompt or not payload.prompt.strip():
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "invalid_prompt", "message": "prompt is required"},
        )
    if not payload.image_url or not payload.image_url.strip():
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "invalid_image_url", "message": "imageUrl is required"},
        )

    logger.info(
        "Gemini edit endpoint called",
        extra={
          "chat_id": payload.chat_id,
          "language_raw": payload.language,
          "file_name": payload.file_name,
          "prompt_len": len(payload.prompt or ""),
          "prompt_preview": (payload.prompt or "")[:120],
          "image_url": payload.image_url[:200],
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
        logger.info(
            "Downloading source image for edit",
            extra={
                "image_url": payload.image_url[:200],
                "chat_id": payload.chat_id,
                "prompt_len": len(prompt),
            },
        )
        inline = _download_image_as_base64(payload.image_url)
        logger.info(
            "Source image downloaded",
            extra={"mime_type": inline["mimeType"], "data_len": len(inline["data"])},
        )

        logger.info("Calling Gemini edit API...", extra={"prompt_preview": prompt[:120], "mime_type": inline["mimeType"]})
        response_json = await _call_gemini_edit_api(prompt, inline["data"], inline["mimeType"], gemini_key)
        logger.info("Gemini edit API response received", extra={"has_candidates": bool(response_json.get("candidates"))})

        inline_data = _extract_image_data(response_json)
        logger.info("Inline data extracted (edit)", extra={"mimeType": inline_data.get("mimeType")})
        tmp_file_path = _save_temp_image(inline_data["data"], inline_data["mimeType"])
        logger.info("Temp file ready for upload (edit)", extra={"tmp_path": tmp_file_path})

        try:
            final_url = _upload_to_storage(tmp_file_path, user_id, payload.file_name or f"gemini-edit{_guess_extension_from_mime(inline_data['mimeType'])}")
            logger.info("Edited image uploaded to storage", extra={"final_url": final_url})
        except Exception as storage_exc:
            logger.warning("Firebase upload failed for edit; returning data URL", extra={"error": str(storage_exc)})
            data_url = f"data:{inline_data['mimeType']};base64,{inline_data['data']}"
            logger.info("Using data URL fallback (edit)", extra={"has_data_url": bool(data_url)})

        result = {
            "success": True,
            "imageUrl": final_url,
            "dataUrl": data_url,
            "chatId": payload.chat_id,
            "language": language,
            "model": "gemini-2.5-flash-image",
            "mimeType": inline_data["mimeType"],
        }
        final_image_link = final_url or data_url
        metadata = {
            "prompt": prompt,
            "model": "gemini-2.5-flash-image",
            "tool": "image_edit_gemini",
        }
        logger.info(
            "Writing Gemini edit message to Firestore",
            extra={
                "userId": user_id or "anonymous",
                "chatId": payload.chat_id,
                "hasImageUrl": bool(final_url),
                "hasDataUrl": bool(data_url),
                "model": "gemini-2.5-flash-image",
            },
        )
        _save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id or "",
            content="Görsel düzenlendi!",
            image_url=final_image_link,
            metadata=metadata,
        )
        logger.info("Gemini edit response ready", extra={"imageUrl": final_url, "hasDataUrl": bool(data_url), "chatId": payload.chat_id})
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Gemini image edit failed", exc_info=exc)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_edit_error", "message": str(exc)},
        ) from exc
    finally:
        if tmp_file_path:
            try:
                os.remove(tmp_file_path)
                logger.info("Temp file removed (edit)", extra={"path": tmp_file_path})
            except OSError:
                logger.warning("Temp file cleanup failed (edit)", extra={"path": tmp_file_path})


