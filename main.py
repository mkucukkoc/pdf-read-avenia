import os
import io
import re
import json
import math
import uuid
import base64
import random
import asyncio
import tempfile
from datetime import datetime
from typing import List, Dict
from io import BytesIO

import requests
import httpx
import aiohttp
import soundfile as sf
import numpy as np
import librosa
import noisereduce as nr
from pydub import AudioSegment, effects
from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pypdf import PdfReader
from fastapi import FastAPI, UploadFile, HTTPException, Body, Form, APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI

import firebase_admin
from firebase_admin import credentials, storage, firestore



router = APIRouter()


from dotenv import load_dotenv
load_dotenv()

FIREBASE_SERVICE_ACCOUNT_BASE64=os.getenv("FIREBASE_SERVICE_ACCOUNT_BASE64")

decoded_json = base64.b64decode(FIREBASE_SERVICE_ACCOUNT_BASE64).decode('utf-8')
service_account_info = json.loads(decoded_json)

if not firebase_admin._apps:
    cred = credentials.Certificate(service_account_info)
    firebase_admin.initialize_app(cred, {
        'storageBucket': 'aveniaapp.firebasestorage.app'
    })


app = FastAPI()

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
TTS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Default voice
API_KEY = os.getenv("AIORNOT_API_KEY")  # aiornot API key


class DocRequest(BaseModel):
    prompt: str

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
        model=DEFAULT_MODEL,
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
            model=DEFAULT_MODEL,
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


from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import JSONResponse
from openai import OpenAI
import os


@app.post("/ask-file-question/")
async def ask_file_question(
    file_text: str = Form(...),
    question: str = Form(...),
    file_type: str = Form(default="genel")  # örnek: 'PDF', 'Word', 'Excel', 'PPT'
):
    print("[/ask-file-question] 🧠 Soru geldi:", question)
    print("[/ask-file-question] 📄 Dosya tipi:", file_type)
    print("[/ask-file-question] 📄 İçerik uzunluğu:", len(file_text))

    prompt = f"""
Aşağıda bir {file_type.upper()} dosyasının içeriği bulunmaktadır. Kullanıcı bu içeriğe dayanarak bir soru sordu.

Lütfen sadece verilen içerikten yararlanarak doğru, detaylı ve anlaşılır bir cevap ver.

📄 Dosya içeriği:
\"\"\"
{file_text[:4000]}
\"\"\"

❓ Soru:
\"\"\"
{question}
\"\"\"

💬 Cevap:
"""

    try:
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": f"Sana bir {file_type} dosyasının metinsel içeriği verildi. Sadece bu içeriğe dayanarak soruları yanıtla. Tahmin yürütme veya içerik dışında yorum yapma."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        answer = response.choices[0].message.content.strip()
        print("[/ask-file-question] ✅ Yanıt üretildi.")
        return JSONResponse(content={"answer": answer})

    except Exception as e:
        print("[/ask-file-question] ❌ Hata:", str(e))
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

        user_id = payload.get("user_id")
        chat_id = payload.get("chat_id")

        # --- Embedding kaydı ekle ---
        file_id = str(uuid.uuid4())  # benzersiz dosya ID’si
        save_embeddings_to_firebase(user_id, chat_id, file_id, text, summary, "PDF")


        # --- Yanıt ---
        return JSONResponse(content={
            "summary": summary,
            "full_text": text,
            "file_id": file_id
        })

    except Exception as e:
        print("[/summarize-pdf-url] ❌ Hata:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-doc")
async def generate_doc(data: DocRequest):
    print("[/generate-doc] 📝 İstek alındı.")
    try:
        # 1. GPT'den içerik al
        print("[/generate-doc] 🧠 GPT'den içerik alınıyor...")
        completion = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[{"role": "user", "content": data.prompt}],
            max_tokens=1500
        )
        generated_text = completion.choices[0].message.content.strip()
        print("[/generate-doc] ✅ GPT içeriği alındı, uzunluk:", len(generated_text))
        print("[/generate-doc] 🔍 İlk 300 karakter:\n", generated_text[:300])

        # 2. Word belgesi oluştur
        print("[/generate-doc] 📄 Word belgesi oluşturuluyor...")
        doc = Document()
        doc.add_heading('Avenia Belgesi', 0)
        for i, paragraph in enumerate(generated_text.split("\n")):
            cleaned = paragraph.strip()
            if cleaned:
                doc.add_paragraph(cleaned)
                print(f"[/generate-doc] ➕ Paragraf {i+1}: {cleaned[:100]}")

        # 3. Geçici dosyaya kaydet
        temp_path = tempfile.gettempdir()
        filename = f"generated_{uuid.uuid4().hex}.docx"
        filepath = os.path.join(temp_path, filename)
        doc.save(filepath)
        print("[/generate-doc] 💾 Word dosyası kaydedildi:", filepath)

        # 4. Firebase Storage’a yükle
        print("[/generate-doc] ☁️ Firebase Storage’a yükleniyor...")
        bucket = storage.bucket()
        blob = bucket.blob(f"generated_docs/{filename}")
        blob.upload_from_filename(filepath)
        blob.make_public()
        print("[/generate-doc] 📤 Yükleme başarılı, link:", blob.public_url)

        # 5. URL’i dön
        return {
            "status": "success",
            "file_url": blob.public_url
        }

    except Exception as e:
        print("[/generate-doc] ❌ Hata oluştu:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-excel")
