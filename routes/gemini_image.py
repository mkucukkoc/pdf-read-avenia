import asyncio
import base64
import logging
import os
import tempfile
import time
from typing import Any, Dict, Optional

import requests
from fastapi import APIRouter, HTTPException, Request

from language_support import normalize_language
from schemas import GeminiImageRequest

logger = logging.getLogger("pdf_read_refresh.gemini_image")

router = APIRouter(prefix="/api/v1/image", tags=["Image"])


def _get_storage():
    from main import storage  # Local import prevents circular dependency

    return storage


def _extract_user_id(request: Request) -> str:
    payload = getattr(request.state, "token_payload", {}) or {}
    return payload.get("uid") or payload.get("userId") or payload.get("sub") or ""


def _build_storage_path(user_id: str, file_name: Optional[str]) -> str:
    safe_user = user_id or "anonymous"
    sanitized_name = (file_name or "gemini-image.png").replace("/", "_")
    timestamp = int(time.time() * 1000)
    return f"image-generations/{safe_user}/{timestamp}-{sanitized_name}"


async def _call_gemini_api(prompt: str, api_key: str) -> Dict[str, Any]:
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_api_key_missing", "message": "GEMINI_API_KEY env is required"},
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
                    {
                        "text": prompt,
                    }
                ],
            }
        ]
    }

    response = await asyncio.to_thread(requests.post, url, json=payload, timeout=120)
    logger.info("Gemini image request completed", extra={"status": response.status_code})

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


def _extract_image_data(resp_json: Dict[str, Any]) -> Dict[str, str]:
    candidates = resp_json.get("candidates") or []
    if not candidates:
        raise ValueError("No candidates in Gemini response")

    parts = (candidates[0].get("content", {}) or {}).get("parts", [])
    for part in parts:
        inline = part.get("inline_data") or part.get("inlineData")
        if inline and inline.get("data"):
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
    return tmp_file_path


def _upload_to_storage(tmp_path: str, user_id: str, file_name: Optional[str]) -> str:
    firebase_storage = _get_storage()
    if firebase_storage is None:
        raise RuntimeError("Firebase storage is not initialized")

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

    user_id = _extract_user_id(request)
    language = normalize_language(payload.language)
    prompt = payload.prompt.strip()
    gemini_key = os.getenv("GEMINI_API_KEY")

    logger.info(
        "Gemini image generation request",
        extra={"userId": user_id, "chatId": payload.chat_id, "language": language},
    )

    tmp_file_path = None
    final_url: Optional[str] = None
    data_url: Optional[str] = None

    try:
        response_json = await _call_gemini_api(prompt, gemini_key)
        inline_data = _extract_image_data(response_json)
        tmp_file_path = _save_temp_image(inline_data["data"], inline_data["mimeType"])

        try:
            final_url = _upload_to_storage(tmp_file_path, user_id, payload.file_name)
        except Exception as storage_exc:
            logger.warning("Firebase upload failed; returning data URL", extra={"error": str(storage_exc)})
            data_url = f"data:{inline_data['mimeType']};base64,{inline_data['data']}"

        return {
            "success": True,
            "imageUrl": final_url,
            "dataUrl": data_url,
            "chatId": payload.chat_id,
            "language": language,
            "model": "gemini-2.5-flash-image",
            "mimeType": inline_data["mimeType"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Gemini image generation failed", exc_info=exc)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_generation_error", "message": str(exc)},
        ) from exc
    finally:
        if tmp_file_path:
            try:
                os.remove(tmp_file_path)
            except OSError:
                pass
