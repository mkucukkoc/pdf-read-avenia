import json
import logging
import base64
import os
import random
from typing import Optional, Dict, Any, Tuple

import httpx
from fastapi import Body, Query, APIRouter, HTTPException
from fastapi.responses import JSONResponse

from core.useChatPersistence import chat_persistence
from core.language_support import (
    normalize_language,
    build_ai_detection_messages,
    format_ai_detection_summary,
    nsfw_flag_from_value,
    quality_flag_from_value,
)

logger = logging.getLogger("pdf_read_refresh.endpoints.analyze_image")
FAIL_MSG = "Görsel şu anda analiz edilemiyor, lütfen tekrar deneyin."
IMAGE_ENDPOINT = os.getenv("IMAGE_ENDPOINT", "https://api.aiornot.com/v1/reports/image")
API_KEY = os.getenv("AIORNOT_API_KEY", "")
router = APIRouter()


def decode_base64_maybe_data_url(data: str) -> bytes:
    """
    Supports raw base64 or data URLs like data:image/png;base64,....
    """
    if not data:
        raise ValueError("empty data")
    if data.startswith("data:"):
        comma = data.find(",")
        if comma == -1:
            raise ValueError("Invalid data URL")
        data = data[comma + 1 :]
    return base64.b64decode(data)


def _save_asst_message(user_id: str, chat_id: str, content: str, raw: dict, language: Optional[str]):
    if not user_id or not chat_id:
        return {"saved": False}
    try:
        message_id = chat_persistence.save_assistant_message(
            user_id=user_id,
            chat_id=chat_id,
            content=content,
            metadata={
                "language": normalize_language(language),
                "tool": "ai_or_not_analysis"
            }
        )
        return {"saved": True, "message_id": message_id}
    except Exception as e:
        logger.warning("Failed to save message to Firestore", exc_info=e)
        return {"saved": False, "error": str(e)}


def _build_messages(verdict: Optional[str], confidence: float, quality, nsfw, language: Optional[str]):
    ai_conf = confidence if verdict == "ai" else max(0.0, 1.0 - confidence)
    human_conf = confidence if verdict == "human" else max(0.0, 1.0 - confidence)

    # Custom ladder to match product expectations
    # AI heavy: >= 99% → "High Likely AI"
    # AI likely: >= 80% → "Likely AI"
    # Otherwise lean to human
    if ai_conf >= 0.99:
        return ["High Likely AI", "Good", "No"]
    if ai_conf >= 0.8:
        return ["Likely AI", "Good", "No"]
    if human_conf >= ai_conf:
        return ["Likely Human", "Good", "No"]

    return build_ai_detection_messages(
        verdict,
        ai_conf,
        human_conf,
        quality_flag_from_value(quality),
        nsfw_flag_from_value(nsfw),
        language=language,
    )