async def generate_excel(data: DocRequest):
    print("[/generate-excel] 🎯 İstek alındı.")
    try:
        # 1. GPT'den içerik al
        print("[/generate-excel] 🧠 GPT'den içerik isteniyor...")
        completion = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[{"role": "user", "content": data.prompt}],
            max_tokens=1500
        )
        generated_text = completion.choices[0].message.content.strip()
        print("[/generate-excel] ✅ GPT içeriği alındı, uzunluk:", len(generated_text))
        print("[/generate-excel] 🔍 İlk 300 karakter:\n", generated_text[:300])

        # 2. Excel dosyası oluştur
        print("[/generate-excel] 📊 Excel dosyası oluşturuluyor...")
        wb = Workbook()
        ws = wb.active
        ws.title = "Avenia"

        for i, line in enumerate(generated_text.split("\n")):
            cleaned_line = line.strip()
            if cleaned_line:
                ws.cell(row=i+1, column=1, value=cleaned_line)
                print(f"[/generate-excel] ➕ Satır {i+1} eklendi: {cleaned_line[:100]}")

        # 3. Geçici dosya olarak kaydet
        temp_path = tempfile.gettempdir()
        filename = f"generated_{uuid.uuid4().hex}.xlsx"
        filepath = os.path.join(temp_path, filename)
        wb.save(filepath)
        print("[/generate-excel] 💾 Excel dosyası kaydedildi:", filepath)

        # 4. Firebase Storage’a yükle
        print("[/generate-excel] ☁️ Firebase Storage’a yükleniyor...")
        bucket = storage.bucket()
        blob = bucket.blob(f"generated_excels/{filename}")
        blob.upload_from_filename(filepath)
        blob.make_public()
        print("[/generate-excel] 📤 Firebase’a yüklendi, erişim linki:", blob.public_url)

        # 5. URL’i dön
        return {
            "status": "success",
            "file_url": blob.public_url
        }

    except Exception as e:
        print("[/generate-excel] ❌ Hata oluştu:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

# Yeni generate-ppt endpoint'i (görsel + başlık + içerik destekli
def generate_random_style():
    bg_colors = [RGBColor(255, 255, 255), RGBColor(240, 248, 255), RGBColor(230, 230, 250), RGBColor(255, 245, 238)]
    title_colors = [RGBColor(91, 55, 183), RGBColor(0, 102, 204), RGBColor(220, 20, 60)]
    fonts = ['Segoe UI', 'Calibri', 'Arial', 'Verdana']
    content_fonts = ['Calibri', 'Georgia', 'Tahoma']
    font_sizes = [Pt(18), Pt(20), Pt(22)]

    return {
        "bg_color": random.choice(bg_colors),
        "title_color": random.choice(title_colors),
        "title_font": random.choice(fonts),
        "content_font": random.choice(content_fonts),
        "content_font_size": random.choice(font_sizes),
    }



@app.post("/generate-ppt")
async def generate_ppt(data: DocRequest):
    print("[/generate-ppt] 🌟 Sunum isteği alındı.")
    try:
        completion = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": """Sen bir sunum üreticisisin. Her slaytı şu formatta ver:
# Slide X
Title: ...
Content: ...
Image: (Bu başlıkla ilgili kısa bir sahne betimlemesi örn: \"kitap okuyan bir kadın\")"""},
                {"role": "user", "content": data.prompt}
            ],
            max_tokens=1500
        )
        generated_text = completion.choices[0].message.content.strip()
        slides = parse_ppt_prompt(generated_text)

        prs = Presentation()
        splash = prs.slides.add_slide(prs.slide_layouts[0])
        splash.shapes.title.text = f"📊 {data.prompt[:60]}..."
        splash.placeholders[1].text = "Bu sunum Avenia tarafından otomatik üretildi."

        for i, slide in enumerate(slides):
            print(f"[/generate-ppt] 📄 Slayt {i+1}: {slide['title'][:50]}...")
            s = prs.slides.add_slide(prs.slide_layouts[6])

            style = generate_random_style()  # prompt'tan tema yoksa rastgele seç

            fill = s.background.fill
            fill.solid()
            fill.fore_color.rgb = style["bg_color"]

            title_box = s.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(8), Inches(1))
            tf = title_box.text_frame
            tf.text = slide['title']
            tf.paragraphs[0].font.size = Pt(32)
            tf.paragraphs[0].font.bold = True
            tf.paragraphs[0].font.name = style["title_font"]
            tf.paragraphs[0].font.color.rgb = style["title_color"]

            date_box = s.shapes.add_textbox(Inches(8), Inches(0.1), Inches(2), Inches(0.3))
            dtf = date_box.text_frame
            dtf.text = datetime.now().strftime("%d %B %Y")
            dtf.paragraphs[0].font.size = Pt(12)
            dtf.paragraphs[0].font.name = 'Calibri'
            dtf.paragraphs[0].font.color.rgb = RGBColor(160, 160, 160)

            logo_path = "avenia_logo.png"
            if os.path.exists(logo_path):
                try:
                    s.shapes.add_picture(logo_path, Inches(0.1), Inches(5.3), height=Inches(0.5))
                except Exception as e:
                    print(f"[/generate-ppt] ⚠️ Logo eklenemedi: {e}")

            if slide['content']:
                content_box = s.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(4.5), Inches(4))
                ctf = content_box.text_frame
                ctf.text = slide['content']
                for p in ctf.paragraphs:
                    p.font.size = style["content_font_size"]
                    p.font.name = style["content_font"]
                    p.font.color.rgb = RGBColor(80, 80, 80)

            if slide['image']:
                try:
                    dalle_response = client.images.generate(
                        model="dall-e-3",
                        prompt=slide['image'],
                        n=1,
                        size="1024x1024"
                    )
                    image_url = dalle_response.data[0].url
                    image_data = requests.get(image_url).content
                    image_path = os.path.join(tempfile.gettempdir(), f"image_{uuid.uuid4().hex}.png")
                    with open(image_path, "wb") as f:
                        f.write(image_data)
                    s.shapes.add_picture(image_path, Inches(5.2), Inches(1.5), height=Inches(3.5))
                except Exception as e:
                    print("[/generate-ppt] ❌ Görsel oluşturulamadı:", str(e))

        filename = f"generated_{uuid.uuid4().hex}.pptx"
        filepath = os.path.join(tempfile.gettempdir(), filename)
        prs.save(filepath)

        bucket = storage.bucket()
        blob = bucket.blob(f"generated_ppts/{filename}")
        blob.upload_from_filename(filepath)
        blob.make_public()

        return {"status": "success", "file_url": blob.public_url}

    except Exception as e:
        print("[/generate-ppt] ❌ Hata oluştu:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

def parse_ppt_prompt(text: str):
    slides = []
    current_slide = {"title": "", "content": "", "image": ""}

    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("# slide"):
            if current_slide["title"] or current_slide["content"]:
                slides.append(current_slide)
            current_slide = {"title": "", "content": "", "image": ""}
        elif line.lower().startswith("title:"):
            current_slide["title"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("content:"):
            current_slide["content"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("image:"):
            current_slide["image"] = line.split(":", 1)[1].strip()

    if current_slide["title"] or current_slide["content"]:
        slides.append(current_slide)

    return slides


# Firebase init
# 🔊 Yeni endpoint: Speech-to-Text
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

# ----------------------------------------------------
# TTS: Chat geçmişini sese çevir (OpenAI tts-1)
# ----------------------------------------------------
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
        raise HTTPException(status_code=400, detail="Chat mesajları eksik.")

    # Mesajları birleştir (4000 karakter limiti)
    combined_text = []
    for m in messages:
        if m.get("role") == "user":
            combined_text.append(f"Sen: {m.get('content','')}")
        elif m.get("role") == "assistant":
            combined_text.append(m.get("content",""))
    combined_text = "\n".join(combined_text)[:4000]

    print("[/tts-chat] 🔊 Metin uzunluğu:", len(combined_text))
    print("[/tts-chat] 📜 Önizleme:\n", combined_text[:300])

    try:
        speech = client.audio.speech.create(
            model="tts-1",
            voice="alloy",  # diğer ör: "verse", "aria"
            input=combined_text,
            # format varsayılan mp3; istenirse: response_format="wav" / "pcm"
        )
        audio_bytes = speech.content
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        print("[/tts-chat] ✅ Ses üretildi.")
        return {"audio_base64": audio_base64}

    except Exception as e:
        print("[/tts-chat] ❌ Hata:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------------------------------
# Audio Isolation (lokal): hafif denoise + filtreleme
# ----------------------------------------------------
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

@app.post("/summarize-excel-url/")
async def summarize_excel_from_url(data: dict):
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL not provided")
    
    # Dosyayı indir
    file_path = "temp.xlsx"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            with open(file_path, "wb") as f:
                f.write(await resp.read())

    # Excel içeriğini oku
    import pandas as pd
    df = pd.read_excel(file_path)
    description = df.describe(include='all').to_string()

    # GPT ile özetle
    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[{
            "role": "system",
            "content": "Aşağıdaki Excel verilerini analiz et ve anlamlı bir özet çıkar:"
        }, {
            "role": "user",
            "content": description
        }]
    )
    summary = response.choices[0].message.content

    # Embedding kaydı
    file_id = str(uuid.uuid4())
    user_id = data.get("user_id")
    chat_id = data.get("chat_id")
    save_embeddings_to_firebase(user_id, chat_id, file_id, description, summary, "XLSX")

    return { "summary": summary, "full_text": description, "file_id": file_id }


@app.post("/summarize-word-url/")
async def summarize_word_from_url(data: dict):

    url = data.get("url")
    print("📥 Dosya URL:", url)
    if not url:
        raise HTTPException(status_code=400, detail="URL not provided")
    
    file_path = "temp.docx"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise HTTPException(status_code=500, detail=f"Dosya indirilemedi: {resp.status}")
            with open(file_path, "wb") as f:
                f.write(await resp.read())
    
    print("📦 Dosya indirildi:", file_path)
    full_text = extract_text_from_docx(file_path)
    

    print("📄 Word dosyası ilk 300 karakter:", full_text[:300])  # LOG EKLENDİ
    print("📄 Word içeriği karakter sayısı:", len(full_text))


    if not full_text.strip():
        raise HTTPException(status_code=500, detail="❌ Word içeriği boş")

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "Lütfen aşağıdaki Word belgesini özetle:"},
            {"role": "user", "content": full_text[:3000]}
        ]
    )
    summary = response.choices[0].message.content
    # Embedding kaydı
    file_id = str(uuid.uuid4())
    user_id = data.get("user_id")
    chat_id = data.get("chat_id")
    save_embeddings_to_firebase(user_id, chat_id, file_id, full_text, summary, "DOCX")

    return { "summary": summary, "full_text": full_text, "file_id": file_id }


