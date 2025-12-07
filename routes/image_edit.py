import asyncio
import logging
import os
import tempfile
import time
from typing import Any, Dict

import requests
from fastapi import APIRouter, HTTPException, Request

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
    vision_model = os.getenv("IMAGE_EDIT_VISION_MODEL", "gpt-4-vision-preview")
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
            max_tokens=180,
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


@router.post("/edit")
async def edit_image(payload: ImageEditRequest, request: Request) -> Dict[str, Any]:
    """
    Edit an existing image by generating a new version with DALL·E 3
    based on a user-provided instruction. The endpoint:
      - downloads the source image,
      - (best-effort) describes it with a vision model,
      - generates a new image with DALL·E 3 using the description + edit prompt,
      - uploads the result to Firebase Storage (if available),
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

    # Best-effort description of source image
    description = await _describe_image_with_vision(payload.image_url, language)
    logger.debug("Image description generated", extra={"description": description})

    combined_prompt = (
        f"Edit the image according to: {payload.prompt.strip()}. "
        "Keep main subjects consistent with the source. "
        f"Source description: {description or 'Not available; keep the main subject and composition similar.'}"
    )

    # Generate new image with DALL·E 3
    try:
        dalle_response = await asyncio.to_thread(
            _get_openai_client().images.generate,
            model="dall-e-3",
            prompt=combined_prompt,
            size="1024x1024",
        )
        generated_url = dalle_response.data[0].url
        logger.info(
            "Image edit generated",
            extra={"userId": user_id, "chatId": payload.chat_id, "generatedUrl": generated_url},
        )
    except Exception as exc:
        logger.error("Image edit generation failed", exc_info=exc)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "image_generation_failed", "message": str(exc)},
        ) from exc

    # Download generated image and upload to storage (if available)
    final_url = generated_url
    tmp_file_path = None

    try:
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp_file_path = tmp_file.name

        dl_resp = requests.get(generated_url, timeout=30)
        dl_resp.raise_for_status()
        tmp_file.write(dl_resp.content)
        tmp_file.close()

        try:
            final_url = _upload_to_storage(tmp_file_path, user_id)
            logger.info(
                "Generated image uploaded to storage",
                extra={"userId": user_id, "chatId": payload.chat_id, "finalUrl": final_url},
            )
        except Exception as storage_exc:
            logger.warning("Storage upload failed; returning OpenAI URL", extra={"error": str(storage_exc)})
    finally:
        if tmp_file_path:
            try:
                os.remove(tmp_file_path)
            except OSError:
                pass

    return {
        "success": True,
        "imageUrl": final_url,
        "sourceImageUrl": payload.image_url,
        "description": description,
        "model": "dall-e-3",
    }

