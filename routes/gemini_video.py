import asyncio
import logging
import os
import tempfile
import time
from typing import Any, Dict, Optional

import requests
from fastapi import APIRouter, HTTPException, Request

from language_support import normalize_language
from schemas import GeminiVideoRequest

logger = logging.getLogger("pdf_read_refresh.gemini_video")

router = APIRouter(prefix="/api/v1/video", tags=["Video"])


def _get_storage():
    from main import storage  # Local import prevents circular dependency

    return storage


def _extract_user_id(request: Request) -> str:
    payload = getattr(request.state, "token_payload", {}) or {}
    return payload.get("uid") or payload.get("userId") or payload.get("sub") or ""


def _build_storage_path(user_id: str, file_name: Optional[str]) -> str:
    safe_user = user_id or "anonymous"
    sanitized_name = (file_name or "gemini-video.mp4").replace("/", "_")
    timestamp = int(time.time() * 1000)
    return f"video-generations/{safe_user}/{timestamp}-{sanitized_name}"


def _save_temp_video_from_bytes(video_bytes: bytes, suffix: str = ".mp4") -> str:
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_file.write(video_bytes)
    tmp_file_path = tmp_file.name
    tmp_file.close()
    logger.info("Temp video saved", extra={"path": tmp_file_path, "size_bytes": os.path.getsize(tmp_file_path)})
    return tmp_file_path


async def _call_veo_generate(prompt: str, api_key: str, model: str = "veo-3.1-generate-preview") -> Dict[str, Any]:
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_api_key_missing", "message": "GEMINI_API_KEY env is required"},
        )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateVideo?key={api_key}"
    payload = {"prompt": prompt}

    logger.info("Veo generateVideo call start", extra={"prompt_preview": prompt[:120], "prompt_len": len(prompt)})
    resp = await asyncio.to_thread(requests.post, url, json=payload, timeout=60)
    logger.info("Veo generateVideo response", extra={"status": resp.status_code})

    if not resp.ok:
        logger.error("Veo generateVideo failed", extra={"status": resp.status_code, "body": resp.text[:500]})
        raise HTTPException(
            status_code=resp.status_code,
            detail={"success": False, "error": "veo_generate_failed", "message": resp.text[:500]},
        )

    data = resp.json()
    operation_name = data.get("name")
    if not operation_name:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "veo_operation_missing", "message": "Operation name missing"},
        )

    return {"operation_name": operation_name}


async def _poll_operation(operation_name: str, api_key: str, poll_interval: float = 5.0, timeout: float = 180.0) -> Dict[str, Any]:
    url = f"https://generativelanguage.googleapis.com/v1beta/operations/{operation_name}?key={api_key}"
    start = time.time()

    while True:
        resp = await asyncio.to_thread(requests.get, url, timeout=30)
        if not resp.ok:
            logger.error("Veo operation poll failed", extra={"status": resp.status_code, "body": resp.text[:300]})
            raise HTTPException(
                status_code=resp.status_code,
                detail={"success": False, "error": "veo_poll_failed", "message": resp.text[:300]},
            )

        data = resp.json()
        done = data.get("done", False)
        if done:
            return data

        if time.time() - start > timeout:
            raise HTTPException(
                status_code=504,
                detail={"success": False, "error": "veo_timeout", "message": "Video generation timed out"},
            )

        await asyncio.sleep(poll_interval)


def _extract_video_bytes(operation_response: Dict[str, Any]) -> bytes:
    response = operation_response.get("response") or {}
    videos = response.get("generatedVideos") or response.get("generated_videos") or []
    if not videos:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "veo_no_video", "message": "No generated video in response"},
        )

    video_obj = videos[0]
    inline_data = video_obj.get("video", {}).get("inlineData") or video_obj.get("video", {}).get("inline_data")
    if not inline_data or not inline_data.get("data"):
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "veo_no_video_data", "message": "Generated video has no inline data"},
        )

    return bytes.fromhex("") if False else base64.b64decode(inline_data["data"])


@router.post("/gemini")
async def generate_gemini_video(payload: GeminiVideoRequest, request: Request) -> Dict[str, Any]:
    """Generate a video via Gemini/Veo API and store in Firebase Storage."""
    if not payload.prompt or not payload.prompt.strip():
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "invalid_prompt", "message": "prompt is required"},
        )

    logger.info(
        "Gemini video endpoint called",
        extra={
            "chat_id": payload.chat_id,
            "language_raw": payload.language,
            "file_name": payload.file_name,
            "prompt_len": len(payload.prompt or ""),
            "prompt_preview": (payload.prompt or "")[:120],
            "duration": payload.duration,
            "resolution": payload.resolution,
        },
    )

    user_id = _extract_user_id(request)
    language = normalize_language(payload.language)
    prompt = payload.prompt.strip()
    gemini_key = os.getenv("GEMINI_API_KEY")

    tmp_file_path = None
    final_url: Optional[str] = None

    try:
        # Step 1: Kick off Veo generateVideo
        op_info = await _call_veo_generate(prompt, gemini_key)
        operation_name = op_info["operation_name"]
        logger.info("Veo operation started", extra={"operation_name": operation_name})

        # Step 2: Poll for completion
        operation_response = await _poll_operation(operation_name, gemini_key, poll_interval=5.0, timeout=240.0)
        logger.info("Veo operation completed", extra={"operation_name": operation_name})

        # Step 3: Extract video bytes
        video_bytes = _extract_video_bytes(operation_response)
        tmp_file_path = _save_temp_video_from_bytes(video_bytes, suffix=".mp4")

        # Step 4: Upload to Firebase Storage
        storage = _get_storage()
        if storage is None:
            raise RuntimeError("Firebase storage is not initialized")

        bucket = storage.bucket()
        blob_path = _build_storage_path(user_id, payload.file_name or "gemini-video.mp4")
        blob = bucket.blob(blob_path)
        logger.info("Uploading video to storage", extra={"blob_path": blob_path})
        blob.upload_from_filename(tmp_file_path)
        blob.make_public()
        final_url = blob.public_url
        logger.info("Video uploaded to storage", extra={"final_url": final_url})

        result = {
            "success": True,
            "videoUrl": final_url,
            "chatId": payload.chat_id,
            "language": language,
            "model": "veo-3.1-generate-preview",
        }
        logger.info("Gemini video response ready", extra={"videoUrl": final_url, "chatId": payload.chat_id})
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Gemini video generation failed", exc_info=exc)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_video_error", "message": str(exc)},
        ) from exc
    finally:
        if tmp_file_path:
            try:
                os.remove(tmp_file_path)
                logger.info("Temp video file removed", extra={"path": tmp_file_path})
            except OSError:
                logger.warning("Temp video cleanup failed", extra={"path": tmp_file_path})

