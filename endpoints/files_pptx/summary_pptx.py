import logging
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from errors_response import get_pdf_error_message
from endpoints.helper_fail_response import build_success_error_response
from schemas import PptxSummaryRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_pptx.summary")

router = APIRouter(prefix="/api/v1/files/pptx", tags=["FilesPPTX"])


_PPTX_MIME_FALLBACK = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_PPTX_MIME_ALLOWED = {
    _PPTX_MIME_FALLBACK,
    "application/vnd.ms-powerpoint",
    "application/vnd.ms-powerpoint.presentation.macroEnabled.12",
}

def _validate_pptx_mime(mime: str) -> str:
    if not mime:
        return _PPTX_MIME_FALLBACK
    mime = mime.split(";")[0].strip()
    if mime.lower() in _PPTX_MIME_ALLOWED:
        return mime
    if "presentation" in mime.lower() or "powerpoint" in mime.lower() or "ppt" in mime.lower():
        return mime
    raise HTTPException(
        status_code=400,
        detail={"success": False, "error": "invalid_file_type", "message": get_pdf_error_message("invalid_file_url", None)},
    )


def _convert_to_pdf_via_libreoffice(content: bytes, suffix: str = ".pptx") -> bytes:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_in = Path(tmpdir) / f"input{suffix}"
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
            extra={"rc": result.returncode, "stdout": stdout_preview, "stderr": stderr_preview},
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"LibreOffice conversion failed rc={result.returncode} stderr={stderr_preview}"
            )
        pdf_path = next(iter(Path(tmpdir).glob("*.pdf")), None)
        if not pdf_path or not pdf_path.exists():
            raise RuntimeError("LibreOffice conversion failed: no PDF output produced")
        size = pdf_path.stat().st_size
        logger.info("LibreOffice convert success", extra={"output_pdf": str(pdf_path), "size": size})
        return pdf_path.read_bytes()


@router.post("/summary")
async def summary_pptx(payload: PptxSummaryRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    raw_language = payload.language
    language = normalize_language(raw_language) or "English"
    log_full_payload(logger, "pptx_summary", payload)
    logger.info(
        "PPTX summary request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )

    logger.info("PPTX summary download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    try:
        content, mime = download_file(payload.file_url, max_mb=30, require_pdf=False)
        mime = _validate_pptx_mime(mime)
    except HTTPException as he:
        return build_success_error_response(
            tool="pptx_summary",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=he.status_code,
            detail=he.detail,
        )
    except Exception as exc:
        return build_success_error_response(
            tool="pptx_summary",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=500,
            detail=str(exc),
        )
    logger.info(
        "PPTX summary download ok",
        extra={"chatId": payload.chat_id, "size": len(content), "mime": mime},
    )

    prompt = (payload.prompt or "").strip() or f"Summarize this presentation in {language} with key sections and bullets."
    logger.debug(
        "PPTX summary prompt | chatId=%s userId=%s lang=%s level=%s prompt=%s",
        payload.chat_id,
        user_id,
        language,
        payload.summary_level or "basic",
        prompt,
    )
    try:
        # PPTX/PDF: PDF ise direkt, değilse LibreOffice ile PDF'e çevir
        is_pdf = mime.lower().startswith("application/pdf")
        if is_pdf:
            pdf_bytes = content
        else:
            suffix = ".pptx"
            if payload.file_name and "." in payload.file_name:
                suffix = "." + payload.file_name.split(".")[-1]
            pdf_bytes = _convert_to_pdf_via_libreoffice(content, suffix=suffix)
        logger.info(
            "PPTX summary PDF ready",
            extra={"chatId": payload.chat_id, "size": len(pdf_bytes), "source_mime": mime},
        )

        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            raise RuntimeError("GEMINI_API_KEY not set")

        model_candidates = [
            payload.model if hasattr(payload, "model") else None,
            os.getenv("GEMINI_PPTX_MODEL"),
            os.getenv("GEMINI_PDF_MODEL"),
            "models/gemini-3-flash-preview",
            "models/gemini-2.5-pro",
            "models/gemini-2.0-flash-001",
        ]
        logger.info("PPTX summary model candidates", extra={"models": model_candidates})
        seen = set()
        candidate_models: list[str] = []
        for m in model_candidates:
            if not m or m in seen:
                continue
            seen.add(m)
            candidate_models.append(m)

        logger.info("PPTX summary upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(pdf_bytes, "application/pdf", payload.file_name or "slides.pdf", gemini_key)
        logger.info("PPTX summary upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})

        streaming_enabled = bool(payload.stream)
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
                    "PPTX summary model attempt",
                    extra={"chatId": payload.chat_id, "attempt": idx + 1, "model": model},
                )
                text, stream_message_id = await generate_text_with_optional_stream(
                    parts=parts,
                    api_key=gemini_key,
                    stream=streaming_enabled,
                    chat_id=payload.chat_id,
                    tool="pptx_summary",
                    model=model,
                    chunk_metadata={
                        "language": language,
                        "summaryLevel": payload.summary_level or "basic",
                        "model": model,
                    },
                    tone_key=payload.tone_key,
                    tone_language=language,
                    followup_language=language,
                )
                selected_model = model
                break
            except Exception as exc:  # keep last error and continue
                last_error = exc
                logger.warning(
                    "PPTX summary model attempt failed",
                    extra={"chatId": payload.chat_id, "attempt": idx + 1, "model": model, "error": str(exc)},
                )
                continue

        if text is None or selected_model is None:
            raise last_error or RuntimeError("All PPTX summary model attempts failed")
        if not text:
            raise RuntimeError("Empty response from Gemini")
        logger.info(
            "PPTX summary gemini response | chatId=%s preview=%s",
            payload.chat_id,
            text[:500],
        )

        response_message_id = (
            stream_message_id
            or getattr(payload, "client_message_id", None)
            or f"pptx_summary_{uuid.uuid4().hex}"
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
            tool="pptx_summary",
            content=text,
            streaming=bool(stream_message_id),
            message_id=response_message_id,
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
                "tool": "pptx_summary",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
                "summaryLevel": payload.summary_level or "basic",
                "provider": "gemini",
            },
            client_message_id=response_message_id,
            stream_message_id=stream_message_id,
        )
        if firestore_ok:
            logger.info("PPTX summary Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("PPTX summary Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        logger.error("PPTX summary HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        return build_success_error_response(
            tool="pptx_summary",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=hexc.status_code,
            detail=hexc.detail,
        )
    except Exception as exc:
        logger.error("PPTX summary failed", exc_info=exc)
        return build_success_error_response(
            tool="pptx_summary",
            language=language,
            chat_id=payload.chat_id,
            user_id=user_id,
            status_code=500,
            detail=str(exc),
        )


