import json
import logging
import time
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


def _format_log_block(label: str, value: Any) -> str:
    try:
        if isinstance(value, (dict, list)):
            pretty = json.dumps(value, ensure_ascii=False, indent=2)
        else:
            pretty = str(value)
    except Exception as exc:
        pretty = f"<unserializable:{exc}>"
    indented = "\n".join(f"    {line}" for line in pretty.splitlines())
    return f"{label}:\n{indented}"


def _log_json_block(
    kind: str,
    request: Request,
    request_id: Optional[str],
    payload: Any,
    extra_fields: Optional[Dict[str, Any]] = None,
) -> None:
    route_value = "styles"
    endpoint_value = "history"
    header = f"[{route_value}] {kind} JSON ({endpoint_value})"
    blocks = [
        f'    request_id: "{request_id}"',
        f'    method: "{request.method}"',
        f'    path: "{request.url.path}"',
        f'    route: "{route_value}"',
        f'    endpoint: "{endpoint_value}"',
    ]
    if extra_fields:
        for key, value in extra_fields.items():
            blocks.append(f'    {key}: "{value}"')
    blocks.append(_format_log_block(kind.lower(), payload))
    logger.info("%s\n%s", header, "\n".join(blocks))


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
    started_at = time.perf_counter()
    request_id = request.headers.get("x-request-id")
    user_id = _get_request_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail={"error": "access_denied", "message": "Authentication required"})

    _log_json_block(
        "Request",
        request,
        request_id,
        {
            "user_id": user_id,
            "query": dict(request.query_params),
        },
    )

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
    response_payload = {"items": trimmed}
    try:
        response_bytes = json.dumps(response_payload, ensure_ascii=False).encode("utf-8")
        content_length = len(response_bytes)
    except Exception:
        content_length = None
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    _log_json_block(
        "Response",
        request,
        request_id,
        response_payload,
        {
            "statusCode": 200,
            "contentLength": content_length,
            "durationMs": duration_ms,
        },
    )
    return JSONResponse(content=response_payload)


@router.delete("/history/{item_id}")
async def delete_history(item_id: str, request: Request):
    started_at = time.perf_counter()
    request_id = request.headers.get("x-request-id")
    user_id = _get_request_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail={"error": "access_denied", "message": "Authentication required"})

    _log_json_block(
        "Request",
        request,
        request_id,
        {
            "user_id": user_id,
            "item_id": item_id,
        },
    )

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
                bucket.blob(path_value).delete()
                logger.info("Deleted storage object %s for user %s", path_value, user_id)
            except Exception as exc:
                logger.warning("Failed to delete storage object %s: %s", path_value, exc)

    doc_ref.delete()
    logger.info("History item deleted for user %s (item=%s)", user_id, item_id)
    response_payload = {"success": True, "id": item_id}
    try:
        response_bytes = json.dumps(response_payload, ensure_ascii=False).encode("utf-8")
        content_length = len(response_bytes)
    except Exception:
        content_length = None
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    _log_json_block(
        "Response",
        request,
        request_id,
        response_payload,
        {
            "statusCode": 200,
            "contentLength": content_length,
            "durationMs": duration_ms,
        },
    )
    return JSONResponse(content=response_payload)
