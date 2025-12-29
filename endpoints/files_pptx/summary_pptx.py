import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from errors_response import get_pdf_error_message
from schemas import PptxSummaryRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_pptx.summary")

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


@router.post("/summary")
async def summary_pptx(payload: PptxSummaryRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    raw_language = payload.language
    language = normalize_language(raw_language) or "English"
    log_full_payload(logger, "pptx_summary", payload)
    logger.info(
        "PPTX summary request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )

    logger.info("PPTX summary download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    content, mime = download_file(payload.file_url, max_mb=30, require_pdf=False)
    mime = _validate_pptx_mime(mime)
    logger.info("PPTX summary download ok", extra={"chatId": payload.chat_id, "size": len(content), "mime": mime})

    gemini_key = os.getenv("GEMINI_API_KEY")
    effective_model = payload.model if hasattr(payload, "model") else None
    effective_model = effective_model or os.getenv("GEMINI_PPTX_MODEL") or os.getenv("GEMINI_PDF_MODEL") or "gemini-2.5-flash"

    prompt = (payload.prompt or "").strip() or f"Summarize this presentation in {language} with key sections and bullets."
    logger.debug(
        "PPTX summary prompt | chatId=%s userId=%s lang=%s level=%s prompt=%s",
        payload.chat_id,
        user_id,
        language,
        payload.summary_level or "basic",
        prompt,
    )
    try:
        logger.info("PPTX summary upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(content, mime, payload.file_name or "slides.pptx", gemini_key)
        logger.info("PPTX summary upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        # Gemini stream endpoint Office MIME (pptx) için destek vermiyor; stream kapalı.
        streaming_enabled = False
        text, stream_message_id = await generate_text_with_optional_stream(
            parts=[
                {"file_data": {"mime_type": mime, "file_uri": file_uri}},
                {"text": prompt},
            ],
            api_key=gemini_key,
            stream=streaming_enabled,
            chat_id=payload.chat_id,
            tool="pptx_summary",
            model=effective_model,
            chunk_metadata={
                "language": language,
                "summaryLevel": payload.summary_level or "basic",
            },
        )
        if not text:
            raise RuntimeError("Empty response from Gemini")
        logger.info(
            "PPTX summary gemini response | chatId=%s preview=%s",
            payload.chat_id,
            text[:500],
        )

        extra_fields = {
            "success": True,
            "chatId": payload.chat_id,
            "summary": text,
            "language": language,
            "model": effective_model,
            "summaryLevel": payload.summary_level or "basic",
        }
        result = attach_streaming_payload(
            extra_fields,
            tool="pptx_summary",
            content=text,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "summary": text,
                "language": language,
                "model": effective_model,
                "summaryLevel": payload.summary_level or "basic",
            },
        )

        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=text,
            metadata={
                "tool": "pptx_summary",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
                "summaryLevel": payload.summary_level or "basic",
            },
        )
        if firestore_ok:
            logger.info("PPTX summary Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("PPTX summary Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        msg = hexc.detail.get("message") if isinstance(hexc.detail, dict) else str(hexc.detail)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pptx_summary", "error": hexc.detail},
            )
        logger.error("PPTX summary HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        raise
    except Exception as exc:
        logger.error("PPTX summary failed", exc_info=exc)
        msg = get_pdf_error_message("pdf_summary_failed", language)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pptx_summary", "error": str(exc)},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "pptx_summary_failed", "message": msg},
        ) from exc