@app.post("/summarize-ppt-url/")
async def summarize_ppt_from_url(data: dict):
    print("🚀 [summarize-ppt-url] Endpoint tetiklendi")
    print("📦 Gelen data:", data)

    url = data.get("url")
    if not url:
        print("❌ URL bulunamadı!")
        raise HTTPException(status_code=400, detail="URL not provided")

    file_path = "temp.pptx"
    print(f"📥 Sunum indiriliyor: {url}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    print(f"❌ Dosya indirilemedi. HTTP status: {resp.status}")
                    raise HTTPException(status_code=500, detail="File download failed")
                with open(file_path, "wb") as f:
                    f.write(await resp.read())
        print("✅ Dosya indirildi:", file_path)
    except Exception as e:
        print("❌ Dosya indirme hatası:", e)
        raise HTTPException(status_code=500, detail="Download error")

    try:
        prs = Presentation(file_path)
        full_text = ""
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    full_text += shape.text + "\n"

        print("📝 Sunumdan çıkarılan içerik (ilk 200 karakter):")
        print(full_text[:200] or "[boş]")

        os.remove(file_path)
    except Exception as e:
        print("❌ PPTX okuma hatası:", e)
        raise HTTPException(status_code=500, detail="PowerPoint parse error")

    try:
        print("🤖 GPT-4 ile özetleniyor...")
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "Bu PowerPoint sunumunun içeriğini özetle:"},
                {"role": "user", "content": full_text[:3000]}
            ]
        )
        summary = response.choices[0].message.content
        print("✅ GPT özeti başarıyla alındı (ilk 200 karakter):")
        print(summary[:200])
        file_id = str(uuid.uuid4())
        user_id = data.get("user_id")
        chat_id = data.get("chat_id")
        print(chat_id,"chat_id")
        print(user_id,"user_id")
        db = firestore.client()
        save_embeddings_to_firebase(user_id, chat_id, file_id, full_text, summary, "PPTX")
        messages_ref = db.collection("users").document(user_id).collection("chats").document(chat_id).collection("messages")
        chat_ref = db.collection("users").document(user_id).collection("chats").document(chat_id)
        chat_ref.update({"file_id": file_id})
        print(f"[summarize-ppt-url] ✅ Chat doc file_id güncellendi: {file_id}")
        print(messages_ref,"messages_ref")
        messages_ref.add({
            "role": "assistant",
            "content": summary,  # GPT özeti
            "file_id": file_id,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        print(messages_ref,"messages_ref")
        return {"full_text": summary}
    except Exception as e:
        print("❌ GPT özetleme hatası:", e)
        raise HTTPException(status_code=500, detail="GPT summarization error")


@app.post("/summarize-html-url/")
async def summarize_html_from_url(data: dict):
    from bs4 import BeautifulSoup

    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL not provided")

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            html = await resp.text()

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "Bu web sayfasının içeriğini özetle:"},
            {"role": "user", "content": text[:3000]}
        ]
    )
    return { "full_text": response.choices[0].message.content }


