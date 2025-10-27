import uuid
import aiohttp
from fastapi import HTTPException
from main import app, client, DEFAULT_MODEL, save_embeddings_to_firebase
from fastapi import Body


@app.post("/summarize-excel-url/")
async def summarize_excel_from_url(data: dict = Body(...)):
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
            "content": "Aşağıdaki Excel verilerini analiz et ve anlamlı bir özet çıkar:",
        }, {
            "role": "user",
            "content": description
        }]
    )
    summary = response.choices[0].message.content

    # Embedding kaydı
    file_id = str(uuid.uuid4())
    user_id = data.get("user_id")
    chat_id = data.get("chat_id")
    save_embeddings_to_firebase(user_id, chat_id, file_id, description, summary, "XLSX")

    return { "summary": summary, "full_text": description, "file_id": file_id }