_CUSTOM_SUMMARY_MAP = {
    "tr": {
        "very_high_ai": [
            "Bu görsel, %98'in üzerinde bir olasılıkla yapay zeka tarafından üretilmiştir. Yapısal tutarlılık yüksek ve AI üretimine özgü desenler tespit edilmiştir. NSFW açısından risk görünmemektedir.",
            "Analiz sonuçlarına göre bu görsel büyük ölçüde (%99+) yapay zeka üretimidir. Görsel kalite dengeli, hassas içerik tespit edilmemiştir.",
            "Bu görselin yapay zeka tarafından oluşturulmuş olma ihtimali son derece yüksektir. Model, AI üretimine özgü güçlü sinyaller algılamıştır."
        ],
        "high_ai": [
            "Görsel, yüksek olasılıkla (%{ai_pct}) yapay zeka tarafından üretilmiştir. İnsan üretimi olasılığı %{human_pct} seviyesindedir.",
            "Yapılan analiz, bu görselin büyük ihtimalle yapay zeka kaynaklı olduğunu göstermektedir. AI olasılığı %{ai_pct}.",
            "Bu görselde yapay zeka üretimine işaret eden güçlü göstergeler bulunmaktadır (%{ai_pct}). NSFW riski tespit edilmemiştir."
        ],
        "uncertain": [
            "Bu görsel için net bir sonuca varılamamıştır. Yapay zeka olasılığı %{ai_pct}, insan üretimi olasılığı %{human_pct} olarak hesaplanmıştır.",
            "Analiz sonuçları kararsızdır. Görsel hem yapay zeka hem de insan üretimi özellikleri taşımaktadır.",
            "Görselin kökeni belirsizdir. AI ve insan üretimi sinyalleri birbirine yakındır."
        ],
        "likely_human": [
            "Bu görselin insan tarafından üretilmiş olma ihtimali daha yüksektir. İnsan olasılığı %{human_pct}, AI olasılığı %{ai_pct}.",
            "Analiz sonuçları, görselin büyük olasılıkla insan üretimi olduğunu göstermektedir.",
            "Bu görsel, insan üretimine daha yakın özellikler sergilemektedir."
        ],
        "human": [
            "Bu görsel büyük olasılıkla (%{human_pct}) gerçek bir fotoğraf veya insan üretimidir. Yapay zeka üretimine dair güçlü bir bulgu bulunmamaktadır.",
            "Analiz sonuçlarına göre bu görsel insan üretimi gibi görünmektedir. AI olasılığı oldukça düşüktür.",
            "Görsel, doğal fotoğraf özellikleri göstermekte ve yapay zeka üretimi izleri taşımamaktadır."
        ]
    },
    "en": {
        "very_high_ai": [
            "This image is over 98% likely to be AI-generated. Structural consistency is high and patterns specific to AI generation have been detected. No NSFW risk.",
            "According to the analysis results, this image is largely (99%+) AI-generated. Visual quality is balanced, no sensitive content detected.",
            "The probability of this image being created by AI is extremely high. The model detected strong signals typical of AI generation."
        ],
        "high_ai": [
            "The image is likely (%{ai_pct}) AI-generated. The probability of human production is at the %{human_pct} level.",
            "The analysis shows that this image is likely originating from AI. AI probability %{ai_pct}.",
            "There are strong indicators pointing to AI generation in this image (%{ai_pct}). No NSFW risk detected."
        ],
        "uncertain": [
            "No clear conclusion could be reached for this image. AI probability is %{ai_pct}, and human production probability is %{human_pct}.",
            "Analysis results are uncertain. The image bears characteristics of both AI and human production.",
            "The origin of the image is ambiguous. AI and human production signals are close to each other."
        ],
        "likely_human": [
            "It is more likely that this image was produced by a human. Human probability %{human_pct}, AI probability %{ai_pct}.",
            "Analysis results indicate that the image is most likely human-produced.",
            "This image exhibits characteristics closer to human production."
        ],
        "human": [
            "This image is most likely (%{human_pct}) a real photo or human-produced. No strong findings of AI generation.",
            "According to analysis results, this image appears to be human-produced. AI probability is quite low.",
            "The image shows natural photo characteristics and bears no traces of AI generation."
        ]
    }
}


def _build_summary(verdict: Optional[str], ai_conf: float, human_conf: float, quality, nsfw, language: Optional[str]):
    lang = normalize_language(language)
    
    ai_pct = round(ai_conf * 100)
    human_pct = round(human_conf * 100)
    
    # %99+ iyileştirmesi
    if ai_pct >= 99:
        ai_pct_str = "%99+"
    else:
        ai_pct_str = f"%{ai_pct}"
        
    human_pct_str = f"%{human_pct}"

    # 1️⃣ Confidence seviyelerine göre anahtar seçimi (Geliştirilmiş Mantık)
    if verdict not in ("ai", "human"):
        key = "uncertain"
    elif ai_pct >= 98:
        key = "very_high_ai"
    elif ai_pct >= 90:
        key = "high_ai"
    elif abs(ai_pct - human_pct) <= 10:
        key = "uncertain"
    elif human_pct >= 90:
        key = "human"
    else:
        key = "likely_human"

    pool = _CUSTOM_SUMMARY_MAP.get(lang, _CUSTOM_SUMMARY_MAP["en"])
    messages = pool.get(key, _CUSTOM_SUMMARY_MAP["en"][key])
    
    # Havuzdan rastgele seç
    selected_text = random.choice(messages)
    
    # Placeholder'ları doldur
    filled_text = selected_text.replace("%{ai_pct}", ai_pct_str).replace("%{human_pct}", human_pct_str)

    # 3️⃣ NSFW & Quality Bilgisini Suffix Olarak Ekle
    suffix = ""
    if lang == "tr":
        if nsfw:
            suffix += " ⚠️ Görsel hassas/NSFW içerik barındırabilir."
        else:
            suffix += " ✅ Hassas içerik riski tespit edilmedi."
        
        if quality is False:
            suffix += " Görsel kalitesi düşük olabilir."
        elif quality is None:
            suffix += " Görsel kalite bilgisi sınırlı."
    else:
        # English fallback suffix
        if nsfw:
            suffix += " ⚠️ Image may contain sensitive/NSFW content."
        else:
            suffix += " ✅ No sensitive content risk detected."
        
        if quality is False:
            suffix += " Image quality may be low."
        elif quality is None:
            suffix += " Image quality information is limited."

    return filled_text + suffix


