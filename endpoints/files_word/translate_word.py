import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from core.word_to_pdf import convert_word_bytes_to_pdf_bytes
from errors_response import get_pdf_error_message
from endpoints.helper_fail_response import build_success_error_response
from schemas import DocTranslateRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    build_usage_context,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_word.translate")

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


@router.post("/translate")
async def translate_word(payload: DocTranslateRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    raw_language = payload.language
    language = normalize_language(raw_language) or "English"
    target_language = payload.target_language
    source_language = payload.source_language
    log_full_payload(logger, "word_translate", payload)
    logger.info(
        "Word translate request",
        extra={
            "chatId": payload.chat_id,
            "userId": user_id,
            "language": language,
            "fileName": payload.file_name,
            "targetLanguage": target_language,
            "sourceLanguage": source_language,
        },
    )

    logger.info("Word translate download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    try:
        content, mime = download_file(payload.file_url, max_mb=30, require_pdf=False)
        mime = _validate_word_mime(mime)
    except HTTPException as he:
        return build_success_error_response(
            tool="word_translate",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=he.status_code,
            detail=he.detail,
        )
    except Exception as exc:
        return build_success_error_response(
            tool="word_translate",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=500,
            detail=str(exc),
        )
    logger.info("Word translate download ok", extra={"chatId": payload.chat_id, "size": len(content), "mime": mime})

    is_pdf = mime.lower().startswith("application/pdf")
    if is_pdf:
        pdf_bytes = content
        pdf_filename = payload.file_name or "document.pdf"
    else:
        suffix = ".docx"
        if payload.file_name and "." in payload.file_name:
            suffix = "." + payload.file_name.split(".")[-1]
        try:
            pdf_bytes, pdf_filename = convert_word_bytes_to_pdf_bytes(content, suffix=suffix)
        except Exception as exc:
            return build_success_error_response(
                tool="word_translate",
                language=language,
                chat_id=payload.chat_id,
                user_id=user_id,
                status_code=500,
                detail=str(exc),
            )

    gemini_key = os.getenv("GEMINI_API_KEY")
    effective_model = payload.model or os.getenv("GEMINI_PDF_MODEL") or "gemini-2.5-flash"

    prompt = (payload.prompt or "").strip() or f"Translate this document to {target_language}."
    logger.debug(
        "Word translate prompt | chatId=%s userId=%s lang=%s target=%s prompt=%s",
        payload.chat_id,
        user_id,
        language,
        target_language,
        prompt,
    )
    try:
        logger.info("Word translate upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(pdf_bytes, "application/pdf", pdf_filename, gemini_key)
        logger.info("Word translate upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        parts = [
            {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
            {"text": f"Translate the document to {target_language}. Source language: {source_language or 'auto'}. {prompt}"},
        ]
        usage_context = build_usage_context(
            request=request,
            user_id=user_id,
            endpoint="translate_word",
            model=effective_model,
            payload=payload,
        )
        text, stream_message_id = await generate_text_with_optional_stream(
            parts=parts,
            api_key=gemini_key,
            stream=bool(payload.stream),
            chat_id=payload.chat_id,
            tool="word_translate",
            model=effective_model,
            chunk_metadata={
                "language": language,
                "targetLanguage": target_language,
                "sourceLanguage": source_language,
            },
            tone_key=payload.tone_key,
            tone_language=target_language or language,
            followup_language=target_language or language,
            usage_context=usage_context,
        )
        if not text:
            raise RuntimeError("Empty response from Gemini")
        logger.info(
            "Word translate gemini response | chatId=%s preview=%s",
            payload.chat_id,
            text[:500],
        )

        extra_fields = {
            "success": True,
            "chatId": payload.chat_id,
            "translation": text,
            "language": language,
            "targetLanguage": target_language,
            "model": effective_model,
        }
        result = attach_streaming_payload(
            extra_fields,
            tool="word_translate",
            content=text,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "translation": text,
                "language": language,
                "targetLanguage": target_language,
                "model": effective_model,
            },
        )
        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=text,
            metadata={
                "tool": "word_translate",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
                "targetLanguage": target_language,
                "sourceLanguage": source_language,
            },
            client_message_id=getattr(payload, "client_message_id", None),
            stream_message_id=stream_message_id,
        )
        if firestore_ok:
            logger.info("Word translate Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("Word translate Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        logger.error("Word translate HTTPException", exc_info=hexc, extra={"ChatId": payload.chat_id})
        return build_success_error_response(
            tool="word_translate",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=hexc.status_code,
            detail=hexc.detail,
        )
    except Exception as exc:
        logger.error("Word translate failed", exc_info=exc)
        return build_success_error_response(
            tool="word_translate",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=500,
            detail=str(exc),
        )
