import logging
import requests
from fastapi import Body, HTTPException
from fastapi.responses import JSONResponse
from main import app, GEMINI_API_KEY
from endpoints.logging.utils_logging import log_gemini_request, log_gemini_response

logger = logging.getLogger("pdf_read_refresh.endpoints.generate_video_prompt")


@app.post("/generate-video-prompt/")
async def generate_video_prompt(prompt: str = Body(..., embed=True)):
    logger.info("Generate video prompt request received", extra={"prompt": prompt})
    try:
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={GEMINI_API_KEY}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"Create a creative short video prompt: {prompt}"}
                    ]
                }
            ],
            "generationConfig": {"candidateCount": 1},
        }

        log_gemini_request(
            logger,
            "generate_video_prompt",
            url=api_url,
            payload=payload,
            model="gemini-1.5-pro",
        )
        logger.debug("Sending Gemini request", extra={"payload": payload})
        response = requests.post(api_url, json=payload)
        if response.status_code != 200:
            logger.error("Gemini request failed", extra={"status": response.status_code, "body": response.text})
            raise HTTPException(status_code=response.status_code, detail=response.text)

        data = response.json() if response.text else {}
        log_gemini_response(
            logger,
            "generate_video_prompt",
            url=api_url,
            status_code=response.status_code,
            response=data,
        )
        logger.debug("Gemini response received", extra={"response": data})

        generated_text = data['candidates'][0]['content']['parts'][0]['text']
        logger.info("Generated video prompt", extra={"generated_prompt": generated_text})

        response_payload = {"video_prompt": generated_text}
        logger.debug("Generate video prompt response payload", extra={"response": response_payload})

        return JSONResponse(content=response_payload)
    except Exception as e:
        logger.exception("Generate video prompt failed")
        raise HTTPException(status_code=500, detail=str(e))









