import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from core.word_to_pdf import convert_word_bytes_to_pdf_bytes
from errors_response import get_pdf_error_message
from endpoints.helper_fail_response import build_success_error_response
from schemas import DocAnalyzeRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_word.analyze")

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


@router.post("/analyze")
async def analyze_word(payload: DocAnalyzeRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    raw_language = payload.language
    language = normalize_language(raw_language) or "English"
    log_full_payload(logger, "word_analyze", payload)
    logger.info(
        "Word analyze request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )

    logger.info("Word analyze download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    try:
        content, mime = download_file(payload.file_url, max_mb=50, require_pdf=False)
        mime = _validate_word_mime(mime)
    except HTTPException as he:
        return build_success_error_response(
            tool="word_analyze",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=he.status_code,
            detail=he.detail,
        )
    except Exception as exc:
        return build_success_error_response(
            tool="word_analyze",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=500,
            detail=str(exc),
        )
    logger.info("Word analyze download ok", extra={"chatId": payload.chat_id, "size": len(content), "mime": mime})

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
                tool="word_analyze",
                language=language,
                chat_id=payload.chat_id,
                user_id=user_id,
                status_code=500,
                detail=str(exc),
            )

    gemini_key = os.getenv("GEMINI_API_KEY")
    effective_model = payload.model or os.getenv("GEMINI_PDF_MODEL") or "gemini-2.5-flash"

    prompt = (payload.prompt or "").strip() or f"Analyze this document in {language} and return your insights."
    logger.debug(
        "Word analyze prompt | chatId=%s userId=%s lang=%s prompt=%s",
        payload.chat_id,
        user_id,
        language,
        prompt,
    )
    try:
        logger.info("Word analyze upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(pdf_bytes, "application/pdf", pdf_filename, gemini_key)
        logger.info("Word analyze upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        text, stream_message_id = await generate_text_with_optional_stream(
            parts=[
                {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
                {"text": f"Language: {language}"},
                {"text": prompt},
            ],
            api_key=gemini_key,
            stream=bool(payload.stream),
            chat_id=payload.chat_id,
            tool="word_analyze",
            model=effective_model,
            chunk_metadata={"language": language},
        )
        if not text:
            raise RuntimeError("Empty response from Gemini")
        logger.info(
            "Word analyze gemini response | chatId=%s preview=%s",
            payload.chat_id,
            text[:500],
        )

        base_payload = {
            "success": True,
            "chatId": payload.chat_id,
            "analysis": text,
            "language": language,
            "model": effective_model,
        }
        result = attach_streaming_payload(
            base_payload,
            tool="word_analyze",
            content=text,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "analysis": text,
                "language": language,
                "model": effective_model,
            },
        )

        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=text,
            metadata={
                "tool": "word_analyze",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
            },
        )
        if firestore_ok:
            logger.info("Word analyze Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("Word analyze Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        logger.error("Word analyze HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        return build_success_error_response(
            tool="word_analyze",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=hexc.status_code,
            detail=hexc.detail,
        )
    except Exception as exc:
        logger.error("Word analyze failed", exc_info=exc)
        return build_success_error_response(
            tool="word_analyze",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=500,
            detail=str(exc),
        )
import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from core.word_to_pdf import convert_word_bytes_to_pdf_bytes
from errors_response import get_pdf_error_message
from schemas import DocAnalyzeRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_word.analyze")

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


@router.post("/analyze")
async def analyze_word(payload: DocAnalyzeRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    raw_language = payload.language
    language = normalize_language(raw_language) or "English"
    log_full_payload(logger, "word_analyze", payload)
    logger.info(
        "Word analyze request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )

    logger.info("Word analyze download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    content, mime = download_file(payload.file_url, max_mb=50, require_pdf=False)
    mime = _validate_word_mime(mime)
    logger.info("Word analyze download ok", extra={"chatId": payload.chat_id, "size": len(content), "mime": mime})

    is_pdf = mime.lower().startswith("application/pdf")
    if is_pdf:
        pdf_bytes = content
        pdf_filename = payload.file_name or "document.pdf"
    else:
        suffix = ".docx"
        if payload.file_name and "." in payload.file_name:
            suffix = "." + payload.file_name.split(".")[-1]
        pdf_bytes, pdf_filename = convert_word_bytes_to_pdf_bytes(content, suffix=suffix)

    gemini_key = os.getenv("GEMINI_API_KEY")
    effective_model = payload.model or os.getenv("GEMINI_PDF_MODEL") or "gemini-2.5-flash"

    prompt = (payload.prompt or "").strip() or f"Analyze this document in {language} and return your insights."
    logger.debug(
        "Word analyze prompt | chatId=%s userId=%s lang=%s prompt=%s",
        payload.chat_id,
        user_id,
        language,
        prompt,
    )
    try:
        logger.info("Word analyze upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(pdf_bytes, "application/pdf", pdf_filename, gemini_key)
        logger.info("Word analyze upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        text, stream_message_id = await generate_text_with_optional_stream(
            parts=[
                {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
                {"text": f"Language: {language}"},
                {"text": prompt},
            ],
            api_key=gemini_key,
            stream=bool(payload.stream),
            chat_id=payload.chat_id,
            tool="word_analyze",
            model=effective_model,
            chunk_metadata={"language": language},
        )
        if not text:
            raise RuntimeError("Empty response from Gemini")
        logger.info(
            "Word analyze gemini response | chatId=%s preview=%s",
            payload.chat_id,
            text[:500],
        )

        base_payload = {
            "success": True,
            "chatId": payload.chat_id,
            "analysis": text,
            "language": language,
            "model": effective_model,
        }
        result = attach_streaming_payload(
            base_payload,
            tool="word_analyze",
            content=text,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "analysis": text,
                "language": language,
                "model": effective_model,
            },
        )

        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=text,
            metadata={
                "tool": "word_analyze",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
            },
        )
        if firestore_ok:
            logger.info("Word analyze Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("Word analyze Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        msg = hexc.detail.get("message") if isinstance(hexc.detail, dict) else str(hexc.detail)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "word_analyze", "error": hexc.detail},
            )
        logger.error("Word analyze HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        raise
    except Exception as exc:
        logger.error("Word analyze failed", exc_info=exc)
        msg = get_pdf_error_message("pdf_analyze_failed", language)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "word_analyze", "error": str(exc)},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "word_analyze_failed", "message": msg},
        ) from exc

