import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from schemas import PdfQnaRequest
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

logger = logging.getLogger("pdf_read_refresh.files_pdf.qna")

router = APIRouter(prefix="/api/v1/files/pdf", tags=["FilesPDF"])


def _ensure_file_uri(payload: PdfQnaRequest, api_key: str) -> str:
    if payload.file_id:
        return payload.file_id
    if payload.file_url:
        content, mime = download_file(payload.file_url, max_mb=30, require_pdf=True)
        display_name = payload.file_name or "document.pdf"
        return upload_to_gemini_files(content, mime, display_name, api_key)
    raise HTTPException(
        status_code=400,
        detail={"success": False, "error": "invalid_file_url", "message": get_pdf_error_message("invalid_file_url", payload.language)},
    )


@router.post("/qna")
async def qna_pdf(payload: PdfQnaRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    raw_language = payload.language
    language = normalize_language(raw_language) or "English"
    log_full_payload(logger, "pdf_qna", payload)
    logger.info(
        "PDF QnA request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )
    logger.debug(
        "PDF QnA question received",
        extra={
            "chatId": payload.chat_id,
            "userId": user_id,
            "language": language,
            "question": (payload.question or "")[:500],
        },
    )

    gemini_key = os.getenv("GEMINI_API_KEY")
    effective_model = payload.model or os.getenv("GEMINI_PDF_MODEL") or "gemini-2.5-flash"
    try:
        logger.info("PDF QnA ensure file", extra={"chatId": payload.chat_id, "fileId": payload.file_id, "fileUrl": payload.file_url})
        file_uri = _ensure_file_uri(payload, gemini_key)
        logger.info("PDF QnA file ready", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        user_prompt = (payload.prompt or "").strip()
        instructions = user_prompt or f"Answer in {language}. Maintain citations if available."
        logger.debug(
            "PDF QnA prompt | chatId=%s userId=%s lang=%s instructions=%s question=%s",
            payload.chat_id,
            user_id,
            language,
            instructions,
            payload.question,
        )
        parts = [
            {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
            {"text": f"Answer the user's question. {instructions}"},
            {"text": payload.question},
        ]
        answer, stream_message_id = await generate_text_with_optional_stream(
            parts=parts,
            api_key=gemini_key,
            stream=bool(payload.stream),
            chat_id=payload.chat_id,
            tool="pdf_qna",
            model=effective_model,
            chunk_metadata={
                "language": language,
                "question": payload.question,
            },
        )
        if not answer:
            msg = get_pdf_error_message("no_answer_found", language)
            raise HTTPException(
                status_code=404,
                detail={"success": False, "error": "no_answer_found", "message": msg},
            )
        logger.info(
            "PDF QnA gemini response | chatId=%s preview=%s",
            payload.chat_id,
            answer[:500],
        )

        extra_fields = {
            "success": True,
            "chatId": payload.chat_id,
            "answer": answer,
            "language": language,
            "model": effective_model,
        }
        result = attach_streaming_payload(
            extra_fields,
            tool="pdf_qna",
            content=answer,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "answer": answer,
                "language": language,
                "model": effective_model,
            },
        )
        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=answer,
            metadata={
                "tool": "pdf_qna",
                "fileUri": file_uri,
                "fileName": payload.file_name,
            },
        )
        if firestore_ok:
            logger.info("PDF QnA Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("PDF QnA Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        msg = hexc.detail.get("message") if isinstance(hexc.detail, dict) else str(hexc.detail)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_qna", "error": hexc.detail},
            )
        logger.error("PDF QnA HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        raise
    except Exception as exc:
        logger.error("PDF QnA failed", exc_info=exc)
        msg = get_pdf_error_message("pdf_qna_failed", language)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_qna", "error": str(exc)},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "pdf_qna_failed", "message": msg},
        ) from exc

