from typing import Optional

CAR_ASSETS = {
    "arkaya_bakan_yesil_bmw": "assets/cars/arkaya_bakan_yesil_bmw.png",
    "mercedes_roma": "assets/cars/mercedes-roma.png",
    "mercedes_ustu_acik": "assets/cars/mercedes_ustu_acik.png",
    "kiz_kulesi_mercedes_ustu_acik": "assets/cars/kız_kulesi_mercedes_ustu_acik.png",
}

CAR_BRAND_LABELS = {
    "arkaya_bakan_yesil_bmw": "BMW",
    "mercedes_roma": "Mercedes",
    "mercedes_ustu_acik": "Mercedes",
    "kiz_kulesi_mercedes_ustu_acik": "Mercedes",
}


def normalize_car_brand(value: Optional[str]) -> str:
    raw = (value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return raw


def get_car_asset_url(brand: Optional[str]) -> Optional[str]:
    key = normalize_car_brand(brand)
    return CAR_ASSETS.get(key)


def get_car_brand_label(brand: Optional[str]) -> str:
    key = normalize_car_brand(brand)
    return CAR_BRAND_LABELS.get(key, key or "Araba")