@app.post("/summarize-json-url/")
async def summarize_json_from_url(data: dict):
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL not provided")

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            json_data = await resp.json()

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "Bu JSON verisinin ne ifade ettiğini açıkla:"},
            {"role": "user", "content": json.dumps(json_data)[:3000]}
        ]
    )
    return { "full_text": response.choices[0].message.content }


@app.post("/summarize-csv-url/")
async def summarize_csv_from_url(data: dict):
    import pandas as pd
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL not provided")

    df = pd.read_csv(url)
    summary = df.describe(include='all').to_string()

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "Bu CSV dosyasını analiz et ve önemli verileri özetle:"},
            {"role": "user", "content": summary}
        ]
    )
    return { "full_text": response.choices[0].message.content }

@app.post("/summarize-txt-url/")
async def summarize_txt_from_url(data: dict):
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL not provided")

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            content = await resp.text()

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "Aşağıdaki metni özetle:"},
            {"role": "user", "content": content[:3000]}
        ]
    )

    # Embedding kaydı
    file_id = str(uuid.uuid4())

    user_id = data.get("user_id")
    chat_id = data.get("chat_id")
    save_embeddings_to_firebase(user_id, chat_id, file_id, text, summary, "TXT")
   

    return { "summary": summary, "full_text": content, "file_id": file_id }


