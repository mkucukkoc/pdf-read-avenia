import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from errors_response import get_pdf_error_message
from endpoints.helper_fail_response import build_success_error_response
from schemas import PdfExtractRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    build_usage_context,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_pdf.extract")

router = APIRouter(prefix="/api/v1/files/pdf", tags=["FilesPDF"])


@router.post("/extract")
async def extract_pdf(payload: PdfExtractRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    language = normalize_language(payload.language) or "English"
    log_full_payload(logger, "pdf_extract", payload)
    logger.info(
        "PDF extract request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )

    logger.info("PDF extract download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    try:
        content, mime = download_file(payload.file_url, max_mb=40, require_pdf=True)
    except HTTPException as he:
        return build_success_error_response(
            tool="pdf_extract",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=he.status_code,
            detail=he.detail,
        )
    except Exception as exc:
        return build_success_error_response(
            tool="pdf_extract",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=500,
            detail=str(exc),
        )
    logger.info("PDF extract download ok", extra={"chatId": payload.chat_id, "size": len(content), "mime": mime})
    gemini_key = os.getenv("GEMINI_API_KEY")
    effective_model = payload.model or os.getenv("GEMINI_PDF_MODEL") or "gemini-2.5-flash"

    prompt = (
        payload.prompt
        or f"Extract all key information from this PDF. Respond in {language} with a clean structured summary."
    ).strip()

    try:
        logger.info("PDF extract upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(content, mime, payload.file_name or "document.pdf", gemini_key)
        logger.info("PDF extract upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        usage_context = build_usage_context(
            request=request,
            user_id=user_id,
            endpoint="extract_pdf",
            model=effective_model,
            payload=payload,
        )
        extraction, stream_message_id = await generate_text_with_optional_stream(
            parts=[
                {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
                {"text": f"Language: {language}"},
                {"text": prompt},
            ],
            api_key=gemini_key,
            stream=bool(payload.stream),
            chat_id=payload.chat_id,
            tool="pdf_extract",
            model=effective_model,
            chunk_metadata={"language": language},
            tone_key=payload.tone_key,
            tone_language=language,
            followup_language=language,
            usage_context=usage_context,
        )
        if not extraction:
            raise RuntimeError("Empty response from Gemini")
        logger.info("PDF extract gemini response | chatId=%s preview=%s", payload.chat_id, extraction[:500])

        extra_fields = {
            "success": True,
            "chatId": payload.chat_id,
            "extraction": extraction,
            "language": language,
            "model": effective_model,
        }
        result = attach_streaming_payload(
            extra_fields,
            tool="pdf_extract",
            content=extraction,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "extraction": extraction,
                "language": language,
                "model": effective_model,
            },
        )

        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=extraction,
            metadata={
                "tool": "pdf_extract",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
            },
            stream_message_id=stream_message_id,
        )
        if firestore_ok:
            logger.info("PDF extract Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("PDF extract Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        logger.error("PDF extract HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        return build_success_error_response(
            tool="pdf_extract",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=hexc.status_code,
            detail=hexc.detail,
        )
    except Exception as exc:
        logger.error("PDF extract failed", exc_info=exc)
        return build_success_error_response(
            tool="pdf_extract",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=500,
            detail=str(exc),
        )
