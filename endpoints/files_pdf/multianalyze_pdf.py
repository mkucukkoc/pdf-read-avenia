import logging
import os
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from errors_response import get_pdf_error_message
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


def _resolve_files(urls: List[str], api_key: str) -> Tuple[List[str], int]:
    uris: List[str] = []
    total_size = 0
    for idx, item in enumerate(urls):
        if item.lower().startswith(("http://", "https://")):
            content, mime = download_file(item, max_mb=40, require_pdf=True)
            total_size += len(content)
            uri = upload_to_gemini_files(content, mime, f"document_{idx+1}.pdf", api_key)
            uris.append(uri)
        else:
            uris.append(item)
    return uris, total_size


@router.post("/multianalyze")
async def multianalyze_pdf(payload: PdfMultiAnalyzeRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    language = normalize_language(payload.language) or "English"
    log_full_payload(logger, "pdf_multianalyze", payload)
    logger.info(
        "PDF multianalyze request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileCount": len(payload.file_urls or [])},
    )

    if not payload.file_urls or len(payload.file_urls) < 2:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "invalid_file_url", "message": "At least two PDF URLs are required."},
        )

    gemini_key = os.getenv("GEMINI_API_KEY")
    effective_model = payload.model or os.getenv("GEMINI_PDF_MODEL") or "gemini-2.5-flash"
    try:
        logger.info("PDF multianalyze upload start", extra={"chatId": payload.chat_id})
        file_uris, total_size = _resolve_files(payload.file_urls, gemini_key)
        if total_size > 120 * 1024 * 1024:  # 120 MB safety
            raise HTTPException(
                status_code=400,
                detail={"success": False, "error": "file_too_large", "message": get_pdf_error_message("file_too_large", language)},
            )
        logger.info(
            "PDF multianalyze upload ok",
            extra={"chatId": payload.chat_id, "fileUris": file_uris, "totalSize": total_size},
        )

        prompt = (
            payload.prompt
            or f"Analyze all provided PDFs together in {language}. Identify common themes, differences, risks, and a merged summary. "
            "If possible, cite page numbers. Return concise, structured markdown."
        ).strip()

        parts = [{"file_data": {"mime_type": "application/pdf", "file_uri": uri}} for uri in file_uris]
        parts.extend(
            [
                {"text": f"Language: {language}"},
                {"text": prompt},
            ]
        )
        analysis, stream_message_id = await generate_text_with_optional_stream(
            parts=parts,
            api_key=gemini_key,
            stream=bool(payload.stream),
            chat_id=payload.chat_id,
            tool="pdf_multianalyze",
            model=effective_model,
            chunk_metadata={
                "language": language,
                "fileCount": len(payload.file_urls),
            },
        )
        if not analysis:
            raise RuntimeError("Empty response from Gemini")
        logger.info("PDF multianalyze gemini response | chatId=%s preview=%s", payload.chat_id, analysis[:500])

        extra_fields = {
            "success": True,
            "chatId": payload.chat_id,
            "analysis": analysis,
            "language": language,
            "model": effective_model,
        }
        result = attach_streaming_payload(
            extra_fields,
            tool="pdf_multianalyze",
            content=analysis,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "analysis": analysis,
                "language": language,
                "model": effective_model,
            },
        )

        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=analysis,
            metadata={
                "tool": "pdf_multianalyze",
                "fileUrls": payload.file_urls,
            },
        )
        if firestore_ok:
            logger.info("PDF multianalyze Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("PDF multianalyze Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        msg = hexc.detail.get("message") if isinstance(hexc.detail, dict) else str(hexc.detail)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_multianalyze", "error": hexc.detail},
            )
        logger.error("PDF multianalyze HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        raise
    except Exception as exc:
        logger.error("PDF multianalyze failed", exc_info=exc)
        msg = get_pdf_error_message("pdf_multianalyze_failed", language)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_multianalyze", "error": str(exc)},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "pdf_multianalyze_failed", "message": msg},
        ) from exc


