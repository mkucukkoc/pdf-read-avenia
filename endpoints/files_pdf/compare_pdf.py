import logging
import os
import asyncio
from typing import Any, Dict, Tuple

from fastapi import APIRouter, HTTPException, Request

from schemas import PdfCompareRequest
from errors_response import get_pdf_error_message
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    call_gemini_generate,
    extract_text_response,
    save_message_to_firestore,
)

logger = logging.getLogger("pdf_read_refresh.files_pdf.compare")

router = APIRouter(prefix="/api/v1/files/pdf", tags=["FilesPDF"])


COMPARE_PROMPT = """
Compare the two PDFs. Identify differences, added/removed/modified sections, risk areas, and provide a concise summary of changes.
Return JSON with:
{
  "differences": [...],
  "removed": [...],
  "added": [...],
  "modified": [...],
  "riskAreas": [...],
  "summary": "..."
}
"""


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
    language = payload.language
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

        parts = [
            {"file_data": {"mime_type": "application/pdf", "file_uri": file1_uri}},
            {"file_data": {"mime_type": "application/pdf", "file_uri": file2_uri}},
            {"text": COMPARE_PROMPT},
        ]
        response_json = await asyncio.to_thread(call_gemini_generate, parts, gemini_key)
        logger.info("PDF compare gemini response", extra={"chatId": payload.chat_id})
        diff = extract_text_response(response_json)
        if not diff:
            raise RuntimeError("Empty response from Gemini")

        result = {
            "success": True,
            "chatId": payload.chat_id,
            "differences": diff,
            "language": language,
            "model": "gemini-2.5-flash",
        }
        save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content="PDF karşılaştırması tamamlandı.",
            metadata={
                "tool": "pdf_compare",
                "file1": payload.file1,
                "file2": payload.file2,
                "fileName": payload.file_name,
            },
        )
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

