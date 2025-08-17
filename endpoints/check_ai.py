import asyncio
import logging
import os
from typing import List, Dict, Any

import httpx
import pytesseract
from fastapi import UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from main import app
from firebase_admin import firestore

from app.doc_text import (
    detect_file_type,
    extract_text_from_pdf_bytes,
    extract_text_via_ocr,
    split_pdf_by_pages,
    extract_text_from_docx_bytes,
    extract_images_from_docx,
    extract_text_from_pptx_bytes,
    extract_images_from_pptx,
    normalize_text,
    split_text_by_size,
    word_count,
    char_count,
)


logger = logging.getLogger(__name__)
MAX_UPLOAD_MB = 25
AIORNOT_API_KEY = os.getenv("AIORNOT_API_KEY", "")


async def rate_limit_check() -> None:
    """Basit rate limit placeholder."""
    return None


def interpret_messages_legacy(data: Dict[str, Any]) -> List[str]:
    messages: List[str] = []
    conf = data.get("confidence", 0.0)
    ai_generated = data.get("ai_generated", False)
    if ai_generated:
        if conf >= 0.85:
            messages.append("🤖 High Likely AI")
        elif conf >= 0.6:
            messages.append("🤖 Medium Likely AI")
        else:
            messages.append("🤖 Low Likely AI")
    else:
        if conf >= 0.85:
            messages.append("🧑 High Likely Human")
        elif conf >= 0.6:
            messages.append("🧑 Medium Likely Human")
        else:
            messages.append("🧑 Low Likely Human")
    quality = data.get("quality")
    if quality:
        messages.append(f"⭐ Quality: {quality}")
    nsfw = data.get("nsfw")
    if nsfw:
        messages.append(f"🚫 NSFW: {nsfw}")
    generator = data.get("generator")
    if generator:
        messages.append(f"🛠️ {generator}")
    return messages


def format_summary_tr(data: Dict[str, Any]) -> str:
    conf = data.get("confidence", 0.0) * 100
    verdict = "yapay zekâ" if data.get("ai_generated") else "insan"
    quality = data.get("quality", "bilinmiyor")
    nsfw = data.get("nsfw", "yok")
    return f"Metnin %{conf:.1f} olasılıkla {verdict} tarafından üretildi. Kalite: {quality}. NSFW: {nsfw}."


def _save_asst_message(user_id: str, chat_id: str, content: str, raw: Any) -> Dict[str, Any]:
    db = firestore.client()
    path = f"users/{user_id}/chats/{chat_id}/messages"
    try:
        ref = db.collection("users").document(user_id).collection("chats").document(chat_id).collection("messages").add({
            "role": "assistant",
            "content": content,
            "meta": {"ai_detect": {"raw": raw}},
        })
        message_id = ref[1].id if isinstance(ref, tuple) else ref.id
        return {"saved": True, "message_id": message_id, "path": path}
    except Exception as e:  # pylint: disable=broad-except
        logger.error("Firestore save error: %s", e)
        return {"saved": False, "message_id": None, "path": path, "error": str(e)}


