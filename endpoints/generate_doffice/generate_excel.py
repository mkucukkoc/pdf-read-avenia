import logging
import os
import tempfile
import uuid
from fastapi import HTTPException
from main import app, client, DEFAULT_MODEL, DocRequest, storage
from openpyxl import Workbook

logger = logging.getLogger("pdf_read_refresh.endpoints.generate_excel")


@app.post("/generate-excel")
async def generate_excel(data: DocRequest):
    logger.info("Generate excel request received", extra={"prompt_length": len(data.prompt)})
    try:
        logger.debug("Requesting GPT completion for excel", extra={"prompt": data.prompt[:300]})
        completion = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[{"role": "user", "content": data.prompt}],
            max_completion_tokens=1500
        )
        generated_text = completion.choices[0].message.content.strip()
        logger.info("GPT content generated for excel", extra={"text_length": len(generated_text)})
        logger.debug("Generated text preview for excel", extra={"preview": generated_text[:300]})

        logger.debug("Building Excel workbook")
        wb = Workbook()
        ws = wb.active
        ws.title = "Avenia"

        for i, line in enumerate(generated_text.split("\n")):
            cleaned_line = line.strip()
            if cleaned_line:
                ws.cell(row=i + 1, column=1, value=cleaned_line)
                logger.debug(
                    "Added Excel row",
                    extra={"row": i + 1, "content_preview": cleaned_line[:100]},
                )

        temp_path = tempfile.gettempdir()
        filename = f"generated_{uuid.uuid4().hex}.xlsx"
        filepath = os.path.join(temp_path, filename)
        wb.save(filepath)
        logger.info("Temporary Excel file saved", extra={"filepath": filepath})

        logger.info("Uploading Excel to Firebase Storage")
        bucket = storage.bucket()
        blob = bucket.blob(f"generated_excels/{filename}")
        blob.upload_from_filename(filepath)
        blob.make_public()
        logger.info("Firebase upload completed", extra={"file_url": blob.public_url})

        response_payload = {"status": "success", "file_url": blob.public_url}
        logger.debug("Generate excel response payload", extra={"response": response_payload})
        return response_payload

    except Exception as e:
        logger.exception("Generate excel failed")
        raise HTTPException(status_code=500, detail=str(e))



