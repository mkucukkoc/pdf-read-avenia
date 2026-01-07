import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from core.word_to_pdf import convert_word_bytes_to_pdf_bytes
from errors_response import get_pdf_error_message
from endpoints.helper_fail_response import build_success_error_response
from schemas import PptxExtractRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_pptx.extract")

router = APIRouter(prefix="/api/v1/files/pptx", tags=["FilesPPTX"])

_PPTX_MIME_FALLBACK = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_PPTX_MIME_ALLOWED = {
    _PPTX_MIME_FALLBACK,
    "application/vnd.ms-powerpoint",
    "application/vnd.ms-powerpoint.presentation.macroEnabled.12",
}


def _validate_pptx_mime(mime: str) -> str:
    if not mime:
        return _PPTX_MIME_FALLBACK
    mime = mime.split(";")[0].strip()
    if mime.lower() in _PPTX_MIME_ALLOWED:
        return mime
    if "presentation" in mime.lower() or "powerpoint" in mime.lower() or "ppt" in mime.lower():
        return mime
    raise HTTPException(
        status_code=400,
        detail={"success": False, "error": "invalid_file_type", "message": get_pdf_error_message("invalid_file_url", None)},
    )


@router.post("/extract")
async def extract_pptx(payload: PptxExtractRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    raw_language = payload.language
    language = normalize_language(raw_language) or "English"
    log_full_payload(logger, "pptx_extract", payload)
    logger.info(
        "PPTX extract request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )

    logger.info("PPTX extract download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    try:
        content, mime = download_file(payload.file_url, max_mb=30, require_pdf=False)
        mime = _validate_pptx_mime(mime)
    except HTTPException as he:
        return build_success_error_response(
            tool="pptx_extract",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=he.status_code,
            detail=he.detail,
        )
    except Exception as exc:
        return build_success_error_response(
            tool="pptx_extract",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=500,
            detail=str(exc),
        )
    logger.info("PPTX extract download ok", extra={"chatId": payload.chat_id, "size": len(content), "mime": mime})

    is_pdf = mime.lower().startswith("application/pdf")
    if is_pdf:
        pdf_bytes = content
        pdf_filename = payload.file_name or "slides.pdf"
    else:
        suffix = ".pptx"
        if payload.file_name and "." in payload.file_name:
            suffix = "." + payload.file_name.split(".")[-1]
        try:
            pdf_bytes, pdf_filename = convert_word_bytes_to_pdf_bytes(content, suffix=suffix)
        except Exception as exc:
            return build_success_error_response(
                tool="pptx_extract",
                language=language,
                chat_id=payload.chat_id,
                user_id=user_id,
                status_code=500,
                detail=str(exc),
            )

    gemini_key = os.getenv("GEMINI_API_KEY")
    effective_model = payload.model or os.getenv("GEMINI_PDF_MODEL") or "gemini-2.5-flash"

    prompt = (payload.prompt or "").strip() or f"Extract key information from this presentation in {language}."
    logger.debug(
        "PPTX extract prompt | chatId=%s userId=%s lang=%s prompt=%s",
        payload.chat_id,
        user_id,
        language,
        prompt,
    )
    try:
        logger.info("PPTX extract upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(pdf_bytes, "application/pdf", pdf_filename, gemini_key)
        logger.info("PPTX extract upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        parts = [
            {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
            {"text": prompt},
        ]
        text, stream_message_id = await generate_text_with_optional_stream(
            parts=parts,
            api_key=gemini_key,
            stream=bool(payload.stream),
            chat_id=payload.chat_id,
            tool="pptx_extract",
            model=effective_model,
            chunk_metadata={
                "language": language,
            },
        )
        if not text:
            raise RuntimeError("Empty response from Gemini")
        logger.info(
            "PPTX extract gemini response | chatId=%s preview=%s",
            payload.chat_id,
            text[:500],
        )

        extra_fields = {
            "success": True,
            "chatId": payload.chat_id,
            "extraction": text,
            "language": language,
            "model": effective_model,
        }
        result = attach_streaming_payload(
            extra_fields,
            tool="pptx_extract",
            content=text,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "extraction": text,
                "language": language,
                "model": effective_model,
            },
        )
        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=text,
            metadata={
                "tool": "pptx_extract",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
            },
        )
        if firestore_ok:
            logger.info("PPTX extract Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("PPTX extract Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        logger.error("PPTX extract HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        return build_success_error_response(
            tool="pptx_extract",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=hexc.status_code,
            detail=hexc.detail,
        )
    except Exception as exc:
        logger.error("PPTX extract failed", exc_info=exc)
        return build_success_error_response(
            tool="pptx_extract",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=500,
            detail=str(exc),
        )

