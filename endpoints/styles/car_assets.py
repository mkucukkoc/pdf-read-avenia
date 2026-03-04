import json
import os
from typing import Optional

DEFAULT_CAR_ASSETS = {
    "bmw": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2Fbmw_yesil.png?alt=media&token=d592afdf-5f99-4bf2-810c-219635b25b27",
    "mercedes": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2Fmercedes.png?alt=media&token=faad1edd-2ebf-4d7b-abe1-05ed91375a13",
    "audi": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2Fporsche.png?alt=media&token=87111b43-45d7-461b-9f7f-5a85803660c2",
    "porsche": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2Fmercedes_ustuacik.png?alt=media&token=82a8a5ae-1f55-4087-84e3-db343f49f345",
    "ferrari": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2FFerrari.png?alt=media&token=7eb371d9-f533-4a74-ab24-ab083f2fbba3",
    "lamborghini": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2FLamborghini.png?alt=media&token=b9bf2521-e4f8-48af-a03f-53587f217664",
    "rolls_royce": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2FRolls-Royce.png?alt=media&token=0de892be-c7c8-4991-aa19-f9988cbf8e45",
    "bentley": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2FBentley.png?alt=media&token=4a9855a5-0d56-4b0f-83fd-60e97c97ea52",
    "tesla": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2Ftesla.png?alt=media&token=4ef3739e-2a9c-4e04-9059-d2039e5ca2b9",
    "land_rover": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2FLandRover.png?alt=media&token=e4c9a383-2531-4f43-afca-d531a6f038d6",
    "bmw_yesil": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2Fbmw_yesil.png?alt=media&token=d592afdf-5f99-4bf2-810c-219635b25b27",
    "mercedes_roma": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2Fmercedes.png?alt=media&token=faad1edd-2ebf-4d7b-abe1-05ed91375a13",
    "mercedes_ustu_acik": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2Fmercedes_ustuacik.png?alt=media&token=82a8a5ae-1f55-4087-84e3-db343f49f345",
    "kiz_kulesi_mercedes": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2Fmercedes_ustuacik.png?alt=media&token=82a8a5ae-1f55-4087-84e3-db343f49f345",
    "mercedes_tokyo": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2Fmercedes.png?alt=media&token=faad1edd-2ebf-4d7b-abe1-05ed91375a13",
    "bmw_alp_dag": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2Fbmw_yesil.png?alt=media&token=d592afdf-5f99-4bf2-810c-219635b25b27",
    "audi_paris": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2Fporsche.png?alt=media&token=87111b43-45d7-461b-9f7f-5a85803660c2",
    "monoca_bmw_yesil": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2Fbmw_yesil.png?alt=media&token=d592afdf-5f99-4bf2-810c-219635b25b27",
    "maldivler_ferrari": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2FFerrari.png?alt=media&token=7eb371d9-f533-4a74-ab24-ab083f2fbba3",
    "venedik_bentley": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2FBentley.png?alt=media&token=4a9855a5-0d56-4b0f-83fd-60e97c97ea52",
    "lamborgini_iskocya": "https://firebasestorage.googleapis.com/v0/b/aveniaapp.firebasestorage.app/o/assets%2Fcars%2FLamborghini.png?alt=media&token=b9bf2521-e4f8-48af-a03f-53587f217664",
}

