import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from errors_response import get_pdf_error_message
from schemas import PdfSummaryRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    generate_text_with_optional_stream,
    save_message_to_firestore,
    log_full_payload,
    attach_streaming_payload,
)

logger = logging.getLogger("pdf_read_refresh.files_pdf.summary")

router = APIRouter(prefix="/api/v1/files/pdf", tags=["FilesPDF"])


def _convert_to_pdf_via_libreoffice(content: bytes, suffix: str = ".pdf") -> bytes:
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


@router.post("/summary")
async def summary_pdf(payload: PdfSummaryRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    raw_language = payload.language
    language = normalize_language(raw_language) or "English"
    log_full_payload(logger, "pdf_summary", payload)
    logger.info(
        "PDF summary request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )

    logger.info("PDF summary download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    content, mime = download_file(payload.file_url, max_mb=20, require_pdf=False)
    logger.info("PDF summary download ok", extra={"chatId": payload.chat_id, "size": len(content), "mime": mime})
    is_pdf = mime.lower().startswith("application/pdf") if mime else False
    if not is_pdf:
        suffix = ".bin"
        if payload.file_name and "." in payload.file_name:
            suffix = "." + payload.file_name.split(".")[-1]
        content = _convert_to_pdf_via_libreoffice(content, suffix=suffix)
        mime = "application/pdf"
        logger.info("PDF summary converted to PDF", extra={"chatId": payload.chat_id, "size": len(content), "source_mime": mime})
    gemini_key = os.getenv("GEMINI_API_KEY")
    effective_model = payload.model or os.getenv("GEMINI_PDF_MODEL") or "gemini-2.5-flash"

    prompt = (payload.prompt or "").strip() or f"Summarize this PDF in {language} with any useful structure you choose."
    logger.debug(
        "PDF summary prompt | chatId=%s userId=%s lang=%s level=%s prompt=%s",
        payload.chat_id,
        user_id,
        language,
        payload.summary_level or "basic",
        prompt,
    )
    try:
        logger.info("PDF summary upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(content, mime, payload.file_name or "document.pdf", gemini_key)
        logger.info("PDF summary upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        text, stream_message_id = await generate_text_with_optional_stream(
            parts=[
                {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
                {"text": prompt},
            ],
            api_key=gemini_key,
            stream=bool(payload.stream),
            chat_id=payload.chat_id,
            tool="pdf_summary",
            model=effective_model,
            chunk_metadata={
                "language": language,
                "summaryLevel": payload.summary_level or "basic",
            },
        )
        if not text:
            raise RuntimeError("Empty response from Gemini")
        logger.info(
            "PDF summary gemini response | chatId=%s preview=%s",
            payload.chat_id,
            text[:500],
        )

        extra_fields = {
            "success": True,
            "chatId": payload.chat_id,
            "summary": text,
            "language": language,
            "model": effective_model,
            "summaryLevel": payload.summary_level or "basic",
        }
        result = attach_streaming_payload(
            extra_fields,
            tool="pdf_summary",
            content=text,
            streaming=bool(stream_message_id),
            message_id=stream_message_id,
            extra_data={
                "summary": text,
                "language": language,
                "model": effective_model,
                "summaryLevel": payload.summary_level or "basic",
            },
        )

        firestore_ok = save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=text,
            metadata={
                "tool": "pdf_summary",
                "fileUrl": payload.file_url,
                "fileName": payload.file_name,
                "summaryLevel": payload.summary_level or "basic",
            },
        )
        if firestore_ok:
            logger.info("PDF summary Firestore save success | chatId=%s", payload.chat_id)
        else:
            logger.error("PDF summary Firestore save failed | chatId=%s", payload.chat_id)
        return result
    except HTTPException as hexc:
        msg = hexc.detail.get("message") if isinstance(hexc.detail, dict) else str(hexc.detail)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_summary", "error": hexc.detail},
            )
        logger.error("PDF summary HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        raise
    except Exception as exc:
        logger.error("PDF summary failed", exc_info=exc)
        msg = get_pdf_error_message("pdf_summary_failed", language)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_summary", "error": str(exc)},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "pdf_summary_failed", "message": msg},
        ) from exc

