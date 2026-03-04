import json
import os
from typing import Optional

DEFAULT_AESTHETIC_CATEGORIES = {
    "turkish_beauty": "Yuz estetigini gelistirirken ayni kimligi koruyun. Turk estetik tarzinda belirgin elmacik kemikleri, dengeli yuz hatlari ve dogal dudak dolgusu olusturun. Kisinin fotografini biraz geriden cekin, yuz net ve detayli gorunsun.",
    "hollywood_beauty": "Yuz estetigini gelistirirken ayni kimligi koruyun. Hollywood tarzi keskin cene hatti, belirgin elmacik kemikleri ve puruzsuz cilt olusturun. Kisinin fotografini biraz geriden cekin, yuz net ve detayli gorunsun.",
    "korean_beauty": "Yuz estetigini gelistirirken ayni kimligi koruyun. Kore guzellik stilinde cam gibi puruzsuz cilt, yumusak yuz hatlari ve dogal dudak gorunumu olusturun. Kisinin fotografini biraz geriden cekin, yuz net ve detayli gorunsun.",
    "instagram_beauty": "Yuz estetigini gelistirirken ayni kimligi koruyun. Instagram influencer tarzinda puruzsuz cilt, dolgun dudaklar ve parlak gozler olusturun. Kisinin fotografini biraz geriden cekin, yuz net ve detayli gorunsun.",
    "model_face": "Yuz estetigini gelistirirken ayni kimligi koruyun. Model yuzu gibi simetrik ve estetik yuz hatlari olusturun. Kisinin fotografini biraz geriden cekin, yuz net ve detayli gorunsun.",
    "glass_skin": "Yuz estetigini gelistirirken ayni kimligi koruyun. Cam gibi parlak ve puruzsuz bir cilt efekti olusturun. Kisinin fotografini biraz geriden cekin, yuz net ve detayli gorunsun.",
    "natural_beauty": "Yuz estetigini gelistirirken ayni kimligi koruyun. Yuz hatlarini dogal sekilde guzellestirin, cildi daha puruzsuz ve saglikli yapin. Kisinin fotografini biraz geriden cekin, yuz net ve detayli gorunsun.",
    "lip_filler": "Yuz estetigini gelistirirken ayni kimligi koruyun. Dogal dudak dolgusu uygulayin ve dudaklari hafif dolgunlastirin. Kisinin fotografini biraz geriden cekin, yuz net ve detayli gorunsun.",
    "botox_effect": "Yuz estetigini gelistirirken ayni kimligi koruyun. Alin bolgesindeki kirisikliklari botoks etkisiyle azaltin ve daha genc bir gorunum olusturun. Kisinin fotografini biraz geriden cekin, yuz net ve detayli gorunsun.",
    "nose_job": "Yuz estetigini gelistirirken ayni kimligi koruyun. Burnu daha ince ve simetrik olacak sekilde dogal burun estetigi uygulayin. Kisinin fotografini biraz geriden cekin, yuz net ve detayli gorunsun.",
    "jawline_sharp": "Yuz estetigini gelistirirken ayni kimligi koruyun. Cene hattini daha keskin ve belirgin yapin. Kisinin fotografini biraz geriden cekin, yuz net ve detayli gorunsun.",
    "youth_effect": "Yuz estetigini gelistirirken ayni kimligi koruyun. Yuzu daha genc ve canli gosterecek duzenlemeler yapin. Kisinin fotografini biraz geriden cekin, yuz net ve detayli gorunsun.",
    "under_eye_filler": "Yuz estetigini gelistirirken ayni kimligi koruyun. Goz altindaki yorgun gorunumu azaltin ve goz altini daha canli hale getirin. Kisinin fotografini biraz geriden cekin, yuz net ve detayli gorunsun.",
}

_PRESET_PATH = os.path.join(os.path.dirname(__file__), "aesthetic_presets.json")


def _load_presets() -> dict:
    try:
        with open(_PRESET_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


_PRESETS = _load_presets()

AESTHETIC_CATEGORIES = _PRESETS.get("aestheticCategories", DEFAULT_AESTHETIC_CATEGORIES)


def normalize_aesthetic_key(value: Optional[str]) -> str:
    raw = (value or "").strip().lower().replace(" ", "_").replace("-", "_")
    replacements = {
        "ı": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c",
    }
    for src, dest in replacements.items():
        raw = raw.replace(src, dest)
    return raw


def get_aesthetic_prompt(key: Optional[str]) -> Optional[str]:
    normalized = normalize_aesthetic_key(key)
    return AESTHETIC_CATEGORIES.get(normalized)
