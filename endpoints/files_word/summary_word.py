import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from errors_response import get_pdf_error_message
from schemas import DocSummaryRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_word.summary")

router = APIRouter(prefix="/api/v1/files/word", tags=["FilesWord"])


_WORD_MIME_FALLBACK = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_WORD_MIME_ALLOWED = {
    _WORD_MIME_FALLBACK,
    "application/msword",
    "application/vnd.ms-word",
    "application/vnd.ms-word.document.macroEnabled.12",
}


def _convert_to_pdf_via_libreoffice(content: bytes, suffix: str = ".docx") -> bytes:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_in = Path(tmpdir) / f"input{suffix}"
        tmp_out = Path(tmpdir) / "output.pdf"
        tmp_in.write_bytes(content)
        cmd = [
            "soffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmpdir),
            str(tmp_in),
        ]
        logger.info("LibreOffice convert start", extra={"cmd": " ".join(cmd), "tmpdir": tmpdir, "suffix": suffix})
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=60)
        except Exception as exc:
            logger.error("LibreOffice spawn failed", extra={"error": str(exc)})
            raise RuntimeError(f"LibreOffice conversion failed: {exc}") from exc
        stderr_preview = result.stderr.decode("utf-8", errors="ignore")[:400] if result.stderr else ""
        stdout_preview = result.stdout.decode("utf-8", errors="ignore")[:200] if result.stdout else ""
        logger.info(
            "LibreOffice convert finished",
            extra={"rc": result.returncode, "stdout": stdout_preview, "stderr": stderr_preview, "out_exists": tmp_out.exists()},
        )
        if result.returncode != 0 or not tmp_out.exists():
            raise RuntimeError(
                f"LibreOffice conversion failed rc={result.returncode} stderr={stderr_preview}"
            )
        size = tmp_out.stat().st_size if tmp_out.exists() else 0
        logger.info("LibreOffice convert success", extra={"output_pdf": str(tmp_out), "size": size})
        return tmp_out.read_bytes()


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


@router.post("/summary")
async def summary_word(payload: DocSummaryRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    raw_language = payload.language
    language = normalize_language(raw_language) or "English"
    log_full_payload(logger, "word_summary", payload)
    logger.info(
        "Word summary request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )

    logger.info("Word summary download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    content, mime = download_file(payload.file_url, max_mb=20, require_pdf=False)
    mime = _validate_word_mime(mime)
    logger.info(
        "Word summary download ok",
        extra={"chatId": payload.chat_id, "size": len(content), "mime": mime},
    )

    prompt = (payload.prompt or "").strip() or f"Summarize this Word document in {language} with any useful structure you choose."
    logger.debug(
        "Word summary prompt | chatId=%s userId=%s lang=%s level=%s prompt=%s",
        payload.chat_id,
        user_id,
        language,
        payload.summary_level or "basic",
        prompt,
    )
    try:
        # Word/PDF: PDF ise direkt, değilse LibreOffice ile PDF'e çevir
        is_pdf = mime.lower().startswith("application/pdf")
        if is_pdf:
            pdf_bytes = content
        else:
            suffix = ".docx"
            if payload.file_name and "." in payload.file_name:
                suffix = "." + payload.file_name.split(".")[-1]
            pdf_bytes = _convert_to_pdf_via_libreoffice(content, suffix=suffix)
        logger.info(
            "Word summary PDF ready",
            extra={"chatId": payload.chat_id, "size": len(pdf_bytes), "source_mime": mime},
        )

        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            raise RuntimeError("GEMINI_API_KEY not set")

        model_candidates = [
            payload.model if hasattr(payload, "model") else None,
            os.getenv("GEMINI_DOC_MODEL"),
            os.getenv("GEMINI_PDF_MODEL"),
            "models/gemini-3-flash-preview",
            "models/gemini-2.5-pro",
            "models/gemini-2.0-flash-001",
        ]
        logger.info("Word summary model candidates", extra={"models": model_candidates})
        seen = set()
        candidate_models: list[str] = []
        for m in model_candidates:
            if not m or m in seen:
                continue
            seen.add(m)
            candidate_models.append(m)

        logger.info("Word summary upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(pdf_bytes, "application/pdf", payload.file_name or "document.pdf", gemini_key)
        logger.info("Word summary upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})

        streaming_enabled = False
        text: str | None = None
        stream_message_id = None
        selected_model: str | None = None
        last_error: Exception | None = None

        for idx, model in enumerate(candidate_models):
            try:
                parts = [
                    {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
                    {"text": prompt},
                ]
                logger.info(
                    "Word summary model attempt",
                    extra={"chatId": payload.chat_id, "attempt": idx + 1, "model": model},
                )
                text, stream_message_id = await generate_text_with_optional_stream(
                    parts=parts,
                    api_key=gemini_key,
                    stream=streaming_enabled,
                    chat_id=payload.chat_id,
                    tool="word_summary",
                    model=model,
                    chunk_metadata={
                        "language": language,
                        "summaryLevel": payload.summary_level or "basic",
                        "model": model,
                    },
                )
                selected_model = model
                break
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Word summary model attempt failed",
                    extra={"chatId": payload.chat_id, "attempt": idx + 1, "model": model, "error": str(exc)},
                )
                continue

        if text is None or selected_model is None:
            raise last_error or RuntimeError("All Word summary model attempts failed")
        if not text:
            raise RuntimeError("Empty response from Gemini")
        logger.info(
            "Word summary gemini response | chatId=%s preview=%s",
            payload.chat_id,
            text[:500],
        )

        extra_fields = {
            "success": True,
            "chatId": payload.chat_id,
            "summary": text,
            "language": language,
            "model": selected_model,
            "summaryLevel": payload.summary_level or "basic",
        }
        result = attach_streaming_payload(
            extra_fields,
            tool="word_summary",
            content=text,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "summary": text,
                "language": language,
                "model": selected_model,
                "summaryLevel": payload.summary_level or "basic",
            },
        )

        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=text,
            metadata={
                "tool": "word_summary",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
                "summaryLevel": payload.summary_level or "basic",
                "provider": "gemini",
            },
        )
        if firestore_ok:
            logger.info("Word summary Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("Word summary Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        msg = hexc.detail.get("message") if isinstance(hexc.detail, dict) else str(hexc.detail)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "word_summary", "error": hexc.detail},
            )
        logger.error("Word summary HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        raise
    except Exception as exc:
        logger.error("Word summary failed", exc_info=exc)
        msg = get_pdf_error_message("pdf_summary_failed", language)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "word_summary", "error": str(exc)},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "word_summary_failed", "message": msg},
        ) from exc


