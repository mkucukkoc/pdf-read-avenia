"""Utility helpers for language-aware AI detection messaging."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple

DEFAULT_LANGUAGE = "tr"
SUPPORTED_LANGUAGES = {"tr", "en", "es", "pt", "fr", "ru"}

LANGUAGE_ALIASES = {
    "tr-tr": "tr",
    "turkish": "tr",
    "en-us": "en",
    "en-gb": "en",
    "english": "en",
    "es-es": "es",
    "es-mx": "es",
    "spanish": "es",
    "pt-br": "pt",
    "pt-pt": "pt",
    "portuguese": "pt",
    "fr-fr": "fr",
    "french": "fr",
    "ru-ru": "ru",
    "russian": "ru",
}


def normalize_language(language: Optional[str]) -> str:
    """Normalize incoming language codes to a supported subset."""

    if not language:
        return DEFAULT_LANGUAGE

    code = language.replace("_", "-").lower().strip()
    code = LANGUAGE_ALIASES.get(code, code)

    if "-" in code:
        primary = code.split("-", 1)[0]
        if primary in SUPPORTED_LANGUAGES:
            code = primary

    if code not in SUPPORTED_LANGUAGES:
        return DEFAULT_LANGUAGE
    return code


def _pct(value: Optional[float]) -> int:
    if value is None:
        return 0
    try:
        return max(0, min(100, int(round(float(value) * 100))))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return 0


def _resolve_flag(value: Any, *, allow_safe: bool = False) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, dict):
        for key in ("label", "value", "verdict", "rating", "score"):
            if key in value and value[key]:
                value = value[key]
                break

    if isinstance(value, (list, tuple)) and value:  # pragma: no cover - defensive
        value = value[0]

    if isinstance(value, str):
        lower = value.lower()
        mapping = {
            "very_low": "low",
            "very-low": "low",
            "low": "low",
            "medium": "medium",
            "moderate": "medium",
            "mid": "medium",
            "high": "high",
            "very_high": "high",
            "very-high": "high",
            "critical": "high",
            "nsfw": "high",
            "safe": "safe" if allow_safe else None,
            "likely": "high",
            "unlikely": "low",
        }
        return mapping.get(lower, lower if allow_safe else None)

    return None


def quality_flag_from_value(value: Any) -> Optional[str]:
    """Reduce external quality verdicts to low/medium/high flags."""

    return _resolve_flag(value, allow_safe=False)


def nsfw_flag_from_value(value: Any) -> Optional[str]:
    """Reduce NSFW verdicts to safe/low/medium/high."""

    flag = _resolve_flag(value, allow_safe=True)
    if flag == "safe":
        return "safe"
    return flag


def extract_generator_info(generator_data: Any) -> Tuple[Optional[str], Optional[float]]:
    """Return (name, confidence) tuple for detected generators."""

    if not isinstance(generator_data, dict):
        return None, None

    name = generator_data.get("name") or generator_data.get("label")
    confidence = generator_data.get("confidence") or generator_data.get("score")

    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):  # pragma: no cover - defensive
        confidence = None

    if name:
        name = str(name)

    return name, confidence


_VERDICT_MESSAGES: Dict[str, Dict[str, str]] = {
    "tr": {
        "ai": "İçerik büyük olasılıkla yapay zekâ tarafından üretildi (%{ai_confidence}).",
        "human": "İçerik insan üretimi gibi görünüyor (%{human_confidence}).",
        "unknown": "İçeriğin kaynağını belirleyemedik.",
    },
    "en": {
        "ai": "The content is likely AI-generated (%{ai_confidence}).",
        "human": "The content appears to be human-generated (%{human_confidence}).",
        "unknown": "We could not determine whether the content is AI-generated.",
    },
    "es": {
        "ai": "Es muy probable que el contenido haya sido generado por IA (%{ai_confidence}).",
        "human": "El contenido parece haber sido creado por una persona (%{human_confidence}).",
        "unknown": "No pudimos determinar el origen del contenido.",
    },
    "pt": {
        "ai": "O conteúdo provavelmente foi gerado por IA (%{ai_confidence}).",
        "human": "O conteúdo aparenta ter sido criado por uma pessoa (%{human_confidence}).",
        "unknown": "Não foi possível determinar a origem do conteúdo.",
    },
    "fr": {
        "ai": "Le contenu a probablement été généré par une IA (%{ai_confidence}).",
        "human": "Le contenu semble avoir été créé par un humain (%{human_confidence}).",
        "unknown": "Nous n'avons pas pu déterminer l'origine du contenu.",
    },
    "ru": {
        "ai": "Контент, вероятнее всего, создан ИИ (%{ai_confidence}).",
        "human": "Контент выглядит созданным человеком (%{human_confidence}).",
        "unknown": "Не удалось определить источник контента.",
    },
}


_CONFIDENCE_LINES: Dict[str, Dict[str, str]] = {
    "tr": {
        "ai": "Yapay zekâ olasılığı: %{ai_confidence}.",
        "human": "İnsan olasılığı: %{human_confidence}.",
    },
    "en": {
        "ai": "AI likelihood: %{ai_confidence}.",
        "human": "Human likelihood: %{human_confidence}.",
    },
    "es": {
        "ai": "Probabilidad de IA: %{ai_confidence}.",
        "human": "Probabilidad humana: %{human_confidence}.",
    },
    "pt": {
        "ai": "Probabilidade de IA: %{ai_confidence}.",
        "human": "Probabilidade humana: %{human_confidence}.",
    },
    "fr": {
        "ai": "Probabilité d'IA : %{ai_confidence}.",
        "human": "Probabilité humaine : %{human_confidence}.",
    },
    "ru": {
        "ai": "Вероятность ИИ: %{ai_confidence}.",
        "human": "Вероятность человека: %{human_confidence}.",
    },
}


_QUALITY_LINES: Dict[str, Dict[str, str]] = {
    "tr": {
        "high": "Kalite metrikleri yüksek.",
        "medium": "Kalite metrikleri orta seviyede.",
        "low": "Kalite metrikleri düşük.",
    },
    "en": {
        "high": "Quality indicators look strong.",
        "medium": "Quality indicators are moderate.",
        "low": "Quality indicators appear weak.",
    },
    "es": {
        "high": "Los indicadores de calidad son altos.",
        "medium": "Los indicadores de calidad son moderados.",
        "low": "Los indicadores de calidad son bajos.",
    },
    "pt": {
        "high": "Os indicadores de qualidade estão altos.",
        "medium": "Os indicadores de qualidade são moderados.",
        "low": "Os indicadores de qualidade estão baixos.",
    },
    "fr": {
        "high": "Les indicateurs de qualité sont élevés.",
        "medium": "Les indicateurs de qualité sont moyens.",
        "low": "Les indicateurs de qualité sont faibles.",
    },
    "ru": {
        "high": "Показатели качества высокие.",
        "medium": "Показатели качества средние.",
        "low": "Показатели качества низкие.",
    },
}


_NSFW_LINES: Dict[str, Dict[str, str]] = {
    "tr": {
        "safe": "NSFW sinyali tespit edilmedi.",
        "low": "Düşük seviye NSFW riski mevcut.",
        "medium": "Orta seviye NSFW riski mevcut.",
        "high": "Yüksek seviye NSFW riski tespit edildi.",
    },
    "en": {
        "safe": "No NSFW signal detected.",
        "low": "Low NSFW risk detected.",
        "medium": "Moderate NSFW risk detected.",
        "high": "High NSFW risk detected.",
    },
    "es": {
        "safe": "No se detectaron señales NSFW.",
        "low": "Se detectó un riesgo NSFW bajo.",
        "medium": "Se detectó un riesgo NSFW moderado.",
        "high": "Se detectó un riesgo NSFW alto.",
    },
    "pt": {
        "safe": "Nenhum sinal NSFW foi detectado.",
        "low": "Risco NSFW baixo detectado.",
        "medium": "Risco NSFW moderado detectado.",
        "high": "Risco NSFW alto detectado.",
    },
    "fr": {
        "safe": "Aucun signal NSFW détecté.",
        "low": "Risque NSFW faible détecté.",
        "medium": "Risque NSFW modéré détecté.",
        "high": "Risque NSFW élevé détecté.",
    },
    "ru": {
        "safe": "NSFW-сигналы не обнаружены.",
        "low": "Обнаружен низкий риск NSFW.",
        "medium": "Обнаружен средний риск NSFW.",
        "high": "Обнаружен высокий риск NSFW.",
    },
}


_GENERATOR_LINE = {
    "tr": "Olası üretici: {name} (%{confidence}).",
    "en": "Possible generator: {name} (%{confidence}).",
    "es": "Posible generador: {name} (%{confidence}).",
    "pt": "Possível gerador: {name} (%{confidence}).",
    "fr": "Générateur possible : {name} (%{confidence}).",
    "ru": "Предполагаемый генератор: {name} (%{confidence}).",
}


_SUBJECT_WORDS: Dict[str, Dict[str, str]] = {
    "tr": {"image": "görsel", "video": "video", "document": "doküman"},
    "en": {"image": "image", "video": "video", "document": "document"},
    "es": {"image": "imagen", "video": "video", "document": "documento"},
    "pt": {"image": "imagem", "video": "vídeo", "document": "documento"},
    "fr": {"image": "image", "video": "vidéo", "document": "document"},
    "ru": {"image": "изображение", "video": "видео", "document": "документ"},
}


def _get_translation(table: Dict[str, Dict[str, str]], language: str, key: str) -> Optional[str]:
    return table.get(language, {}).get(key) or table.get(DEFAULT_LANGUAGE, {}).get(key)


def build_ai_detection_messages(
    verdict: Optional[str],
    ai_confidence: Optional[float],
    human_confidence: Optional[float],
    quality_flag: Optional[str],
    nsfw_flag: Optional[str],
    *,
    language: Optional[str] = None,
    generator_name: Optional[str] = None,
    generator_confidence: Optional[float] = None,
) -> Iterable[str]:
    lang = normalize_language(language)

    ai_pct = _pct(ai_confidence)
    human_pct = _pct(human_confidence)

    verdict_key = verdict if verdict in {"ai", "human"} else "unknown"
    verdict_msg_tmpl = _get_translation(_VERDICT_MESSAGES, lang, verdict_key)

    messages = []
    if verdict_msg_tmpl:
        messages.append(
            verdict_msg_tmpl
            .replace("%{ai_confidence}", f"{ai_pct}%")
            .replace("%{human_confidence}", f"{human_pct}%")
        )

    conf_table = _CONFIDENCE_LINES.get(lang) or _CONFIDENCE_LINES[DEFAULT_LANGUAGE]
    if ai_pct:
        messages.append(conf_table["ai"].replace("%{ai_confidence}", f"{ai_pct}%"))
    if human_pct:
        messages.append(conf_table["human"].replace("%{human_confidence}", f"{human_pct}%"))

    if quality_flag:
        quality_line = _get_translation(_QUALITY_LINES, lang, quality_flag)
        if quality_line:
            messages.append(quality_line)

    if nsfw_flag:
        nsfw_line = _get_translation(_NSFW_LINES, lang, nsfw_flag)
        if nsfw_line:
            messages.append(nsfw_line)

    if generator_name and generator_confidence is not None:
        gen_line = _GENERATOR_LINE.get(lang, _GENERATOR_LINE[DEFAULT_LANGUAGE])
        messages.append(
            gen_line.replace("{name}", generator_name).replace(
                "%{confidence}", f"{_pct(generator_confidence)}%"
            )
        )

    return messages


def format_ai_detection_summary(
    verdict: Optional[str],
    ai_confidence: Optional[float],
    human_confidence: Optional[float],
    quality_flag: Optional[str],
    nsfw_flag: Optional[str],
    *,
    language: Optional[str] = None,
    subject: str = "image",
) -> str:
    lang = normalize_language(language)
    subject_word = _SUBJECT_WORDS.get(lang, _SUBJECT_WORDS[DEFAULT_LANGUAGE]).get(
        subject, subject
    )

    verdict_msgs = list(
        build_ai_detection_messages(
            verdict,
            ai_confidence,
            human_confidence,
            quality_flag,
            nsfw_flag,
            language=lang,
        )
    )

    if not verdict_msgs:
        verdict_msgs.append(_VERDICT_MESSAGES[lang]["unknown"])

    summary_intro = {
        "tr": f"{subject_word.capitalize()} için AI analizi:",
        "en": f"AI analysis for the {subject_word}:",
        "es": f"Análisis de IA para el/la {subject_word}:",
        "pt": f"Análise de IA para o/la {subject_word}:",
        "fr": f"Analyse IA pour {subject_word} :",
        "ru": f"Результат анализа ИИ для {subject_word}:",
    }.get(lang, f"AI analysis for the {subject_word}:")

    return " ".join([summary_intro] + verdict_msgs)


_IMAGE_GEN_MESSAGES = {
    "tr": {
        "ready": "Görsel hazır!",
        "failed": "Görsel oluşturulamadı.",
        "edited": "Görsel düzenlendi!",
        "edit_failed": "Görsel düzenlenemedi.",
    },
    "en": {
        "ready": "Image is ready!",
        "failed": "Failed to generate image.",
        "edited": "Image edited!",
        "edit_failed": "Failed to edit image.",
    },
    "es": {
        "ready": "¡La imagen está lista!",
        "failed": "Error al generar la imagen.",
        "edited": "¡Imagen editada!",
        "edit_failed": "Error al editar la imagen.",
    },
    "pt": {
        "ready": "A imagem está pronta!",
        "failed": "Falha ao gerar a imagem.",
        "edited": "Imagem editada!",
        "edit_failed": "Falha ao editar a imagem.",
    },
    "fr": {
        "ready": "L'image est prête !",
        "failed": "Échec de la génération de l'image.",
        "edited": "Image éditée !",
        "edit_failed": "Échec de l'édition de l'image.",
    },
    "ru": {
        "ready": "Изображение готово!",
        "failed": "Не удалось создать изображение.",
        "edited": "Изображение отредактировано!",
        "edit_failed": "Не удалось отредактировать изображение.",
    },
}


def get_image_gen_message(language: Optional[str], key: str = "ready") -> str:
    lang = normalize_language(language)
    return _IMAGE_GEN_MESSAGES.get(lang, _IMAGE_GEN_MESSAGES[DEFAULT_LANGUAGE]).get(key, "Image is ready!")