@app.post("/check-ai")
async def check_ai(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    chat_id: str = Form(...),
    external_id: str | None = Form(None),
    chunk_strategy: str | None = Form(None),
    max_chars_per_chunk: int = Form(200000),
    min_chars_required: int = Form(250),
    ocr_for_pdf: bool = Form(True),
    ocr_for_office_images: bool = Form(False),
    office_legacy_convert: bool = Form(False),
):
    await rate_limit_check()

    raw_bytes = await file.read()
    if len(raw_bytes) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Dosya boyutu çok büyük")

    file_type = detect_file_type(file.filename, file.content_type)
    if file_type == "unknown":
        raise HTTPException(status_code=415, detail="Desteklenmeyen dosya tipi")
    if file_type == "ppt" and not office_legacy_convert:
        raise HTTPException(status_code=415, detail="Legacy PPT dosyaları desteklenmiyor")

    strategy_defaults = {"pdf": "size", "docx": "sections", "pptx": "slides"}
    chunk_strategy = chunk_strategy or strategy_defaults.get(file_type, "size")
    if chunk_strategy not in {"none", "pages", "size", "slides", "sections"}:
        raise HTTPException(status_code=400, detail="Geçersiz chunk_strategy")

    max_chars_per_chunk = min(max_chars_per_chunk, 500_000)

    # Metin çıkarımı
    chunks: List[Dict[str, str]] = []
    ocr_used = False

    if file_type == "pdf":
        text = extract_text_from_pdf_bytes(raw_bytes)
        if len(text.strip()) < min_chars_required and ocr_for_pdf:
            text = extract_text_via_ocr(raw_bytes, None)
            ocr_used = True
        text = normalize_text(text)
        if chunk_strategy == "pages":
            chunks = split_pdf_by_pages(raw_bytes, max_chars_per_chunk)
        else:
            chunks = [{"source": "document", "text": text}]

    elif file_type == "docx":
        sections = extract_text_from_docx_bytes(raw_bytes)
        if ocr_for_office_images:
            for idx, img in enumerate(extract_images_from_docx(raw_bytes), start=1):
                try:
                    img_text = normalize_text(pytesseract.image_to_string(img))
                except Exception:  # pylint: disable=broad-except
                    img_text = ""
                if img_text:
                    sections.append({"source": f"image:{idx}", "text": img_text})
        if chunk_strategy == "sections":
            chunks = sections
        else:
            joined = normalize_text("\n".join(sec["text"] for sec in sections))
            chunks = [{"source": "document", "text": joined}]

    elif file_type == "pptx":
        slides = extract_text_from_pptx_bytes(raw_bytes)
        if ocr_for_office_images:
            for img in extract_images_from_pptx(raw_bytes):
                try:
                    img_text = normalize_text(pytesseract.image_to_string(img["image"]))
                except Exception:  # pylint: disable=broad-except
                    img_text = ""
                if img_text:
                    slides.append({"source": f"slide:{img['slide']}", "text": img_text})
        if chunk_strategy == "slides":
            chunks = slides
        else:
            joined = normalize_text("\n".join(slide["text"] for slide in slides))
            chunks = [{"source": "document", "text": joined}]
    else:
        raise HTTPException(status_code=415, detail="Desteklenmeyen dosya tipi")

    # size veya none stratejileri
    if chunk_strategy == "size":
        joined = normalize_text("\n".join(c["text"] for c in chunks))
        chunks = [{"source": f"size:{i+1}", "text": part} for i, part in enumerate(split_text_by_size(joined, max_chars_per_chunk))]
    elif chunk_strategy == "none":
        joined = normalize_text("\n".join(c["text"] for c in chunks))
        chunks = [{"source": "document", "text": joined}]
    else:
        # ensure pieces not exceeding max
        new_chunks: List[Dict[str, str]] = []
        for c in chunks:
            for part in split_text_by_size(c["text"], max_chars_per_chunk):
                new_chunks.append({"source": c["source"], "text": part})
        chunks = new_chunks

    total_chars_extracted = sum(len(c["text"]) for c in chunks)
    if total_chars_extracted < min_chars_required:
        raise HTTPException(status_code=400, detail="Metin çıkarılamadı veya çok kısa. OCR deneyin / resim ağırlıklı olabilir.")

    # AI or Not çağrıları
    results: List[Dict[str, Any]] = []
    provider_raw: List[Any] = []
    total_words = 0
    total_chars = 0
    async with httpx.AsyncClient() as client:
        for idx, chunk in enumerate(chunks, start=1):
            wc = word_count(chunk["text"])
            cc = char_count(chunk["text"])
            total_words += wc
            total_chars += cc
            params = {}
            if external_id:
                params["external_id"] = f"{external_id}-chunk-{idx}"
            data = {"text": chunk["text"]}
            headers = {"Authorization": f"Bearer {AIORNOT_API_KEY}"}
            for attempt in range(3):
                try:
                    resp = await client.post(
                        "https://api.aiornot.com/v2/text/sync",
                        params=params,
                        data=data,
                        headers=headers,
                        timeout=60,
                    )
                    if resp.status_code == 200:
                        rjson = resp.json()
                        provider_raw.append(rjson)
                        results.append({
                            "index": idx,
                            "source": chunk["source"],
                            "word_count": wc,
                            "character_count": cc,
                            "is_detected": rjson.get("ai_generated", False),
                            "confidence": rjson.get("confidence", 0.0),
                            "provider_id": rjson.get("id"),
                            "created_at": rjson.get("created_at"),
                        })
                        break
                    if 400 <= resp.status_code < 500:
                        raise HTTPException(status_code=resp.status_code, detail=resp.text)
                except httpx.TimeoutException:
                    if attempt == 2:
                        raise HTTPException(status_code=504, detail="AI or Not zaman aşımı")
                await asyncio.sleep(2 ** attempt)
            else:
                raise HTTPException(status_code=502, detail="AI or Not hizmet hatası")

    ai_weight = sum(r["word_count"] for r in results if r["is_detected"])
    human_weight = total_words - ai_weight
    ai_generated = ai_weight >= human_weight
    confidence = (
        sum(r["confidence"] * r["word_count"] for r in results) / total_words if total_words else 0.0
    )

    merged_raw = {
        "chunks": provider_raw,
        "ai_generated": ai_generated,
        "confidence": confidence,
        "ocr_used": ocr_used,
    }

    summary = format_summary_tr({"ai_generated": ai_generated, "confidence": confidence})
    messages = interpret_messages_legacy({"ai_generated": ai_generated, "confidence": confidence})
    content = summary + "\nMessages: " + ", ".join(messages)
    firebase_info = _save_asst_message(user_id, chat_id, content, merged_raw)

    response = {
        "document_type": file_type,
        "ai_generated": ai_generated,
        "confidence": confidence,
        "total_words": total_words,
        "total_characters": total_chars,
        "chunks": results,
        "firebase": firebase_info,
        "provider_raw": merged_raw,
    }
    if not firebase_info.get("saved"):
        response["firestore_error"] = firebase_info.get("error")

    return JSONResponse(response)