def extract_text_from_docx(file_path):
    doc = Document(file_path)
    text_parts = []

    # Paragraflar
    for para in doc.paragraphs:
        if para.text.strip():
            text_parts.append(para.text.strip())

    # Tablolar
    for table in doc.tables:
        for row in table.rows:
            row_text = "\t".join(cell.text.strip() for cell in row.cells)
            if row_text:
                text_parts.append(row_text)

    return "\n".join(text_parts)



    # ----------------------------
# EMBEDDINGS DESTEKLİ ARAMA
# ----------------------------


# 1. Embedding oluşturma
def create_embedding(text: str) -> List[float]:
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding

# 2. Cosine similarity
def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    return dot / (norm1 * norm2)

# 3. PDF yüklenince embedding kaydetme (mevcut summarize_pdf_url sonrası çağır)
def save_embeddings_to_firebase(user_id: str, chat_id: str, file_id: str, file_text: str, summary: str, file_type: str):
    db = firestore.client()

    print(f"[save_embeddings_to_firebase] 📥 Başlatıldı")
    print(f"   → user_id: {user_id}")
    print(f"   → chat_id: {chat_id}")
    print(f"   → file_id: {file_id}")
    print(f"   → file_type: {file_type}")
    print(f"   → file_text uzunluğu: {len(file_text) if file_text else 0}")
    print(f"   → summary uzunluğu: {len(summary) if summary else 0}")

    # Base reference: embeddings/userId/chatId
    base_ref = db.collection("embeddings").document(user_id).collection(chat_id)
    print(f"[save_embeddings_to_firebase] 🔗 Firestore path: embeddings/{user_id}/{chat_id}")

    # 1. Meta veriyi kaydet (chunk_index = -999)
    try:
        meta_doc = {
            "file_id": file_id,
            "chunk_index": -999,
            "summary": summary,
            "type": file_type,
            "createdAt": firestore.SERVER_TIMESTAMP
        }
        base_ref.add(meta_doc)
        print(f"[save_embeddings_to_firebase] ✅ Meta veri kaydedildi: {meta_doc}")
    except Exception as e:
        print(f"[save_embeddings_to_firebase] ❌ Meta kaydı hatası: {e}")

    # 2. Summary’nin embedding’i
    if summary and summary.strip():
        try:
            summary_clean = " ".join(summary.split())
            print(f"[save_embeddings_to_firebase] 🔄 Summary temizlendi: {summary_clean[:100]}...")
            summary_embedding = create_embedding(summary_clean)
            print(f"[save_embeddings_to_firebase] 🧠 Summary embedding boyutu: {len(summary_embedding)}")

            base_ref.add({
                "file_id": file_id,
                "chunk_index": -1,
                "text": summary_clean,
                "embedding": summary_embedding
            })
            print(f"[save_embeddings_to_firebase] ✅ Summary embedding kaydedildi (chunk_index=-1)")
        except Exception as e:
            print(f"[save_embeddings_to_firebase] ❌ Summary embedding hatası: {e}")

    # 3. Chunk embedding’leri
    chunks = [file_text[i:i+500] for i in range(0, len(file_text), 500)]
    print(f"[save_embeddings_to_firebase] 🔄 Toplam {len(chunks)} chunk üretildi")

    for idx, chunk in enumerate(chunks):
        try:
            chunk_clean = " ".join(chunk.split())
            print(f"[save_embeddings_to_firebase] → Chunk {idx} temizlendi (ilk 80 karakter): {chunk_clean[:80]}")

            embedding = create_embedding(chunk_clean)
            print(f"[save_embeddings_to_firebase] 🧠 Chunk {idx} embedding boyutu: {len(embedding)}")

            base_ref.add({
                "file_id": file_id,
                "chunk_index": idx,
                "text": chunk_clean,
                "embedding": embedding
            })
            print(f"[save_embeddings_to_firebase] ✅ Chunk {idx} kaydedildi")
        except Exception as e:
            print(f"[save_embeddings_to_firebase] ❌ Chunk {idx} hatası: {e}")

    print("[save_embeddings_to_firebase] 🎉 Tüm kayıt işlemleri tamamlandı.")


