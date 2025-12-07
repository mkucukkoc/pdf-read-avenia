import asyncio
import base64
import logging
import os
import tempfile
import time
from io import BytesIO
from typing import Any, Dict, Optional

import requests
from fastapi import APIRouter, HTTPException, Request
from openai import PermissionDeniedError
from PIL import Image

from schemas import ImageEditRequest
from language_support import normalize_language

logger = logging.getLogger("pdf_read_refresh.image_edit")

router = APIRouter(prefix="/api/v1/image", tags=["Image"])


def _get_openai_client():
    from main import client  # Local import to avoid circular dependency

    return client


def _get_storage():
    from main import storage  # Local import to avoid circular dependency

    return storage


def _extract_user_id(request: Request) -> str:
    payload = getattr(request.state, "token_payload", {}) or {}
    return payload.get("uid") or payload.get("userId") or payload.get("sub") or ""


async def _describe_image_with_vision(image_url: str, language: str) -> str:
    """
    Attempt to get a concise description of the uploaded image using a vision model.
    Falls back to an empty string on failure.
    """
    vision_model = os.getenv("IMAGE_EDIT_VISION_MODEL", "gpt-4o-mini")
    prompt = (
        "Describe the main subjects, colors, camera angle, and background of this image "
        "concisely in the requested language. Keep it under 80 words."
    )

    try:
        response = await asyncio.to_thread(
            _get_openai_client().chat.completions.create,
            model=vision_model,
            messages=[
                {"role": "system", "content": f"You are an assistant that describes images in {language or 'English'}."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            max_completion_tokens=180,
            temperature=0.2,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("Vision description failed", extra={"error": str(exc)})
        return ""


def _upload_to_storage(tmp_path: str, user_id: str) -> str:
    """
    Upload generated image to Firebase Storage if available.
    Returns the public URL or raises on failure.
    """
    firebase_storage = _get_storage()
    if firebase_storage is None:
        raise RuntimeError("Firebase storage is not initialized")

    bucket = firebase_storage.bucket()
    safe_user = user_id or "anonymous"
    blob_path = f"image-edits/{safe_user}/{int(time.time() * 1000)}.png"
    blob = bucket.blob(blob_path)
    blob.upload_from_filename(tmp_path)
    blob.make_public()
    return blob.public_url


def _download_image_as_png(url: str) -> str:
    """
    Download the original image, convert it to PNG (RGBA) and write to a temp file.
    Returns the temp file path.
    """
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp_file_path = tmp_file.name
    tmp_file.close()

    with BytesIO(response.content) as buffer:
        with Image.open(buffer) as img:
            rgba_image = img.convert("RGBA")
            rgba_image.save(tmp_file_path, format="PNG")

    return tmp_file_path


def _perform_image_edit(source_path: str, prompt: str) -> Any:
    """
    Blocking helper that calls OpenAI's image edit endpoint.
    """
    model = os.getenv("IMAGE_EDIT_MODEL", "gpt-image-1")
    size = os.getenv("IMAGE_EDIT_SIZE", "1024x1024")

    with open(source_path, "rb") as image_file:
        return _get_openai_client().images.edit(
            model=model,
            image=image_file,
            prompt=prompt,
            size=size,
        )


async def _generate_image_edit(source_path: str, prompt: str) -> str:
    """
    Run the image edit request in a worker thread and persist the base64 output as PNG.
    Returns the path to the edited temporary PNG.
    """
    response = await asyncio.to_thread(_perform_image_edit, source_path, prompt)
    if not response.data:
        raise RuntimeError("Image edit response did not contain any data")

    first_item = response.data[0]
    image_b64 = getattr(first_item, "b64_json", None)
    if image_b64 is None and isinstance(first_item, dict):
        image_b64 = first_item.get("b64_json")
    if not image_b64:
        raise RuntimeError("Image edit response missing b64_json payload")

    raw_bytes = base64.b64decode(image_b64)
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp_file.write(raw_bytes)
    tmp_file_path = tmp_file.name
    tmp_file.close()

    return tmp_file_path



@router.post("/edit")
async def edit_image(payload: ImageEditRequest, request: Request) -> Dict[str, Any]:
    """
    Edit an existing image by sending the source PNG to OpenAI's image edit endpoint.
    The endpoint:
      - downloads + normalizes the source image,
      - (best-effort) describes it with a vision model,
      - sends the source image + edit prompt to OpenAI,
      - uploads the edited result to Firebase Storage,
      - returns the final URL.
    """
    user_id = _extract_user_id(request)
    language = normalize_language(payload.language)

    logger.info(
        "Image edit request received",
        extra={
            "userId": user_id,
            "chatId": payload.chat_id,
            "imageUrl": payload.image_url,
            "language": language,
        },
    )

    if not payload.image_url or not payload.prompt:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "invalid_request", "message": "imageUrl and prompt are required"},
        )

    try:
        source_tmp_path = _download_image_as_png(payload.image_url)
    except Exception as exc:
        logger.error("Failed to download/normalize source image", exc_info=exc)
        raise HTTPException(
            status_code=422,
            detail={"success": False, "error": "source_download_failed", "message": "Original image could not be read"},
        ) from exc

    description = ""
    edited_tmp_path = None
    final_url: Optional[str] = None
    try:
        description = await _describe_image_with_vision(payload.image_url, language)
        logger.debug("Image description generated", extra={"description": description})

        combined_prompt = (
            f"Edit the image according to: {payload.prompt.strip()}. "
            "Keep main subjects consistent with the source. "
            f"Source description: {description or 'Not available; keep the main subject and composition similar.'}"
        )

        try:
            edited_tmp_path = await _generate_image_edit(source_tmp_path, combined_prompt)
        except PermissionDeniedError as exc:
            logger.error(
                "Image edit endpoint forbidden by OpenAI",
                extra={"error": str(exc)},
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "success": False,
                    "error": "image_edit_forbidden",
                    "message": "OpenAI image edit API denied access. Please verify the organization in OpenAI settings.",
                },
            ) from exc
        logger.info(
            "Image edit generated",
            extra={"userId": user_id, "chatId": payload.chat_id, "tmpPath": edited_tmp_path},
        )

        final_url = _upload_to_storage(edited_tmp_path, user_id)
        logger.info(
            "Edited image uploaded to storage",
            extra={"userId": user_id, "chatId": payload.chat_id, "finalUrl": final_url},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Image edit generation failed", exc_info=exc)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "image_generation_failed", "message": str(exc)},
        ) from exc
    finally:
        for tmp_path in (source_tmp_path, edited_tmp_path):
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    return {
        "success": True,
        "imageUrl": final_url,
        "sourceImageUrl": payload.image_url,
        "description": description,
        "model": os.getenv("IMAGE_EDIT_MODEL", "gpt-image-1"),
    }

