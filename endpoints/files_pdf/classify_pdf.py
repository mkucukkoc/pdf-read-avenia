import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from errors_response import get_pdf_error_message
from schemas import PdfClassifyRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_pdf.classify")

router = APIRouter(prefix="/api/v1/files/pdf", tags=["FilesPDF"])


@router.post("/classify")
async def classify_pdf(payload: PdfClassifyRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    language = normalize_language(payload.language) or "English"
    log_full_payload(logger, "pdf_classify", payload)
    logger.info(
        "PDF classify request",
        extra={
            "chatId": payload.chat_id,
            "userId": user_id,
            "language": language,
            "fileName": payload.file_name,
        },
    )

    logger.info("PDF classify download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    content, mime = download_file(payload.file_url, max_mb=25, require_pdf=True)
    logger.info("PDF classify download ok", extra={"chatId": payload.chat_id, "size": len(content), "mime": mime})
    gemini_key = os.getenv("GEMINI_API_KEY")
    effective_model = payload.model or os.getenv("GEMINI_PDF_MODEL") or "gemini-2.5-flash"

    label_candidates = payload.labels or [
        "contract",
        "invoice",
        "report",
        "article",
        "resume / cv",
        "technical document",
        "form",
        "presentation",
        "other",
    ]
    label_text = ", ".join(label_candidates)
    base_prompt = (
        payload.prompt
        or f"Classify this PDF in {language}. Allowed labels: {label_text}. "
        "Return a short JSON with fields label, confidence (0-1), and rationale."
    ).strip()

    try:
        logger.info("PDF classify upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(content, mime, payload.file_name or "document.pdf", gemini_key)
        logger.info("PDF classify upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        classification, stream_message_id = await generate_text_with_optional_stream(
            parts=[
                {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
                {"text": f"Language: {language}"},
                {"text": base_prompt},
            ],
            api_key=gemini_key,
            stream=bool(payload.stream),
            chat_id=payload.chat_id,
            tool="pdf_classify",
            model=effective_model,
            chunk_metadata={
                "language": language,
                "labels": label_candidates,
            },
        )
        if not classification:
            raise RuntimeError("Empty response from Gemini")
        logger.info("PDF classify gemini response | chatId=%s preview=%s", payload.chat_id, classification[:500])

        extra_fields = {
            "success": True,
            "chatId": payload.chat_id,
            "classification": classification,
            "language": language,
            "model": effective_model,
        }
        result = attach_streaming_payload(
            extra_fields,
            tool="pdf_classify",
            content=classification,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "classification": classification,
                "language": language,
                "model": effective_model,
            },
        )

        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=classification,
            metadata={
                "tool": "pdf_classify",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
                "labels": label_candidates,
            },
        )
        if firestore_ok:
            logger.info("PDF classify Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("PDF classify Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        msg = hexc.detail.get("message") if isinstance(hexc.detail, dict) else str(hexc.detail)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_classify", "error": hexc.detail},
            )
        logger.error("PDF classify HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        raise
    except Exception as exc:
        logger.error("PDF classify failed", exc_info=exc)
        msg = get_pdf_error_message("pdf_classify_failed", language)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_classify", "error": str(exc)},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "pdf_classify_failed", "message": msg},
        ) from exc


