import base64
import io
from fastapi import Body, HTTPException
from main import app, client
from endpoints.audio_isolation import audio_isolation


@app.post("/stt")
async def speech_to_text(data: dict = Body(...)):
    print("[/stt] 🎤 İstek alındı.")

    base64_audio = data.get("base64")
    if not base64_audio:
        print("[/stt] ⚠️ Ses verisi (base64) bulunamadı.")
        return {"error": "Ses verisi eksik"}

    try:
        # (İsteğe bağlı) Lokal gürültü azaltma endpoint’imiz
        print("[/stt] 🔄 Audio Isolation çağrılıyor...")
        try:
            isolate_resp = await audio_isolation({"base64": base64_audio})
            if isinstance(isolate_resp, dict) and isolate_resp.get("audio_base64"):
                base64_audio = isolate_resp["audio_base64"]
                print("[/stt] 🎛 Gürültüsüz sesle devam ediliyor.")
            else:
                print("[/stt] ⚠️ Audio Isolation pas geçildi.")
        except Exception as _:
            print("[/stt] ⚠️ Audio Isolation başarısız, orijinal ses kullanılacak.")

        print("[/stt] 🧬 Base64 ses verisi decode ediliyor...")
        audio_bytes = base64.b64decode(base64_audio)
        print(f"[/stt] ✅ Decode başarılı. Boyut: {len(audio_bytes)} byte")

        # OpenAI Whisper-1 transkripsiyon
        bio = io.BytesIO(audio_bytes)
        bio.name = "audio.m4a"  # dosya adı gerekli
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=bio,
            # dil tahmini güzel çalışıyor; gerekirse language="tr" verilebilir
        )
        text = transcript.text or ""
        print("[/stt] ✅ Çözümleme başarılı. Metin:", text[:120])
        return {"text": text}

    except Exception as e:
        print("[/stt] ❗️Hata:", str(e))
        raise HTTPException(status_code=500, detail=str(e))
