from fastapi import Form, HTTPException
from fastapi.responses import JSONResponse
from main import app, client, DEFAULT_MODEL


@app.post("/ask-question")
async def ask_pdf_question(pdf_text: str = Form(...), question: str = Form(...)):
    print("[/ask-question] 🤖 Soru alındı:", question)
    print("[/ask-question] 📄 PDF metni uzunluğu:", len(pdf_text))

    prompt = f"""\nSen PDF belgesi içeriğini analiz eden bir asistansın. Kullanıcının sorusu aşağıda. Sadece PDF içeriğine dayanarak cevap ver:\n\n📄 PDF içeriği:\n\"\"\"\n{pdf_text[:4000]}\n\"\"\"\n\n❓ Soru:\n{question}\n\n💬 Cevabın:\n"""

    try:
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "Sen uzman bir PDF içeriği analistisin, sadece verilen içerikten faydalan."},
                {"role": "user", "content": prompt}
            ]
        )
        answer = response.choices[0].message.content.strip()
        print("[/ask-question] ✅ Yanıt alındı:", answer)
        return JSONResponse(content={"answer": answer})

    except Exception as e:
        print("[/ask-question] ❌ Hata:", str(e))
        raise HTTPException(status_code=500, detail=str(e))
