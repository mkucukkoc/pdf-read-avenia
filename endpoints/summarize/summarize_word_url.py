import logging
import uuid
import aiohttp
from fastapi import HTTPException
from fastapi import Body
from main import app, client, DEFAULT_MODEL, extract_text_from_docx, save_embeddings_to_firebase

logger = logging.getLogger("pdf_read_refresh.endpoints.summarize_word_url")


@app.post("/summarize-word-url/")
async def summarize_word_from_url(data: dict = Body(...)):
    url = data.get("url")
    logger.info("Summarize Word URL request received", extra={"url": url})
    if not url:
        logger.warning("URL missing for Word summary")
        raise HTTPException(status_code=400, detail="URL not provided")

    file_path = "temp.docx"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                logger.error("Failed to download Word file", extra={"status": resp.status})
                raise HTTPException(status_code=500, detail=f"Dosya indirilemedi: {resp.status}")
            with open(file_path, "wb") as f:
                f.write(await resp.read())
    logger.info("Word file downloaded", extra={"file_path": file_path})

    full_text = extract_text_from_docx(file_path)
    logger.debug(
        "Extracted Word text",
        extra={"preview": full_text[:300], "length": len(full_text)},
    )

    if not full_text.strip():
        logger.warning("Word file text empty")
        raise HTTPException(status_code=500, detail="❌ Word içeriği boş")

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "Lütfen aşağıdaki Word belgesini özetle:"},
            {"role": "user", "content": full_text[:3000]},
        ],
    )
    summary = response.choices[0].message.content
    logger.info("Word summary generated", extra={"summary_length": len(summary)})

    file_id = str(uuid.uuid4())
    user_id = data.get("user_id")
    chat_id = data.get("chat_id")
    save_embeddings_to_firebase(user_id, chat_id, file_id, full_text, summary, "DOCX")

    response_payload = {
        "summary": summary,
        "full_text": full_text,
        "file_id": file_id,
    }
    logger.debug("Summarize Word response payload", extra={"response": response_payload})
    return response_payload









