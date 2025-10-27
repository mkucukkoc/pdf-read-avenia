import asyncio
import io
import logging
import os
from typing import List, Dict, Any

import httpx
import pytesseract
from fastapi import UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from main import app, IMAGE_ENDPOINT
from firebase_admin import firestore

from app.doc_text import (
    detect_file_type,
    extract_text_from_pdf_bytes,
    extract_text_via_ocr,
    split_pdf_by_pages,
    extract_images_from_pdf_bytes,
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
    # >>> EKLENDİ: daha olasılıklı ve açıklayıcı özet + quality/nsfw dahil <<<
    logger.debug("[format_summary_tr] input=%s", {k: data.get(k) for k in ["ai_generated", "confidence", "quality", "nsfw"]})
    conf = float(data.get("confidence", 0.0))
    pct = conf * 100.0
    ai_flag = bool(data.get("ai_generated"))

    # Güven bandı metni
    if conf >= 0.85:
        band = "kuvvetli işaretler"
    elif conf >= 0.60:
        band = "belirgin işaretler"
    elif conf >= 0.40:
        band = "karışık / belirsiz işaretler"
    elif conf >= 0.20:
        band = "zayıf işaretler"
    else:
        band = "çok zayıf işaretler"

    # Eğilim cümlesi (yumuşatılmış)
    if ai_flag:
        lean = "AI üretimine doğru bir eğilim"
        stance = "Metin, yapay zekâ tarafından üretilmiş olabilir"
    else:
        lean = "insan yazımına daha yakın bir eğilim"
        stance = "Metnin AI tarafından üretilmediği yönünde işaretler bulunuyor"

    quality = data.get("quality", "bilinmiyor")
    nsfw = data.get("nsfw", "yok")

    summary = (
        f"Ön değerlendirme: göstergeler %{pct:.1f} düzeyinde {lean} olduğunu gösteriyor ({band}). "
        f"{stance}; ancak bu sonuç kesin bir kanıt değildir. Bağlam, yoğun düzenleme/çeviri veya alıntılar "
        f"analizi etkileyebilir. Kalite: {quality}. NSFW: {nsfw}."
    )
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


# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# EKLENEN: Kısa chunk'ları min_chars_required'e ulaşana kadar birleştir.
def _coalesce_short_chunks(chunks: List[Dict[str, str]], min_chars: int) -> List[Dict[str, str]]:
    coalesced: List[Dict[str, str]] = []
    buf_txt: List[str] = []
    buf_src: List[str] = []
    buf_len = 0

    logger.info("[/check-ai] coalesce: start chunks=%d min_chars=%d", len(chunks), min_chars)
    for ch in chunks:
        t = ch.get("text") or ""
        s = ch.get("source") or "?"
        if len(t) >= min_chars:
            if buf_txt:
                combined = "\n".join(buf_txt)
                coalesced.append({"source": "+".join(buf_src), "text": combined})
                logger.debug("[/check-ai] coalesce flush -> sources=%s total_chars=%d", buf_src, len(combined))
                buf_txt, buf_src, buf_len = [], [], 0
            coalesced.append(ch)
            logger.debug("[/check-ai] coalesce keep -> source=%s len=%d", s, len(t))
        else:
            buf_txt.append(t)
            buf_src.append(s)
            buf_len += len(t)
            logger.debug("[/check-ai] coalesce add -> source=%s buf_len=%d", s, buf_len)
            if buf_len >= min_chars:
                combined = "\n".join(buf_txt)
                coalesced.append({"source": "+".join(buf_src), "text": combined})
                logger.debug("[/check-ai] coalesce emit -> sources=%s total_chars=%d", buf_src, len(combined))
                buf_txt, buf_src, buf_len = [], [], 0

    if buf_txt:
        combined = "\n".join(buf_txt)
        coalesced.append({"source": "+".join(buf_src), "text": combined})
        logger.debug("[/check-ai] coalesce tail -> sources=%s total_chars=%d", buf_src, len(combined))

    logger.info("[/check-ai] coalesce: end new_chunks=%d", len(coalesced))
    return coalesced
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<


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
    images_to_check: List[Dict[str, Any]] = []
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
        pdf_images = extract_images_from_pdf_bytes(raw_bytes)
        logger.info("[/check-ai] pdf_images_count=%s", len(pdf_images))
        for idx, info in enumerate(pdf_images, start=1):
            images_to_check.append({"source": f"page:{info['page']}:image:{idx}", "image": info["image"]})

    elif file_type == "docx":
        logger.info("[/check-ai] extract DOCX sections")
        sections = extract_text_from_docx_bytes(raw_bytes)
        logger.info("[/check-ai] docx_sections_count=%s", len(sections))
        docx_images = extract_images_from_docx(raw_bytes)
        logger.info("[/check-ai] docx_images_count=%s", len(docx_images))
        if ocr_for_office_images:
            logger.info("[/check-ai] DOCX image OCR enabled")
            for idx, img in enumerate(docx_images, start=1):
                try:
                    logger.debug("[/check-ai] OCR on DOCX image idx=%s", idx)
                    img_text = normalize_text(pytesseract.image_to_string(img))
                except Exception as e:  # pylint: disable=broad-except
                    logger.error("[/check-ai] DOCX image OCR error idx=%s err=%s", idx, e)
                    img_text = ""
                if img_text:
                    logger.debug("[/check-ai] DOCX image OCR text_len=%s", len(img_text))
                    sections.append({"source": f"image:{idx}", "text": img_text})
        for idx, img in enumerate(docx_images, start=1):
            images_to_check.append({"source": f"docx_image:{idx}", "image": img})
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
        pptx_images = extract_images_from_pptx(raw_bytes)
        logger.info("[/check-ai] pptx_images_count=%s", len(pptx_images))
        if ocr_for_office_images:
            logger.info("[/check-ai] PPTX image OCR enabled")
            for img in pptx_images:
                try:
                    logger.debug("[/check-ai] OCR on PPTX slide=%s", img.get("slide"))
                    img_text = normalize_text(pytesseract.image_to_string(img["image"]))
                except Exception as e:  # pylint: disable=broad-except
                    logger.error("[/check-ai] PPTX image OCR error slide=%s err=%s", img.get("slide"), e)
                    img_text = ""
                if img_text:
                    logger.debug("[/check-ai] PPTX image OCR text_len=%s", len(img_text))
                    slides.append({"source": f"slide:{img['slide']}", "text": img_text})
        for img in pptx_images:
            images_to_check.append({"source": f"slide:{img['slide']}", "image": img["image"]})
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

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # EKLENEN: Sağlayıcı minimumu (< min_chars_required) yakalamak için birleştir.
    if any(len((c.get("text") or "")) < min_chars_required for c in chunks):
        logger.info("[/check-ai] some chunks < %d chars → coalescing …", min_chars_required)
        before = len(chunks)
        chunks = _coalesce_short_chunks(chunks, min_chars_required)
        logger.info("[/check-ai] after coalesce: chunks=%d (was %d)", len(chunks), before)
    # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
    logger.info("[/check-ai] final_chunks_count=%s", len(chunks))
    total_chars_extracted = sum(len(c["text"]) for c in chunks)
    logger.info("[/check-ai] total_chars_extracted=%s min_required=%s", total_chars_extracted, min_chars_required)

    if total_chars_extracted < min_chars_required:
        logger.warning(
            "[/check-ai] text too short after extraction (len=%d, min=%d)",
            total_chars_extracted, min_chars_required
    )

    user_hint = (
        "Çıkarılan metin minimum eşikten kısa görünüyor; bu yüzden AI tespiti yapılmadı. "
        "Daha sağlıklı analiz için şunları deneyebilirsiniz: "
        "• min_chars_required değerini düşürmek, "
        "• chunk_strategy=none ya da size kullanmak, "
        "• OCR seçeneklerini açmak (PDF/Office), "
        "• belgeye birkaç cümle daha eklemek."
    )

    return JSONResponse(
        status_code=200,
        content={
            "document_type": file_type,
            "insufficient_text": True,
            "message": "Metin miktarı analiz için düşük; sağlayıcıya göndermedik.",
            "hint": user_hint,
            "total_characters": total_chars_extracted,
            "min_chars_required": min_chars_required,
            "chunks_found": len(chunks),
            "image_candidates": len(images_to_check),
            "ocr_used": ocr_used,
        },
    )

    # AI or Not çağrıları
    results: List[Dict[str, Any]] = []
    provider_raw: List[Any] = []
    image_results: List[Dict[str, Any]] = []
    image_provider_raw: List[Any] = []
    total_words = 0
    total_chars = 0
    logger.info("[/check-ai] calling AI or Not for each chunk headers_present=%s", bool(AIORNOT_API_KEY))
    async with httpx.AsyncClient() as client:
        for idx, chunk in enumerate(chunks, start=1):
            wc = word_count(chunk["text"])
            cc = char_count(chunk["text"])
            logger.info("[/check-ai] chunk idx=%s source=%s wc=%s cc=%s text_preview=%s",
                        idx, chunk["source"], wc, cc, (chunk["text"] or "")[:120])

            params = {}
            if external_id:
                params["external_id"] = f"{external_id}-chunk-{idx}"
            data = {"text": chunk["text"]}
            headers = {"Authorization": f"Bearer {AIORNOT_API_KEY}"}

            for attempt in range(3):
                try:
                    logger.info("[/check-ai] → POST attempt=%s idx=%s url=%s params=%s",
                                attempt + 1, idx, "https://api.aiornot.com/v2/text/sync", params)
                    resp = await client.post(
                        "https://api.aiornot.com/v2/text/sync",
                        params=params,
                        data=data,            # form-encoded; JSON gerekiyorsa burada json=data yapabilirsin
                        headers=headers,
                        timeout=60,
                    )
                    logger.info("[/check-ai] ← status=%s idx=%s", resp.status_code, idx)

                    if resp.status_code == 200:
                        rjson = resp.json()
                        logger.debug("[/check-ai] resp_json_preview idx=%s %s", idx, str(rjson)[:300])

                        # --- ŞEMA NORMALİZASYONU ---
                        report = (rjson.get("report") or {})
                        ai_block = (report.get("ai_text") or report.get("ai") or {})  # bazı sürümlerde 'ai' olabilir

                        # is_detected
                        if ai_block.get("is_detected") is not None:
                            is_detected = bool(ai_block.get("is_detected"))
                        else:
                            is_detected = bool(rjson.get("ai_generated", False))

                        # confidence
                        if ai_block.get("confidence") is not None:
                            confidence_val = ai_block.get("confidence")
                        else:
                            confidence_val = rjson.get("confidence", 0.0)
                        try:
                            confidence_norm = float(confidence_val or 0.0)
                        except Exception:
                            confidence_norm = 0.0
                        # --- son ---

                        provider_raw.append(rjson)
                        results.append({
                            "index": idx,
                            "source": chunk["source"],
                            "word_count": wc,
                            "character_count": cc,
                            "is_detected": is_detected,
                            "confidence": confidence_norm,
                            "provider_id": rjson.get("id"),
                            "created_at": rjson.get("created_at"),
                        })
                        logger.info("[/check-ai] result appended idx=%s is_detected=%s confidence=%s",
                                    idx, is_detected, confidence_norm)

                        # Toplamları SADECE başarılı çağrılara ekle
                        total_words += wc
                        total_chars += cc
                        break

                    if 400 <= resp.status_code < 500:
                        body_preview = (await resp.aread())[:300].decode(errors="ignore")
                        logger.warning("[/check-ai] client error status=%s body_preview=%s",
                                       resp.status_code, body_preview)
                        raise HTTPException(status_code=resp.status_code, detail=body_preview)

                except httpx.TimeoutException:
                    logger.warning("[/check-ai] timeout attempt=%s idx=%s", attempt + 1, idx)
                    if attempt == 2:
                        logger.error("[/check-ai] timeout final attempt idx=%s", idx)
                        # zaman aşımında da parçayı atlayıp devam et
                        break

                await asyncio.sleep(2 ** attempt)

            else:
                # for-attempt döngüsünden hiç break edilmediyse (yani başarı yoksa)
                logger.error("[/check-ai] provider service error after retries — skipping idx=%s", idx)
                # bu parça sonuçlara eklenmeden atlanır
                continue

        if images_to_check:
            logger.info("[/check-ai] calling AI or Not for images count=%s", len(images_to_check))
            for iidx, img_info in enumerate(images_to_check, start=1):
                buf = io.BytesIO()
                img_info["image"].save(buf, format="JPEG")
                img_bytes = buf.getvalue()
                for attempt in range(3):
                    try:
                        logger.info("[/check-ai] → IMAGE POST attempt=%s idx=%s source=%s", attempt + 1, iidx, img_info["source"])
                        resp = await client.post(
                            IMAGE_ENDPOINT,
                            headers={"Authorization": f"Bearer {AIORNOT_API_KEY}"},
                            files={"object": ("image.jpg", img_bytes, "image/jpeg")},
                            timeout=60,
                        )
                        logger.info("[/check-ai] ← image status=%s idx=%s", resp.status_code, iidx)

                        if resp.status_code == 200:
                            rjson = resp.json()
                            report = (rjson.get("report") or {})
                            verdict = report.get("verdict")
                            if verdict == "ai":
                                is_detected = True
                                conf = float((report.get("ai", {}) or {}).get("confidence", 0.0) or 0.0)
                            elif verdict == "human":
                                is_detected = False
                                conf = float((report.get("human", {}) or {}).get("confidence", 0.0) or 0.0)
                            else:
                                is_detected = False
                                conf = 0.0
                            image_provider_raw.append(rjson)
                            image_results.append({
                                "index": iidx,
                                "source": img_info["source"],
                                "is_detected": is_detected,
                                "confidence": conf,
                                "provider_id": rjson.get("id"),
                                "created_at": rjson.get("created_at"),
                            })
                            break

                        if 400 <= resp.status_code < 500:
                            body_preview = (await resp.aread())[:300].decode(errors="ignore")
                            logger.warning("[/check-ai] image client error status=%s body_preview=%s", resp.status_code, body_preview)
                            raise HTTPException(status_code=resp.status_code, detail=body_preview)

                    except httpx.TimeoutException:
                        logger.warning("[/check-ai] image timeout attempt=%s idx=%s", attempt + 1, iidx)
                        if attempt == 2:
                            logger.error("[/check-ai] image timeout final attempt idx=%s", iidx)
                            break

                    await asyncio.sleep(2 ** attempt)

                else:
                    logger.error("[/check-ai] image provider service error after retries — skipping idx=%s", iidx)
                    continue
        else:
            logger.info("[/check-ai] no images to analyze")

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
        "image_chunks": image_provider_raw,
        "ai_generated": ai_generated,
        "confidence": confidence,
        "ocr_used": ocr_used,
    }

    # >>> EKLENDİ: provider_raw içinden quality/nsfw (varsa) türet
    agg_quality = None
    agg_nsfw = None
    try:
        qualities = []
        nsfws = []
        for pr in provider_raw:
            rep = (pr.get("report") or {})
            q = rep.get("quality")
            if q is None:
                for _k, _v in rep.items():
                    if isinstance(_v, dict) and "quality" in _v:
                        q = _v.get("quality")
                        break
            if q is not None:
                qualities.append(q)
            n = rep.get("nsfw")
            if n is None:
                for _k, _v in rep.items():
                    if isinstance(_v, dict) and "nsfw" in _v:
                        n = _v.get("nsfw")
                        break
            if n is not None:
                nsfws.append(n)
        agg_quality = qualities[0] if qualities else None
        if nsfws:
            any_true = any(bool(x) and str(x).lower() not in ("0", "false", "none", "no", "yok") for x in nsfws)
            agg_nsfw = "var" if any_true else "yok"
    except Exception as e:  # güvenli tarafta kal
        logger.debug("[/check-ai] quality/nsfw aggregation skipped due to: %s", e)

    q_out = agg_quality if agg_quality is not None else "bilinmiyor"
    n_out = agg_nsfw if agg_nsfw is not None else "yok"

    summary = format_summary_tr({"ai_generated": ai_generated, "confidence": confidence, "quality": q_out, "nsfw": n_out})
    messages = interpret_messages_legacy({"ai_generated": ai_generated, "confidence": confidence, "quality": q_out, "nsfw": n_out})
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
        "image_results": image_results,
        "firebase": firebase_info,
        "provider_raw": merged_raw,
    }
    if not firebase_info.get("saved"):
        logger.warning("[/check-ai] firestore save failed error=%s", firebase_info.get("error"))
        response["firestore_error"] = firebase_info.get("error")

    logger.info("[/check-ai] END 200 response_keys=%s", list(response.keys()))
    return JSONResponse(response)
