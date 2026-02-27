# Video + City Logging & Storage (pdf-read-fresh)

This doc explains the video/city endpoints, logging, and Firestore collections.

## Endpoints
- POST `/api/styles/video/generate`
- POST `/api/styles/city/generate-photo`
- GET `/api/styles/history`
- DELETE `/api/styles/history/{item_id}`

## Request Fields
### Video
Body example:
```
{
  "style_id": "v1",
  "user_image_url": "https://...",
  "request_id": "req_123",
  "model": "fal-ai/pixverse/swap"
}
```

### City
Body example:
```
{
  "style_id": "city_1",
  "user_image_url": "https://...",
  "city_name": "Istanbul",
  "request_id": "req_456",
  "model": "fal-ai/imagen3"
}
```

## Storage Paths
Video flow:
- Input image: `users_video/{uid}/uploads/{uuid}-input.{ext}`
- Output video: `users_video/{uid}/generatevideos/{uuid}.{ext}`

City flow:
- Input image: `users_image/{uid}/uploads/city/{uuid}-input.{ext}`
- Output image: `users_image/{uid}/generatedimages/{uuid}.{ext}`

## Firestore Collections
- Video records: `users/{uid}/generatedVideos/{generatedId}`
- City image records: `users/{uid}/generatedImages/{generatedId}`

History endpoint merges both collections and returns max 200 items.

## Logging (Render)
Detailed logs are emitted from:
- `core/error_handler.py`
  - Logs request + response payloads for `/api/styles/*` and coin routes.
  - Controlled with `REQUEST_LOG_MAX_BYTES` (default 20000).
- `endpoints/styles/video.py`
  - Request details, storage paths, provider output, Firestore write.
- `endpoints/styles/city.py`
  - Request details, storage paths, provider output, Firestore write.
- `endpoints/styles/history.py`
  - List/delete calls, collection resolution, storage deletes.
- `endpoints/styles/fal_utils.py`
  - FAL subscribe start/end with payload/response preview.

## Notes
- If logs are too large, lower `REQUEST_LOG_MAX_BYTES` or set `LOG_LEVEL=info`.
- Swagger visibility can be controlled with `HIDE_UNUSED_SWAGGER_ENDPOINTS=true`.
