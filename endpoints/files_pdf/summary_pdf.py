import logging
import os
import asyncio
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from errors_response import get_pdf_error_message
from schemas import PdfSummaryRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    call_gemini_generate,
    extract_text_response,
    save_message_to_firestore,
)

logger = logging.getLogger("pdf_read_refresh.files_pdf.summary")

router = APIRouter(prefix="/api/v1/files/pdf", tags=["FilesPDF"])


SUMMARY_PROMPT_TEMPLATE = """
You are a PDF summarizer. Produce a concise summary with three levels:
- Basic: 3-5 bullet points.
- Professional: 5-8 bullet points with key metrics/figures.
- Expert: structured paragraph with context, implications, risks.
Also include:
- Keywords (5-10)
- Document structure (sections/headings)
- If tables exist: brief table insights.
- If figures exist: brief visual insights.
Return Markdown text with sections:
## Basic
...
## Professional
...
## Expert
...
## Keywords
- ...
## Structure
- ...
## Tables
- ...
## Figures
- ...
Adjust language to: {language}
"""


@router.post("/summary")
async def summary_pdf(payload: PdfSummaryRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    language = payload.language
    logger.info(
        "PDF summary request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )

    logger.info("PDF summary download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    content, mime = download_file(payload.file_url, max_mb=20, require_pdf=True)
    logger.info("PDF summary download ok", extra={"chatId": payload.chat_id, "size": len(content), "mime": mime})
    gemini_key = os.getenv("GEMINI_API_KEY")

    prompt = SUMMARY_PROMPT_TEMPLATE.format(language=language or "English")
    try:
        logger.info("PDF summary upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(content, mime, payload.file_name or "document.pdf", gemini_key)
        logger.info("PDF summary upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        response_json = await asyncio.to_thread(
            call_gemini_generate,
            [
                {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
                {"text": prompt},
            ],
            gemini_key,
        )
        text = extract_text_response(response_json)
        if not text:
            raise RuntimeError("Empty response from Gemini")
        logger.info(
            "PDF summary gemini response",
            extra={"chatId": payload.chat_id, "preview": text[:500]},
        )

        result = {
            "success": True,
            "chatId": payload.chat_id,
            "summary": text,
            "language": language,
            "model": "gemini-2.5-flash",
            "summaryLevel": payload.summary_level or "basic",
        }

        save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=text,
            metadata={
                "tool": "pdf_summary",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
                "summaryLevel": payload.summary_level or "basic",
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
                metadata={"tool": "pdf_summary", "error": hexc.detail},
            )
        logger.error("PDF summary HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        raise
    except Exception as exc:
        logger.error("PDF summary failed", exc_info=exc)
        msg = get_pdf_error_message("pdf_summary_failed", language)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_summary", "error": str(exc)},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "pdf_summary_failed", "message": msg},
        ) from exc

