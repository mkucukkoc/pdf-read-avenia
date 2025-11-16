import base64
import io
import logging
import numpy as np
import soundfile as sf
from pydub import AudioSegment, effects
import noisereduce as nr
from fastapi import Body, HTTPException
from main import app

logger = logging.getLogger("pdf_read_refresh.endpoints.audio_isolation")


@app.post("/audio-isolation")
async def audio_isolation(data: dict = Body(...)):
    """
    Base64 ses -> hafif gürültü azaltma -> base64 ses
    Not: Bu uç ElevenLabs yerine lokal çalışır. Aşırı gürültülü kayıtlarda
    mucize beklemeyin; temel bir NR ve filtre uygular.
    """
    logger.info("Audio isolation request received")

    base64_audio = data.get("base64")
    if not base64_audio:
        logger.warning("Audio data missing for isolation")
        raise HTTPException(status_code=400, detail="Ses verisi (base64) eksik.")

    try:
        logger.debug("Decoding base64 audio")
        audio_bytes = base64.b64decode(base64_audio)

        seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format="m4a")
        seg = effects.normalize(seg)
        seg = seg.high_pass_filter(80).low_pass_filter(7500)

        samples = np.array(seg.get_array_of_samples()).astype(np.float32)
        if seg.channels == 2:
            samples = samples.reshape((-1, 2)).mean(axis=1)

        sr = seg.frame_rate
        logger.debug("Applying spectral noise reduction", extra={"sr": sr})
        reduced = nr.reduce_noise(y=samples, sr=sr, prop_decrease=0.7, verbose=False)

        wav_buf = io.BytesIO()
        sf.write(wav_buf, reduced, sr, format="WAV")
        wav_buf.seek(0)

        cleaned = AudioSegment.from_file(wav_buf, format="wav")
        out_buf = io.BytesIO()
        cleaned.export(out_buf, format="mp3")
        audio_bytes_out = out_buf.getvalue()

        audio_base64_out = base64.b64encode(audio_bytes_out).decode("utf-8")
        logger.info("Audio isolation completed")
        return {"audio_base64": audio_base64_out}

    except Exception as e:
        logger.exception("Audio isolation failed")
        return {"audio_base64": base64_audio}
