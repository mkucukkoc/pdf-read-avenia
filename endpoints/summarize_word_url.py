import uuid
import aiohttp
from fastapi import HTTPException
from fastapi import Body
from main import app, client, DEFAULT_MODEL, extract_text_from_docx, save_embeddings_to_firebase


@app.post("/summarize-word-url/")
async def summarize_word_from_url(data: dict = Body(...)):

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
