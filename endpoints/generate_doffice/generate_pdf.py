import json
import logging
import os
import tempfile
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from fpdf import FPDF
from firebase_admin import storage

from core.gemini_prompt import build_system_message, merge_parts_with_system
from schemas import PdfGenRequest
from endpoints.logging.utils_logging import log_gemini_request, log_gemini_response

logger = logging.getLogger("pdf_read_refresh.endpoints.generate_pdf")
router = APIRouter()

SYSTEM_INSTRUCTION = (
    "You are a professional report generator. "
    'Return ONLY valid JSON with this schema: {"title": "...", "sections": [{"heading": "...", "content": "..."}]}. '
    "Each section must have a concise heading and paragraph-style content. "
    "No markdown, no code fences, no extra text outside JSON."
)


def _effective_model() -> str:
    model = os.getenv("GEMINI_PDF_GEN_MODEL") or os.getenv("GEMINI_SEARCH_MODEL") or "models/gemini-2.5-pro"
    if not model.startswith("models/"):
        model = f"models/{model}"
    return model


async def _call_gemini_json(prompt: str, system_message: Optional[str]) -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "gemini_api_key_missing", "message": "GEMINI_API_KEY is required"},
        )

    model = _effective_model()
    url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={api_key}"
    parts = [
        {"text": SYSTEM_INSTRUCTION},
        {"text": f"USER_PROMPT: {prompt}"},
    ]
    effective_parts = merge_parts_with_system(parts, system_message)
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": effective_parts,
            }
        ],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.45,
            "maxOutputTokens": 2048,
        },
    }

    log_gemini_request(
        logger,
        "generate_pdf",
        url=url,
        payload=payload,
        model=model,
    )
    logger.info("Gemini PDF JSON request", extra={"model": model, "prompt_preview": prompt[:200]})

    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(url, json=payload)

    body_preview = (resp.text or "")[:800]
    response_json = resp.json() if resp.text else {}
    log_gemini_response(
        logger,
        "generate_pdf",
        url=url,
        status_code=resp.status_code,
        response=response_json,
    )
    logger.info("Gemini PDF JSON response", extra={"status": resp.status_code, "body_preview": body_preview})

    if not resp.ok:
        raise HTTPException(
            status_code=resp.status_code,
            detail={"success": False, "error": "gemini_pdf_failed", "message": body_preview},
        )

    data = response_json
    parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    if not parts:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "empty_response", "message": "Gemini returned no content"},
        )
    try:
        parsed = json.loads(parts[0].get("text") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "invalid_json", "message": "Gemini returned non-JSON content"},
        )
    return parsed


def _add_font_if_available(pdf: FPDF) -> Optional[str]:
    """
    Try to register a TTF font to avoid Turkish character issues.
    Looks for env FONT_TTF_PATH or ./fonts/DejaVuSans.ttf.
    Returns font family name if added, else None.
    """
    font_path = os.getenv("FONT_TTF_PATH") or os.path.join("fonts", "DejaVuSans.ttf")
    if os.path.exists(font_path):
        try:
            pdf.add_font("DejaVu", "", font_path, uni=True)
            return "DejaVu"
        except Exception:
            logger.warning("Failed to add custom font", exc_info=True)
    return None


def _build_pdf_from_json(doc_data: Dict[str, Any]) -> str:
    title = doc_data.get("title") or "Avenia Raporu"
    sections: List[Dict[str, Any]] = doc_data.get("sections") or []

    pdf = FPDF()
    pdf.add_page()

    custom_font = _add_font_if_available(pdf)
    title_font = custom_font or "Arial"
    body_font = custom_font or "Arial"

    pdf.set_font(title_font, "B", 20)
    pdf.cell(0, 16, title, ln=True, align="C")
    pdf.ln(8)

    for section in sections:
        heading = (section or {}).get("heading") or ""
        content = (section or {}).get("content") or ""

        if heading:
            pdf.set_font(title_font, "B", 14)
            pdf.cell(0, 10, heading, ln=True)

        pdf.set_font(body_font, "", 11)
        pdf.multi_cell(0, 8, str(content))
        pdf.ln(4)

    temp_dir = tempfile.gettempdir()
    filename = f"generated_{uuid.uuid4().hex}.pdf"
    filepath = os.path.join(temp_dir, filename)
    pdf.output(filepath)
    return filepath, filename


@router.post("/generate-pdf")
async def generate_pdf(data: PdfGenRequest):
    logger.info("Generate PDF request received", extra={"prompt_length": len(data.prompt or "")})
    try:
        # 1) Gemini'den yapılandırılmış JSON al
        system_message = build_system_message(
            language=None,
            tone_key=data.tone_key,
            response_style=None,
            include_response_style=False,
            include_followup=False,
        )
        doc_json = await _call_gemini_json(data.prompt, system_message)
        logger.debug("Gemini PDF JSON parsed", extra={"keys": list(doc_json.keys())})

        # 2) PDF dosyasını oluştur
        filepath, filename = _build_pdf_from_json(doc_json)
        logger.info("PDF built", extra={"filepath": filepath})

        # 3) Firebase'e yükle
        bucket = storage.bucket()
        blob = bucket.blob(f"generated_pdfs/{filename}")
        blob.upload_from_filename(filepath)
        blob.make_public()
        logger.info("PDF uploaded to Firebase", extra={"file_url": blob.public_url})

        response_payload = {
            "status": "success",
            "file_url": blob.public_url,
            "title": doc_json.get("title"),
            "section_count": len(doc_json.get("sections") or []),
        }
        logger.debug("Generate PDF response payload", extra={"response": response_payload})
        return response_payload

    except HTTPException:
        logger.exception("Generate PDF failed (HTTPException)")
        raise
    except Exception as e:
        logger.exception("Generate PDF failed")
        raise HTTPException(status_code=500, detail=str(e))
