from fastapi import Form, HTTPException
from fastapi.responses import JSONResponse
from main import app, client, DEFAULT_MODEL


@app.post("/ask-file-question/")
async def ask_file_question(
    file_text: str = Form(...),
    question: str = Form(...),
    file_type: str = Form(default="genel")  # örnek: 'PDF', 'Word', 'Excel', 'PPT'
):
    print("[/ask-file-question] 🧠 Soru geldi:", question)
    print("[/ask-file-question] 📄 Dosya tipi:", file_type)
    print("[/ask-file-question] 📄 İçerik uzunluğu:", len(file_text))

    prompt = f"""\nAşağıda bir {file_type.upper()} dosyasının içeriği bulunmaktadır. Kullanıcı bu içeriğe dayanarak bir soru sordu.\n\nLütfen sadece verilen içerikten yararlanarak doğru, detaylı ve anlaşılır bir cevap ver.\n\n📄 Dosya içeriği:\n\"\"\"\n{file_text[:4000]}\n\"\"\"\n\n❓ Soru:\n\"\"\"\n{question}\n\"\"\"\n\n💬 Cevap:\n"""

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
