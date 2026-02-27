import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from firebase_admin import firestore, storage

logger = logging.getLogger("pdf_read_refresh.styles.history")

router = APIRouter(prefix="/api/styles", tags=["Styles"])


def _get_request_user_id(request: Request) -> str:
    payload = getattr(request.state, "token_payload", {}) or {}
    return (
        payload.get("uid")
        or payload.get("userId")
        or payload.get("sub")
        or ""
    )


def _serialize_timestamp(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "to_datetime"):
        return value.to_datetime().isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _timestamp_sort_key(value: Any) -> float:
    if value is None:
        return 0.0
    if hasattr(value, "timestamp"):
        try:
            return float(value.timestamp())
        except Exception:
            return 0.0
    if hasattr(value, "to_datetime"):
        try:
            return float(value.to_datetime().timestamp())
        except Exception:
            return 0.0
    if isinstance(value, str):
        try:
            return float(value)
        except Exception:
            return 0.0
    return 0.0


def _collect_history_items(collection_name: str, user_id: str) -> List[Dict[str, Any]]:
    db = firestore.client()
    query = (
        db.collection("users")
        .document(user_id)
        .collection(collection_name)
        .order_by("createdAt", direction=firestore.Query.DESCENDING)
        .limit(200)
    )
    items: List[Dict[str, Any]] = []
    for doc in query.stream():
        data = doc.to_dict() or {}
        items.append(
            {
                "id": doc.id,
                "styleType": data.get("styleType"),
                "styleId": data.get("styleId"),
                "prompt": data.get("prompt"),
                "outputImageUrl": data.get("outputImageUrl"),
                "outputImagePath": data.get("outputImagePath"),
                "outputVideoUrl": data.get("outputVideoUrl"),
                "outputVideoPath": data.get("outputVideoPath"),
                "outputMimeType": data.get("outputMimeType"),
                "inputImageUrl": data.get("inputImageUrl"),
                "createdAt": _serialize_timestamp(data.get("createdAt")),
                "updatedAt": _serialize_timestamp(data.get("updatedAt")),
                "_createdAtRaw": data.get("createdAt"),
            }
        )
    return items


@router.get("/history")
async def list_history(request: Request):
    user_id = _get_request_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail={"error": "access_denied", "message": "Authentication required"})

    logger.info("History list requested by user %s", user_id)
    video_items = _collect_history_items("generatedVideos", user_id)
    image_items = _collect_history_items("generatedImages", user_id)
    items = video_items + image_items
    items.sort(key=lambda item: _timestamp_sort_key(item.get("_createdAtRaw")), reverse=True)
    trimmed: List[Dict[str, Any]] = []
    for item in items[:200]:
        item.pop("_createdAtRaw", None)
        trimmed.append(item)

    logger.info(
        "History list prepared for user %s (videos=%s, images=%s, total=%s)",
        user_id,
        len(video_items),
        len(image_items),
        len(trimmed),
    )
    return JSONResponse(content={"items": trimmed})


@router.delete("/history/{item_id}")
async def delete_history(item_id: str, request: Request):
    user_id = _get_request_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail={"error": "access_denied", "message": "Authentication required"})

    logger.info("History delete requested by user %s for item %s", user_id, item_id)
    db = firestore.client()
    target_collection = "generatedVideos"
    doc_ref = (
        db.collection("users")
        .document(user_id)
        .collection(target_collection)
        .document(item_id)
    )
    snapshot = doc_ref.get()
    if not snapshot.exists:
        target_collection = "generatedImages"
        doc_ref = (
            db.collection("users")
            .document(user_id)
            .collection(target_collection)
            .document(item_id)
        )
        snapshot = doc_ref.get()
        if not snapshot.exists:
            raise HTTPException(status_code=404, detail={"error": "not_found", "message": "History item not found"})
    logger.info("History item found in collection %s for user %s", target_collection, user_id)

    data = snapshot.to_dict() or {}
    bucket: Any = storage.bucket()
    for path_key in ("outputImagePath", "outputVideoPath", "inputImagePath"):
        path_value = data.get(path_key)
        if isinstance(path_value, str) and path_value.strip():
            try:
                bucket.file(path_value).delete()
                logger.info("Deleted storage object %s for user %s", path_value, user_id)
            except Exception as exc:
                logger.warning("Failed to delete storage object %s: %s", path_value, exc)

    doc_ref.delete()
    logger.info("History item deleted for user %s (item=%s)", user_id, item_id)
    return JSONResponse(content={"success": True, "id": item_id})
