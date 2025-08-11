import requests
from fastapi import Body, HTTPException
from fastapi.responses import JSONResponse
from main import app, GEMINI_API_KEY


@app.post("/generate-video-prompt/")
async def generate_video_prompt(prompt: str = Body(..., embed=True)):
    print("[/generate-video-prompt] 🔄 İstek alındı, prompt:", prompt)
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

        print("[/generate-video-prompt] 🚀 Gemini API isteği gönderiliyor...")
        response = requests.post(api_url, json=payload)
        if response.status_code != 200:
            print("[/generate-video-prompt] ❌ Hata:", response.text)
            raise HTTPException(status_code=response.status_code, detail=response.text)

        data = response.json()
        print("[/generate-video-prompt] ✅ Başarılı Gemini cevabı:", data)

        generated_text = data['candidates'][0]['content']['parts'][0]['text']
        print("[/generate-video-prompt] 📜 Üretilen prompt:", generated_text)

        return JSONResponse(content={"video_prompt": generated_text})
    except Exception as e:
        print("[/generate-video-prompt] ❗️Exception:", str(e))
        raise HTTPException(status_code=500, detail=str(e))
