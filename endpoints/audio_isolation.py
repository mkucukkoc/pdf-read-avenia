import base64
import io
import numpy as np
import soundfile as sf
from pydub import AudioSegment, effects
import noisereduce as nr
from fastapi import Body, HTTPException
from main import app


@app.post("/audio-isolation")
async def audio_isolation(data: dict = Body(...)):
    """
    Base64 ses -> hafif gürültü azaltma -> base64 ses
    Not: Bu uç ElevenLabs yerine lokal çalışır. Aşırı gürültülü kayıtlarda
    mucize beklemeyin; temel bir NR ve filtre uygular.
    """
    print("[/audio-isolation] 🎧 İstek alındı.")

    base64_audio = data.get("base64")
    if not base64_audio:
        raise HTTPException(status_code=400, detail="Ses verisi (base64) eksik.")

    try:
        print("[/audio-isolation] 📥 Base64 decode ediliyor...")
        audio_bytes = base64.b64decode(base64_audio)

        # Pydub ile yükle (ffmpeg gerekir)
        seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format="m4a")

        # Hafif normalize + high/low pass
        seg = effects.normalize(seg)
        seg = seg.high_pass_filter(80).low_pass_filter(7500)

        # NumPy array’e çevir
        samples = np.array(seg.get_array_of_samples()).astype(np.float32)
        if seg.channels == 2:
            samples = samples.reshape((-1, 2)).mean(axis=1)  # mono

        sr = seg.frame_rate

        # Noisereduce (spektral gürültü azaltma)
        reduced = nr.reduce_noise(y=samples, sr=sr, prop_decrease=0.7, verbose=False)

        # WAV olarak buffer’a yaz, sonra tekrar pydub ile m4a/mp3’e dön
        wav_buf = io.BytesIO()
        sf.write(wav_buf, reduced, sr, format="WAV")
        wav_buf.seek(0)

        cleaned = AudioSegment.from_file(wav_buf, format="wav")
        out_buf = io.BytesIO()
        # M4A yazımı için ffmpeg; isterseniz "mp3" seçebilirsiniz
        cleaned.export(out_buf, format="mp3")  # "mp3" daha sorunsuz
        out_bytes = out_buf.getvalue()

        audio_base64_out = base64.b64encode(out_bytes).decode("utf-8")
        print("[/audio-isolation] ✅ Gürültü azaltma tamam.")
        return {"audio_base64": audio_base64_out}

    except Exception as e:
        print("[/audio-isolation] ❗️ Hata, orijinal ses iade edilecek:", str(e))
        # Fail-safe: Orijinal sesi geri ver
        return {"audio_base64": base64_audio}
