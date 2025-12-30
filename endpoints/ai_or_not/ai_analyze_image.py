import json
import logging
import base64
import os
from typing import Optional

import httpx
from fastapi import Body, Query, APIRouter, HTTPException
from fastapi.responses import JSONResponse
from firebase_admin import firestore

from core.language_support import (
    normalize_language,
    build_ai_detection_messages,
    format_ai_detection_summary,
    nsfw_flag_from_value,
    quality_flag_from_value,
)

logger = logging.getLogger("pdf_read_refresh.endpoints.analyze_image")
FAIL_MSG = "Görsel şu anda analiz edilemiyor, lütfen tekrar deneyin."
IMAGE_ENDPOINT = os.getenv("IMAGE_ENDPOINT", "https://api.aiornot.com/v1/reports/image")
API_KEY = os.getenv("AIORNOT_API_KEY", "")
router = APIRouter()


def decode_base64_maybe_data_url(data: str) -> bytes:
    """
    Supports raw base64 or data URLs like data:image/png;base64,....
    """
    if not data:
        raise ValueError("empty data")
    if data.startswith("data:"):
        comma = data.find(",")
        if comma == -1:
            raise ValueError("Invalid data URL")
        data = data[comma + 1 :]
    return base64.b64decode(data)


def _save_asst_message(user_id: str, chat_id: str, content: str, raw: dict, language: Optional[str]):
    if not user_id or not chat_id:
        return {"saved": False}
    try:
        db = firestore.client()
        path = f"users/{user_id}/chats/{chat_id}/messages"
        ref = db.collection("users").document(user_id).collection("chats").document(chat_id).collection("messages").add({
            "role": "assistant",
            "content": content,
            "meta": {
                "language": normalize_language(language),
                "ai_detect": {"raw": raw},
            },
        })
        message_id = ref[1].id if isinstance(ref, tuple) else ref.id
        return {"saved": True, "message_id": message_id, "path": path}
    except Exception as e:  # pragma: no cover
        logger.warning("Failed to save message to Firestore", exc_info=e)
        return {"saved": False, "error": str(e)}


def _build_messages(verdict: Optional[str], confidence: float, quality, nsfw, language: Optional[str]):
    ai_conf = confidence if verdict == "ai" else max(0.0, 1.0 - confidence)
    human_conf = confidence if verdict == "human" else max(0.0, 1.0 - confidence)
    return build_ai_detection_messages(
        verdict,
        ai_conf,
        human_conf,
        quality_flag_from_value(quality),
        nsfw_flag_from_value(nsfw),
        language=language,
    )


def _build_summary(verdict: Optional[str], confidence: float, quality, nsfw, language: Optional[str]):
    ai_conf = confidence if verdict == "ai" else max(0.0, 1.0 - confidence)
    human_conf = confidence if verdict == "human" else max(0.0, 1.0 - confidence)
    return format_ai_detection_summary(
        verdict,
        ai_conf,
        human_conf,
        quality_flag_from_value(quality),
        nsfw_flag_from_value(nsfw),
        language=language,
        subject="image",
    )


def _save_failure_message(user_id: str, chat_id: str, language: Optional[str], message: str, raw: Optional[dict] = None):
    _save_asst_message(user_id, chat_id, message, raw or {"error": message}, language)


async def _run_analysis(image_bytes: bytes, user_id: str, chat_id: str, language: Optional[str] = None, mock: bool = False):
    language_norm = normalize_language(language)

    files = {"object": ('image.jpg', image_bytes, 'image/jpeg')}
    try:
        logger.info("Calling AI or Not API")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                IMAGE_ENDPOINT,
                headers={"Authorization": f"Bearer {API_KEY}"},
                files=files,
            )
        logger.info("AI or Not API responded", extra={"status_code": resp.status_code})
    except httpx.RequestError as e:
        logger.error("AI or Not API request failed", exc_info=e)
        raise HTTPException(status_code=502, detail={"error": "AI analysis failed", "details": str(e)})

    if resp.status_code != 200:
        body_text = resp.text
        logger.error("AI or Not API returned error", extra={"status": resp.status_code, "body": body_text})
        raise HTTPException(
            status_code=500,
            detail={"error": "AI analysis failed", "details": body_text, "status": resp.status_code},
        )

    logger.info("Parsing AI or Not API response")
    result = resp.json()
    logger.debug("AI or Not API JSON response", extra={"response": json.dumps(result, indent=2)})

    verdict = (result.get("report") or {}).get("verdict")
    confidence = float((result.get("report") or {}).get("ai", {}).get("confidence", 0.0) or result.get("confidence", 0.0) or 0.0)
    quality = (result.get("facets") or {}).get("quality", {}).get("is_detected")
    nsfw = (result.get("facets") or {}).get("nsfw", {}).get("is_detected")

    messages = _build_messages(verdict, confidence, quality, nsfw, language_norm)
    summary_tr = _build_summary(verdict, confidence, quality, nsfw, language_norm)

    saved_info = _save_asst_message(user_id, chat_id, summary_tr, result, language_norm)
    logger.info("Firestore save result", extra={"saved_info": saved_info})

    return {
        "raw_response": result,
        "messages": messages,
        "summary": summary_tr,
        "summary_tr": summary_tr,
        "language": language_norm,
        "saved": saved_info,
    }


