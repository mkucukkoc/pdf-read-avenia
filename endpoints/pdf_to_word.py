import os
import io
import uuid
import tempfile
from fastapi import UploadFile, HTTPException
from main import app, storage
from pypdf import PdfReader
from docx import Document


@app.post("/pdf-to-word")
async def pdf_to_word(file: UploadFile):
    """Convert an uploaded PDF file to a DOCX document and return a Firebase URL."""
    try:
        # Read uploaded PDF bytes
        pdf_bytes = await file.read()
        reader = PdfReader(io.BytesIO(pdf_bytes))

        # Create Word document from PDF text
        doc = Document()
        for page in reader.pages:
            text = page.extract_text() or ""
            for line in text.split("\n"):
                cleaned = line.strip()
                if cleaned:
                    doc.add_paragraph(cleaned)

        # Save to a temporary DOCX file
        temp_dir = tempfile.gettempdir()
        filename = f"converted_{uuid.uuid4().hex}.docx"
        filepath = os.path.join(temp_dir, filename)
        doc.save(filepath)

        # Upload to Firebase Storage
        bucket = storage.bucket()
        blob = bucket.blob(f"converted_docs/{filename}")
        blob.upload_from_filename(filepath)
        blob.make_public()

        return {"status": "success", "file_url": blob.public_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
