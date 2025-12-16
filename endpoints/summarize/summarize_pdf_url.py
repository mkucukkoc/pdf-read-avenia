import logging
from io import BytesIO
import uuid

import requests
from fastapi import Body, HTTPException
from fastapi.responses import JSONResponse
from pypdf import PdfReader

from main import app, ask_gpt_summary, save_embeddings_to_firebase

logger = logging.getLogger("pdf_read_refresh.endpoints.summarize_pdf_url")


@app.post("/summarize-pdf-url")
async def summarize_pdf_url(payload: dict = Body(...)):
    url = payload.get("url")
    logger.info("Summarize PDF URL request received", extra={"url": url})
    if not url:
        logger.warning("PDF URL missing in request")
        raise HTTPException(status_code=400, detail="PDF URL gerekli")

    try:
        logger.debug("Downloading PDF", extra={"url": url})
        response = requests.get(url)
        if response.status_code != 200:
            logger.error("Failed to download PDF", extra={"status_code": response.status_code})
            raise HTTPException(status_code=400, detail="PDF indirilemedi")

        pdf_bytes = response.content
        reader = PdfReader(BytesIO(pdf_bytes))

        all_text = ""
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            char_count = len(page_text) if page_text else 0
            logger.debug(
                "Extracted PDF page text",
                extra={"page": i + 1, "char_count": char_count},
            )
            if page_text:
                all_text += page_text + "\n"

        text = all_text[:4000]  # sadece ilk kısmı al
        logger.debug("Requesting GPT summary", extra={"text_length": len(text)})

        summary = ask_gpt_summary(text)

        user_id = payload.get("user_id")
        chat_id = payload.get("chat_id")

        file_id = str(uuid.uuid4())
        save_embeddings_to_firebase(user_id, chat_id, file_id, text, summary, "PDF")

        response_payload = {
            "summary": summary,
            "full_text": text,
            "file_id": file_id,
        }
        logger.info("Summarize PDF URL succeeded", extra={"file_id": file_id})
        logger.debug("Summarize PDF URL response payload", extra={"response": response_payload})

        return JSONResponse(content=response_payload)

    except Exception as e:
        logger.exception("Summarize PDF URL failed")
        raise HTTPException(status_code=500, detail=str(e))








