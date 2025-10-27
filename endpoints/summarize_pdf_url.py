from io import BytesIO
import uuid

import requests
from fastapi import Body, HTTPException
from fastapi.responses import JSONResponse
from pypdf import PdfReader

from main import app, ask_gpt_summary, save_embeddings_to_firebase


@app.post("/summarize-pdf-url")
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