# 4. Yeni endpoint: embeddings tabanlı soru-cevap
@app.post("/ask-with-embeddings/")
async def ask_with_embeddings(
    question: str = Form(...),
    file_id: str = Form(...),
    user_id: str = Form(...),
    chat_id: str = Form(...)
):
    from firebase_admin import firestore
    db = firestore.client()

    print("\n[ask-with-embeddings] 📥 İstek alındı")
    print(f"   → user_id: {user_id}")
    print(f"   → chat_id: {chat_id}")
    print(f"   → file_id: {file_id}")
    print(f"   → question: {question}")

    # Firestore Path
    base_ref = db.collection("embeddings").document(user_id).collection(chat_id)
    print(f"[ask-with-embeddings] 🔗 Firestore path: embeddings/{user_id}/{chat_id}")

    # 1. Soru embedding oluştur
    try:
        q_embedding = create_embedding(question)
        print(f"[ask-with-embeddings] 🧠 Soru embedding boyutu: {len(q_embedding)}")
    except Exception as e:
        print(f"[ask-with-embeddings] ❌ Soru embedding hatası: {e}")
        raise

    # 2. İlgili chunk'ları çek (meta hariç)
    try:
        docs = base_ref.where("file_id", "==", file_id).stream()
        print("[ask-with-embeddings] 🔄 Firestore'dan chunk'lar çekiliyor...")

        chunks = []
        for doc in docs:
            data = doc.to_dict()
            if data.get("chunk_index", 0) >= 0:  # Python’da filtre
                score = cosine_similarity(q_embedding, data["embedding"])
                chunks.append((score, data["text"]))
                print(f"   → Chunk skor: {score:.4f}, text (ilk 60): {data['text'][:60]}")
    except Exception as e:
        print(f"[ask-with-embeddings] ❌ Chunk okuma hatası: {e}")
        raise

    # 3. En yakın 3 chunk seç
    top_chunks = [text for score, text in sorted(chunks, key=lambda x: x[0], reverse=True)[:3]]
    print(f"[ask-with-embeddings] 🏆 Seçilen top_chunks (adet: {len(top_chunks)}):")
    for i, tc in enumerate(top_chunks):
        print(f"   {i+1}. {tc[:100]}...")

    # 4. GPT prompt hazırla
    context = "\n".join(top_chunks)
    prompt = f"""
Bağlama dayanarak soruya yanıt ver. Doğrudan cevap yoksa en yakın bilgiyi özetle:
{context}

Soru: {question}
"""
    print(f"[ask-with-embeddings] 📝 GPT'ye gönderilen prompt (ilk 300): {prompt[:300]}")

    # 5. GPT çağır ve cevap döndür
    try:
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "Sen bağlam tabanlı bir asistansın."},
                {"role": "user", "content": prompt}
            ]
        )
        answer = response.choices[0].message.content
        print(f"[ask-with-embeddings] ✅ GPT yanıtı (ilk 200): {answer[:200]}")
    except Exception as e:
        print(f"[ask-with-embeddings] ❌ GPT yanıt hatası: {e}")
        raise

    return {"answer": answer, "context_used": top_chunks}



