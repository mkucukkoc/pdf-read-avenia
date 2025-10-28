import os
import tempfile
import uuid
from fastapi import HTTPException
from main import app, client, DEFAULT_MODEL, DocRequest, storage
from openpyxl import Workbook


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
