import logging
import os
from fastapi import UploadFile, HTTPException
from fastapi.responses import JSONResponse
from main import app, extract_text_from_pdf, ask_gpt_summary

logger = logging.getLogger("pdf_read_refresh.endpoints.summarize_pdf")


@app.post("/summarize")
async def summarize_pdf(file: UploadFile):
    logger.info("Summarize PDF request received", extra={"filename": file.filename})
    temp_path = f"temp_{file.filename}"
    try:
        logger.debug("Saving uploaded PDF temporarily", extra={"temp_path": temp_path})
        with open(temp_path, "wb") as f:
            f.write(await file.read())

        logger.debug("Extracting text from PDF")
        text = extract_text_from_pdf(temp_path)

        logger.debug("Requesting GPT summary", extra={"text_length": len(text)})
        summary = ask_gpt_summary(text)

        os.remove(temp_path)
        logger.info("Temporary file cleaned up", extra={"temp_path": temp_path})

        response_payload = {"summary": summary, "full_text": text}
        logger.debug("Summarize response payload", extra={"response": response_payload})

        return JSONResponse(content=response_payload)
    except Exception as e:
        logger.exception("Summarize PDF failed")
        raise HTTPException(status_code=500, detail=str(e))