##
IMAGE_ENDPOINT = "https://api.aiornot.com/v1/reports/image"
MOCK_MODE = os.getenv("MOCK_MODE", "0") == "1"

# --- Firebase init (service account JSON'u base64 ile ENV'den) ---
FIREBASE_SERVICE_ACCOUNT_BASE64 = os.getenv("FIREBASE_SERVICE_ACCOUNT_BASE64")
if FIREBASE_SERVICE_ACCOUNT_BASE64 and not firebase_admin._apps:
    decoded = base64.b64decode(FIREBASE_SERVICE_ACCOUNT_BASE64).decode("utf-8")
    cred = credentials.Certificate(json.loads(decoded))
    firebase_admin.initialize_app(cred)
db = firestore.client()
##

def decode_base64_maybe_data_url(s: str) -> bytes:
    """Hem düz base64'ü hem de data URL'yi destekler."""
    if not isinstance(s, str):
        raise ValueError("image_base64 must be a string")
    if s.startswith("data:"):
        m = re.match(r"^data:[^;]+;base64,(.+)$", s)
        if not m:
            raise ValueError("Invalid data URL")
        s = m.group(1)
    return base64.b64decode(s)

def interpret_messages_legacy(data):
    """
    Eski 'messages' array'ini üretir ("Medium Likely AI", "Good", "No" gibi).
    """
    msgs = []
    report = data.get("report", {}) or {}
    facets = data.get("facets", {}) or {}
    verdict = report.get("verdict")
    ai_info = report.get("ai", {}) or {}
    human_info = report.get("human", {}) or {}
    generators = report.get("generator", {}) or {}

    # verdict
    if verdict == "ai":
        c = ai_info.get("confidence", 0.0) or 0.0
        if c >= 0.95: msgs.append("High Likely AI")
        elif 0.7 <= c < 0.95: msgs.append("Medium Likely AI")
        elif 0.5 <= c < 0.7: msgs.append("Low Likely AI")
        else: msgs.append("Possibly AI")
    elif verdict == "human":
        c = human_info.get("confidence", 0.0) or 0.0
        if c >= 0.9: msgs.append("High Likely Human")
        elif c < 0.7: msgs.append("Likely Human")
        else: msgs.append("Possibly Human")
    else:
        msgs.append("Unknown")

    # generator (varsa)
    for gen_name, gen_data in generators.items():
        if gen_data.get("is_detected") and (gen_data.get("confidence", 0) or 0) >= 0.7:
            msgs.append(
                f"🖼️ İçerik, %{int(gen_data['confidence'] * 100)} oranla "
                f"{gen_name.replace('_',' ').title()} tarafından oluşturulmuş olabilir."
            )
            break

    # quality / nsfw
    quality = (facets.get("quality", {}) or {}).get("is_detected", True)
    nsfw = (facets.get("nsfw", {}) or {}).get("is_detected", False)
    msgs.append("Good" if quality else "Bad")
    msgs.append("Yes" if nsfw else "No")
    return msgs

def format_summary_tr(data) -> str:
    """
    İnsan-dili Türkçe özet:
    - % güvene göre: AI/insan
    - kalite: iyi/kötü
    - NSFW: sorun var/yok
    """
    report = data.get("report", {}) or {}
    facets = data.get("facets", {}) or {}
    verdict = report.get("verdict")
    ai_conf = float((report.get("ai", {}) or {}).get("confidence", 0.0) or 0.0)
    human_conf = float((report.get("human", {}) or {}).get("confidence", 0.0) or 0.0)

    if verdict == "ai":
        pct = round(ai_conf * 100)
        base = f"Görsel, %{pct} olasılıkla yapay zeka tarafından üretilmiş"
        if ai_conf >= 0.95:
            base += " (yüksek güven)."
        elif ai_conf >= 0.7:
            base += " (orta-yüksek güven)."
        else:
            base += "."
    elif verdict == "human":
        pct = round(human_conf * 100)
        base = f"Görsel, %{pct} olasılıkla insan tarafından üretilmiş"
        if human_conf >= 0.9:
            base += " (yüksek güven)."
        else:
            base += "."
    else:
        base = "Görselin kaynağı net değil."

    quality_good = (facets.get("quality", {}) or {}).get("is_detected", True)
    nsfw_flag = (facets.get("nsfw", {}) or {}).get("is_detected", False)
    quality_part = "Görsel yapısı iyi." if quality_good else "Görsel kalitesi düşük."
    nsfw_part = "NSFW açısından bir sorun görünmüyor." if not nsfw_flag else "NSFW içerik tespit edildi."
    return f"{base} {quality_part} {nsfw_part}"

