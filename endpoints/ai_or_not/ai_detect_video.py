import json
import logging
from fastapi import Body, Query
from fastapi.responses import JSONResponse
import requests
import hashlib  # LOG+ md5 için


from core.language_support import normalize_language
from errors_response.api_errors import get_api_error_message
from main import (
    app,
    decode_base64_maybe_data_url,
    interpret_messages_legacy,
    format_summary_tr,
    _save_asst_message,
    API_KEY,
    MOCK_MODE,
)

logger = logging.getLogger("pdf_read_refresh.endpoints.analyze_video")

# --- DEĞİŞTİ: Doğru video endpoint'i ---
VIDEO_ENDPOINT = "https://api.aiornot.com/v2/video/sync"


def _log_aiornot_breakdown(result: dict, resp: requests.Response | None = None) -> None:
    """AI or Not yanıtını özetleyen detaylı log."""
    print("[5.2] AI or Not - detaylı özet başlıyor...")
    rep = (result or {}).get("report", {}) or {}

    # Ana sinyaller
    for key in ("ai_video", "ai_voice", "ai_music", "deepfake", "nsfw", "quality"):
        obj = rep.get(key)
        if isinstance(obj, dict):
            print(f"    - {key}: is_detected={obj.get('is_detected')} confidence={obj.get('confidence')} score={obj.get('score')}")

    # Meta bilgiler (varsa)
    meta = rep.get("meta") or {}
    if meta:
        known = {k: meta.get(k) for k in ("duration", "total_bytes", "width", "height", "format")}
        print(f"    - meta: {known}")

    # İstek/yanıt trace bilgileri (varsa)
    if resp is not None:
        # Bazı servisler farklı header isimleri kullanabilir; birkaç olası ismi deniyoruz:
        req_id = (
            resp.headers.get("x-request-id")
            or resp.headers.get("x-ai-request-id")
            or resp.headers.get("x-aiornot-request-id")
        )
        print(f"    - http.request_id: {req_id}")
        print(f"    - http.headers.content-type: {resp.headers.get('content-type')}")
    print("[5.2] AI or Not - detaylı özet bitti.")


