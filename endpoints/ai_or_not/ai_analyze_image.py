import json
import logging
import base64
import os
from typing import Optional, Dict, Any, Tuple

import httpx
from fastapi import Body, Query, APIRouter, HTTPException
from fastapi.responses import JSONResponse
from firebase_admin import firestore

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
        db = firestore.client()
        path = f"users/{user_id}/chats/{chat_id}/messages"
        ref = db.collection("users").document(user_id).collection("chats").document(chat_id).collection("messages").add({
            "role": "assistant",
            "content": content,
            "meta": {
                "language": normalize_language(language),
                "ai_detect": {"raw": raw},
            },
        })
        message_id = ref[1].id if isinstance(ref, tuple) else ref.id
        return {"saved": True, "message_id": message_id, "path": path}
    except Exception as e:  # pragma: no cover
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


def _build_summary(verdict: Optional[str], confidence: float, quality, nsfw, language: Optional[str]):
    ai_conf = confidence if verdict == "ai" else max(0.0, 1.0 - confidence)
    human_conf = confidence if verdict == "human" else max(0.0, 1.0 - confidence)

    # Custom summary aligned with messages ladder
    if ai_conf >= 0.99:
        return "Görsel, %99+ olasılıkla yapay zeka tarafından üretilmiş (yüksek güven). Görsel yapısı iyi. NSFW açısından bir sorun görünmüyor."
    if ai_conf >= 0.8:
        return f"Görsel için AI analizi: Yapay zeka olasılığı %{ai_conf*100:.0f}. İnsan olasılığı %{human_conf*100:.0f}."
    if human_conf >= ai_conf:
        return f"Görsel insan üretimi gibi görünüyor. İnsan olasılığı %{human_conf*100:.0f}, yapay zeka olasılığı %{ai_conf*100:.0f}."

    return format_ai_detection_summary(
        verdict,
        ai_conf,
        human_conf,
        quality_flag_from_value(quality),
        nsfw_flag_from_value(nsfw),
        language=language,
        subject="image",
    )


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
        es_map = {
            "title": "🔍 Resultado del Análisis de la Imagen",
            "general_label": "• Evaluación General:",
            "ai_label": "• Probabilidad de IA:",
            "human_label": "• Probabilidad de Foto Real:",
            "nsfw_label": "• Contenido NSFW / Sensible:",
            "share_label": "• Seguridad y Compartir:",
            "summary_label": "• Resumen:",
            "generator_label": "• Posible Generador:",
            "deepfake_label": "• Comprobación Deepfake:",
            "quality_label": "• Análisis de Calidad:",
            "general_ai_high": "El análisis indica que la imagen probablemente fue generada por IA.",
            "general_human": "El análisis se inclina a que la imagen sea tomada/creada por una persona.",
            "general_unknown": "Los datos son limitados; compartimos una evaluación tentativa.",
            "general_mixed": "Los resultados son mixtos; el modelo no es concluyente, procede con cautela.",
            "ai_line": "Probabilidad de generación por IA: %{pct}. Es una estimación del modelo, no certeza.",
            "ai_missing": "El reporte no incluye probabilidad de IA.",
            "human_line": "Probabilidad de foto real: %{pct} según el reporte.",
            "human_missing": "No hay valor de probabilidad de foto real en el reporte.",
            "nsfw_true": "Podría haber contenido sensible/NSFW; comparte con cautela.",
            "nsfw_false": "No se detectó contenido NSFW o sensible.",
            "nsfw_unknown": "No se proporcionó información de revisión NSFW.",
            "quality_true": "Análisis de calidad completado; no se reportan problemas adicionales.",
            "quality_false": "El análisis de calidad indica que puede haber algunos problemas en la imagen.",
            "quality_unknown": "No hay información de análisis de calidad en el reporte.",
            "deepfake_true_conf": "Probabilidad de deepfake %{pct}; podría ser sospechoso, comparte con cuidado.",
            "deepfake_true": "Se reportó sospecha de deepfake; procede con cautela.",
            "deepfake_false_conf": "Probabilidad de deepfake %{pct}; si es baja, el riesgo es limitado, pero no seguro.",
            "deepfake_false": "No se reportó sospecha de deepfake.",
            "share_safe": "Parece seguro para compartir; considera la probabilidad de generación por IA.",
            "share_caution": "Evalúa riesgos de seguridad y posible desinformación antes de compartir.",
            "summary_ai": "La imagen es probablemente generada por IA; no se reportan riesgos extra de seguridad.",
            "summary_human": "La imagen se inclina a ser humana; no se reportan riesgos relevantes de seguridad.",
            "summary_mixed": "El modelo está incierto; comparte con cuidado y sin tratarlo como definitivo.",
            "meta": "(Formato: {format}, Tamaño: {width}x{height})",
            "generator_line_conf": "Posible generador: {name} (confianza del modelo %{conf}).",
            "generator_line": "Posible generador: {name}.",
        }
        pt_map = {
            "title": "🔍 Resultado da Análise da Imagem",
            "general_label": "• Avaliação Geral:",
            "ai_label": "• Probabilidade de IA:",
            "human_label": "• Probabilidade de Foto Real:",
            "nsfw_label": "• Conteúdo NSFW / Sensível:",
            "share_label": "• Segurança e Compartilhamento:",
            "summary_label": "• Resumo:",
            "generator_label": "• Possível Gerador:",
            "deepfake_label": "• Verificação de Deepfake:",
            "quality_label": "• Análise de Qualidade:",
            "general_ai_high": "A análise indica que a imagem provavelmente foi gerada por IA.",
            "general_human": "A análise sugere que a imagem foi feita/tirada por uma pessoa.",
            "general_unknown": "Dados limitados; fornecendo uma avaliação preliminar.",
            "general_mixed": "Resultados mistos; o modelo não é conclusivo, tenha cautela.",
            "ai_line": "Probabilidade de geração por IA: %{pct}. É uma estimativa do modelo, não certeza.",
            "ai_missing": "O relatório não traz probabilidade de IA.",
            "human_line": "Probabilidade de foto real: %{pct} conforme o relatório.",
            "human_missing": "Probabilidade de foto real não está presente no relatório.",
            "nsfw_true": "Pode haver conteúdo sensível/NSFW; compartilhe com cautela.",
            "nsfw_false": "Nenhum conteúdo NSFW ou sensível detectado.",
            "nsfw_unknown": "Informação de verificação NSFW não fornecida.",
            "quality_true": "Análise de qualidade concluída; nenhum problema adicional reportado.",
            "quality_false": "Análise de qualidade indica que a imagem pode ter alguns problemas.",
            "quality_unknown": "Informação de qualidade não está no relatório.",
            "deepfake_true_conf": "Probabilidade de deepfake %{pct}; pode ser suspeito, compartilhe com cuidado.",
            "deepfake_true": "Suspeita de deepfake relatada; tenha cautela ao compartilhar.",
            "deepfake_false_conf": "Probabilidade de deepfake %{pct}; se baixa, risco limitado, mas não certo.",
            "deepfake_false": "Nenhuma suspeita de deepfake relatada.",
            "share_safe": "Parece seguro para compartilhar; ainda considere a probabilidade de IA.",
            "share_caution": "Considere segurança e risco de má interpretação antes de compartilhar.",
            "summary_ai": "A imagem é provavelmente gerada por IA; sem riscos extras de segurança relatados.",
            "summary_human": "A imagem tende a ser humana; nenhum risco relevante de segurança relatado.",
            "summary_mixed": "O modelo está incerto; compartilhe com cuidado e sem tratá-lo como definitivo.",
            "meta": "(Formato: {format}, Tamanho: {width}x{height})",
            "generator_line_conf": "Possível gerador: {name} (confiança do modelo %{conf}).",
            "generator_line": "Possível gerador: {name}.",
        }
        fr_map = {
            "title": "🔍 Résultat d’Analyse de l’Image",
            "general_label": "• Évaluation Générale :",
            "ai_label": "• Probabilité d’IA :",
            "human_label": "• Probabilité de Photo Réelle :",
            "nsfw_label": "• Contenu NSFW / Sensible :",
            "share_label": "• Sécurité et Partage :",
            "summary_label": "• Résumé :",
            "generator_label": "• Générateur Possible :",
            "deepfake_label": "• Vérification Deepfake :",
            "quality_label": "• Analyse de Qualité :",
            "general_ai_high": "L’analyse indique que l’image est probablement générée par IA.",
            "general_human": "L’analyse penche pour une image réalisée/prise par un humain.",
            "general_unknown": "Données limitées ; partage d’une évaluation provisoire.",
            "general_mixed": "Résultats mitigés ; le modèle n’est pas décisif, soyez prudent.",
            "ai_line": "Probabilité de génération par IA : %{pct}. Estimation du modèle, pas une certitude.",
            "ai_missing": "Le rapport ne fournit pas de probabilité d’IA.",
            "human_line": "Probabilité de photo réelle : %{pct} selon le rapport.",
            "human_missing": "Le rapport ne contient pas de probabilité de photo réelle.",
            "nsfw_true": "Du contenu sensible/NSFW peut être présent ; partagez avec prudence.",
            "nsfw_false": "Aucun contenu NSFW ou sensible détecté.",
            "nsfw_unknown": "Aucune information de contrôle NSFW fournie.",
            "quality_true": "Analyse de qualité terminée ; aucun problème supplémentaire signalé.",
            "quality_false": "L’analyse de qualité indique que l’image peut avoir certains problèmes.",
            "quality_unknown": "Informations d’analyse de qualité absentes du rapport.",
            "deepfake_true_conf": "Probabilité de deepfake %{pct} ; pourrait être suspect, partagez avec prudence.",
            "deepfake_true": "Suspicion de deepfake signalée ; soyez prudent lors du partage.",
            "deepfake_false_conf": "Probabilité de deepfake %{pct} ; si faible, risque limité mais pas certain.",
            "deepfake_false": "Aucune suspicion de deepfake signalée.",
            "share_safe": "Semble sûr à partager ; tenez compte de la probabilité de génération par IA.",
            "share_caution": "Évaluez les risques de sécurité et de désinformation avant de partager.",
            "summary_ai": "L’image est probablement générée par IA ; aucun risque de sécurité supplémentaire signalé.",
            "summary_human": "L’image semble humaine ; aucun risque de sécurité notable signalé.",
            "summary_mixed": "Le modèle est incertain ; partagez avec prudence et sans conclusion définitive.",
            "meta": "(Format : {format}, Taille : {width}x{height})",
            "generator_line_conf": "Générateur possible : {name} (confiance du modèle %{conf}).",
            "generator_line": "Générateur possible : {name}.",
        }
        ru_map = {
            "title": "🔍 Результат анализа изображения",
            "general_label": "• Общая оценка:",
            "ai_label": "• Вероятность ИИ:",
            "human_label": "• Вероятность реального фото:",
            "nsfw_label": "• NSFW / чувствительный контент:",
            "share_label": "• Безопасность и распространение:",
            "summary_label": "• Итог:",
            "generator_label": "• Возможный генератор:",
            "deepfake_label": "• Проверка на дипфейк:",
            "quality_label": "• Анализ качества:",
            "general_ai_high": "Анализ показывает, что изображение, вероятно, сгенерировано ИИ.",
            "general_human": "Анализ склоняется к тому, что изображение создано/снято человеком.",
            "general_unknown": "Данных мало; приводим предварительную оценку.",
            "general_mixed": "Результаты смешанные; модель не уверена, действуйте осторожно.",
            "ai_line": "Вероятность генерации ИИ: %{pct}. Это оценка модели, не гарантия.",
            "ai_missing": "В отчёте нет вероятности ИИ.",
            "human_line": "Вероятность реального фото: %{pct} по отчёту.",
            "human_missing": "В отчёте отсутствует вероятность реального фото.",
            "nsfw_true": "Возможен чувствительный/NSFW контент; делитесь осторожно.",
            "nsfw_false": "NSFW или чувствительный контент не обнаружен.",
            "nsfw_unknown": "Информация о проверке NSFW не предоставлена.",
            "quality_true": "Анализ качества завершён; дополнительных проблем не выявлено.",
            "quality_false": "Анализ качества указывает на возможные проблемы с изображением.",
            "quality_unknown": "Информация об анализе качества отсутствует в отчёте.",
            "deepfake_true_conf": "Вероятность дипфейка %{pct}; может быть подозрительно, делитесь аккуратно.",
            "deepfake_true": "Сообщено о подозрении на дипфейк; будьте осторожны при распространении.",
            "deepfake_false_conf": "Вероятность дипфейка %{pct}; при низком значении риск ограничен, но не исключён.",
            "deepfake_false": "Подозрение на дипфейк не сообщалось.",
            "share_safe": "Похоже безопасно для распространения; учитывайте вероятность генерации ИИ.",
            "share_caution": "Оцените риски безопасности и возможного введения в заблуждение перед распространением.",
            "summary_ai": "Изображение, вероятно, сгенерировано ИИ; дополнительных рисков безопасности не выявлено.",
            "summary_human": "Изображение скорее человеческое; существенных рисков безопасности не отмечено.",
            "summary_mixed": "Модель не уверена; делитесь осторожно и не считайте результат окончательным.",
            "meta": "(Формат: {format}, Размер: {width}x{height})",
            "generator_line_conf": "Возможный генератор: {name} (уверенность модели %{conf}).",
            "generator_line": "Возможный генератор: {name}.",
        }

        lang_map = {
            "tr": tr_map,
            "en": en_map,
            "es": es_map,
            "pt": pt_map,
            "fr": fr_map,
            "ru": ru_map,
        }
        active = lang_map.get(lang) or en_map
        return active.get(key, en_map.get(key, key))

    # Overall assessment
    if ai_pct is not None and ai_pct >= 80:
        general = t("general_ai_high")
    elif human_pct is not None and (ai_pct is None or human_pct >= ai_pct + 10):
        general = t("general_human")
    elif ai_pct is None and human_pct is None:
        general = t("general_unknown")
    else:
        general = t("general_mixed")

    # AI likelihood
    if ai_pct is not None:
        ai_line = t("ai_line").replace("%{pct}", f"%{ai_pct}")
    else:
        ai_line = t("ai_missing")

    # Human likelihood
    if human_pct is not None:
        human_line = t("human_line").replace("%{pct}", f"%{human_pct}")
    else:
        human_line = t("human_missing")

    # NSFW
    if nsfw is True:
        nsfw_line = t("nsfw_true")
    elif nsfw is False:
        nsfw_line = t("nsfw_false")
    else:
        nsfw_line = t("nsfw_unknown")

    # Quality
    if quality is True:
        quality_line = t("quality_true")
    elif quality is False:
        quality_line = t("quality_false")
    else:
        quality_line = t("quality_unknown")

    # Deepfake
    deepfake_line = None
    if deepfake_flag is True:
        if deepfake_conf is not None:
            deepfake_line = t("deepfake_true_conf").replace("%{pct}", f"%{deepfake_conf}")
        else:
            deepfake_line = t("deepfake_true")
    elif deepfake_flag is False:
        if deepfake_conf is not None:
            deepfake_line = t("deepfake_false_conf").replace("%{pct}", f"%{deepfake_conf}")
        else:
            deepfake_line = t("deepfake_false")

    # Generator
    generator_line = None
    if generator_pick:
        gen_name, gen_conf = generator_pick
        if gen_conf is not None:
            generator_line = t("generator_line_conf").format(name=gen_name, conf=gen_conf)
        else:
            generator_line = t("generator_line").format(name=gen_name)

    # Safety & sharing
    if nsfw is False and (deepfake_flag is False or deepfake_flag is None):
        share_line = t("share_safe")
    else:
        share_line = t("share_caution")

    # Summary
    if ai_pct is not None and ai_pct >= 80:
        summary = t("summary_ai")
    elif human_pct is not None and (ai_pct is None or human_pct > ai_pct):
        summary = t("summary_human")
    else:
        summary = t("summary_mixed")

    meta_line = None
    if width and height and img_format:
        meta_line = t("meta").format(format=img_format, width=width, height=height)

    parts = [
        t("title"),
        "",
        t("general_label"),
        general,
        "",
        t("ai_label"),
        ai_line,
        "",
        t("human_label"),
        human_line,
        "",
        t("nsfw_label"),
        nsfw_line,
        "",
        t("share_label"),
        share_line,
        "",
        t("summary_label"),
        summary,
    ]

    if generator_line:
        parts.insert(-2, "")  # before Summary section
        parts.insert(-2, t("generator_label"))
        parts.insert(-2, generator_line)

    if deepfake_line:
        parts.insert(-2, "")  # before Summary section
        parts.insert(-2, t("deepfake_label"))
        parts.insert(-2, deepfake_line)

    if quality_line:
        parts.insert(-2, "")  # before Summary section
        parts.insert(-2, t("quality_label"))
        parts.insert(-2, quality_line)

    if meta_line:
        parts.append("")
        parts.append(meta_line)

    return "\n".join(parts)


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
    analysis_message = _build_analysis_message(result, language_norm)
    logger.debug(
        "Generated analysis message",
        extra={
            "user_id": user_id,
            "chat_id": chat_id,
            "language": language_norm,
            "analysis_preview": analysis_message[:500],
            "analysis_length": len(analysis_message),
        },
    )

    saved_info = _save_asst_message(user_id, chat_id, analysis_message, result, language_norm)
    logger.info("Firestore save result", extra={"saved_info": saved_info})

    return {
        "success": True,
        "raw_response": result,
        "summary": analysis_message,
        "summary_tr": analysis_message,
        "language": language_norm,
        "saved": saved_info,
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