def _save_failure_message(user_id: str, chat_id: str, language: Optional[str], message: str, raw: Optional[dict] = None):
    _save_asst_message(user_id, chat_id, message, raw or {"error": message}, language)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _pct(value: Optional[float]) -> Optional[int]:
    if value is None:
        return None
    return max(0, min(100, round(value * 100)))


def _friendly_generator_name(key: str) -> str:
    mapping = {
        "midjourney": "Midjourney",
        "dall_e": "DALL·E",
        "stable_diffusion": "Stable Diffusion",
        "this_person_does_not_exist": "This Person Does Not Exist",
        "adobe_firefly": "Adobe Firefly",
        "flux": "Flux",
        "four_o": "4.0",
    }
    return mapping.get(key, key.replace("_", " ").title())


def _pick_generator(generator_data: Dict[str, Any]) -> Optional[Tuple[str, Optional[int]]]:
    best = None
    for name, data in generator_data.items():
        conf = _pct(_safe_float((data or {}).get("confidence")))
        is_detected = (data or {}).get("is_detected", False)
        if conf is None:
            continue
        # Prefer detected items; otherwise pick the highest confidence
        score = conf + (5 if is_detected else 0)
        if best is None or score > best[2]:
            best = (name, conf, score, is_detected)
    if best:
        return _friendly_generator_name(best[0]), best[1]
    return None


