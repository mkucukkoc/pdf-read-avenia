import uuid
import aiohttp
from fastapi import HTTPException
from fastapi import Body
from main import app, client, DEFAULT_MODEL, save_embeddings_to_firebase


@app.post("/summarize-txt-url/")
async def summarize_txt_from_url(data: dict = Body(...)):
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
        ],
    )

    # Embedding kaydı
    file_id = str(uuid.uuid4())

    user_id = data.get("user_id")
    chat_id = data.get("chat_id")
    save_embeddings_to_firebase(user_id, chat_id, file_id, text, summary, "TXT")

    return { "summary": summary, "full_text": content, "file_id": file_id }
