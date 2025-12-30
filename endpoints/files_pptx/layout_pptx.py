import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from core.word_to_pdf import convert_word_bytes_to_pdf_bytes
from errors_response import get_pdf_error_message
from schemas import PptxLayoutRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_pptx.layout")

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


@router.post("/layout")
async def layout_pptx(payload: PptxLayoutRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    raw_language = payload.language
    language = normalize_language(raw_language) or "English"
    log_full_payload(logger, "pptx_layout", payload)
    logger.info(
        "PPTX layout request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )

    logger.info("PPTX layout download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    content, mime = download_file(payload.file_url, max_mb=30, require_pdf=False)
    mime = _validate_pptx_mime(mime)
    logger.info("PPTX layout download ok", extra={"chatId": payload.chat_id, "size": len(content), "mime": mime})

    is_pdf = mime.lower().startswith("application/pdf")
    if is_pdf:
        pdf_bytes = content
        pdf_filename = payload.file_name or "slides.pdf"
    else:
        suffix = ".pptx"
        if payload.file_name and "." in payload.file_name:
            suffix = "." + payload.file_name.split(".")[-1]
        pdf_bytes, pdf_filename = convert_word_bytes_to_pdf_bytes(content, suffix=suffix)

    gemini_key = os.getenv("GEMINI_API_KEY")
    effective_model = payload.model or os.getenv("GEMINI_PDF_MODEL") or "gemini-2.5-flash"

    prompt_text = (payload.prompt or "").strip() or f"Describe the layout and structure of this presentation in {language}."
    logger.debug(
        "PPTX layout prompt | chatId=%s userId=%s lang=%s prompt=%s",
        payload.chat_id,
        user_id,
        language,
        prompt_text,
    )
    try:
        logger.info("PPTX layout upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(pdf_bytes, "application/pdf", pdf_filename, gemini_key)
        logger.info("PPTX layout upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        parts = [
            {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
            {"text": prompt_text},
        ]
        text, stream_message_id = await generate_text_with_optional_stream(
            parts=parts,
            api_key=gemini_key,
            stream=bool(payload.stream),
            chat_id=payload.chat_id,
            tool="pptx_layout",
            model=effective_model,
            chunk_metadata={
                "language": language,
            },
        )
        if not text:
            raise RuntimeError("Empty response from Gemini")
        logger.info(
            "PPTX layout gemini response | chatId=%s preview=%s",
            payload.chat_id,
            text[:500],
        )

        extra_fields = {
            "success": True,
            "chatId": payload.chat_id,
            "layout": text,
            "language": language,
            "model": effective_model,
        }
        result = attach_streaming_payload(
            extra_fields,
            tool="pptx_layout",
            content=text,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "layout": text,
                "language": language,
                "model": effective_model,
            },
        )
        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=text,
            metadata={
                "tool": "pptx_layout",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
            },
        )
        if firestore_ok:
            logger.info("PPTX layout Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("PPTX layout Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        msg = hexc.detail.get("message") if isinstance(hexc.detail, dict) else str(hexc.detail)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pptx_layout", "error": hexc.detail},
            )
        logger.error("PPTX layout HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        raise
    except Exception as exc:
        logger.error("PPTX layout failed", exc_info=exc)
        msg = get_pdf_error_message("pdf_layout_failed", language)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pptx_layout", "error": str(exc)},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "pptx_layout_failed", "message": msg},
        ) from exc

