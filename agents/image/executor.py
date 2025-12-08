from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from language_support import normalize_language
from routes.gemini_image import (
    _call_gemini_api,
    _call_gemini_edit_api,
    _extract_image_data,
    _save_temp_image,
    _upload_to_storage,
    _download_image_as_base64,
    _guess_extension_from_mime,
)

logger = logging.getLogger("pdf_read_refresh.image_agents")


async def execute_generate_image(
    *,
    prompt: str,
    chat_id: Optional[str] = None,
    language: Optional[str] = None,
    file_name: Optional[str] = None,
    use_google_search: bool = False,
    aspect_ratio: Optional[str] = None,
    model: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate image via Gemini (backend agent equivalent of frontend generateImageGeminiAgent)."""
    if not prompt or not prompt.strip():
        return {"success": False, "error": "invalid_prompt", "message": "prompt is required"}

    prompt = prompt.strip()
    language = normalize_language(language)
    gemini_key = os.getenv("GEMINI_API_KEY")
    tmp_file_path: Optional[str] = None
    final_url: Optional[str] = None
    data_url: Optional[str] = None
    model_name = model or ("gemini-3-pro-image-preview" if use_google_search else "gemini-2.5-flash-image")
    user = user_id or "agent"

    logger.info(
        "Agent generate_image start",
        extra={
            "chatId": chat_id,
            "language": language,
            "useGoogleSearch": use_google_search,
            "aspectRatio": aspect_ratio,
            "model": model_name,
            "promptPreview": prompt[:120],
            "promptLen": len(prompt),
        },
    )

    try:
        resp_json = await _call_gemini_api(prompt, gemini_key, model_name, use_google_search, aspect_ratio)
        inline_data = _extract_image_data(resp_json)
        tmp_file_path = _save_temp_image(inline_data["data"], inline_data["mimeType"])

        try:
            final_url = _upload_to_storage(tmp_file_path, user, file_name)
        except Exception as storage_exc:
            logger.warning("Storage upload failed; returning data URL", extra={"error": str(storage_exc)})
            data_url = f"data:{inline_data['mimeType']};base64,{inline_data['data']}"

        return {
            "success": True,
            "imageUrl": final_url,
            "dataUrl": data_url,
            "chatId": chat_id,
            "language": language,
            "model": model_name,
            "mimeType": inline_data["mimeType"],
        }
    finally:
        if tmp_file_path:
            try:
                import os

                os.remove(tmp_file_path)
            except OSError:
                logger.warning("Temp file cleanup failed", extra={"path": tmp_file_path})


async def execute_generate_image_search(
    *,
    prompt: str,
    chat_id: Optional[str] = None,
    language: Optional[str] = None,
    file_name: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
    model: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate image via Gemini + Google Search grounding (frontend generateImageGeminiSearchAgent equivalent)."""
    return await execute_generate_image(
        prompt=prompt,
        chat_id=chat_id,
        language=language,
        file_name=file_name,
        use_google_search=True,
        aspect_ratio=aspect_ratio,
        model=model or "gemini-3-pro-image-preview",
        user_id=user_id,
    )


async def execute_edit_image(
    *,
    prompt: str,
    image_url: str,
    chat_id: Optional[str] = None,
    language: Optional[str] = None,
    file_name: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Edit image via Gemini (frontend imageEditGeminiAgent equivalent)."""
    if not prompt or not prompt.strip():
        return {"success": False, "error": "invalid_prompt", "message": "prompt is required"}
    if not image_url or not image_url.strip():
        return {"success": False, "error": "invalid_image_url", "message": "imageUrl is required"}

    prompt = prompt.strip()
    language = normalize_language(language)
    gemini_key = os.getenv("GEMINI_API_KEY")
    tmp_file_path: Optional[str] = None
    final_url: Optional[str] = None
    data_url: Optional[str] = None
    user = user_id or "agent"

    logger.info(
        "Agent edit_image start",
        extra={
            "chatId": chat_id,
            "language": language,
            "promptPreview": prompt[:120],
            "imageUrlPreview": image_url[:200],
        },
    )

    try:
        inline_src = _download_image_as_base64(image_url)
        resp_json = await _call_gemini_edit_api(prompt, inline_src["data"], inline_src["mimeType"], gemini_key)
        inline_data = _extract_image_data(resp_json)
        tmp_file_path = _save_temp_image(inline_data["data"], inline_data["mimeType"])

        try:
            final_url = _upload_to_storage(
                tmp_file_path,
                user,
                file_name or f"gemini-edit{_guess_extension_from_mime(inline_data['mimeType'])}",
            )
        except Exception as storage_exc:
            logger.warning("Storage upload failed (edit); returning data URL", extra={"error": str(storage_exc)})
            data_url = f"data:{inline_data['mimeType']};base64,{inline_data['data']}"

        return {
            "success": True,
            "imageUrl": final_url,
            "dataUrl": data_url,
            "chatId": chat_id,
            "language": language,
            "model": "gemini-2.5-flash-image",
            "mimeType": inline_data["mimeType"],
        }
    finally:
        if tmp_file_path:
            try:
                import os

                os.remove(tmp_file_path)
            except OSError:
                logger.warning("Temp file cleanup failed (edit)", extra={"path": tmp_file_path})