@app.post("/analyze-video")
def analyze_video(
    payload: dict = Body(...),
    mock: str = Query(default="0"),
):
    """
    Body:
    {
        "video_base64": "<base64 or data URL>",
        "user_id": "uid",
        "chat_id": "cid"
    }
    """
    def _map_error_key(status_code: int) -> str:
        if status_code == 404:
            return "upstream_404"
        if status_code == 429:
            return "upstream_429"
        if status_code in (401, 403):
            return "upstream_401"
        if status_code == 408:
            return "upstream_timeout"
        if status_code >= 500:
            return "upstream_500"
        return "unknown_error"

    def _error_response(language: str, chat_id: str, user_id: str, status_code: int, detail: Any) -> JSONResponse:
        key = _map_error_key(status_code)
        msg = get_api_error_message(key, language)
        message_id = f"ai_detect_video_error_{hashlib.md5(str(os.urandom(4)).encode()).hexdigest()[:8]}"
        try:
            _save_asst_message(user_id, chat_id, msg, {"error": key, "detail": detail}, language)
        except Exception:
            logger.warning("Analyze video error persist failed chatId=%s userId=%s", chat_id, user_id, exc_info=True)

        payload = {
            "success": True,
            "raw_response": {},
            "messages": [],
            "summary": msg,
            "summary_tr": msg,
            "language": language,
            "saved": {"saved": True, "message_id": message_id},
        }
        return JSONResponse(status_code=200, content=payload)

    logger.info("Analyze video request received", extra={"payload": payload})

    language = normalize_language(payload.get("language"))
    video_b64 = payload.get("video_base64")
    user_id = payload.get("user_id")
    chat_id = payload.get("chat_id")
    logger.info(
        "Analyze video parameters",
        extra={
            "user_id": user_id,
            "chat_id": chat_id,
            "video_length": len(video_b64) if video_b64 else "missing",
        },
    )

    if not video_b64:
        logger.warning("video_base64 missing")
        return _error_response(language, chat_id or "", user_id or "", 400, "video_base64_missing")
    if not user_id or not chat_id:
        logger.warning("user_id or chat_id missing")
        return _error_response(language, chat_id or "", user_id or "", 400, "user_or_chat_missing")

    if MOCK_MODE or mock == "1":
        logger.info("Mock analyze video flow active")
        mock_result = {
            "report": {
                # AI or Not video şemasına yakın mock
                "ai_video": {"is_detected": True, "confidence": 0.9},
                "ai_voice": {"is_detected": False, "confidence": 0.1},
                "ai_music": {"is_detected": False, "confidence": 0.1},
                "meta": {"duration": 7, "total_bytes": 2388425}
            }
        }
        # Mevcut interpret/summary fonksiyonlarını bozmayalım diye küçük adaptasyon:
        ai_v = mock_result["report"].get("ai_video", {}) or {}
        conf = ai_v.get("confidence")
        legacy_like = {
            "report": {
                "verdict": "ai" if ai_v.get("is_detected") else "human",
                "ai": {"confidence": conf},
                "human": {"confidence": (1 - conf) if isinstance(conf, (int, float, float)) else None},
                "generator": {},
                "meta": mock_result["report"].get("meta", {}),
            }
        }

        messages = interpret_messages_legacy(legacy_like, language)
        summary_tr = format_summary_tr(legacy_like, language, subject="video")
        logger.debug("Mock summary generated", extra={"summary_tr": summary_tr})
        saved_info = _save_asst_message(user_id, chat_id, summary_tr, mock_result, language)  # orijinali kaydet
        logger.info("Mock Firestore save result", extra={"saved_info": saved_info})
        logger.info("Analyze video mock complete")
        return JSONResponse(status_code=200, content={
            "raw_response": mock_result,   # orijinal şema
            "messages": messages,
            "summary": summary_tr,
            "summary_tr": summary_tr,
            "language": language,
            "saved": saved_info,
        })

    try:
        logger.info("Decoding base64 video")
        video_bytes = decode_base64_maybe_data_url(video_b64)
        logger.info("Base64 decoded", extra={"byte_length": len(video_bytes)})

        video_md5 = hashlib.md5(video_bytes).hexdigest()
        logger.info("Video MD5 computed", extra={"md5": video_md5})
    except Exception as e:
        logger.error("Base64 decode failed", exc_info=e)
        return _error_response(language, chat_id, user_id, 400, {"error": str(e)})

    # --- DEĞİŞTİ: alan adı 'video' olmalı ---
    files = {"video": ("video.mp4", video_bytes, "video/mp4")}
    try:
        logger.info("Calling video AI or Not API")
        resp = requests.post(
            VIDEO_ENDPOINT,
            headers={"Authorization": f"Bearer {API_KEY}"},
            files=files,
            timeout=120,  # --- DEĞİŞTİ: önerilen timeout ---
        )
        logger.info("Video API response", extra={"status_code": resp.status_code})
        if resp.status_code != 200:
            logger.error("Video AI response error", extra={"status": resp.status_code, "body": resp.text})
            return _error_response(language, chat_id, user_id, resp.status_code, resp.text)
    except requests.RequestException as e:
        logger.error("Video API request failed", exc_info=e)
        return _error_response(language, chat_id, user_id, 502, {"error": str(e)})

    logger.info("Parsing video API response")
    result = resp.json()  # orijinal AI or Not yanıtı (video şeması)
    logger.debug("Video API JSON response", extra={"response": json.dumps(result, indent=2)})
    _log_aiornot_breakdown(result, resp)


    # --- YENİ: Mevcut interpret/summary fonksiyonların eski şema bekliyor olabilir.
    # Burada "legacy-like" küçük bir map ile uyumluluk sağlıyoruz. ---
    rep = (result or {}).get("report", {}) or {}
    ai_v = rep.get("ai_video") or {}
    conf = ai_v.get("confidence")
    legacy_like = {
        "report": {
            "verdict": "ai" if ai_v.get("is_detected") else "human",
            "ai": {"confidence": conf},
            "human": {"confidence": (1 - conf) if isinstance(conf, (int, float, float)) else None},
            "generator": {},
            "meta": rep.get("meta", {}),
        }
    }

    try:
        logger.info("Calling interpret_messages_legacy")
        messages = interpret_messages_legacy(legacy_like, language)
        logger.debug("Interpret messages result", extra={"messages": messages})

        logger.info("Calling format_summary_tr")
        summary_tr = format_summary_tr(legacy_like, language, subject="video")
        logger.debug("Format summary output", extra={"summary_tr": summary_tr})

        logger.info("Saving assistant message to Firestore")
        # Kayda ORİJİNAL sonucu geçiyoruz (eski davranış korunur)
        saved_info = _save_asst_message(user_id, chat_id, summary_tr, result, language)
        logger.info("Firestore save result", extra={"saved_info": saved_info})
        logger.info("Analyze video complete")
        return JSONResponse(status_code=200, content={
            "raw_response": result,   # orijinal video şeması
            "messages": messages,
            "summary": summary_tr,
            "summary_tr": summary_tr,
            "language": language,
            "saved": saved_info,
        })
    except Exception as exc:
        logger.exception("Analyze video processing error")
        return _error_response(language, chat_id, user_id, 500, str(exc))
