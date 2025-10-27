import random
import requests
import httpx
from fastapi import Body, HTTPException
from fastapi.responses import JSONResponse
from main import app, wait_for_video_ready, GEMINI_API_KEY, RUNWAY_API_KEY


@app.post("/generate-video/")
async def generate_video(user_prompt: str = Body(..., embed=True)):
    print("[/generate-video] 🧠 Kullanıcı prompt'u:", user_prompt)

    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={GEMINI_API_KEY}"
    gemini_payload = {
        "contents": [
            {"parts": [{"text": f"Create a creative short video prompt for: {user_prompt}"}]}
        ],
        "generationConfig": {"candidateCount": 1},
    }

    try:
        gemini_response = requests.post(gemini_url, json=gemini_payload)
        gemini_data = gemini_response.json()
        creative_prompt = gemini_data["candidates"][0]["content"]["parts"][0]["text"]
        if len(creative_prompt) > 1000:
            print(f"🧹 promptText uzunluğu: {len(creative_prompt)} — kırpılıyor")
            creative_prompt = creative_prompt[:997] + "..."

        print("[/generate-video] ✨ Gemini'den yaratıcı prompt:", creative_prompt)

    except Exception as e:
        print("❗️ Hata:", str(e))
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
        async with httpx.AsyncClient() as client:
            runway_response = await client.post(runway_url, headers=headers, json=payload)

        print("[/generate-video] 🎥 Runway cevabı:", runway_response.status_code, runway_response.text)

        if runway_response.status_code != 200:
            raise HTTPException(status_code=runway_response.status_code, detail=runway_response.text)

        video_id = runway_response.json().get("id")
        video_url = await wait_for_video_ready(video_id)
        print("🎬 Üretilen video linki:", video_url)

        return JSONResponse(content={"video_url": video_url})

    except Exception as e:
        print("❗️ Hata:", str(e))
        raise HTTPException(status_code=500, detail="Runway video üretim hatası: " + str(e))
