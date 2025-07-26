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
import tempfile
import uuid
import aiohttp
from docx import Document
from pydantic import BaseModel
import firebase_admin
from firebase_admin import credentials, storage
from openpyxl import Workbook
from pptx import Presentation
import uuid
import tempfile
import firebase_admin
import base64
from datetime import datetime
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
import os, uuid, tempfile, requests
from fastapi import HTTPException
import random
import mimetypes
import requests
from fastapi import APIRouter
from fastapi import UploadFile
import aiohttp
from docx import Document


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

        return JSONResponse(content={"summary": summary, "full_text": text})

    except Exception as e:
        print("[/summarize-pdf-url] ❌ Hata:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

class DocRequest(BaseModel):
    prompt: str

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
        # 🎧 Gürültü temizleme (Audio Isolation)
        print("[/stt] 🔄 Audio Isolation çağrılıyor...")
        isolation_response = requests.post(
            "https://avenia.onrender.com/audio-isolation",
            json={ "base64": base64_audio }
        )

        if isolation_response.status_code == 200:
            base64_audio = isolation_response.json().get("audio_base64", base64_audio)
            print("[/stt] 🎛 Gürültüsüz sesle devam ediliyor.")
        else:
            print("[/stt] ⚠️ Audio Isolation başarısız, orijinal ses kullanılacak.")

        print("[/stt] 🧬 Base64 ses verisi decode ediliyor...")
        audio_bytes = base64.b64decode(base64_audio)
        print(f"[/stt] ✅ Decode işlemi başarılı. Boyut: {len(audio_bytes)} byte")

        # multipart/form-data formatında gönderim
        files = {
            "file": ("audio.m4a", audio_bytes, "audio/m4a"),
            "model_id": (None, "scribe_v1"),
        }

        print("[/stt] 📡 ElevenLabs STT API'ye istek gönderiliyor...")
        response = requests.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={ "xi-api-key": ELEVENLABS_API_KEY },
            files=files
        )

        print(f"[/stt] 🧾 API yanıt kodu: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            transcribed_text = result.get("text")
            print("[/stt] ✅ Çözümleme başarılı. Metin:", transcribed_text)
            return {"text": transcribed_text}
        else:
            print("[/stt] ❌ API hatası:", response.text)
            return {"error": response.text}

    except Exception as e:
        print("[/stt] ❗️İşlem sırasında hata oluştu:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stt/quota")
def check_stt_quota():
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY
    }

    response = requests.get("https://api.elevenlabs.io/v1/user/subscription", headers=headers)

    if response.status_code == 200:
        data = response.json()
        return {
            "plan": data.get("tier"),
            "character_limit": data.get("character_limit"),
            "character_count": data.get("character_count"),
            "next_character_reset_unix": data.get("next_character_count_reset_unix"),
        }
    else:
        return JSONResponse(status_code=response.status_code, content={"error": response.text})

app.include_router(router)


@app.post("/tts-chat")
async def tts_chat(payload: dict = Body(...)):
    """
    Chat geçmişini sese çevirir.
    Beklenen payload formatı:
    {
        "messages": [
            {"role": "user", "content": "Selam"},
            {"role": "assistant", "content": "Merhaba! Size nasıl yardımcı olabilirim?"}
        ]
    }
    """
    messages = payload.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="Chat mesajları eksik.")

    # Mesajları birleştir
    combined_text = ""
    for msg in messages:
        if msg["role"] == "user":
            combined_text += f"Sen: {msg['content']}\n"
        elif msg["role"] == "assistant":
            combined_text += f"{msg['content']}\n"  # "Asistan:" eklenmedi

    print("[/tts-chat] 🔊 Toplam metin uzunluğu:", len(combined_text))
    print("[/tts-chat] 📜 İlk 300 karakter:\n", combined_text[:300])

    # ElevenLabs endpoint'i
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{TTS_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }

    body = {
        "text": combined_text[:4000],  # 4000 karakter sınırı
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.4,
            "similarity_boost": 0.75
        }
    }

    try:
        response = requests.post(url, headers=headers, json=body)

        if response.status_code == 200:
            audio_bytes = response.content
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            print("[/tts-chat] ✅ Başarıyla ses üretildi.")
            return {"audio_base64": audio_base64}
        else:
            print("[/tts-chat] ❌ Hata:", response.text)
            raise HTTPException(status_code=response.status_code, detail=response.text)

    except Exception as e:
        print("[/tts-chat] ❗️ Exception:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/audio-isolation")
async def audio_isolation(data: dict = Body(...)):
    """
    Kullanıcıdan gelen base64 ses verisini arka plan gürültüsünden arındırır.
    Dönüş olarak temizlenmiş base64 ses verir.
    """
    print("[/audio-isolation] 🎧 İstek alındı.")

    base64_audio = data.get("base64")
    if not base64_audio:
        raise HTTPException(status_code=400, detail="Ses verisi (base64) eksik.")

    try:
        print("[/audio-isolation] 📥 Base64 decode ediliyor...")
        audio_bytes = base64.b64decode(base64_audio)
        print(f"[/audio-isolation] ✅ Ses dosyası decode edildi, boyut: {len(audio_bytes)} byte")

        # Multipart form veri oluştur
        files = {
            "file": ("input.m4a", audio_bytes, "audio/m4a")
        }

        headers = {
            "xi-api-key": ELEVENLABS_API_KEY
        }

        print("[/audio-isolation] 🧼 ElevenLabs Audio Isolation API'ye istek gönderiliyor...")
        response = requests.post(
            "https://api.elevenlabs.io/v1/audio/isolate",
            headers=headers,
            files=files
        )

        print(f"[/audio-isolation] 🧾 Yanıt kodu: {response.status_code}")

        if response.status_code == 200:
            isolated_audio = response.content
            audio_base64 = base64.b64encode(isolated_audio).decode("utf-8")
            print("[/audio-isolation] ✅ Gürültüsüz ses başarıyla elde edildi.")
            return {"audio_base64": audio_base64}
        else:
            print("[/audio-isolation] ❌ API hatası:", response.text)
            raise HTTPException(status_code=response.status_code, detail=response.text)

    except Exception as e:
        print("[/audio-isolation] ❗️ Hata:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


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
    return { "full_text": summary }


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
    return { "full_text": summary }


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
    return { "full_text": response.choices[0].message.content }


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
