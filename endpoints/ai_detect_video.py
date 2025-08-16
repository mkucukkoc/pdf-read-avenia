import json
from fastapi import Body, Query
from fastapi.responses import JSONResponse
import requests

from main import (
    app,
    decode_base64_maybe_data_url,
    interpret_messages_legacy,
    format_summary_tr,
    _save_asst_message,
    API_KEY,
    MOCK_MODE,
)

VIDEO_ENDPOINT = "https://api.aiornot.com/v1/reports?mod=video"

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
    print("========== [/analyze-video] BAŞLADI ==========")
    print("[1] Gelen payload:", payload)

    video_b64 = payload.get("video_base64")
    user_id = payload.get("user_id")
    chat_id = payload.get("chat_id")
    print(f"[2] Parametreler -> user_id: {user_id}, chat_id: {chat_id}, video_base64 uzunluğu: {len(video_b64) if video_b64 else 'YOK'}")

    if not video_b64:
        print("[HATA] video_base64 eksik")
        return JSONResponse(status_code=400, content={"error": "No base64 video data provided"})
    if not user_id or not chat_id:
        print("[HATA] user_id veya chat_id eksik")
        return JSONResponse(status_code=400, content={"error": "user_id and chat_id are required"})

    if MOCK_MODE or mock == "1":
        print("[3] MOCK_MODE aktif - Sahte sonuç döndürülüyor.")
        mock_result = {
            "report": {
                "verdict": "ai",
                "ai": {"confidence": 0.9},
                "human": {"confidence": 0.1},
                "generator": {},
            },
            "facets": {
                "quality": {"is_detected": True, "score": 0.9},
                "nsfw": {"is_detected": False, "score": 0.01},
            },
        }
        messages = ["Medium Likely AI", "Good", "No"]
        summary_tr = "Video, %90 olasılıkla yapay zeka tarafından üretilmiş (orta güven). Video yapısı iyi. NSFW açısından bir sorun görünmüyor."
        print(f"[4] MOCK summary_tr: {summary_tr}")
        saved_info = _save_asst_message(user_id, chat_id, summary_tr, mock_result)
        print(f"[5] MOCK Firestore kayıt sonucu: {saved_info}")
        print("========== [/analyze-video] BİTTİ (MOCK) ==========")
        return JSONResponse(status_code=200, content={
            "raw_response": mock_result,
            "messages": messages,
            "summary_tr": summary_tr,
            "saved": saved_info,
        })

    try:
        print("[3] Base64 decode başlatılıyor...")
        video_bytes = decode_base64_maybe_data_url(video_b64)
        print(f"[3.1] Base64 decode başarılı. Byte boyutu: {len(video_bytes)}")
    except Exception as e:
        print("[HATA] Base64 decode başarısız:", e)
        return JSONResponse(status_code=400, content={"error": "Invalid base64 data", "details": str(e)})

    files = {"object": ("video.mp4", video_bytes, "video/mp4")}
    try:
        print("[4] AI or Not API'ye istek gönderiliyor...")
        resp = requests.post(
            VIDEO_ENDPOINT,
            headers={"Authorization": f"Bearer {API_KEY}"},
            files=files,
            timeout=60,
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
    messages = interpret_messages_legacy(result)
    print(f"[6.1] interpret_messages_legacy çıktı: {messages}")

    print("[7] format_summary_tr çağrılıyor...")
    summary_tr = format_summary_tr(result)
    print(f"[7.1] format_summary_tr çıktı: {summary_tr}")

    print("[8] Firestore kaydı başlatılıyor...")
    saved_info = _save_asst_message(user_id, chat_id, summary_tr, result)
    print(f"[8.1] Firestore kayıt sonucu: {saved_info}")

    print("========== [/analyze-video] BİTTİ ==========")
    return JSONResponse(status_code=200, content={
        "raw_response": result,
        "messages": messages,
        "summary_tr": summary_tr,
        "saved": saved_info,
    })