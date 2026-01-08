import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from core.word_to_pdf import convert_word_bytes_to_pdf_bytes
from errors_response import get_pdf_error_message
from endpoints.helper_fail_response import build_success_error_response
from schemas import DocQnaRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_word.qna")

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


def _ensure_file_uri(payload: DocQnaRequest, api_key: str) -> str:
    if payload.file_id:
        return payload.file_id
    if payload.file_url:
        content, mime = download_file(payload.file_url, max_mb=30, require_pdf=False)
        mime = _validate_word_mime(mime)
        suffix = ".docx"
        if payload.file_name and "." in payload.file_name:
            suffix = "." + payload.file_name.split(".")[-1]
        pdf_bytes, pdf_filename = convert_word_bytes_to_pdf_bytes(content, suffix=suffix)
        display_name = pdf_filename or payload.file_name or "document.pdf"
        return upload_to_gemini_files(pdf_bytes, "application/pdf", display_name, api_key)
    raise HTTPException(
        status_code=400,
        detail={"success": False, "error": "invalid_file_url", "message": get_pdf_error_message("invalid_file_url", payload.language)},
    )


@router.post("/qna")
async def qna_word(payload: DocQnaRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    raw_language = payload.language
    language = normalize_language(raw_language) or "English"
    log_full_payload(logger, "word_qna", payload)
    logger.info(
        "Word QnA request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )
    logger.debug(
        "Word QnA question received",
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
        logger.info("Word QnA ensure file", extra={"chatId": payload.chat_id, "fileId": payload.file_id, "fileUrl": payload.file_url})
        try:
            file_uri = _ensure_file_uri(payload, gemini_key)
        except HTTPException as he:
            return build_success_error_response(
                tool="word_qna",
                language=language,
                chat_id=payload.chat_id,
                user_id=user_id,
                status_code=he.status_code,
                detail=he.detail,
            )
        except Exception as exc:
            return build_success_error_response(
                tool="word_qna",
                language=language,
                chat_id=payload.chat_id,
                user_id=user_id,
                status_code=500,
                detail=str(exc),
            )
        logger.info("Word QnA file ready", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        user_prompt = (payload.prompt or "").strip()
        instructions = user_prompt or f"Answer in {language}. Maintain citations if available."
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
            tool="word_qna",
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
            "Word QnA gemini response | chatId=%s preview=%s",
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
            tool="word_qna",
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
                "tool": "word_qna",
                "fileUri": file_uri,
                "fileName": payload.file_name,
            },
            client_message_id=getattr(payload, "client_message_id", None),
        )
        if firestore_ok:
            logger.info("Word QnA Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("Word QnA Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        logger.error("Word QnA HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        return build_success_error_response(
            tool="word_qna",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=hexc.status_code,
            detail=hexc.detail,
        )
    except Exception as exc:
        logger.error("Word QnA failed", exc_info=exc)
        return build_success_error_response(
            tool="word_qna",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=500,
            detail=str(exc),
        )

