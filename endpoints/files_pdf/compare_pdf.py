import logging
import os
from typing import Any, Dict, Tuple

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from schemas import PdfCompareRequest
from errors_response import get_pdf_error_message
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_pdf.compare")

router = APIRouter(prefix="/api/v1/files/pdf", tags=["FilesPDF"])


def _resolve_file(item: str, api_key: str, label: str, max_mb: int = 25) -> Tuple[str, int]:
    # item can be a file uri/id or an http(s) url
    if item.lower().startswith(("http://", "https://")):
        content, mime = download_file(item, max_mb=max_mb, require_pdf=True)
        file_uri = upload_to_gemini_files(content, mime, f"{label}.pdf", api_key)
        return file_uri, len(content)
    return item, 0


@router.post("/compare")
async def compare_pdf(payload: PdfCompareRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    raw_language = payload.language
    language = normalize_language(raw_language) or "English"
    log_full_payload(logger, "pdf_compare", payload)
    logger.info(
        "PDF compare request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )

    gemini_key = os.getenv("GEMINI_API_KEY")

    try:
        logger.info("PDF compare resolve file1", extra={"chatId": payload.chat_id, "file1": payload.file1})
        file1_uri, size1 = _resolve_file(payload.file1, gemini_key, "file1", max_mb=30)
        logger.info("PDF compare resolve file1 ok", extra={"chatId": payload.chat_id, "file1Uri": file1_uri, "size1": size1})
        logger.info("PDF compare resolve file2", extra={"chatId": payload.chat_id, "file2": payload.file2})
        file2_uri, size2 = _resolve_file(payload.file2, gemini_key, "file2", max_mb=30)
        logger.info("PDF compare resolve file2 ok", extra={"chatId": payload.chat_id, "file2Uri": file2_uri, "size2": size2})
        if size1 + size2 > 50 * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail={"success": False, "error": "file_too_large", "message": get_pdf_error_message("file_too_large", language)},
            )

        prompt = (payload.prompt or "").strip() or f"Compare these PDFs in {language} and highlight the key differences."
        logger.debug(
            "PDF compare prompt | chatId=%s userId=%s lang=%s prompt=%s",
            payload.chat_id,
            user_id,
            language,
            prompt,
        )
        parts = [
            {"file_data": {"mime_type": "application/pdf", "file_uri": file1_uri}},
            {"file_data": {"mime_type": "application/pdf", "file_uri": file2_uri}},
            {"text": f"Language: {language}"},
            {"text": prompt},
        ]
        diff, stream_message_id = await generate_text_with_optional_stream(
            parts=parts,
            api_key=gemini_key,
            stream=bool(payload.stream),
            chat_id=payload.chat_id,
            tool="pdf_compare",
            chunk_metadata={
                "language": language,
                "file1": payload.file1,
                "file2": payload.file2,
            },
        )
        if not diff:
            raise RuntimeError("Empty response from Gemini")
        logger.info(
            "PDF compare gemini response | chatId=%s preview=%s",
            payload.chat_id,
            diff[:500],
        )

        extra_fields = {
            "success": True,
            "chatId": payload.chat_id,
            "differences": diff,
            "language": language,
            "model": "gemini-2.5-flash",
        }
        result = attach_streaming_payload(
            extra_fields,
            tool="pdf_compare",
            content=diff,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "differences": diff,
                "language": language,
                "model": "gemini-2.5-flash",
            },
        )
        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=diff,
            metadata={
                "tool": "pdf_compare",
                "file1": payload.file1,
                "file2": payload.file2,
                "fileName": payload.file_name,
            },
        )
        if firestore_ok:
            logger.info("PDF compare Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("PDF compare Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        msg = hexc.detail.get("message") if isinstance(hexc.detail, dict) else str(hexc.detail)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_compare", "error": hexc.detail},
            )
        logger.error("PDF compare HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        raise
    except Exception as exc:
        logger.error("PDF compare failed", exc_info=exc)
        msg = get_pdf_error_message("pdf_compare_failed", language)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_compare", "error": str(exc)},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "pdf_compare_failed", "message": msg},
        ) from exc

