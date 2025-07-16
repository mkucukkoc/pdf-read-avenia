from fastapi import FastAPI, UploadFile, HTTPException, Body
from fastapi.responses import JSONResponse
from pypdf import PdfReader
import os
import requests
import httpx
from openai import OpenAI
import random
import asyncio
import json
from fastapi import Form
from io import BytesIO


from dotenv import load_dotenv
load_dotenv()


app = FastAPI()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY")

async def wait_for_video_ready(video_id, retries=30, delay=5):
    status_url = f"https://api.dev.runwayml.com/v1/tasks/{video_id}"  # ✅ doğru endpoint
    headers = {
        "Authorization": f"Bearer {RUNWAY_API_KEY}",
        "Content-Type": "application/json",
        "X-Runway-Version": "2024-11-06"
    }

    async with httpx.AsyncClient() as client:
        for attempt in range(retries):
            print(f"🎞️ Video durumu sorgulanıyor (deneme {attempt + 1})...")
            response = await client.get(status_url, headers=headers)

            try:
                data = response.json()
            except Exception:
                print(f"❌ JSON çözümleme hatası (deneme {attempt + 1}):", response.text)
                print(response.status_code, response.text) 
                await asyncio.sleep(delay)
                continue

            status = data.get("status")
            print(f"📌 Durum: {status}")

            if status == "SUCCEEDED":
                print("🧾 API'den dönen tüm veri (debug):")
                print("------------------------")
                print(json.dumps(data, indent=2))
                print("------------------------")
                video_output = data.get("output")
                if not video_output or not isinstance(video_output,list) or not video_output[0]:
                    raise Exception("✅ Video üretildi ama videoUri bulunamadı.")
                return video_output[0]

            if status == "FAILED":
                error_detail = data.get("error", {}).get("message", "Bilinmeyen hata")
                raise HTTPException(
                    status_code=422,  # Unprocessable Entity
                    detail={
                        "type": "runway_failure",
                        "message": f"Runway video üretimi başarısız oldu: {error_detail}",
                        "runway_response": data
                    }
                )

            await asyncio.sleep(delay)

    raise Exception("⚠️ Video üretimi zaman aşımına uğradı.")


@app.post("/generate-video/")
async def generate_video(user_prompt: str = Body(..., embed=True)):
    print("[/generate-video] 🧠 Kullanıcı prompt'u:", user_prompt)

    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={GEMINI_API_KEY}"
    gemini_payload = {
        "contents": [
            {"parts": [{"text": f"Create a creative short video prompt for: {user_prompt}"}]}
        ],
        "generationConfig": {"candidateCount": 1}
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
        "X-Runway-Version": "2024-11-06"
    }
    payload = {
        "promptImage": stock_image_url,
        "model": "gen4_turbo",
        "promptText": creative_prompt,
        "duration": 5,
        "ratio": "1280:720",
        "seed": random.randint(0, 4294967295),
        "contentModeration": {
            "publicFigureThreshold": "auto"
        }
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
            "generationConfig": {"candidateCount": 1}
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

@app.post("/summarize-pdf/")
async def summarize_pdf(file: UploadFile):
    print("[/summarize-pdf] 📄 PDF dosyası alındı:", file.filename)
    try:
        temp_path = f"temp_{file.filename}"
        print("[/summarize-pdf] 💾 Geçici dosya kaydediliyor:", temp_path)
        with open(temp_path, "wb") as f:
            f.write(await file.read())

        print("[/summarize-pdf] 📤 PDF'ten metin çıkarılıyor...")
        text = extract_text_from_pdf(temp_path)

        print("[/summarize-pdf] 🧠 GPT'den özet isteniyor...")
        summary = ask_gpt_summary(text)

        os.remove(temp_path)
        print("[/summarize-pdf] 🧹 Geçici dosya silindi.")

        return JSONResponse(content={"summary": summary, "full_text": text})
    except Exception as e:
        print("[/summarize-pdf] ❗️Exception:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

def extract_text_from_pdf(path: str) -> str:
    print("[extract_text_from_pdf] 📥 Dosya okunuyor:", path)
    reader = PdfReader(path)
    all_text = ""
    for i, page in enumerate(reader.pages):
        page_text = page.extract_text()
        print(f"[extract_text_from_pdf] 📄 Sayfa {i+1} okundu, karakter:", len(page_text) if page_text else 0)
        if page_text:
            all_text += page_text + "\n"

    print("[extract_text_from_pdf] 🧾 Toplam metin uzunluğu:", len(all_text))
    print("[extract_text_from_pdf] 🔍 İlk 500 karakter:\n", all_text[:500])

    return all_text[:4000]

def ask_gpt_summary(text: str) -> str:
    print("[ask_gpt_summary] 🤖 GPT ile özetleme başlıyor...")
    prompt = f"Bu PDF dosyasının içeriğini kısaca özetle:\n\n{text}"
    print("[ask_gpt_summary] 📤 Gönderilen prompt uzunluğu:", len(prompt))
    print("[ask_gpt_summary] 🔍 İlk 500 karakter:\n", prompt[:500])

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Sen profesyonel bir özetleyicisin."},
            {"role": "user", "content": prompt},
        ],
    )
    result = response.choices[0].message.content.strip()
    print("[ask_gpt_summary] ✅ GPT özeti alındı:\n", result)
    return result




# PDF metni üzerinden soru cevap
@app.post("/ask-pdf-question/")
async def ask_pdf_question(pdf_text: str = Form(...), question: str = Form(...)):
    print("[/ask-pdf-question] 🤖 Soru alındı:", question)
    print("[/ask-pdf-question] 📄 PDF metni uzunluğu:", len(pdf_text))

    prompt = f"""
Sen PDF belgesi içeriğini analiz eden bir asistansın. Kullanıcının sorusu aşağıda. Sadece PDF içeriğine dayanarak cevap ver:

📄 PDF içeriği:
\"\"\"
{pdf_text[:4000]}
\"\"\"

❓ Soru:
{question}

💬 Cevabın:
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Sen uzman bir PDF içeriği analistisin, sadece verilen içerikten faydalan."},
                {"role": "user", "content": prompt}
            ]
        )
        answer = response.choices[0].message.content.strip()
        print("[/ask-pdf-question] ✅ Yanıt alındı:", answer)
        return JSONResponse(content={"answer": answer})

    except Exception as e:
        print("[/ask-pdf-question] ❌ Hata:", str(e))
        raise HTTPException(status_code=500, detail=str(e))




@app.post("/summarize-pdf-url/")
async def summarize_pdf_url(payload: dict = Body(...)):
    url = payload.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="PDF URL gerekli")

    try:
        print("[/summarize-pdf-url] 🌐 PDF indiriliyor:", url)
        response = requests.get(url)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="PDF indirilemedi")

        pdf_bytes = response.content
        reader = PdfReader(BytesIO(pdf_bytes))

        all_text = ""
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            print(f"[PDF] Sayfa {i+1} — Karakter: {len(page_text) if page_text else 0}")
            if page_text:
                all_text += page_text + "\n"

        text = all_text[:4000]  # sadece ilk kısmı al

        print("[/summarize-pdf-url] 🧠 GPT özeti isteniyor...")
        summary = ask_gpt_summary(text)

        return JSONResponse(content={"summary": summary, "full_text": text})

    except Exception as e:
        print("[/summarize-pdf-url] ❌ Hata:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

