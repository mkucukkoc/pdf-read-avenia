import logging
import os
import io
import uuid
import tempfile
from fastapi import UploadFile, HTTPException
from main import app, storage
from pypdf import PdfReader
from docx import Document

logger = logging.getLogger("pdf_read_refresh.endpoints.pdf_to_word")


@app.post("/pdf-to-word")
async def pdf_to_word(file: UploadFile):
    """Convert an uploaded PDF file to a DOCX document and return a Firebase URL."""
    logger.info(
        "PDF to Word request",
        extra={"filename": getattr(file, "filename", None), "content_type": getattr(file, "content_type", None)},
    )
    try:
        pdf_bytes = await file.read()
        reader = PdfReader(io.BytesIO(pdf_bytes))

        doc = Document()
        page_count = len(reader.pages)
        logger.debug("PDF page count", extra={"pages": page_count})
        for idx, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            logger.debug("Extracted page text", extra={"page": idx, "length": len(text)})
            for line in text.split("\n"):
                cleaned = line.strip()
                if cleaned:
                    doc.add_paragraph(cleaned)

        temp_dir = tempfile.gettempdir()
        filename = f"converted_{uuid.uuid4().hex}.docx"
        filepath = os.path.join(temp_dir, filename)
        doc.save(filepath)
        logger.info("DOCX saved", extra={"path": filepath})

        bucket = storage.bucket()
        blob = bucket.blob(f"converted_docs/{filename}")
        blob.upload_from_filename(filepath)
        blob.make_public()
        logger.info("Uploaded DOCX to Firebase", extra={"url": blob.public_url})

        response = {"status": "success", "file_url": blob.public_url}
        logger.debug("PDF to Word response", extra={"response": response})
        return response
    except Exception as e:
        logger.exception("PDF to Word failed")
        raise HTTPException(status_code=500, detail=str(e))









