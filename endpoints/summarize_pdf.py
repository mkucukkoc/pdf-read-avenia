import os
from fastapi import UploadFile, HTTPException
from fastapi.responses import JSONResponse
from main import app, extract_text_from_pdf, ask_gpt_summary


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
