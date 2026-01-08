import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from core.word_to_pdf import convert_word_bytes_to_pdf_bytes
from errors_response import get_pdf_error_message
from endpoints.helper_fail_response import build_success_error_response
from schemas import DocCompareRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_word.compare")

router = APIRouter(prefix="/api/v1/files/word", tags=["FilesWord"])

_WORD_MIME_FALLBACK = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_WORD_MIME_ALLOWED = {
    _WORD_MIME_FALLBACK,
    "application/msword",
    "application/vnd.ms-word",
    "application/vnd.ms-word.document.macroEnabled.12",
}


def _validate_word_mime(mime: str) -> str:
    if not mime:
        return _WORD_MIME_FALLBACK
    mime = mime.split(";")[0].strip()
    if mime.lower() in _WORD_MIME_ALLOWED:
        return mime
    if "word" in mime.lower():
        return mime
    raise HTTPException(
        status_code=400,
        detail={"success": False, "error": "invalid_file_type", "message": get_pdf_error_message("invalid_file_url", None)},
    )


def _download_and_convert(file_url: str, file_name: str | None, max_mb: int) -> tuple[bytes, str]:
    content, mime = download_file(file_url, max_mb=max_mb, require_pdf=False)
    mime = _validate_word_mime(mime)
    is_pdf = mime.lower().startswith("application/pdf")
    if is_pdf:
        return content, file_name or "document.pdf"
    suffix = ".docx"
    if file_name and "." in file_name:
        suffix = "." + file_name.split(".")[-1]
    pdf_bytes, pdf_filename = convert_word_bytes_to_pdf_bytes(content, suffix=suffix)
    return pdf_bytes, pdf_filename or file_name or "document.pdf"


@router.post("/compare")
async def compare_word(payload: DocCompareRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    raw_language = payload.language
    language = normalize_language(raw_language) or "English"
    log_full_payload(logger, "word_compare", payload)
    logger.info(
        "Word compare request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )

    try:
        logger.info("Word compare download start file1", extra={"chatId": payload.chat_id, "fileUrl": payload.file1})
        try:
            pdf1_bytes, pdf1_name = _download_and_convert(payload.file1, payload.file_name, max_mb=30)
            logger.info("Word compare download start file2", extra={"chatId": payload.chat_id, "fileUrl": payload.file2})
            pdf2_bytes, pdf2_name = _download_and_convert(payload.file2, payload.file_name, max_mb=30)
        except HTTPException as he:
            return build_success_error_response(
                tool="word_compare",
                language=language,
                chat_id=payload.chat_id,
                user_id=user_id,
                status_code=he.status_code,
                detail=he.detail,
            )
        except Exception as exc:
            return build_success_error_response(
                tool="word_compare",
                language=language,
                chat_id=payload.chat_id,
                user_id=user_id,
                status_code=500,
                detail=str(exc),
            )

        gemini_key = os.getenv("GEMINI_API_KEY")
        effective_model = payload.model or os.getenv("GEMINI_PDF_MODEL") or "gemini-2.5-flash"

        file_uri_1 = upload_to_gemini_files(pdf1_bytes, "application/pdf", pdf1_name, gemini_key)
        file_uri_2 = upload_to_gemini_files(pdf2_bytes, "application/pdf", pdf2_name, gemini_key)
        logger.info(
            "Word compare upload ok",
            extra={"chatId": payload.chat_id, "fileUri1": file_uri_1, "fileUri2": file_uri_2},
        )

        prompt = (payload.prompt or "").strip() or f"Compare these two documents in {language} and list the differences."
        parts = [
            {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri_1}},
            {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri_2}},
            {"text": prompt},
        ]
        text, stream_message_id = await generate_text_with_optional_stream(
            parts=parts,
            api_key=gemini_key,
            stream=bool(payload.stream),
            chat_id=payload.chat_id,
            tool="word_compare",
            model=effective_model,
            chunk_metadata={"language": language},
            followup_language=language,
        )
        if not text:
            raise RuntimeError("Empty response from Gemini")
        logger.info(
            "Word compare gemini response | chatId=%s preview=%s",
            payload.chat_id,
            text[:500],
        )

        base_payload = {
            "success": True,
            "chatId": payload.chat_id,
            "comparison": text,
            "language": language,
            "model": effective_model,
        }
        result = attach_streaming_payload(
            base_payload,
            tool="word_compare",
            content=text,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "comparison": text,
                "language": language,
                "model": effective_model,
            },
        )

        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=text,
            metadata={
                "tool": "word_compare",
                "file1": payload.file1,
                "file2": payload.file2,
                "fileName": payload.file_name,
            },
            client_message_id=getattr(payload, "client_message_id", None),
            stream_message_id=stream_message_id,
        )
        if firestore_ok:
            logger.info("Word compare Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("Word compare Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        logger.error("Word compare HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        return build_success_error_response(
            tool="word_compare",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=hexc.status_code,
            detail=hexc.detail,
        )
    except Exception as exc:
        logger.error("Word compare failed", exc_info=exc)
        return build_success_error_response(
            tool="word_compare",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=500,
            detail=str(exc),
        )

