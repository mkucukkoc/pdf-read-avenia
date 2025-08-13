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
from fastapi import FastAPI, UploadFile, HTTPException, Body, Form, APIRouter ,Query
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
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import JSONResponse
from openai import OpenAI
import os


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
# ----------------------------------------------------
# TTS: Chat geçmişini sese çevir (OpenAI tts-1)
# ----------------------------------------------------
# ----------------------------------------------------
# Audio Isolation (lokal): hafif denoise + filtreleme
# ----------------------------------------------------
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
    Sadece yüzde, kalite ve NSFW bilgisini veren sade ama akıcı Türkçe özet.
    'Güven seviyesi' yorumu eklenmez.
    """
    report = data.get("report", {}) or {}
    facets = data.get("facets", {}) or {}

    verdict = report.get("verdict")
    ai_conf = float((report.get("ai", {}) or {}).get("confidence", 0.0) or 0.0)
    human_conf = float((report.get("human", {}) or {}).get("confidence", 0.0) or 0.0)

    if verdict == "ai":
        pct = round(ai_conf * 100)
        base = f"İnceleme sonunda görselin %{pct} ihtimalle yapay zekâ tarafından oluşturulduğu anlaşılıyor."
    elif verdict == "human":
        pct = round(human_conf * 100)
        base = f"İnceleme sonunda görselin %{pct} ihtimalle insan tarafından oluşturulduğu anlaşılıyor."
    else:
        base = "Görselin kaynağı net olarak belirlenemedi."

    quality_good = (facets.get("quality", {}) or {}).get("is_detected", True)
    nsfw_flag = (facets.get("nsfw", {}) or {}).get("is_detected", False)

    quality_part = "Görüntü kalitesi genel olarak iyi; belirgin bir bozulma ya da yapısal sorun yok." \
        if quality_good else "Görüntüde kalite sorunları veya bozulmalar tespit edildi."
    nsfw_part = "NSFW kontrolü açısından da olumsuz bir durum tespit edilmediği görülüyor." \
        if not nsfw_flag else "NSFW taramasında uygunsuz içerik tespit edildi."

    return f"{base} {quality_part} {nsfw_part}"

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

import endpoints.generate_video
import endpoints.generate_video_prompt
import endpoints.summarize_pdf
import endpoints.ask_pdf_question
import endpoints.ask_file_question
import endpoints.summarize_pdf_url
import endpoints.generate_doc
import endpoints.generate_excel
import endpoints.generate_ppt
import endpoints.audio_isolation
import endpoints.stt
import endpoints.tts_chat
import endpoints.summarize_excel_url
import endpoints.summarize_word_url
import endpoints.summarize_ppt_url
import endpoints.summarize_html_url
import endpoints.summarize_json_url
import endpoints.summarize_csv_url
import endpoints.summarize_txt_url
import endpoints.ask_with_embeddings
import endpoints.search_docs
import endpoints.healthz
import endpoints.analyze_image
import endpoints.image_caption

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)
