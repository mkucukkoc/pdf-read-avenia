import logging
import os
import io
import uuid
import tempfile
from fastapi import UploadFile, HTTPException
from main import app, storage
from pypdf import PdfReader
from openpyxl import Workbook

logger = logging.getLogger("pdf_read_refresh.endpoints.pdf_to_excel")


@app.post("/pdf-to-excel")
async def pdf_to_excel(file: UploadFile):
    """Convert an uploaded PDF file to an Excel workbook and return a Firebase URL."""
    logger.info(
        "PDF to Excel request",
        extra={"filename": getattr(file, "filename", None), "content_type": getattr(file, "content_type", None)},
    )
    try:
        pdf_bytes = await file.read()
        reader = PdfReader(io.BytesIO(pdf_bytes))

        wb = Workbook()
        ws = wb.active
        row = 1
        for idx, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            logger.debug("Extracted text for page", extra={"page": idx, "length": len(text)})
            for line in text.split("\n"):
                cleaned = line.strip()
                if cleaned:
                    ws.cell(row=row, column=1, value=cleaned)
                    row += 1

        temp_dir = tempfile.gettempdir()
        filename = f"converted_{uuid.uuid4().hex}.xlsx"
        filepath = os.path.join(temp_dir, filename)
        wb.save(filepath)
        logger.info("Workbook saved", extra={"path": filepath})

        bucket = storage.bucket()
        blob = bucket.blob(f"converted_excels/{filename}")
        blob.upload_from_filename(filepath)
        blob.make_public()
        logger.info("Uploaded Excel to Firebase", extra={"url": blob.public_url})

        response = {"status": "success", "file_url": blob.public_url}
        logger.debug("PDF to Excel response", extra={"response": response})
        return response
    except Exception as e:
        logger.exception("PDF to Excel failed")
        raise HTTPException(status_code=500, detail=str(e))