@app.get("/healthz")
def healthz():
    return "OK", 200

@app.post("/analyze-image")
def analyze_image():
    """
    Beklenen body:
    {
      "image_base64": "<base64 veya data URL>",
      "user_id": "uid",
      "chat_id": "cid"
    }

    Dönüş:
    {
      "raw_response": {...},
      "messages": ["Medium Likely AI", "Good", "No"],
      "summary_tr": "Görsel, %99 ... Görsel yapısı iyi. NSFW ...",
      "saved": { "message_id": "...", "path": "users/{uid}/chats/{cid}/messages" }
    }
    """
    payload = request.get_json(silent=True) or {}
    print("[/analyze-image] Gelen JSON:", payload)

    image_b64 = payload.get("image_base64")
    user_id = payload.get("user_id")
    chat_id = payload.get("chat_id")
    if not image_b64:
        return jsonify({"error": "No base64 image data provided"}), 400
    if not user_id or not chat_id:
        return jsonify({"error": "user_id and chat_id are required"}), 400

    # MOCK (sabit: %99 AI, kalite iyi, NSFW yok) — env ile aç: MOCK_MODE=1
    if MOCK_MODE or request.args.get("mock") == "1":
        mock = {
            "report": {
                "verdict": "ai",
                "ai": {"confidence": 0.99},
                "human": {"confidence": 0.01},
                "generator": {}
            },
            "facets": {
                "quality": {"is_detected": True, "score": 0.92},
                "nsfw": {"is_detected": False, "score": 0.01}
            }
        }
        messages = ["High Likely AI", "Good", "No"]
        summary_tr = "Görsel, %99 olasılıkla yapay zeka tarafından üretilmiş (yüksek güven). Görsel yapısı iyi. NSFW açısından bir sorun görünmüyor."
        saved_info = _save_asst_message(user_id, chat_id, summary_tr, mock)
        return jsonify({
            "raw_response": mock,
            "messages": messages,
            "summary_tr": summary_tr,
            "saved": saved_info
        }), 200

    # Gerçek çağrı
    try:
        image_bytes = decode_base64_maybe_data_url(image_b64)
    except Exception as e:
        return jsonify({"error": "Invalid base64 data", "details": str(e)}), 400

    files = {"object": ('image.jpg', image_bytes, 'image/jpeg')}
    try:
        resp = requests.post(
            IMAGE_ENDPOINT,
            headers={"Authorization": f"Bearer {API_KEY}"},
            files=files,
            timeout=30
        )
    except requests.RequestException as e:
        return jsonify({"error": "AI analysis failed", "details": str(e)}), 502

    if resp.status_code != 200:
        return jsonify({"error": "AI analysis failed", "details": resp.text, "status": resp.status_code}), 500

    result = resp.json()
    messages = interpret_messages_legacy(result)
    summary_tr = format_summary_tr(result)
    saved_info = _save_asst_message(user_id, chat_id, summary_tr, result)

    return jsonify({
        "raw_response": result,
        "messages": messages,
        "summary_tr": summary_tr,
        "saved": saved_info
    }), 200

def _save_asst_message(user_id: str, chat_id: str, content: str, raw: dict):
    """
    Firestore'a assistant mesajı olarak yazar.
    """
    try:
        messages_ref = db.collection("users").document(user_id)\
                         .collection("chats").document(chat_id)\
                         .collection("messages")
        doc_ref = messages_ref.add({
            "role": "assistant",
            "content": content,
            "meta": {
                "ai_detect": {
                    "verdict": raw.get("report", {}).get("verdict"),
                    "ai_confidence": (raw.get("report", {}).get("ai", {}) or {}).get("confidence"),
                    "human_confidence": (raw.get("report", {}).get("human", {}) or {}).get("confidence"),
                    "quality": (raw.get("facets", {}).get("quality", {}) or {}),
                    "nsfw": (raw.get("facets", {}).get("nsfw", {}) or {}),
                    "raw": raw
                }
            },
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        message_id = doc_ref[1].id if isinstance(doc_ref, tuple) else doc_ref.id
        print("[/analyze-image] Firestore kaydı:", message_id)
        return {"message_id": message_id, "path": f"users/{user_id}/chats/{chat_id}/messages"}
    except Exception as e:
        print("[/analyze-image] Firestore yazım hatası:", e)
        return None

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)