async def analyze_image_from_url(image_url: str, user_id: str, chat_id: str, language: Optional[str] = None, mock: bool = False):
    logger.info("Analyze image from URL", extra={"image_url": image_url, "user_id": user_id, "chat_id": chat_id})
    headers = {"User-Agent": "Mozilla/5.0 (Avenia-Agent)"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(image_url, headers=headers)
        logger.info("Image download response", extra={"status": resp.status_code})
        resp.raise_for_status()
    except Exception as e:
        logger.error("Image download failed", exc_info=e)
        _save_failure_message(user_id, chat_id, language, FAIL_MSG, {"error": str(e)})
        raise HTTPException(status_code=400, detail=FAIL_MSG)

    content = resp.content or b""
    b64 = base64.b64encode(content).decode("utf-8")
    if len(b64) < 1000:
        logger.error("Downloaded content too small or not image")
        _save_failure_message(user_id, chat_id, language, FAIL_MSG, {"error": "invalid_image"})
        raise HTTPException(status_code=400, detail=FAIL_MSG)
    try:
        return await _run_analysis(content, user_id, chat_id, language, mock)
    except HTTPException as he:
        _save_failure_message(user_id, chat_id, language, FAIL_MSG, he.detail if isinstance(he.detail, dict) else {"error": str(he.detail)})
        raise HTTPException(status_code=he.status_code, detail=FAIL_MSG)
    except Exception as e:
        _save_failure_message(user_id, chat_id, language, FAIL_MSG, {"error": str(e)})
        raise HTTPException(status_code=500, detail=FAIL_MSG)


@router.post("/analyze-image")
async def analyze_image(
    payload: dict = Body(...),
    mock: str = Query(default="0"),  # ?mock=1 desteği için,
):
    """
    Beklenen body:
    {
      "image_base64": "<base64 veya data URL>",
      "user_id": "uid",
      "chat_id": "cid"
    }
    """
    logger.info("Analyze image request received", extra={"payload": payload})

    language = normalize_language(payload.get("language"))
    image_b64 = payload.get("image_base64")
    user_id = payload.get("user_id")
    chat_id = payload.get("chat_id")
    logger.info(
        "Analyze image parameters",
        extra={
            "user_id": user_id,
            "chat_id": chat_id,
            "image_length": len(image_b64) if image_b64 else "missing",
        },
    )

    if not image_b64:
        return JSONResponse(status_code=400, content={"message": FAIL_MSG})
    if not user_id or not chat_id:
        return JSONResponse(status_code=400, content={"message": FAIL_MSG})

    try:
        logger.info("Decoding base64 image")
        image_bytes = decode_base64_maybe_data_url(image_b64)
        logger.info("Base64 decoded", extra={"byte_length": len(image_bytes)})
    except Exception as e:
        logger.error("Base64 decode failed", exc_info=e)
        _save_failure_message(user_id, chat_id, language, FAIL_MSG, {"error": str(e)})
        return JSONResponse(status_code=400, content={"message": FAIL_MSG})

    try:
        result = await _run_analysis(image_bytes, user_id, chat_id, language, mock == "1")
        return JSONResponse(status_code=200, content=result)
    except HTTPException as he:
        _save_failure_message(
            user_id,
            chat_id,
            language,
            FAIL_MSG,
            he.detail if isinstance(he.detail, dict) else {"error": str(he.detail)},
        )
        raise HTTPException(status_code=he.status_code, detail=FAIL_MSG)
    except Exception as e:
        logger.exception("Analyze image failed")
        raise HTTPException(
            status_code=500,
            detail=FAIL_MSG,
        )


