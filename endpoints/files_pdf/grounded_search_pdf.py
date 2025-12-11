import logging
import os
import asyncio
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from errors_response import get_pdf_error_message
from schemas import PdfGroundedSearchRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    call_gemini_generate,
    extract_text_response,
    save_message_to_firestore,
    log_full_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_pdf.grounded_search")

router = APIRouter(prefix="/api/v1/files/pdf", tags=["FilesPDF"])


@router.post("/grounded_search")
async def grounded_search_pdf(payload: PdfGroundedSearchRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    language = normalize_language(payload.language) or "English"
    log_full_payload(logger, "pdf_grounded_search", payload)
    logger.info(
        "PDF grounded search request",
        extra={
            "chatId": payload.chat_id,
            "userId": user_id,
            "language": language,
            "fileName": payload.file_name,
        },
    )

    logger.info("PDF grounded search download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    content, mime = download_file(payload.file_url, max_mb=30, require_pdf=True)
    logger.info("PDF grounded search download ok", extra={"chatId": payload.chat_id, "size": len(content), "mime": mime})
    gemini_key = os.getenv("GEMINI_API_KEY")

    question = (payload.question or "").strip()
    prompt = (
        payload.prompt
        or f"Answer the user's question using the PDF and verify claims with external knowledge if possible. "
        f"Provide citations or page references. If uncertain, say so. Respond in {language}. Question: {question}"
    ).strip()

    try:
        logger.info("PDF grounded search upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(content, mime, payload.file_name or "document.pdf", gemini_key)
        logger.info("PDF grounded search upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        response_json = await asyncio.to_thread(
            call_gemini_generate,
            [
                {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
                {"text": f"Language: {language}"},
                {"text": prompt},
            ],
            gemini_key,
        )
        answer = extract_text_response(response_json)
        if not answer:
            raise RuntimeError("Empty response from Gemini")
        logger.info("PDF grounded search gemini response | chatId=%s preview=%s", payload.chat_id, answer[:500])

        result = {
            "success": True,
            "chatId": payload.chat_id,
            "answer": answer,
            "language": language,
            "model": "gemini-2.5-flash",
        }

        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=answer,
            metadata={
                "tool": "pdf_grounded_search",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
                "question": question,
            },
        )
        if firestore_ok:
            logger.info("PDF grounded search Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("PDF grounded search Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        msg = hexc.detail.get("message") if isinstance(hexc.detail, dict) else str(hexc.detail)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_grounded_search", "error": hexc.detail},
            )
        logger.error("PDF grounded search HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        raise
    except Exception as exc:
        logger.error("PDF grounded search failed", exc_info=exc)
        msg = get_pdf_error_message("pdf_grounded_search_failed", language)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_grounded_search", "error": str(exc)},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "pdf_grounded_search_failed", "message": msg},
        ) from exc


