import base64
from typing import List, Dict
from fastapi import Body, HTTPException
from main import app, client


@app.post("/tts-chat")
async def tts_chat(payload: dict = Body(...)):
    """
    Beklenen payload:
    {
        "messages": [
            {"role": "user", "content": "Selam"},
            {"role": "assistant", "content": "Merhaba! Size nasıl yardımcı olabilirim?"}
        ]
    }
    """
    messages: List[Dict[str, str]] = payload.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="Chat mesajları eksik.")

    # Mesajları birleştir (4000 karakter limiti)
    combined_text = []
    for m in messages:
        if m.get("role") == "user":
            combined_text.append(f"Sen: {m.get('content','')}")
        elif m.get("role") == "assistant":
            combined_text.append(m.get("content",""))
    combined_text = "\n".join(combined_text)[:4000]

    print("[/tts-chat] 🔊 Metin uzunluğu:", len(combined_text))
    print("[/tts-chat] 📜 Önizleme:\n", combined_text[:300])

    try:
        speech = client.audio.speech.create(
            model="tts-1",
            voice="alloy",  # diğer ör: "verse", "aria"
            input=combined_text,
            # format varsayılan mp3; istenirse: response_format="wav" / "pcm"
        )
        audio_bytes = speech.content
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        print("[/tts-chat] ✅ Ses üretildi.")
        return {"audio_base64": audio_base64}

    except Exception as e:
        print("[/tts-chat] ❌ Hata:", str(e))
        raise HTTPException(status_code=500, detail=str(e))
