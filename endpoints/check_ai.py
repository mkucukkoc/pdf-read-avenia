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
    logger.debug("[rate_limit_check] called")
    return None


def interpret_messages_legacy(data: Dict[str, Any]) -> List[str]:
    logger.debug("[interpret_messages_legacy] input=%s", {k: data.get(k) for k in ["ai_generated", "confidence", "quality", "nsfw", "generator"]})
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
    logger.debug("[interpret_messages_legacy] output=%s", messages)
    return messages


def format_summary_tr(data: Dict[str, Any]) -> str:
    logger.debug("[format_summary_tr] input=%s", {k: data.get(k) for k in ["ai_generated", "confidence", "quality", "nsfw"]})
    conf = data.get("confidence", 0.0) * 100
    verdict = "yapay zekâ" if data.get("ai_generated") else "insan"
    quality = data.get("quality", "bilinmiyor")
    nsfw = data.get("nsfw", "yok")
    summary = f"Metnin %{conf:.1f} olasılıkla {verdict} tarafından üretildi. Kalite: {quality}. NSFW: {nsfw}."
    logger.debug("[format_summary_tr] output=%s", summary)
    return summary


def _save_asst_message(user_id: str, chat_id: str, content: str, raw: Any) -> Dict[str, Any]:
    logger.info("[_save_asst_message] user_id=%s chat_id=%s content_preview=%s", user_id, chat_id, (content or "")[:200])
    db = firestore.client()
    path = f"users/{user_id}/chats/{chat_id}/messages"
    try:
        ref = db.collection("users").document(user_id).collection("chats").document(chat_id).collection("messages").add({
            "role": "assistant",
            "content": content,
            "meta": {"ai_detect": {"raw": raw}},
        })
        message_id = ref[1].id if isinstance(ref, tuple) else ref.id
        logger.info("[_save_asst_message] saved=True message_id=%s path=%s", message_id, path)
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
    logger.info("[/check-ai] START filename=%s content_type=%s user_id=%s chat_id=%s external_id=%s chunk_strategy=%s max_chars_per_chunk=%s min_chars_required=%s ocr_for_pdf=%s ocr_for_office_images=%s office_legacy_convert=%s api_key_present=%s",
                getattr(file, "filename", None), getattr(file, "content_type", None), user_id, chat_id, external_id, chunk_strategy, max_chars_per_chunk, min_chars_required, ocr_for_pdf, ocr_for_office_images, office_legacy_convert, bool(AIORNOT_API_KEY))

    await rate_limit_check()

    raw_bytes = await file.read()
    logger.info("[/check-ai] file_read bytes=%s", len(raw_bytes))
    if len(raw_bytes) > MAX_UPLOAD_MB * 1024 * 1024:
        logger.warning("[/check-ai] file too large len=%s limit_MB=%s", len(raw_bytes), MAX_UPLOAD_MB)
        raise HTTPException(status_code=413, detail="Dosya boyutu çok büyük")

    file_type = detect_file_type(file.filename, file.content_type)
    logger.info("[/check-ai] detected file_type=%s", file_type)
    if file_type == "unknown":
        logger.warning("[/check-ai] unsupported file type")
        raise HTTPException(status_code=415, detail="Desteklenmeyen dosya tipi")
    if file_type == "ppt" and not office_legacy_convert:
        logger.warning("[/check-ai] legacy ppt without convert flag")
        raise HTTPException(status_code=415, detail="Legacy PPT dosyaları desteklenmiyor")

    strategy_defaults = {"pdf": "size", "docx": "sections", "pptx": "slides"}
    chunk_strategy = chunk_strategy or strategy_defaults.get(file_type, "size")
    logger.info("[/check-ai] resolved chunk_strategy=%s", chunk_strategy)
    if chunk_strategy not in {"none", "pages", "size", "slides", "sections"}:
        logger.warning("[/check-ai] invalid chunk_strategy=%s", chunk_strategy)
        raise HTTPException(status_code=400, detail="Geçersiz chunk_strategy")

    max_chars_per_chunk = min(max_chars_per_chunk, 500_000)
    logger.info("[/check-ai] max_chars_per_chunk_capped=%s", max_chars_per_chunk)

    # Metin çıkarımı
    chunks: List[Dict[str, str]] = []
    ocr_used = False

    if file_type == "pdf":
        logger.info("[/check-ai] extract PDF text")
        text = extract_text_from_pdf_bytes(raw_bytes)
        logger.debug("[/check-ai] pdf_text_len=%s", len(text or ""))
        if len(text.strip()) < min_chars_required and ocr_for_pdf:
            logger.info("[/check-ai] PDF text too short (%s < %s), using OCR", len((text or "").strip()), min_chars_required)
            text = extract_text_via_ocr(raw_bytes, None)
            ocr_used = True
            logger.debug("[/check-ai] pdf_ocr_text_len=%s", len(text or ""))
        text = normalize_text(text)
        logger.debug("[/check-ai] pdf_text_len_after_normalize=%s", len(text or ""))
        if chunk_strategy == "pages":
            logger.info("[/check-ai] splitting PDF by pages with max_chars=%s", max_chars_per_chunk)
            chunks = split_pdf_by_pages(raw_bytes, max_chars_per_chunk)
        else:
            chunks = [{"source": "document", "text": text}]
        logger.info("[/check-ai] pdf_chunks_count=%s", len(chunks))

    elif file_type == "docx":
        logger.info("[/check-ai] extract DOCX sections")
        sections = extract_text_from_docx_bytes(raw_bytes)
        logger.info("[/check-ai] docx_sections_count=%s", len(sections))
        if ocr_for_office_images:
            logger.info("[/check-ai] DOCX image OCR enabled")
            for idx, img in enumerate(extract_images_from_docx(raw_bytes), start=1):
                try:
                    logger.debug("[/check-ai] OCR on DOCX image idx=%s", idx)
                    img_text = normalize_text(pytesseract.image_to_string(img))
                except Exception as e:  # pylint: disable=broad-except
                    logger.error("[/check-ai] DOCX image OCR error idx=%s err=%s", idx, e)
                    img_text = ""
                if img_text:
                    logger.debug("[/check-ai] DOCX image OCR text_len=%s", len(img_text))
                    sections.append({"source": f"image:{idx}", "text": img_text})
        if chunk_strategy == "sections":
            chunks = sections
        else:
            joined = normalize_text("\n".join(sec["text"] for sec in sections))
            logger.debug("[/check-ai] docx_joined_len=%s", len(joined))
            chunks = [{"source": "document", "text": joined}]
        logger.info("[/check-ai] docx_chunks_count=%s", len(chunks))

    elif file_type == "pptx":
        logger.info("[/check-ai] extract PPTX slides")
        slides = extract_text_from_pptx_bytes(raw_bytes)
        logger.info("[/check-ai] pptx_slides_count=%s", len(slides))
        if ocr_for_office_images:
            logger.info("[/check-ai] PPTX image OCR enabled")
            for img in extract_images_from_pptx(raw_bytes):
                try:
                    logger.debug("[/check-ai] OCR on PPTX slide=%s", img.get("slide"))
                    img_text = normalize_text(pytesseract.image_to_string(img["image"]))
                except Exception as e:  # pylint: disable=broad-except
                    logger.error("[/check-ai] PPTX image OCR error slide=%s err=%s", img.get("slide"), e)
                    img_text = ""
                if img_text:
                    logger.debug("[/check-ai] PPTX image OCR text_len=%s", len(img_text))
                    slides.append({"source": f"slide:{img['slide']}", "text": img_text})
        if chunk_strategy == "slides":
            chunks = slides
        else:
            joined = normalize_text("\n".join(slide["text"] for slide in slides))
            logger.debug("[/check-ai] pptx_joined_len=%s", len(joined))
            chunks = [{"source": "document", "text": joined}]
        logger.info("[/check-ai] pptx_chunks_count=%s", len(chunks))
    else:
        logger.warning("[/check-ai] unsupported file type (post-detect guard) type=%s", file_type)
        raise HTTPException(status_code=415, detail="Desteklenmeyen dosya tipi")

    # size veya none stratejileri
    if chunk_strategy == "size":
        logger.info("[/check-ai] chunk_strategy=size joining and splitting with max_chars=%s", max_chars_per_chunk)
        joined = normalize_text("\n".join(c["text"] for c in chunks))
        logger.debug("[/check-ai] joined_len_before_size_split=%s", len(joined))
        chunks = [{"source": f"size:{i+1}", "text": part} for i, part in enumerate(split_text_by_size(joined, max_chars_per_chunk))]
    elif chunk_strategy == "none":
        logger.info("[/check-ai] chunk_strategy=none joining to single chunk")
        joined = normalize_text("\n".join(c["text"] for c in chunks))
        logger.debug("[/check-ai] joined_len_none=%s", len(joined))
        chunks = [{"source": "document", "text": joined}]
    else:
        # ensure pieces not exceeding max
        logger.info("[/check-ai] chunk_strategy=%s ensuring max size per chunk=%s", chunk_strategy, max_chars_per_chunk)
        new_chunks: List[Dict[str, str]] = []
        for c in chunks:
            for part in split_text_by_size(c["text"], max_chars_per_chunk):
                new_chunks.append({"source": c["source"], "text": part})
        chunks = new_chunks

    logger.info("[/check-ai] final_chunks_count=%s", len(chunks))
    total_chars_extracted = sum(len(c["text"]) for c in chunks)
    logger.info("[/check-ai] total_chars_extracted=%s min_required=%s", total_chars_extracted, min_chars_required)
    if total_chars_extracted < min_chars_required:
        logger.warning("[/check-ai] text too short after extraction")
        raise HTTPException(status_code=400, detail="Metin çıkarılamadı veya çok kısa. OCR deneyin / resim ağırlıklı olabilir.")

    # AI or Not çağrıları
    results: List[Dict[str, Any]] = []
    provider_raw: List[Any] = []
    total_words = 0
    total_chars = 0
    logger.info("[/check-ai] calling AI or Not for each chunk headers_present=%s", bool(AIORNOT_API_KEY))
    async with httpx.AsyncClient() as client:
        for idx, chunk in enumerate(chunks, start=1):
            wc = word_count(chunk["text"])
            cc = char_count(chunk["text"])
            total_words += wc
            total_chars += cc
            logger.info("[/check-ai] chunk idx=%s source=%s wc=%s cc=%s text_preview=%s", idx, chunk["source"], wc, cc, (chunk["text"] or "")[:120])
            params = {}
            if external_id:
                params["external_id"] = f"{external_id}-chunk-{idx}"
            data = {"text": chunk["text"]}
            headers = {"Authorization": f"Bearer {AIORNOT_API_KEY}"}
            for attempt in range(3):
                try:
                    logger.info("[/check-ai] → POST attempt=%s idx=%s url=%s params=%s", attempt + 1, idx, "https://api.aiornot.com/v2/text/sync", params)
                    resp = await client.post(
                        "https://api.aiornot.com/v2/text/sync",
                        params=params,
                        data=data,
                        headers=headers,
                        timeout=60,
                    )
                    logger.info("[/check-ai] ← status=%s idx=%s", resp.status_code, idx)
                    if resp.status_code == 200:
                        rjson = resp.json()
                        logger.debug("[/check-ai] resp_json_preview idx=%s %s", idx, str(rjson)[:300])
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
                        logger.info("[/check-ai] result appended idx=%s is_detected=%s confidence=%s", idx, results[-1]["is_detected"], results[-1]["confidence"])
                        break
                    if 400 <= resp.status_code < 500:
                        logger.warning("[/check-ai] client error status=%s body_preview=%s", resp.status_code, (resp.text or "")[:300])
                        raise HTTPException(status_code=resp.status_code, detail=resp.text)
                except httpx.TimeoutException:
                    logger.warning("[/check-ai] timeout attempt=%s idx=%s", attempt + 1, idx)
                    if attempt == 2:
                        logger.error("[/check-ai] timeout final attempt idx=%s", idx)
                        raise HTTPException(status_code=504, detail="AI or Not zaman aşımı")
                await asyncio.sleep(2 ** attempt)
            else:
                logger.error("[/check-ai] provider service error after retries idx=%s", idx)
                raise HTTPException(status_code=502, detail="AI or Not hizmet hatası")

    ai_weight = sum(r["word_count"] for r in results if r["is_detected"])
    human_weight = total_words - ai_weight
    ai_generated = ai_weight >= human_weight
    confidence = (
        sum(r["confidence"] * r["word_count"] for r in results) / total_words if total_words else 0.0
    )
    logger.info("[/check-ai] aggregation total_words=%s total_chars=%s ai_weight=%s human_weight=%s ai_generated=%s confidence=%s",
                total_words, total_chars, ai_weight, human_weight, ai_generated, confidence)

    merged_raw = {
        "chunks": provider_raw,
        "ai_generated": ai_generated,
        "confidence": confidence,
        "ocr_used": ocr_used,
    }

    summary = format_summary_tr({"ai_generated": ai_generated, "confidence": confidence})
    messages = interpret_messages_legacy({"ai_generated": ai_generated, "confidence": confidence})
    content = summary + "\nMessages: " + ", ".join(messages)
    logger.info("[/check-ai] summary_len=%s messages_count=%s", len(summary), len(messages))
    firebase_info = _save_asst_message(user_id, chat_id, content, merged_raw)
    logger.info("[/check-ai] firebase_info=%s", firebase_info)

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
        logger.warning("[/check-ai] firestore save failed error=%s", firebase_info.get("error"))
        response["firestore_error"] = firebase_info.get("error")

    logger.info("[/check-ai] END 200 response_keys=%s", list(response.keys()))
    return JSONResponse(response)
