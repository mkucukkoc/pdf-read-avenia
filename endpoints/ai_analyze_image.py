import json
import logging
from fastapi import Body, Query
from fastapi.responses import JSONResponse
import requests
from language_support import normalize_language
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


@app.post("/analyze-image")
def analyze_image(
    payload: dict = Body(...),
    mock: str = Query(default="0")  # ?mock=1 desteği için,
):
    """
    Beklenen body:
    {
      "image_base64": "<base64 veya data URL>",
      "user_id": "uid",
      "chat_id": "cid"
    }

    Dönüş:
    {
      "raw_response": {...},
      "messages": ["Medium Likely AI", "Good", "No"],
      "summary_tr": "Görsel, %99 ... Görsel yapısı iyi. NSFW ...",
      "saved": { "message_id": "...", "path": "users/{uid}/chats/{cid}/messages" }
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
        print("[HATA] image_base64 eksik")
        return JSONResponse(status_code=400, content={"error": "No base64 image data provided"})
    if not user_id or not chat_id:
        print("[HATA] user_id veya chat_id eksik")
        return JSONResponse(status_code=400, content={"error": "user_id and chat_id are required"})

    # MOCK verisi
    if MOCK_MODE or mock == "1":
        logger.info("Mock mode active - returning fake response")
        mock_result = {
            "report": {
                "verdict": "ai",
                "ai": {"confidence": 0.99},
                "human": {"confidence": 0.01},
                "generator": {},
            },
            "facets": {
                "quality": {"is_detected": True, "score": 0.92},
                "nsfw": {"is_detected": False, "score": 0.01},
            },
        }
        messages = interpret_messages_legacy(mock_result, language)
        summary_tr = format_summary_tr(mock_result, language, subject="image")
        logger.debug("Mock summary generated", extra={"summary_tr": summary_tr})
        saved_info = _save_asst_message(user_id, chat_id, summary_tr, mock_result, language)
        logger.info("Mock Firestore save result", extra={"saved_info": saved_info})
        logger.info("Analyze image mock flow complete")
        return JSONResponse(status_code=200, content={
            "raw_response": mock_result,
            "messages": messages,
            "summary": summary_tr,
            "summary_tr": summary_tr,
            "language": language,
            "saved": saved_info,
        })

    # Gerçek çağrı
    try:
        logger.info("Decoding base64 image")
        image_bytes = decode_base64_maybe_data_url(image_b64)
        logger.info("Base64 decoded", extra={"byte_length": len(image_bytes)})
    except Exception as e:
        logger.error("Base64 decode failed", exc_info=e)
        return JSONResponse(status_code=400, content={"error": "Invalid base64 data", "details": str(e)})

    files = {"object": ('image.jpg', image_bytes, 'image/jpeg')}
    try:
        logger.info("Calling AI or Not API")
        resp = requests.post(
            IMAGE_ENDPOINT,
            headers={"Authorization": f"Bearer {API_KEY}"},
            files=files,
            timeout=30,
        )
        logger.info("AI or Not API responded", extra={"status_code": resp.status_code})
    except requests.RequestException as e:
        logger.error("AI or Not API request failed", exc_info=e)
        return JSONResponse(status_code=502, content={"error": "AI analysis failed", "details": str(e)})

    if resp.status_code != 200:
        logger.error("AI or Not API returned error", extra={"status": resp.status_code, "body": resp.text})
        return JSONResponse(status_code=500, content={
            "error": "AI analysis failed",
            "details": resp.text,
            "status": resp.status_code,
        })

    logger.info("Parsing AI or Not API response")
    result = resp.json()
    logger.debug("AI or Not API JSON response", extra={"response": json.dumps(result, indent=2)})

    logger.info("Calling interpret_messages_legacy")
    messages = interpret_messages_legacy(result, language)
    logger.debug("Interpret messages result", extra={"messages": messages})

    logger.info("Calling format_summary_tr")
    summary_tr = format_summary_tr(result, language, subject="image")
    logger.debug("Format summary result", extra={"summary_tr": summary_tr})

    logger.info("Saving assistant message")
    saved_info = _save_asst_message(user_id, chat_id, summary_tr, result, language)
    logger.info("Firestore save result", extra={"saved_info": saved_info})
    logger.info("Analyze image complete")
    return JSONResponse(status_code=200, content={
        "raw_response": result,
        "messages": messages,
        "summary": summary_tr,
        "summary_tr": summary_tr,
        "language": language,
        "saved": saved_info,
    })


