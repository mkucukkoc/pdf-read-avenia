import logging
import random
import requests
import httpx
from fastapi import Body, HTTPException
from fastapi.responses import JSONResponse
from main import app, wait_for_video_ready, GEMINI_API_KEY, RUNWAY_API_KEY

logger = logging.getLogger("pdf_read_refresh.endpoints.generate_video")


@app.post("/generate-video/")
async def generate_video(user_prompt: str = Body(..., embed=True)):
    logger.info("Generate video request received", extra={"user_prompt": user_prompt})

    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={GEMINI_API_KEY}"
    gemini_payload = {
        "contents": [
            {"parts": [{"text": f"Create a creative short video prompt for: {user_prompt}"}]}
        ],
        "generationConfig": {"candidateCount": 1},
    }

    try:
        logger.debug("Sending Gemini prompt generation request", extra={"payload": gemini_payload})
        gemini_response = requests.post(gemini_url, json=gemini_payload)
        gemini_data = gemini_response.json()
        creative_prompt = gemini_data["candidates"][0]["content"]["parts"][0]["text"]
        if len(creative_prompt) > 1000:
            logger.debug("Cleaning creative prompt length", extra={"original_length": len(creative_prompt)})
            creative_prompt = creative_prompt[:997] + "..."

        logger.debug("Gemini creative prompt generated", extra={"creative_prompt": creative_prompt})

    except Exception as e:
        logger.exception("Gemini prompt generation failed")
        raise HTTPException(status_code=500, detail="Gemini prompt üretimi başarısız: " + str(e))

    stock_image_url = "https://upload.wikimedia.org/wikipedia/commons/3/3a/Cat03.jpg"
    runway_url = "https://api.dev.runwayml.com/v1/image_to_video"
    headers = {
        "Authorization": f"Bearer {RUNWAY_API_KEY}",
        "Content-Type": "application/json",
        "X-Runway-Version": "2024-11-06",
    }
    payload = {
        "promptImage": stock_image_url,
        "model": "gen4_turbo",
        "promptText": creative_prompt,
        "duration": 5,
        "ratio": "1280:720",
        "seed": random.randint(0, 4294967295),
        "contentModeration": {
            "publicFigureThreshold": "auto",
        },
    }

    try:
        logger.debug("Sending Runway video request", extra={"payload": payload})
        async with httpx.AsyncClient() as client:
            runway_response = await client.post(runway_url, headers=headers, json=payload)

        logger.debug(
            "Runway response received",
            extra={
                "status_code": runway_response.status_code,
                "body": runway_response.text,
            },
        )

        if runway_response.status_code != 200:
            raise HTTPException(status_code=runway_response.status_code, detail=runway_response.text)

        video_id = runway_response.json().get("id")
        video_url = await wait_for_video_ready(video_id)
        logger.info("Generated video ready", extra={"video_id": video_id, "video_url": video_url})

        response_payload = {"video_url": video_url}
        logger.debug("Generate video response payload", extra={"response": response_payload})
        return JSONResponse(content=response_payload)

    except Exception as e:
        logger.exception("Runway video generation failed")
        raise HTTPException(status_code=500, detail="Runway video üretim hatası: " + str(e))


