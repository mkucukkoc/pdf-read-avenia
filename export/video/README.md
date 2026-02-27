# Video Export Bundle

Bu klasor, video uretim akisini baska projeye tasimak icin hazirlandi.

## Icerik
- `bundle.ts`: Tek parca, copy-paste hazir video akisi
- `parts/video.ts`: Servis (FAL Pixverse akisi)
- `parts/utils.ts`: FAL/Gemini utils ve env anahtarlar
- `parts/styleUrls.ts`: Referans video URL'leri

## Bagimliliklar
- `express`, `firebase-admin`, `@fal-ai/client`
- Proje icindeki `firebase`, `middleware/authMiddleware`, `utils/logger`

## Kurulum Notlari
- `FAL_KEY` (veya `FAL_API_KEY`) gerekli
- Opsiyonel: `FAL_VIDEO_MODEL`, `FAL_VIDEO_RESOLUTION`, `FAL_VIDEO_KEYFRAME_ID`
- Opsiyonel: `FAL_VIDEO_ENABLE_BACKGROUND_SWAP`, `FAL_VIDEO_BABY_BACKGROUND_IMAGE_URL`

## Kullanım
- Router'a `registerVideoRoutes(router)` ekleyin.
- Endpoint: `POST /video/generate`
