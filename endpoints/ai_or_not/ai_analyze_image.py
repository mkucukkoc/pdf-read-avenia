import json
import logging
import base64
from typing import Optional

import httpx
from fastapi import Body, Query
from fastapi.responses import JSONResponse

from core.language_support import normalize_language
from main import (
    app,
    decode_base64_maybe_data_url,
    interpret_messages_legacy,
    format_summary_tr,
    _save_asst_message,
    IMAGE_ENDPOINT,
    API_KEY,
    MOCK_MODE,
)

logger = logging.getLogger("pdf_read_refresh.endpoints.analyze_image")
FAIL_MSG = "Görsel şu anda analiz edilemiyor, lütfen tekrar deneyin."


def _save_failure_message(user_id: str, chat_id: str, language: Optional[str], message: str, raw: Optional[dict] = None):
    if not user_id or not chat_id:
        return
    try:
        _save_asst_message(
            user_id=user_id,
            chat_id=chat_id,
            content=message,
            raw=raw or {"error": message},
            language=normalize_language(language),
        )
    except Exception as e:  # pragma: no cover - best effort
        logger.warning("Failed to save error message to Firestore", exc_info=e)


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

    messages = interpret_messages_legacy(result, language_norm)
    summary_tr = format_summary_tr(result, language_norm, subject="image")

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


@app.post("/analyze-image")
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


