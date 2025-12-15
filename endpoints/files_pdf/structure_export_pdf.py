import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from errors_response import get_pdf_error_message
from schemas import PdfStructureExportRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_pdf.structure_export")

router = APIRouter(prefix="/api/v1/files/pdf", tags=["FilesPDF"])


@router.post("/structure_export")
async def structure_export_pdf(payload: PdfStructureExportRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    language = normalize_language(payload.language) or "English"
    log_full_payload(logger, "pdf_structure_export", payload)
    logger.info(
        "PDF structure export request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )

    logger.info("PDF structure export download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    content, mime = download_file(payload.file_url, max_mb=30, require_pdf=True)
    logger.info("PDF structure export download ok", extra={"chatId": payload.chat_id, "size": len(content), "mime": mime})
    gemini_key = os.getenv("GEMINI_API_KEY")

    prompt = (
        payload.prompt
        or "Export the PDF structure as JSON with keys: metadata, headings[], paragraphs[], tables[], images[], pageMap[]. "
        f"Provide concise {language} descriptions. Keep page numbers and coordinates when available."
    ).strip()

    try:
        logger.info("PDF structure export upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(content, mime, payload.file_name or "document.pdf", gemini_key)
        logger.info("PDF structure export upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        structure, stream_message_id = await generate_text_with_optional_stream(
            parts=[
                {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
                {"text": f"Language: {language}"},
                {"text": prompt},
            ],
            api_key=gemini_key,
            stream=bool(payload.stream),
            chat_id=payload.chat_id,
            tool="pdf_structure_export",
            chunk_metadata={"language": language},
        )
        if not structure:
            raise RuntimeError("Empty response from Gemini")
        logger.info("PDF structure export gemini response | chatId=%s preview=%s", payload.chat_id, structure[:500])

        extra_fields = {
            "success": True,
            "chatId": payload.chat_id,
            "structure": structure,
            "language": language,
            "model": "gemini-2.5-flash",
        }
        result = attach_streaming_payload(
            extra_fields,
            tool="pdf_structure_export",
            content=structure,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "structure": structure,
                "language": language,
                "model": "gemini-2.5-flash",
            },
        )

        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=structure,
            metadata={
                "tool": "pdf_structure_export",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
            },
        )
        if firestore_ok:
            logger.info("PDF structure export Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("PDF structure export Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        msg = hexc.detail.get("message") if isinstance(hexc.detail, dict) else str(hexc.detail)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_structure_export", "error": hexc.detail},
            )
        logger.error("PDF structure export HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        raise
    except Exception as exc:
        logger.error("PDF structure export failed", exc_info=exc)
        msg = get_pdf_error_message("pdf_structure_export_failed", language)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_structure_export", "error": str(exc)},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "pdf_structure_export_failed", "message": msg},
        ) from exc


