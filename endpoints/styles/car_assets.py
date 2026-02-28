from typing import Optional

CAR_ASSETS = {
    "bmw_yesil": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2Fbmw_yesil.png?alt=media&token=d592afdf-5f99-4bf2-810c-219635b25b27",
    "mercedes_roma": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2Fmercedes.png?alt=media&token=faad1edd-2ebf-4d7b-abe1-05ed91375a13",
    "mercedes_ustu_acik": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2Fmercedes_ustuacik.png?alt=media&token=82a8a5ae-1f55-4087-84e3-db343f49f345",
    "kiz_kulesi_mercedes": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2Fmercedes_ustuacik.png?alt=media&token=82a8a5ae-1f55-4087-84e3-db343f49f345",
}

CAR_PROMPTS = {
    "bmw_yesil": "Bir daglik yolda hava gunesli, arabanin direksiyon koltugunda oturan ve arkaya bakan ve arka koltuktan bu kisinin fotografini cekin.",
    "mercedes_roma": "Italyanin roma meydaninda, arabanin direksiyon koltugunda oturan ve kapisi acik icinde oturan kisinin fotografini cekin.",
    "mercedes_ustu_acik": "Istanbul'daki Kiz Kulesi'nin onunde, arabanin kenarina yaslanmis kisinin fotografini cekin.",
    "kiz_kulesi_mercedes": "Istanbul'daki Kiz Kulesi'nin onunde arabanin kenarina yaslanmis kisinin fotografini cekin.",
}

CAR_BRAND_LABELS = {
    "bmw_yesil": "BMW",
    "mercedes_roma": "Mercedes",
    "mercedes_ustu_acik": "Mercedes",
    "kiz_kulesi_mercedes": "Mercedes",
}


def normalize_car_brand(value: Optional[str]) -> str:
    raw = (value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if raw.startswith("car_"):
        raw = raw[4:]
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
    aliases = {
        "arkaya_bakan_yesil_bmw": "bmw_yesil",
        "kiz_kulesi_mercedes_ustu_acik": "kiz_kulesi_mercedes",
        "mercedes_ustuacik": "mercedes_ustu_acik",
    }
    return aliases.get(raw, raw)


def get_car_asset_url(brand: Optional[str]) -> Optional[str]:
    key = normalize_car_brand(brand)
    return CAR_ASSETS.get(key)


def get_car_brand_label(brand: Optional[str]) -> str:
    key = normalize_car_brand(brand)
    return CAR_BRAND_LABELS.get(key, key or "Araba")


def get_car_prompt(brand: Optional[str]) -> Optional[str]:
    key = normalize_car_brand(brand)
    return CAR_PROMPTS.get(key)
