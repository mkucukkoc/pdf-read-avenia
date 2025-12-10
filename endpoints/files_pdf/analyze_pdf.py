import logging
import os
import asyncio
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from core.language_support import normalize_language
from errors_response import get_pdf_error_message
from schemas import PdfAnalyzeRequest
from endpoints.files_pdf.utils import (
    extract_user_id,
    download_file,
    upload_to_gemini_files,
    call_gemini_generate,
    extract_text_response,
    save_message_to_firestore,
)

logger = logging.getLogger("pdf_read_refresh.files_pdf.analyze")

router = APIRouter(prefix="/api/v1/files/pdf", tags=["FilesPDF"])


ANALYZE_PROMPT = """
You are a PDF analyst. Perform FULL ANALYSIS:
- Extract key findings, metrics, entities (people/orgs/locations), dates.
- Table understanding: summarize tables, totals, anomalies.
- Visual insight: describe important charts/figures.
- Numerical insight: KPIs, trends, comparisons.
- Section summaries and overall professional+academic summary.
- Actionable recommendations.
- Consistency / risk / issues.
Return JSON with keys:
{
  "summary": { "brief": "...", "professional": "...", "academic": "..." },
  "sections": [ { "title": "...", "summary": "..." } ],
  "tables": [ { "title": "...", "insights": "...", "totals": "...", "anomalies": "..." } ],
  "figures": [ { "description": "...", "insights": "..." } ],
  "numbers": [ { "label": "...", "value": "...", "unit": "...", "context": "..." } ],
  "entities": [ { "type": "person|org|location|other", "name": "...", "role": "...", "context": "..." } ],
  "dates": [ { "value": "...", "context": "..." } ],
  "actions": [ "..." ],
  "risks": [ "..." ],
  "consistency": [ "..." ]
}
Keep it concise but complete. All textual values (not JSON keys) must be written in {language}.
"""


@router.post("/analyze")
async def analyze_pdf(payload: PdfAnalyzeRequest, request: Request) -> Dict[str, Any]:
    user_id = extract_user_id(request)
    raw_language = payload.language
    language = normalize_language(raw_language) or "English"
    logger.info(
        "PDF analyze request",
        extra={"chatId": payload.chat_id, "userId": user_id, "language": language, "fileName": payload.file_name},
    )

    logger.info("PDF analyze download start", extra={"chatId": payload.chat_id, "fileUrl": payload.file_url})
    content, mime = download_file(payload.file_url, max_mb=50, require_pdf=True)
    logger.info("PDF analyze download ok", extra={"chatId": payload.chat_id, "size": len(content), "mime": mime})
    gemini_key = os.getenv("GEMINI_API_KEY")

    prompt = ANALYZE_PROMPT.replace("{language}", language)
    try:
        logger.info("PDF analyze upload start", extra={"chatId": payload.chat_id})
        file_uri = upload_to_gemini_files(content, mime, payload.file_name or "document.pdf", gemini_key)
        logger.info("PDF analyze upload ok", extra={"chatId": payload.chat_id, "fileUri": file_uri})
        response_json = await asyncio.to_thread(
            call_gemini_generate,
            [
                {"file_data": {"mime_type": "application/pdf", "file_uri": file_uri}},
                {"text": f"Language: {language}"},
                {"text": prompt},
            ],
            gemini_key,
        )
        text = extract_text_response(response_json)
        if not text:
            raise RuntimeError("Empty response from Gemini")
        logger.info(
            "PDF analyze gemini response",
            extra={"chatId": payload.chat_id, "preview": text[:500]},
        )

        result = {
            "success": True,
            "chatId": payload.chat_id,
            "analysis": text,
            "language": language,
            "model": "gemini-2.5-flash",
        }

        save_message_to_firestore(
            user_id=user_id,
            chat_id=payload.chat_id,
            content=text,
            metadata={
                "tool": "pdf_analyze",
                "fileUrl": payload.file_url,
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
                metadata={"tool": "pdf_analyze", "error": hexc.detail},
            )
        logger.error("PDF analyze HTTPException", exc_info=hexc, extra={"chatId": payload.chat_id})
        raise
    except Exception as exc:
        logger.error("PDF analyze failed", exc_info=exc)
        msg = get_pdf_error_message("pdf_analyze_failed", language)
        if payload.chat_id:
            save_message_to_firestore(
                user_id=user_id,
                chat_id=payload.chat_id,
                content=msg,
                metadata={"tool": "pdf_analyze", "error": str(exc)},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "pdf_analyze_failed", "message": msg},
        ) from exc

