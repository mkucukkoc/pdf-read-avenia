import os
import io
import uuid
import tempfile
from fastapi import UploadFile, HTTPException
from main import app, storage
from docx import Document
from fpdf import FPDF


@app.post("/word-to-pdf")
async def word_to_pdf(file: UploadFile):
    """Convert an uploaded DOCX file to PDF and return a Firebase URL."""
    try:
        doc_bytes = await file.read()
        document = Document(io.BytesIO(doc_bytes))

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        for para in document.paragraphs:
            pdf.multi_cell(0, 10, para.text)

        temp_dir = tempfile.gettempdir()
        filename = f"converted_{uuid.uuid4().hex}.pdf"
        filepath = os.path.join(temp_dir, filename)
        pdf.output(filepath)

        bucket = storage.bucket()
        blob = bucket.blob(f"converted_pdfs/{filename}")
        blob.upload_from_filename(filepath)
        blob.make_public()

        return {"status": "success", "file_url": blob.public_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
