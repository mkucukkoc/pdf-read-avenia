import re
from typing import Optional

PROMPTS_BY_ID = {
    "l1": (
        "bebekli zarif aile portresi; lüks klasik iç mekan, nötr bej tonları, "
        "yumuşak sinematik aydınlatma, modern resmi kıyafetler giyen ebeveynler, "
        "merkezde bebek, yüksek moda yaşam tarzı fotoğrafçılığı, fotogerçekçi, "
        "editoryal tarz. erkek ,kadın ve bebeği yerleştirip gorsel olusturun"
    ),
    "l2": (
        "modern oturma odasında bebeği tutan mutlu aile, sıcak doğal ışık, "
        "duygusal samimi an, yaşam tarzı fotoğrafçılığı, gerçekçi cilt tonları, "
        "yumuşak odaklı arka plan, birinci sınıf editoryal görünüm, rahat ev atmosferi "
        ",bebek ,kadın ve erkek yerleştirip gorsel olusturun"
    ),
    "l3": (
        "renkli neon şehir gece arka planında yürüyen ebeveynleri ile bebek arabasındaki bebek, "
        "sinematik şehir atmosferi, parlayan ışıklar, gerçekçi sokak fotoğrafçılığı stili, "
        "canlı renkler, sığ alan derinliği, modern yaşam tarzı estetiği , "
        "bebek ,kadın ve erkek yerleştirip gorsel olusturun"
    ),
    "l9": (
        "Anne, baba, ve bebeğin rahat bir kanepede birlikte oturduğu yaşam tarzı aile portresi, "
        "modern İskandinav oturma odası, yumuşak doğal gün ışığı, samimi mutlu anlar, "
        "ultra gerçekçi fotoğrafçılık, sinematik alan derinliği ,"
        "bebek ,kadın ve erkek yerleştirip gorsel olusturun"
    ),
    "l10": (
        "Bebek , bebek arabasındayken, yeşil bir parkta yürümeye başlayan ebeveynlerin "
        "aile yaşam tarzı fotoğrafı, altın saat güneş ışığı, doğal samimi atmosfer, "
        "sıcak sinema tonları ,bebek ,kadın ve erkek yerleştirip gorsel olusturun"
    ),
    "l11": (
        "Aile yaşam tarzı sahnesi: Anne ve baba yerde oturmuş, bebek önünde oynarken; "
        "aydınlık oyun odası ortamı, rahat ve doğal bir atmosfer."
    ),
    "l12": (
        "aile doğum günü kutlama sahnesi, pastanın yanındaki bebek, ebeveynler ve birlikte gülümseme, "
        "sıcak bayram aydınlatması, samimi yaşam tarzı fotoğrafçılığı ,"
        "bebek ,kadın ve erkek yerleştirip gorsel olusturun"
    ),
}

ALIASES = {
    "kraliyet": "l1",
    "luks_ev": "l2",
    "lux_ev": "l2",
    "times_meydani": "l3",
    "modern_salon_ailesi": "l9",
    "parkta_yuruyen_aile": "l10",
    "evde_oyun_zamani": "l11",
    "dogum_gunu_kutlamasi": "l12",
}


def _normalize(value: Optional[str]) -> str:
    if not value:
        return ""
    value = value.strip().lower()
    value = value.translate(
        str.maketrans(
            {
                "ı": "i",
                "İ": "i",
                "ş": "s",
                "Ş": "s",
                "ğ": "g",
                "Ğ": "g",
                "ü": "u",
                "Ü": "u",
                "ö": "o",
                "Ö": "o",
                "ç": "c",
                "Ç": "c",
            }
        )
    )
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def resolve_family_style_id(style_id: Optional[str]) -> Optional[str]:
    if not style_id:
        return None
    if style_id in PROMPTS_BY_ID:
        return style_id
    normalized = _normalize(style_id)
    return ALIASES.get(normalized) or style_id


def get_family_prompt(style_id: Optional[str], prompt_override: Optional[str] = None) -> Optional[str]:
    resolved_id = resolve_family_style_id(style_id)
    if resolved_id and resolved_id in PROMPTS_BY_ID:
        return PROMPTS_BY_ID[resolved_id]
    return prompt_override
