# City Teleport Export Bundle

Bu klasor, sehir teleport (city) akisini baska projeye tasimak icin hazirlandi.

## Icerik
- `bundle.ts`: Tek parca, copy-paste hazir city akisi
- `parts/city.ts`: Servis (FAL city teleport)
- `parts/utils.ts`: FAL/Gemini utils ve env anahtarlar

## Bagimliliklar
- `express`, `firebase-admin`, `@fal-ai/client`
- Proje icindeki `firebase`, `middleware/authMiddleware`, `utils/logger`

## Kurulum Notlari
- `FAL_KEY` (veya `FAL_API_KEY`) gerekli
- Opsiyonel: `FAL_CITY_MODEL`

## Kullanım
- Router'a `registerCityRoutes(router)` ekleyin.
- Endpoint: `POST /city/generate-photo`
