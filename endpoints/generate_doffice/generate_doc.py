import logging
import os
import tempfile
import uuid
from fastapi import HTTPException
from main import app, client, DEFAULT_MODEL, DocRequest, storage
from docx import Document

logger = logging.getLogger("pdf_read_refresh.endpoints.generate_doc")


@app.post("/generate-doc")
async def generate_doc(data: DocRequest):
    logger.info("Generate doc request received", extra={"prompt_length": len(data.prompt)})
    try:
        logger.debug("Requesting GPT completion for doc", extra={"prompt": data.prompt[:300]})
        completion = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[{"role": "user", "content": data.prompt}],
            max_completion_tokens=1500
        )
        generated_text = completion.choices[0].message.content.strip()
        logger.info("GPT content generated", extra={"text_length": len(generated_text)})
        logger.debug("Generated text preview", extra={"preview": generated_text[:300]})

        logger.debug("Building Word document from generated text")
        doc = Document()
        doc.add_heading('Avenia Belgesi', 0)
        for i, paragraph in enumerate(generated_text.split("\n")):
            cleaned = paragraph.strip()
            if cleaned:
                doc.add_paragraph(cleaned)
                logger.debug("Added paragraph", extra={"index": i + 1, "content_preview": cleaned[:100]})

        temp_path = tempfile.gettempdir()
        filename = f"generated_{uuid.uuid4().hex}.docx"
        filepath = os.path.join(temp_path, filename)
        doc.save(filepath)
        logger.info("Temporary Word file saved", extra={"filepath": filepath})

        logger.info("Uploading document to Firebase Storage")
        bucket = storage.bucket()
        blob = bucket.blob(f"generated_docs/{filename}")
        blob.upload_from_filename(filepath)
        blob.make_public()
        logger.info("Firebase upload completed", extra={"file_url": blob.public_url})

        response_payload = {"status": "success", "file_url": blob.public_url}
        logger.debug("Generate doc response payload", extra={"response": response_payload})
        return response_payload

    except Exception as e:
        logger.exception("Generate doc failed")
        raise HTTPException(status_code=500, detail=str(e))







