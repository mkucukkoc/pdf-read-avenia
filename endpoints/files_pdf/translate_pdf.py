import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from errors_response import get_pdf_error_message
from endpoints.helper_fail_response import build_success_error_response
from schemas import PdfTranslateRequest
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

logger = logging.getLogger("pdf_read_refresh.files_pdf.translate")

router = APIRouter(prefix="/api/v1/files/pdf", tags=["FilesPDF"])


@router.post("/translate")
async def translate_pdf(payload: PdfTranslateRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    language = normalize_language(payload.language) or "English"
    log_full_payload(logger, "pdf_translate", payload)
    logger.info(
        "PDF translate request",
        extra={
            "chatId": payload.chat_id,
            "userId": user_id,
            "language": language,
            "target": payload.targetLanguage,
            "fileName": payload.file_name,
        },
    )

    logger.info("PDF translate download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    try:
        content, mime = download_file(payload.file_url, max_mb=40, require_pdf=True)
    except HTTPException as he:
        return build_success_error_response(
            tool="pdf_translate",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=he.status_code,
            detail=he.detail,
        )
    except Exception as exc:
        return build_success_error_response(
            tool="pdf_translate",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=500,
            detail=str(exc),
        )
    logger.info("PDF translate download ok", extra={"chatId": payload.chat_id, "size": len(content), "mime": mime})
    gemini_key = os.getenv("GEMINI_API_KEY")
    effective_model = payload.model or os.getenv("GEMINI_PDF_MODEL") or "gemini-2.5-flash"

    target_lang = payload.targetLanguage or language
    source_info = f" from {payload.sourceLanguage}" if payload.sourceLanguage else ""
    prompt = (
        payload.prompt
        or f"Translate the content of this PDF{source_info} to {target_lang}. Preserve the tone and intent of the original document."
    ).strip()

    try:
        logger.info("PDF translate upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(content, mime, payload.file_name or "document.pdf", gemini_key)
        logger.info("PDF translate upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        usage_context = build_usage_context(
            request=request,
            user_id=user_id,
            endpoint="translate_pdf",
            model=effective_model,
            payload=payload,
        )
        translation, stream_message_id = await generate_text_with_optional_stream(
            parts=[
                {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
                {"text": f"Language: {target_lang}"},
                {"text": prompt},
            ],
            api_key=gemini_key,
            stream=bool(payload.stream),
            chat_id=payload.chat_id,
            tool="pdf_translate",
            model=effective_model,
            chunk_metadata={"language": target_lang},
            tone_key=payload.tone_key,
            tone_language=target_lang,
            followup_language=target_lang,
            usage_context=usage_context,
        )
        if not translation:
            raise RuntimeError("Empty response from Gemini")
        logger.info("PDF translate gemini response | chatId=%s preview=%s", payload.chat_id, translation[:500])

        extra_fields = {
            "success": True,
            "chatId": payload.chat_id,
            "translation": translation,
            "language": language,
            "targetLanguage": target_lang,
            "model": effective_model,
        }
        result = attach_streaming_payload(
            extra_fields,
            tool="pdf_translate",
            content=translation,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "translation": translation,
                "language": language,
                "targetLanguage": target_lang,
                "model": effective_model,
            },
        )

        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=translation,
            metadata={
                "tool": "pdf_translate",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
                "targetLanguage": target_lang,
                "sourceLanguage": payload.sourceLanguage,
            },
            stream_message_id=stream_message_id,
        )
        if firestore_ok:
            logger.info("PDF translate Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("PDF translate Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        logger.error("PDF translate HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        return build_success_error_response(
            tool="pdf_translate",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=hexc.status_code,
            detail=hexc.detail,
        )
    except Exception as exc:
        logger.error("PDF translate failed", exc_info=exc)
        return build_success_error_response(
            tool="pdf_translate",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=500,
            detail=str(exc),
        )