def _build_analysis_message(result: Dict[str, Any], language: str) -> str:
    # Legacy function kept for reference or other uses if needed
    lang = language or "tr"
    report = result.get("report") or {}
    ai_generated = report.get("ai_generated") or {}
    ai_conf_raw = _safe_float((ai_generated.get("ai") or {}).get("confidence"))
    human_conf_raw = _safe_float((ai_generated.get("human") or {}).get("confidence"))
    ai_pct = _pct(ai_conf_raw)
    human_pct = _pct(human_conf_raw)
    verdict = ai_generated.get("verdict")

    nsfw = (report.get("nsfw") or {}).get("is_detected")
    quality = (report.get("quality") or {}).get("is_detected")

    deepfake_section = report.get("deepfake") or {}
    deepfake_flag = deepfake_section.get("is_detected")
    deepfake_conf = _pct(_safe_float(deepfake_section.get("confidence")))

    generator_pick = _pick_generator(ai_generated.get("generator") or {})

    meta = report.get("meta") or {}
    width = meta.get("width")
    height = meta.get("height")
    img_format = meta.get("format")

    logger.debug(
        "Parsed AI or Not report",
        extra={
            "ai_pct": ai_pct,
            "human_pct": human_pct,
            "verdict": verdict,
            "nsfw": nsfw,
            "quality": quality,
            "deepfake_flag": deepfake_flag,
            "deepfake_conf": deepfake_conf,
            "generator_pick": generator_pick,
            "meta": {"width": width, "height": height, "format": img_format},
        },
    )

    def t(key: str) -> str:
        tr_map = {
            "title": "🔍 Görsel Analiz Sonucu",
            "general_label": "• Genel Değerlendirme:",
            "ai_label": "• Yapay Zekâ Olasılığı:",
            "human_label": "• Gerçek Fotoğraf Olasılığı:",
            "nsfw_label": "• NSFW / Hassas İçerik Durumu:",
            "share_label": "• Güven ve Paylaşım Değerlendirmesi:",
            "summary_label": "• Özet:",
            "generator_label": "• Olası Üretici:",
            "deepfake_label": "• Deepfake Kontrolü:",
            "quality_label": "• Kalite Analizi:",
            "general_ai_high": "Analizlere göre görsel yüksek olasılıkla yapay zekâ tarafından üretilmiş görünüyor.",
            "general_human": "Analizlere göre görselin insan tarafından üretilmiş/çekilmiş olma ihtimali daha yüksek görünüyor.",
            "general_unknown": "Analiz verisi sınırlı; kesin olmayan ön değerlendirme paylaşıldı.",
            "general_mixed": "Analiz sonuçları karışık; model net bir yön göstermiyor, temkinli olun.",
            "ai_line": "Yapay zekâ ile üretilmiş olma ihtimali %{pct}. Bu değer model tahminidir ve kesinlik ifade etmez.",
            "ai_missing": "Yapay zekâ olasılık değeri raporda belirtilmedi.",
            "human_line": "Gerçek fotoğraf olma ihtimali %{pct} olarak raporlandı.",
            "human_missing": "Gerçek fotoğraf olasılığına dair bir değer raporda bulunmuyor.",
            "nsfw_true": "Hassas/NSFW içerik tespit edilmiş olabilir, paylaşırken dikkatli olun.",
            "nsfw_false": "NSFW veya hassas içerik tespit edilmedi.",
            "nsfw_unknown": "NSFW kontrol bilgisi paylaşılmadı.",
            "quality_true": "Kalite analizi tamamlandı; görselde ek bir sorun raporlanmadı.",
            "quality_false": "Kalite analizi, görselde bazı sorunlar olabileceğini belirtiyor.",
            "quality_unknown": "Kalite analizi bilgisi raporda yer almıyor.",
            "deepfake_true_conf": "Deepfake olasılığı %{pct} seviyesinde ve şüpheli olabilir; dikkatli paylaşın.",
            "deepfake_true": "Deepfake şüphesi bildirildi; paylaşımda temkinli olun.",
            "deepfake_false_conf": "Deepfake olasılığı %{pct}; değer düşükse risk sınırlıdır, ancak kesinlik yoktur.",
            "deepfake_false": "Deepfake için şüphe raporlanmadı.",
            "share_safe": "İçerik güvenliği açısından paylaşım için uygundur; yine de AI üretimi olasılığını göz önünde bulundurun.",
            "share_caution": "Paylaşmadan önce içerik güvenliği ve olası yanlış yönlendirme risklerini göz önünde bulundurun.",
            "summary_ai": "Bu görsel yüksek olasılıkla yapay zekâ üretimi ve içerik güvenliği açısından ek risk görülmüyor.",
            "summary_human": "Bu görsel insan üretimine daha yakın görünüyor; içerik güvenliği açısından kayda değer bir risk bildirilmedi.",
            "summary_mixed": "Model kararsız; güvenli paylaşım için dikkatli olun ve sonuçları kesin kabul etmeyin.",
            "meta": "(Format: {format}, Boyut: {width}x{height})",
            "generator_line_conf": "Olası üretici: {name} (model güveni %{conf}).",
            "generator_line": "Olası üretici: {name}.",
        }
        en_map = {
            "title": "🔍 Image Analysis Result",
            "general_label": "• Overall Assessment:",
            "ai_label": "• AI Likelihood:",
            "human_label": "• Real Photo Likelihood:",
            "nsfw_label": "• NSFW / Sensitive Content:",
            "share_label": "• Safety & Sharing:",
            "summary_label": "• Summary:",
            "generator_label": "• Possible Generator:",
            "deepfake_label": "• Deepfake Check:",
            "quality_label": "• Quality Analysis:",
            "general_ai_high": "The analysis suggests the image is likely AI-generated.",
            "general_human": "The analysis leans toward the image being human-made/taken.",
            "general_unknown": "Analysis data is limited; sharing a tentative assessment.",
            "general_mixed": "Results are mixed; the model is not decisive, so be cautious.",
            "ai_line": "AI-generation likelihood is %{pct}. This is a model estimate, not certainty.",
            "ai_missing": "AI likelihood was not provided in the report.",
            "human_line": "Real-photo likelihood is %{pct} per the report.",
            "human_missing": "Real-photo likelihood value is missing in the report.",
            "nsfw_true": "Sensitive/NSFW content may be present; share with caution.",
            "nsfw_false": "No NSFW or sensitive content detected.",
            "nsfw_unknown": "NSFW check information was not provided.",
            "quality_true": "Quality analysis completed; no additional issues reported.",
            "quality_false": "Quality analysis indicates the image may have some issues.",
            "quality_unknown": "Quality analysis information is missing.",
            "deepfake_true_conf": "Deepfake likelihood is %{pct}; could be suspicious, share carefully.",
            "deepfake_true": "Deepfake suspicion reported; be cautious when sharing.",
            "deepfake_false_conf": "Deepfake likelihood %{pct}; if low, risk is limited but not certain.",
            "deepfake_false": "No deepfake suspicion reported.",
            "share_safe": "Looks safe to share; still consider the AI-generation likelihood.",
            "share_caution": "Consider safety and potential misrepresentation risks before sharing.",
            "summary_ai": "The image is likely AI-generated; no extra safety risks reported.",
            "summary_human": "The image leans human-made; no notable safety risks reported.",
            "summary_mixed": "Model is uncertain; share carefully and avoid treating it as definitive.",
            "meta": "(Format: {format}, Size: {width}x{height})",
            "generator_line_conf": "Possible generator: {name} (model confidence %{conf}).",
            "generator_line": "Possible generator: {name}.",
        }
        active = tr_map if lang == "tr" else en_map
        return active.get(key, en_map.get(key, key))

    # Simplified legacy construction
    return t("title") + "\n" + t("general_ai_high") if ai_pct and ai_pct >= 80 else t("general_human")


