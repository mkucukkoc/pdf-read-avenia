import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from core.word_to_pdf import convert_word_bytes_to_pdf_bytes
from errors_response import get_pdf_error_message
from schemas import PptxCompareRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_pptx.compare")

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


def _download_and_convert(file_url: str, file_name: str | None, max_mb: int) -> tuple[bytes, str]:
    content, mime = download_file(file_url, max_mb=max_mb, require_pdf=False)
    mime = _validate_pptx_mime(mime)
    is_pdf = mime.lower().startswith("application/pdf")
    if is_pdf:
        return content, file_name or "slides.pdf"
    suffix = ".pptx"
    if file_name and "." in file_name:
        suffix = "." + file_name.split(".")[-1]
    pdf_bytes, pdf_filename = convert_word_bytes_to_pdf_bytes(content, suffix=suffix)
    return pdf_bytes, pdf_filename or file_name or "slides.pdf"


@router.post("/compare")
async def compare_pptx(payload: PptxCompareRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    raw_language = payload.language
    language = normalize_language(raw_language) or "English"
    log_full_payload(logger, "pptx_compare", payload)
    logger.info(
        "PPTX compare request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )

    try:
        logger.info("PPTX compare download start file1", extra={"chatId": payload.chat_id, "fileUrl": payload.file1})
        pdf1_bytes, pdf1_name = _download_and_convert(payload.file1, payload.file_name, max_mb=30)
        logger.info("PPTX compare download start file2", extra={"chatId": payload.chat_id, "fileUrl": payload.file2})
        pdf2_bytes, pdf2_name = _download_and_convert(payload.file2, payload.file_name, max_mb=30)

        gemini_key = os.getenv("GEMINI_API_KEY")
        effective_model = payload.model or os.getenv("GEMINI_PDF_MODEL") or "gemini-2.5-flash"

        file_uri_1 = upload_to_gemini_files(pdf1_bytes, "application/pdf", pdf1_name, gemini_key)
        file_uri_2 = upload_to_gemini_files(pdf2_bytes, "application/pdf", pdf2_name, gemini_key)
        logger.info(
            "PPTX compare upload ok",
            extra={"chatId": payload.chat_id, "fileUri1": file_uri_1, "fileUri2": file_uri_2},
        )

        prompt = (payload.prompt or "").strip() or f"Compare these two presentations in {language} and list the differences."
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
            tool="pptx_compare",
            model=effective_model,
            chunk_metadata={"language": language},
        )
        if not text:
            raise RuntimeError("Empty response from Gemini")
        logger.info(
            "PPTX compare gemini response | chatId=%s preview=%s",
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
            tool="pptx_compare",
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
                "tool": "pptx_compare",
                "file1": payload.file1,
                "file2": payload.file2,
                "fileName": payload.file_name,
            },
        )
        if firestore_ok:
            logger.info("PPTX compare Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("PPTX compare Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("PPTX compare failed", exc_info=exc)
        msg = get_pdf_error_message("pdf_compare_failed", language)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pptx_compare", "error": str(exc)},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "pptx_compare_failed", "message": msg},
        ) from exc

