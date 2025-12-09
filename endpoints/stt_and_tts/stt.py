import base64
import io
import logging
from fastapi import APIRouter, Body, HTTPException
from core.openai_client import get_client

logger = logging.getLogger("pdf_read_refresh.endpoints.stt")
router = APIRouter()


@router.post("/stt")
async def speech_to_text(data: dict = Body(...)):
    logger.info("STT request received")

    base64_audio = data.get("base64")
    if not base64_audio:
        logger.warning("Base64 audio missing in STT request")
        return {"error": "Ses verisi eksik"}

    try:
        logger.debug("Decoding base64 audio")
        audio_bytes = base64.b64decode(base64_audio)
        logger.info("Audio decoded", extra={"byte_length": len(audio_bytes)})

        bio = io.BytesIO(audio_bytes)
        bio.name = "audio.m4a"
        client = get_client()
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=bio,
        )
        text = transcript.text or ""
        logger.info("STT transcription completed", extra={"text_preview": text[:120]})
        response_payload = {"text": text}
        logger.debug("STT response payload", extra={"response": response_payload})
        return response_payload

    except Exception as e:
        logger.exception("STT request failed")
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ["router"]