async def _run_analysis(image_bytes: bytes, user_id: str, chat_id: str, language: Optional[str] = None, mock: bool = False):
    language_norm = normalize_language(language) or "en"
    logger.info(
        "Starting AI or Not analysis",
        extra={
            "user_id": user_id,
            "chat_id": chat_id,
            "language": language_norm,
            "mock": mock,
            "image_bytes": len(image_bytes),
        },
    )

    files = {"object": ('image.jpg', image_bytes, 'image/jpeg')}
    try:
        logger.info("Calling AI or Not API")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                IMAGE_ENDPOINT,
                headers={"Authorization": f"Bearer {API_KEY}"},
                files=files,
            )
        logger.info(
            "AI or Not API responded",
            extra={
                "status_code": resp.status_code,
                "headers": dict(resp.headers),
                "content_length": len(resp.content or b""),
            },
        )
    except httpx.RequestError as e:
        logger.error("AI or Not API request failed", exc_info=e)
        raise HTTPException(status_code=502, detail={"error": "AI analysis failed", "details": str(e)})

    if resp.status_code != 200:
        body_text = resp.text
        logger.error("AI or Not API returned error", extra={"status": resp.status_code, "body": body_text})
        raise HTTPException(
            status_code=500,
            detail={"error": "AI analysis failed", "details": body_text, "status": resp.status_code},
        )

    logger.info("Parsing AI or Not API response")
    result = resp.json()
    logger.debug("AI or Not API JSON response", extra={"response": json.dumps(result, indent=2)})

    logger.debug("Extracting report fields")
    report = result.get("report") or {}
    ai_generated = report.get("ai_generated") or {}
    
    # Debug log for API structure
    logger.info("AI or Not API Report structure", extra={
        "report_keys": list(report.keys()),
        "ai_gen_keys": list(ai_generated.keys()),
        "verdict": ai_generated.get("verdict")
    })

    verdict = ai_generated.get("verdict")
    
    ai_conf = _safe_float((ai_generated.get("ai") or {}).get("confidence")) or 0.0
    human_conf = _safe_float((ai_generated.get("human") or {}).get("confidence")) or 0.0
    
    nsfw = (report.get("nsfw") or {}).get("is_detected")
    quality = (report.get("quality") or {}).get("is_detected")

    analysis_message = _build_summary(verdict, ai_conf, human_conf, quality, nsfw, language_norm)
    
    logger.debug(
        "Generated analysis message (summary)",
        extra={
            "user_id": user_id,
            "chat_id": chat_id,
            "language": language_norm,
            "analysis_preview": analysis_message[:500],
        },
    )

    saved_info = _save_asst_message(user_id, chat_id, analysis_message, result, language_norm)
    logger.info("Firestore save result", extra={"saved_info": saved_info})

    # Frontend beklentisine göre veriyi sarmala
    message_id = saved_info.get("message_id") if saved_info else f"ai_check_{os.urandom(4).hex()}"

    return {
        "success": True,
        "data": {
            "message": {
                "content": analysis_message,
                "id": message_id
            },
            "streaming": False,
        "raw_response": result,
        }
    }