DEFAULT_CAR_PROMPTS = {
    "bmw_alp_dag": "Alp dag yolu, {weather} hava durumunda, arabanin direksiyon koltugunda oturan  ve direksiyon sol da olan ,kisiyi arka koltuktan ve hafif yukaridan cekin; sinematik isik, net detay.",
    "mercedes": "Paris gece sokagi, {weather} hava durumunda, kapisi acik mercedes icinde oturan kisiyi yandan cekin; luks editoryal, yumusak bokeh.",
    "audi": "Tokyo modern cadde, {weather} hava durumunda, araba onunde arabanin on kaputuun ustune oturmus sekilde dilini cikarmis sekilde oturmus kisinin ,neon yansimalar, sinematik olarak fotografini cekin",
    "porsche": "Monaco sahil yolu, {weather} hava durumunda, arabaya yaslanmis kisiyi 3/4 acidan cekin; premium yasam stili.",
    "ferrari": "Monza pist kenari, {weather} hava durumunda, direksiyon basinda atletik poz; dramatik kenar isigi.",
    "lamborghini": "Dubai gece skyline, {weather} hava durumunda, kapisi yukari acik lambo yaninda guclu poz; yuksek kontrast.",
    "rolls_royce": "Londra klasik bina onunde, {weather} hava durumunda, arka koltukta oturan kisiyi arkadan cekin; kraliyet luks.",
    "bentley": "Venedik dar sokak, {weather} hava durumunda, arabadan inen kisiyi tam boy cekin; zarif editoryal.",
    "tesla": "Norvec fiyordu, {weather} hava durumunda, minimalist ic mekanda direksiyon basinda kisi; temiz kompozisyon.",
    "land_rover": "Iskocya yaylalari offroad, {weather} hava durumunda, SUV yaninda dis mekanda kisi; sert ve sinematik.",
    "bmw_yesil": "Bir daglik yolda, {weather} hava durumunda, arabanin direksiyon koltugunda oturan ve arkaya bakan kisinin, arka koltuktan cekilmis fotografini cekin.",
    "mercedes_roma": "Italyanin Roma meydaninda, {weather} hava durumunda, kapisi acik mercedes icinde oturan kisinin fotografini cekin.",
    "mercedes_ustu_acik": "Istanbul'daki Kiz Kulesi onunde, {weather} hava durumunda, ustu acik mercedesin yaninda arabanin kenarina yaslanmis kisinin fotografini cekin.",
    "kiz_kulesi_mercedes": "Istanbul'daki Kiz Kulesi'nin onunde arabanin kenarina yaslanmis ve {weather} hava durumunda kisinin fotografini cekin.",
    "mercedes_tokyo": "Tokyo modern cadde, {weather} hava durumunda, araba onunde arabanin on kaputuun ustune oturmus sekilde dilini cikarmis sekilde oturmus kisinin ,neon yansimalar, sinematik olarak fotografini cekin",
    "bmw_alp_dag": "Alp dag yolu, {weather} hava durumunda, arabanin direksiyon koltugunda oturan  ve direksiyon sol da olan ,kisiyi arka koltuktan ve hafif yukaridan cekin; sinematik isik, net detay.",
    "audi_paris": "Paris gece sokagi, {weather} hava durumunda, kapisi acik mercedes icinde oturan kisiyi yandan cekin; luks editoryal, yumusak bokeh.",
    "monoca_bmw_yesil": "Monaco sahil yolu, {weather} hava durumunda, yansimalar hava durumunda, arabaya yaslanmis kisiyi 3/4 acidan cekin; arkada sahil olucak sekilde fotografini cekin",
    "maldivler_ferrari": "Maldivler de , {weather} hava durumunda, direksiyon basinda cool bakisli kisinin elleri arabanin camdan sarkmis sekilde, arabanin sol caprazindan ve araba markasi olucak sekilde on tarafdan biraz geriden araba tamami gozukecek sekilde kisinin fotografini cekin.",
    "venedik_bentley": "Venedik dar sokak, {weather} hava durumunda, arabadan inen kisiyi tam boy cekin; zarif editoryal asagidan kisinin fotografini cekin",
    "lamborgini_iskocya": "Iskocya yaylalari offroad, {weather} hava durumunda, SUV yaninda dis mekanda kisi; sert ve sinematik. fotografini cekin.",
}

DEFAULT_CAR_BRAND_LABELS = {
    "bmw": "BMW",
    "mercedes": "Mercedes",
    "audi": "Audi",
    "porsche": "Porsche",
    "ferrari": "Ferrari",
    "lamborghini": "Lamborghini",
    "rolls_royce": "Rolls-Royce",
    "bentley": "Bentley",
    "tesla": "Tesla",
    "land_rover": "Land Rover",
    "bmw_yesil": "BMW",
    "mercedes_roma": "Mercedes",
    "mercedes_ustu_acik": "Mercedes",
    "kiz_kulesi_mercedes": "Mercedes",
    "mercedes_tokyo": "Mercedes",
    "bmw_alp_dag": "BMW",
    "audi_paris": "Audi",
    "monoca_bmw_yesil": "BMW",
    "maldivler_ferrari": "Ferrari",
    "venedik_bentley": "Bentley",
    "lamborgini_iskocya": "Lamborghini",
}

DEFAULT_WEATHER_STYLES = {
    "sunny": "parlak dogal gun isigi, altin saat, acik gokyuzu, yuksek kontrast",
    "rainy": "camda yagmur damlalari, melankolik atmosfer, islak asfalt, kapali hava, yansimalar",
    "snowy": "karla kapli yol, yumusak beyaz isik, soguk mavi tonlar, cam kenarlarinda buz",
    "foggy": "yogun sis, gizemli atmosfer, arka plan bulanak, yumusak dagilmis isik, dusuk gorus",
    "stormy": "koyu gok gurultulu bulutlar, uzakta simsek parlamalari, sert ruzgar etkisi, dramatik gri tonlar",
    "sunset": "sicak turuncu ve mor tonlar, uzun golgeler, lens flare, yuzde altin parlama",
    "night_city": "sehir isiklari, neon tabelalarin kokpitte yansimasi, bokeh arka plan, gece kontrasti",
    "overcast": "yumusak ve esit isik, sert golge yok, gercekci duz tonlar, bulutlu gokyuzu",
    "sandstorm": "tozlu turuncu atmosfer, puslu col yolu, sicak sepya tonlar, sinematik gren",
    "dawn": "sabah erken saat yumusak mavi isik, ince sis, acik pembe ufuk, sakin atmosfer",
}

_PRESET_PATH = os.path.join(os.path.dirname(__file__), "car_presets.json")


def _load_presets() -> dict:
    try:
        with open(_PRESET_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


_PRESETS = _load_presets()

CAR_ASSETS = _PRESETS.get("carAssets", DEFAULT_CAR_ASSETS)
CAR_PROMPTS = _PRESETS.get("carPrompts", DEFAULT_CAR_PROMPTS)
CAR_BRAND_LABELS = _PRESETS.get("carBrandLabels", DEFAULT_CAR_BRAND_LABELS)
WEATHER_STYLES = _PRESETS.get("weatherStyles", DEFAULT_WEATHER_STYLES)


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


def get_weather_style_prompt(style: Optional[str]) -> Optional[str]:
    key = (style or "").strip().lower()
    return WEATHER_STYLES.get(key)
