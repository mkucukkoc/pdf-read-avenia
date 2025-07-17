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
from docx import Document
from pydantic import BaseModel
import firebase_admin
from firebase_admin import credentials, storage
from openpyxl import Workbook
from pptx import Presentation
import uuid
import tempfile
import firebase_admin
from firebase_admin import credentials, storage
import base64
import datetime
from pptx.util import Inches
from pptx.dml.color import RGBColor
import os, uuid, datetime, tempfile, requests
from fastapi import HTTPException
from google.cloud import storage



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

class DocRequest(BaseModel):
    prompt: str

@app.post("/generate-doc")
async def generate_doc(data: DocRequest):
    print("[/generate-doc] 📝 İstek alındı.")
    try:
        # 1. GPT'den içerik al
        print("[/generate-doc] 🧠 GPT'den içerik alınıyor...")
        completion = client.chat.completions.create(
            model="gpt-4",
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
            model="gpt-4",
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

@app.post("/generate-ppt")
async def generate_ppt(data: DocRequest):
    print("[/generate-ppt] 🌟 Sunum isteği alındı.")
    try:
        print("[/generate-ppt] 🧬 GPT'den prompt formatında sunum metni isteniyor...")
        completion = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": """Sen bir sunum üreticisisin. Her slaytı şu formatta ver:
# Slide X
Title: ...
Content: ...
Image: (Bu başlıkla ilgili kısa bir sahne betimlemesi örn: "kitap okuyan bir kadın", "modern ofis manzarası")"""
                },
                {"role": "user", "content": data.prompt}
            ],
            max_tokens=1500
        )
        generated_text = completion.choices[0].message.content.strip()
        print("[/generate-ppt] 📚 GPT metni alındı. Uzunluk:", len(generated_text))

        # Prompt'u parse et
        slides = parse_ppt_prompt(generated_text)
        print(f"[/generate-ppt] ✅ {len(slides)} slayt parse edildi.")

        prs = Presentation()

        # Açılış slaytı
        splash = prs.slides.add_slide(prs.slide_layouts[0])
        splash.shapes.title.text = f"📊 {data.prompt[:60]}..."
        splash.placeholders[1].text = "Bu sunum Avenia tarafından otomatik üretildi."

        for i, slide in enumerate(slides):
            print(f"[/generate-ppt] 📄 Slayt {i+1}: {slide['title'][:50]}...")
            s = prs.slides.add_slide(prs.slide_layouts[6])  # boş şablon

            # 🎨 Arka plan rengi
            fill = s.background.fill
            fill.solid()
            fill.fore_color.rgb = RGBColor(245, 245, 245)

            # 🔤 Başlık
            title_box = s.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(8), Inches(1))
            tf = title_box.text_frame
            tf.text = slide['title']
            tf.paragraphs[0].font.size = Pt(32)
            tf.paragraphs[0].font.bold = True
            tf.paragraphs[0].font.name = 'Segoe UI'
            tf.paragraphs[0].font.color.rgb = RGBColor(91, 55, 183)

            # 🕓 Tarih (sağ üst)
            date_box = s.shapes.add_textbox(Inches(8), Inches(0.1), Inches(2), Inches(0.3))
            dtf = date_box.text_frame
            dtf.text = datetime.datetime.now().strftime("%d %B %Y")
            dtf.paragraphs[0].font.size = Pt(12)
            dtf.paragraphs[0].font.name = 'Calibri'
            dtf.paragraphs[0].font.color.rgb = RGBColor(160, 160, 160)

            # 🖼 Logo (sol alt köşe)
            logo_path = "avenia_logo.png"
            if os.path.exists(logo_path):
                try:
                    s.shapes.add_picture(logo_path, Inches(0.1), Inches(5.3), height=Inches(0.5))
                except Exception as e:
                    print(f"[/generate-ppt] ⚠️ Logo eklenemedi: {e}")

            # 📘 İçerik (sol)
            if slide['content']:
                left_content = Inches(0.5)
                top_content = Inches(1.5)
                width_content = Inches(4.5)
                height_content = Inches(4)
                content_box = s.shapes.add_textbox(left_content, top_content, width_content, height_content)
                ctf = content_box.text_frame
                ctf.text = slide['content']
                for p in ctf.paragraphs:
                    p.font.size = Pt(18)
                    p.font.name = 'Calibri'
                    p.font.color.rgb = RGBColor(80, 80, 80)

            # 🎨 Görsel (sağ)
            if slide['image']:
                try:
                    dalle_response = client.images.generate(
                        model="dall-e-3",
                        prompt=slide['image'],
                        n=1,
                        size="1024x1024"
                    )
                    image_url = dalle_response.data[0].url
                    print(f"[/generate-ppt] 📸 Görsel URL alındı: {image_url}")

                    image_data = requests.get(image_url).content
                    image_path = os.path.join(tempfile.gettempdir(), f"image_{uuid.uuid4().hex}.png")
                    with open(image_path, "wb") as f:
                        f.write(image_data)

                    left_img = Inches(5.2)
                    top_img = Inches(1.5)
                    height_img = Inches(3.5)
                    s.shapes.add_picture(image_path, left_img, top_img, height=height_img)
                    print("[/generate-ppt] 📊 Görsel slayta eklendi.")
                except Exception as e:
                    print("[/generate-ppt] ❌ Görsel oluşturulamadı:", str(e))

        filename = f"generated_{uuid.uuid4().hex}.pptx"
        filepath = os.path.join(tempfile.gettempdir(), filename)
        prs.save(filepath)
        print(f"[/generate-ppt] 📂 Sunum dosyası kaydedildi: {filepath}")

        bucket = storage.bucket()
        blob = bucket.blob(f"generated_ppts/{filename}")
        blob.upload_from_filename(filepath)
        blob.make_public()
        print("[/generate-ppt] ☁️ Firebase'e yüklendi. URL:", blob.public_url)

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
