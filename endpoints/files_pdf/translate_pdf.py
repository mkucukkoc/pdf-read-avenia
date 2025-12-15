import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from errors_response import get_pdf_error_message
from schemas import PdfTranslateRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_pdf.translate")

router = APIRouter(prefix="/api/v1/files/pdf", tags=["FilesPDF"])


@router.post("/translate")
async def translate_pdf(payload: PdfTranslateRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    target_language = normalize_language(payload.target_language) or "English"
    source_language = normalize_language(payload.source_language) or "auto"
    log_full_payload(logger, "pdf_translate", payload)
    logger.info(
        "PDF translate request",
        extra={
            "chatId": payload.chat_id,
            "userId": user_id,
            "targetLanguage": target_language,
            "sourceLanguage": source_language,
            "fileName": payload.file_name,
        },
    )

    logger.info("PDF translate download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    content, mime = download_file(payload.file_url, max_mb=35, require_pdf=True)
    logger.info("PDF translate download ok", extra={"chatId": payload.chat_id, "size": len(content), "mime": mime})
    gemini_key = os.getenv("GEMINI_API_KEY")

    prompt = (
        payload.prompt
        or f"Translate the PDF from {source_language} to {target_language}. Keep structure, headings, lists, and tables. "
        "Return clear translated text; use markdown where helpful."
    ).strip()

    try:
        logger.info("PDF translate upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(content, mime, payload.file_name or "document.pdf", gemini_key)
        logger.info("PDF translate upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        translation, stream_message_id = await generate_text_with_optional_stream(
            parts=[
                {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
                {"text": f"Target language: {target_language}"},
                {"text": prompt},
            ],
            api_key=gemini_key,
            stream=bool(payload.stream),
            chat_id=payload.chat_id,
            tool="pdf_translate",
            chunk_metadata={
                "targetLanguage": target_language,
                "sourceLanguage": source_language,
            },
        )
        if not translation:
            raise RuntimeError("Empty response from Gemini")
        logger.info("PDF translate gemini response | chatId=%s preview=%s", payload.chat_id, translation[:500])

        extra_fields = {
            "success": True,
            "chatId": payload.chat_id,
            "translation": translation,
            "targetLanguage": target_language,
            "model": "gemini-2.5-flash",
        }
        result = attach_streaming_payload(
            extra_fields,
            tool="pdf_translate",
            content=translation,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "translation": translation,
                "targetLanguage": target_language,
                "sourceLanguage": source_language,
                "model": "gemini-2.5-flash",
            },
        )

        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=translation,
            metadata={
                "tool": "pdf_translate",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
                "targetLanguage": target_language,
                "sourceLanguage": source_language,
            },
        )
        if firestore_ok:
            logger.info("PDF translate Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("PDF translate Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        msg = hexc.detail.get("message") if isinstance(hexc.detail, dict) else str(hexc.detail)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_translate", "error": hexc.detail},
            )
        logger.error("PDF translate HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        raise
    except Exception as exc:
        logger.error("PDF translate failed", exc_info=exc)
        msg = get_pdf_error_message("pdf_translate_failed", target_language)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_translate", "error": str(exc)},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "pdf_translate_failed", "message": msg},
        ) from exc


