import logging
import os
import asyncio
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from schemas import PdfExtractRequest
from errors_response import get_pdf_error_message
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    call_gemini_generate,
    extract_text_response,
    save_message_to_firestore,
)

logger = logging.getLogger("pdf_read_refresh.files_pdf.extract")

router = APIRouter(prefix="/api/v1/files/pdf", tags=["FilesPDF"])


EXTRACT_PROMPT = """
Extract structured insights from this PDF and present them as Markdown bullet lists:
- Tables & Key Values
- Numbers with context and units
- Important entities (name, role, context)
- Definitions of key concepts
- Important dates with descriptions
- Emails (if any) with surrounding context
- Document headings/sections
- Detected metadata (title, author, etc.)

For each section, use clear headings and bullet points. Write the entire response in {language}. Do not return JSON.
"""


@router.post("/extract")
async def extract_pdf(payload: PdfExtractRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    raw_language = payload.language
    language = normalize_language(raw_language) or "English"
    logger.info(
        "PDF extract request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )

    logger.info("PDF extract download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    content, mime = download_file(payload.file_url, max_mb=30, require_pdf=True)
    logger.info("PDF extract download ok", extra={"chatId": payload.chat_id, "size": len(content), "mime": mime})
    gemini_key = os.getenv("GEMINI_API_KEY")

    prompt = EXTRACT_PROMPT.replace("{language}", language)
    try:
        logger.info("PDF extract upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(content, mime, payload.file_name or "document.pdf", gemini_key)
        logger.info("PDF extract upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        response_json = await asyncio.to_thread(
            call_gemini_generate,
            [
                {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
                {"text": f"Language: {language}"},
                {"text": prompt},
            ],
            gemini_key,
        )
        extracted = extract_text_response(response_json)
        if not extracted:
            raise RuntimeError("Empty response from Gemini")
        logger.info(
            "PDF extract gemini response",
            extra={"chatId": payload.chat_id, "preview": extracted[:500]},
        )

        result = {
            "success": True,
            "chatId": payload.chat_id,
            "data": extracted,
            "language": language,
            "model": "gemini-2.5-flash",
        }

        save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=extracted,
            metadata={
                "tool": "pdf_extract",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
            },
        )
        return result
    except HTTPException as hexc:
        msg = hexc.detail.get("message") if isinstance(hexc.detail, dict) else str(hexc.detail)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_extract", "error": hexc.detail},
            )
        logger.error("PDF extract HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        raise
    except Exception as exc:
        logger.error("PDF extract failed", exc_info=exc)
        msg = get_pdf_error_message("pdf_extract_failed", language)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_extract", "error": str(exc)},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "pdf_extract_failed", "message": msg},
        ) from exc

