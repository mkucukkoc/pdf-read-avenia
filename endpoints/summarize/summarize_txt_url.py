import logging
import uuid

import aiohttp
from fastapi import Body, HTTPException

from main import app, client, DEFAULT_MODEL, save_embeddings_to_firebase

logger = logging.getLogger("pdf_read_refresh.endpoints.summarize_txt_url")


@app.post("/summarize-txt-url/")
async def summarize_txt_from_url(data: dict = Body(...)):
    url = data.get("url")
    logger.info("Summarize TXT URL request received", extra={"url": url})
    if not url:
        logger.warning("TXT URL missing")
        raise HTTPException(status_code=400, detail="URL not provided")

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            content = await resp.text()
    logger.debug("Fetched TXT content", extra={"length": len(content)})

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "Aşağıdaki metni özetle:"},
            {"role": "user", "content": content[:3000]},
        ],
    )
    summary = response.choices[0].message.content
    logger.info("TXT summary generated", extra={"summary_length": len(summary)})

    file_id = str(uuid.uuid4())
    user_id = data.get("user_id")
    chat_id = data.get("chat_id")

    if user_id and chat_id:
        save_embeddings_to_firebase(user_id, chat_id, file_id, content, summary, "TXT")

    response_payload = {"summary": summary, "full_text": content, "file_id": file_id}
    logger.debug("Summarize TXT response payload", extra={"response": response_payload})
    return response_payload









