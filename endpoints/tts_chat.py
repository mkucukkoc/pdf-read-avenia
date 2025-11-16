import base64
from typing import List, Dict
import logging
from fastapi import Body, HTTPException
from main import app, client

logger = logging.getLogger("pdf_read_refresh.endpoints.tts_chat")


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
        logger.warning("TTS chat request missing messages")
        raise HTTPException(status_code=400, detail="Chat mesajları eksik.")

    combined_text = []
    for m in messages:
        if m.get("role") == "user":
            combined_text.append(f"Sen: {m.get('content','')}")
        elif m.get("role") == "assistant":
            combined_text.append(m.get("content",""))
    combined_text = "\n".join(combined_text)[:4000]

    logger.info(
        "TTS chat request received",
        extra={"message_count": len(messages), "combined_length": len(combined_text)},
    )
    logger.debug("TTS text preview", extra={"preview": combined_text[:300]})

    try:
        speech = client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=combined_text,
        )
        audio_bytes = speech.content
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        logger.info("TTS chat output generated")
        response_payload = {"audio_base64": audio_base64}
        logger.debug("TTS chat response payload", extra={"response": response_payload})
        return response_payload

    except Exception as e:
        logger.exception("TTS chat failed")
        raise HTTPException(status_code=500, detail=str(e))
