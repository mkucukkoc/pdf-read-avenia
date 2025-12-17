import logging
import uuid
import aiohttp
from fastapi import HTTPException
from fastapi import Body
from main import app, client, DEFAULT_MODEL, save_embeddings_to_firebase

logger = logging.getLogger("pdf_read_refresh.endpoints.summarize_excel_url")


@app.post("/summarize-excel-url/")
async def summarize_excel_from_url(data: dict = Body(...)):
    url = data.get("url")
    logger.info("Summarize Excel URL request received", extra={"url": url})
    if not url:
        logger.warning("URL missing in summarize Excel request")
        raise HTTPException(status_code=400, detail="URL not provided")

    file_path = "temp.xlsx"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                logger.error("Failed to download Excel file", extra={"status": resp.status})
                raise HTTPException(status_code=resp.status, detail="Failed to download Excel")
            with open(file_path, "wb") as f:
                f.write(await resp.read())
    logger.info("Excel file downloaded", extra={"file_path": file_path})

    import pandas as pd
    df = pd.read_excel(file_path)
    description = df.describe(include="all").to_string()
    logger.debug("Excel description generated", extra={"length": len(description)})

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {
                "role": "system",
                "content": "Aşağıdaki Excel verilerini analiz et ve anlamlı bir özet çıkar:",
            },
            {"role": "user", "content": description},
        ],
    )
    summary = response.choices[0].message.content
    logger.info("GPT summary generated for Excel", extra={"summary_length": len(summary)})

    file_id = str(uuid.uuid4())
    user_id = data.get("user_id")
    chat_id = data.get("chat_id")
    save_embeddings_to_firebase(user_id, chat_id, file_id, description, summary, "XLSX")

    response_payload = {
        "summary": summary,
        "full_text": description,
        "file_id": file_id,
    }
    logger.debug("Summarize Excel response", extra={"response": response_payload})
    return response_payload









