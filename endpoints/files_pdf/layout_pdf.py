import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from errors_response import get_pdf_error_message
from schemas import PdfLayoutRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_pdf.layout")

router = APIRouter(prefix="/api/v1/files/pdf", tags=["FilesPDF"])


@router.post("/layout")
async def layout_pdf(payload: PdfLayoutRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    language = normalize_language(payload.language) or "English"
    log_full_payload(logger, "pdf_layout", payload)
    logger.info(
        "PDF layout request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )

    logger.info("PDF layout download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    content, mime = download_file(payload.file_url, max_mb=30, require_pdf=True)
    logger.info("PDF layout download ok", extra={"chatId": payload.chat_id, "size": len(content), "mime": mime})
    gemini_key = os.getenv("GEMINI_API_KEY")

    prompt = (
        payload.prompt
        or "Analyze the PDF layout. Return JSON with headings[], paragraphs[], tables[], images[], graphs[] and pageMap[]. "
        f"Use {language} descriptions and keep coordinates if available."
    ).strip()

    try:
        logger.info("PDF layout upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(content, mime, payload.file_name or "document.pdf", gemini_key)
        logger.info("PDF layout upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        layout, stream_message_id = await generate_text_with_optional_stream(
            parts=[
                {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
                {"text": f"Language: {language}"},
                {"text": prompt},
            ],
            api_key=gemini_key,
            stream=bool(payload.stream),
            chat_id=payload.chat_id,
            tool="pdf_layout",
            chunk_metadata={"language": language},
        )
        if not layout:
            raise RuntimeError("Empty response from Gemini")
        logger.info("PDF layout gemini response | chatId=%s preview=%s", payload.chat_id, layout[:500])

        extra_fields = {
            "success": True,
            "chatId": payload.chat_id,
            "layout": layout,
            "language": language,
            "model": "gemini-2.5-flash",
        }
        result = attach_streaming_payload(
            extra_fields,
            tool="pdf_layout",
            content=layout,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "layout": layout,
                "language": language,
                "model": "gemini-2.5-flash",
            },
        )

        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=layout,
            metadata={
                "tool": "pdf_layout",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
            },
        )
        if firestore_ok:
            logger.info("PDF layout Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("PDF layout Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        msg = hexc.detail.get("message") if isinstance(hexc.detail, dict) else str(hexc.detail)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_layout", "error": hexc.detail},
            )
        logger.error("PDF layout HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        raise
    except Exception as exc:
        logger.error("PDF layout failed", exc_info=exc)
        msg = get_pdf_error_message("pdf_layout_failed", language)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_layout", "error": str(exc)},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "pdf_layout_failed", "message": msg},
        ) from exc


