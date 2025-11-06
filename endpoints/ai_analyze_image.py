import json
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
    print("========== [/analyze-image] BAŞLADI ==========")
    print("[1] Gelen payload:", payload)

    language = normalize_language(payload.get("language"))
    image_b64 = payload.get("image_base64")
    user_id = payload.get("user_id")
    chat_id = payload.get("chat_id")
    print(f"[2] Parametreler -> user_id: {user_id}, chat_id: {chat_id}, image_base64 uzunluğu: {len(image_b64) if image_b64 else 'YOK'}")

    if not image_b64:
        print("[HATA] image_base64 eksik")
        return JSONResponse(status_code=400, content={"error": "No base64 image data provided"})
    if not user_id or not chat_id:
        print("[HATA] user_id veya chat_id eksik")
        return JSONResponse(status_code=400, content={"error": "user_id and chat_id are required"})

    # MOCK verisi
    if MOCK_MODE or mock == "1":
        print("[3] MOCK_MODE aktif - Sahte sonuç döndürülüyor.")
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
        print(f"[4] MOCK summary_tr: {summary_tr}")
        saved_info = _save_asst_message(user_id, chat_id, summary_tr, mock_result, language)
        print(f"[5] MOCK Firestore kayıt sonucu: {saved_info}")
        print("========== [/analyze-image] BİTTİ (MOCK) ==========")
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
        print("[3] Base64 decode başlatılıyor...")
        image_bytes = decode_base64_maybe_data_url(image_b64)
        print(f"[3.1] Base64 decode başarılı. Byte boyutu: {len(image_bytes)}")
    except Exception as e:
        print("[HATA] Base64 decode başarısız:", e)
        return JSONResponse(status_code=400, content={"error": "Invalid base64 data", "details": str(e)})

    files = {"object": ('image.jpg', image_bytes, 'image/jpeg')}
    try:
        print("[4] AI or Not API'ye istek gönderiliyor...")
        resp = requests.post(
            IMAGE_ENDPOINT,
            headers={"Authorization": f"Bearer {API_KEY}"},
            files=files,
            timeout=30,
        )
        print(f"[4.1] API yanıt kodu: {resp.status_code}")
    except requests.RequestException as e:
        print("[HATA] API isteği başarısız:", e)
        return JSONResponse(status_code=502, content={"error": "AI analysis failed", "details": str(e)})

    if resp.status_code != 200:
        print("[HATA] API yanıtı başarısız:", resp.text)
        return JSONResponse(status_code=500, content={
            "error": "AI analysis failed",
            "details": resp.text,
            "status": resp.status_code,
        })

    print("[5] API yanıtı JSON parse ediliyor...")
    result = resp.json()
    print("[5.1] API yanıtı:", json.dumps(result, indent=2))

    print("[6] interpret_messages_legacy çağrılıyor...")
    messages = interpret_messages_legacy(result, language)
    print(f"[6.1] interpret_messages_legacy çıktı: {messages}")

    print("[7] format_summary_tr çağrılıyor...")
    summary_tr = format_summary_tr(result, language, subject="image")
    print(f"[7.1] format_summary_tr çıktı: {summary_tr}")

    print("[8] Firestore kaydı başlatılıyor...")
    saved_info = _save_asst_message(user_id, chat_id, summary_tr, result, language)
    print(f"[8.1] Firestore kayıt sonucu: {saved_info}")

    print("========== [/analyze-image] BİTTİ ==========")
    return JSONResponse(status_code=200, content={
        "raw_response": result,
        "messages": messages,
        "summary": summary_tr,
        "summary_tr": summary_tr,
        "language": language,
        "saved": saved_info,
    })