async def analyze_image_from_url(image_url: str, user_id: str, chat_id: str, language: Optional[str] = None, mock: bool = False):
    logger.info("Analyze image from URL", extra={"image_url": image_url, "user_id": user_id, "chat_id": chat_id})
    headers = {"User-Agent": "Mozilla/5.0 (Avenia-Agent)"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(image_url, headers=headers)
        logger.info("Image download response", extra={"status": resp.status_code})
        resp.raise_for_status()
    except Exception as e:
        logger.error("Image download failed", exc_info=e)
        _save_failure_message(user_id, chat_id, language, FAIL_MSG, {"error": str(e)})
        raise HTTPException(status_code=400, detail=FAIL_MSG)

    content = resp.content or b""
    b64 = base64.b64encode(content).decode("utf-8")
    if len(b64) < 1000:
        logger.error("Downloaded content too small or not image")
        _save_failure_message(user_id, chat_id, language, FAIL_MSG, {"error": "invalid_image"})
        raise HTTPException(status_code=400, detail=FAIL_MSG)
    try:
        return await _run_analysis(content, user_id, chat_id, language, mock)
    except HTTPException as he:
        _save_failure_message(user_id, chat_id, language, FAIL_MSG, he.detail if isinstance(he.detail, dict) else {"error": str(he.detail)})
        raise HTTPException(status_code=he.status_code, detail=FAIL_MSG)
    except Exception as e:
        _save_failure_message(user_id, chat_id, language, FAIL_MSG, {"error": str(e)})
        raise HTTPException(status_code=500, detail=FAIL_MSG)


@router.post("/analyze-image")
async def analyze_image(
    payload: dict = Body(...),
    mock: str = Query(default="0"),  # ?mock=1 desteği için,
):
    """
    Beklenen body:
    {
      "image_base64": "<base64 veya data URL>",
      "user_id": "uid",
      "chat_id": "cid"
    }
    """
    logger.info("Analyze image request received", extra={"payload": payload})

    language = normalize_language(payload.get("language"))
    image_b64 = payload.get("image_base64")
    user_id = payload.get("user_id")
    chat_id = payload.get("chat_id")
    logger.info(
        "Analyze image parameters",
        extra={
            "user_id": user_id,
            "chat_id": chat_id,
            "image_length": len(image_b64) if image_b64 else "missing",
        },
    )

    if not image_b64:
        return JSONResponse(status_code=400, content={"message": FAIL_MSG})
    if not user_id or not chat_id:
        return JSONResponse(status_code=400, content={"message": FAIL_MSG})

    try:
        logger.info("Decoding base64 image")
        image_bytes = decode_base64_maybe_data_url(image_b64)
        logger.info("Base64 decoded", extra={"byte_length": len(image_bytes)})
    except Exception as e:
        logger.error("Base64 decode failed", exc_info=e)
        _save_failure_message(user_id, chat_id, language, FAIL_MSG, {"error": str(e)})
        return JSONResponse(status_code=400, content={"message": FAIL_MSG})

    try:
        result = await _run_analysis(image_bytes, user_id, chat_id, language, mock == "1")
        return JSONResponse(status_code=200, content={"success": True, **result})
    except HTTPException as he:
        _save_failure_message(
            user_id,
            chat_id,
            language,
            FAIL_MSG,
            he.detail if isinstance(he.detail, dict) else {"error": str(he.detail)},
        )
        raise HTTPException(status_code=he.status_code, detail=FAIL_MSG)
    except Exception as e:
        logger.exception("Analyze image failed")
        raise HTTPException(
            status_code=500,
            detail=FAIL_MSG,
        )
