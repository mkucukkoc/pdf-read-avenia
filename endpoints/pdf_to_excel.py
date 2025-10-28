import os
import io
import uuid
import tempfile
from fastapi import UploadFile, HTTPException
from main import app, storage
from pypdf import PdfReader
from openpyxl import Workbook


@app.post("/pdf-to-excel")
async def pdf_to_excel(file: UploadFile):
    """Convert an uploaded PDF file to an Excel workbook and return a Firebase URL."""
    try:
        pdf_bytes = await file.read()
        reader = PdfReader(io.BytesIO(pdf_bytes))

        wb = Workbook()
        ws = wb.active
        row = 1
        for page in reader.pages:
            text = page.extract_text() or ""
            for line in text.split("\n"):
                cleaned = line.strip()
                if cleaned:
                    ws.cell(row=row, column=1, value=cleaned)
                    row += 1

        temp_dir = tempfile.gettempdir()
        filename = f"converted_{uuid.uuid4().hex}.xlsx"
        filepath = os.path.join(temp_dir, filename)
        wb.save(filepath)

        bucket = storage.bucket()
        blob = bucket.blob(f"converted_excels/{filename}")
        blob.upload_from_filename(filepath)
        blob.make_public()

        return {"status": "success", "file_url": blob.public_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
