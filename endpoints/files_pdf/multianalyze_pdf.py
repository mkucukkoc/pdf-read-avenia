import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from errors_response import get_pdf_error_message
from endpoints.helper_fail_response import build_success_error_response
from schemas import PdfMultiAnalyzeRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_pdf.multianalyze")

router = APIRouter(prefix="/api/v1/files/pdf", tags=["FilesPDF"])


@router.post("/multianalyze")
async def multianalyze_pdf(payload: PdfMultiAnalyzeRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    language = normalize_language(payload.language) or "English"
    log_full_payload(logger, "pdf_multianalyze", payload)
    logger.info(
        "PDF multianalyze request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileCount": len(payload.file_urls)},
    )

    gemini_key = os.getenv("GEMINI_API_KEY")
    effective_model = os.getenv("GEMINI_PDF_MODEL") or "gemini-2.5-flash"

    try:
        parts = []
        try:
            for i, url in enumerate(payload.file_urls):
                logger.info("PDF multianalyze download start", extra={"chatId": payload.chat_id, "url": url})
                content, mime = download_file(url, max_mb=30, require_pdf=True)
                file_uri = upload_to_gemini_files(content, mime, f"doc_{i}.pdf", gemini_key)
                parts.append({"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}})
        except HTTPException as he:
            return build_success_error_response(
                tool="pdf_multianalyze",
                language=language,
                chat_id=payload.chat_id,
                user_id=user_id,
                status_code=he.status_code,
                detail=he.detail,
            )
        except Exception as exc:
            return build_success_error_response(
                tool="pdf_multianalyze",
                language=language,
                chat_id=payload.chat_id,
                user_id=user_id,
                status_code=500,
                detail=str(exc),
            )

        prompt = (payload.prompt or "").strip() or f"Analyze these multiple PDFs together in {language} and provide a combined synthesis."
        parts.append({"text": f"Language: {language}"})
        parts.append({"text": prompt})

        text, stream_message_id = await generate_text_with_optional_stream(
            parts=parts,
            api_key=gemini_key,
            stream=bool(payload.stream),
            chat_id=payload.chat_id,
            tool="pdf_multianalyze",
            model=effective_model,
            chunk_metadata={"language": language},
            followup_language=language,
        )
        if not text:
            raise RuntimeError("Empty response from Gemini")
        logger.info("PDF multianalyze gemini response | chatId=%s preview=%s", payload.chat_id, text[:500])

        base_payload = {
            "success": True,
            "chatId": payload.chat_id,
            "analysis": text,
            "language": language,
            "model": effective_model,
        }
        result = attach_streaming_payload(
            base_payload,
            tool="pdf_multianalyze",
            content=text,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "analysis": text,
                "language": language,
                "model": effective_model,
            },
        )

        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=text,
            metadata={
                "tool": "pdf_multianalyze",
                "fileUrls": payload.file_urls,
            },
            stream_message_id=stream_message_id,
        )
        if firestore_ok:
            logger.info("PDF multianalyze Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("PDF multianalyze Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        logger.error("PDF multianalyze HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        return build_success_error_response(
            tool="pdf_multianalyze",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=hexc.status_code,
            detail=hexc.detail,
        )
    except Exception as exc:
        logger.error("PDF multianalyze failed", exc_info=exc)
        return build_success_error_response(
            tool="pdf_multianalyze",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=500,
            detail=str(exc),
        )
