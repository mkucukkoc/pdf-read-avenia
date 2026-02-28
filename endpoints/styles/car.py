import base64
import json
import logging
import os
import time
from typing import Any, Dict, Optional
from uuid import uuid4
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse
from firebase_admin import firestore, storage

from .car_assets import get_car_asset_url, get_car_brand_label, get_car_prompt, normalize_car_brand
from .fal_utils import extract_image_url_from_fal_response, fal_subscribe, get_fal_key, summarize_url

logger = logging.getLogger("pdf_read_refresh.styles.car")

router = APIRouter(prefix="/api/styles", tags=["Styles"])


def _ext_from_mime(mime: str) -> str:
    if "png" in mime:
        return "png"
    if "webp" in mime:
        return "webp"
    if "heic" in mime:
        return "heic"
    return "jpg"


def _resolve_storage_object_path(input_value: str) -> Optional[str]:
    raw = (input_value or "").strip()
    if not raw:
        return None

    if raw.startswith("gs://"):
        no_prefix = raw[5:]
        slash_index = no_prefix.find("/")
        if slash_index < 0:
            return None
        return no_prefix[slash_index + 1 :]

    if raw.startswith("http://") or raw.startswith("https://"):
        try:
            parsed = urlparse(raw)
            marker = "/o/"
            idx = parsed.path.find(marker)
            if idx >= 0:
                encoded_path = parsed.path[idx + len(marker) :]
                return requests.utils.unquote(encoded_path)
        except Exception:
            return None
        return None

    return raw


def _download_image_from_source(source: str) -> Dict[str, Any]:
    bucket: Any = storage.bucket()
    parsed = _resolve_storage_object_path(source)
    if parsed:
        blob = bucket.blob(parsed)
        exists = blob.exists()
        if isinstance(exists, tuple):
            exists = exists[0]
        if exists:
            content = blob.download_as_bytes()
            mime_type = "image/png" if blob.name.lower().endswith(".png") else "image/jpeg"
            return {"buffer": content, "mimeType": mime_type, "objectPath": parsed}

    if source.startswith("http://") or source.startswith("https://"):
        response = requests.get(source, timeout=60)
        if not response.ok:
            raise ValueError(f"Unable to download source image from URL ({response.status_code})")
        response_mime = (response.headers.get("content-type") or "").lower().strip()
        inferred = "image/jpeg"
        lower = source.lower()
        if ".png" in lower:
            inferred = "image/png"
        elif ".webp" in lower:
            inferred = "image/webp"
        elif ".heic" in lower:
            inferred = "image/heic"
        elif ".jpg" in lower or ".jpeg" in lower:
            inferred = "image/jpeg"
        mime_type = response_mime if response_mime.startswith("image/") else inferred
        return {"buffer": response.content, "mimeType": mime_type, "objectPath": None}

    raise ValueError("Source image could not be resolved from storage/url")


def _get_signed_or_public_url(file_path: str) -> str:
    bucket: Any = storage.bucket()
    blob = bucket.blob(file_path)
    try:
        signed_url = blob.generate_signed_url(expiration="2099-12-31", method="GET")
        return signed_url
    except Exception:
        bucket_name = bucket.name
        return (
            f"https://firebasestorage.googleapis.com/v0/b/{bucket_name}/o/"
            f"{requests.utils.quote(file_path, safe='')}"
            "?alt=media"
        )


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
    endpoint_value = "car"
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


def _generate_car_photo(
    person_image_url: str,
    car_image_url: str,
    prompt: str,
    model: Optional[str],
) -> Dict[str, Any]:
    resolved_model = model or os.getenv("FAL_CAR_MODEL", "fal-ai/gemini-3.1-flash-image-preview/edit")
    if not get_fal_key():
        raise ValueError("FAL_KEY is not configured")

    input_payload = {
        "prompt": prompt,
        "num_images": 1,
        "aspect_ratio": "auto",
        "output_format": "png",
        "image_urls": [person_image_url, car_image_url],
        "resolution": "1K",
        "limit_generations": True,
    }
    logger.info(
        "FAL car edit request prepared | %s",
        {
            "model": resolved_model,
            "input": {
                "prompt": prompt,
                "image_urls": [summarize_url(person_image_url), summarize_url(car_image_url)],
            },
        },
    )

    result = fal_subscribe(resolved_model, input_payload)
    output_url = extract_image_url_from_fal_response(result)
    if not output_url:
        raise ValueError("FAL car edit returned no output URL")

    output_response = requests.get(output_url, timeout=120)
    if not output_response.ok:
        raise ValueError(f"Unable to download generated image ({output_response.status_code})")
    output_mime = (output_response.headers.get("content-type") or "image/png").lower().strip()
    output_base64 = base64.b64encode(output_response.content).decode("utf-8")

    return {"data": output_base64, "mimeType": output_mime, "text": None}


@router.post("/car/generate-photo")
async def generate_car_photo(payload: Dict[str, Any] = Body(...), request: Request = None):
    started_at = time.perf_counter()
    user_id = _get_request_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail={"error": "access_denied", "message": "Authentication required"})

    try:
        style_id = payload.get("style_id") if isinstance(payload.get("style_id"), str) else None
        user_image_source = ""
        if isinstance(payload.get("user_image_url"), str):
            user_image_source = payload.get("user_image_url") or ""
        elif isinstance(payload.get("user_image_path"), str):
            user_image_source = payload.get("user_image_path") or ""
        car_brand = payload.get("car_brand") if isinstance(payload.get("car_brand"), str) else ""
        request_id = payload.get("request_id") if isinstance(payload.get("request_id"), str) else request.headers.get("x-request-id")
        requested_model = payload.get("model") if isinstance(payload.get("model"), str) else None
        prompt_override = payload.get("prompt") if isinstance(payload.get("prompt"), str) else None

        _log_json_block(
            "Request",
            request,
            request_id,
            {
                "style_id": style_id,
                "user_id": user_id,
                "car_brand": car_brand,
                "user_image_url": summarize_url(user_image_source),
                "model": requested_model,
                "prompt": prompt_override,
            },
        )

        logger.info(
            "Car generate request received | %s",
            {
                "requestId": request_id,
                "userId": user_id,
                "styleId": style_id,
                "carBrand": car_brand,
                "userImageSourcePreview": summarize_url(user_image_source),
                "model": requested_model,
            },
        )

        if not user_image_source or not car_brand:
            raise ValueError("Missing required fields")

        car_asset_url = get_car_asset_url(car_brand)
        if not car_asset_url:
            raise ValueError("Unknown car brand")

        brand_label = get_car_brand_label(car_brand)
        mapped_prompt = get_car_prompt(car_brand)
        prompt_text = mapped_prompt or prompt_override or (
            f"{brand_label} arabanin direksiyon koltugunda oturan ve kapisi acik, gercekci bir fotograf cekin."
        )

        bucket: Any = storage.bucket()
        resolved_user_image = _download_image_from_source(user_image_source)
        input_ext = _ext_from_mime(resolved_user_image.get("mimeType") or "image/jpeg")
        input_upload_id = str(uuid4())
        input_path = f"image/{input_upload_id}/input.{input_ext}"
        input_blob = bucket.blob(input_path)
        input_blob.cache_control = "public,max-age=31536000"
        input_blob.upload_from_string(
            resolved_user_image["buffer"],
            content_type=resolved_user_image.get("mimeType") or "image/jpeg",
        )
        input_url = _get_signed_or_public_url(input_path)

        logger.info(
            "Car generate input stored | %s",
            {
                "requestId": request_id,
                "userId": user_id,
                "inputPath": input_path,
                "inputUrlPreview": summarize_url(input_url),
                "inputMime": resolved_user_image.get("mimeType"),
                "carAssetPreview": summarize_url(car_asset_url),
            },
        )

        generated = _generate_car_photo(input_url, car_asset_url, prompt_text, requested_model)

        generated_ext = _ext_from_mime(generated.get("mimeType") or "image/png")
        generated_id = str(uuid4())
        generated_path = f"image/{generated_id}/output.{generated_ext}"
        generated_buffer = base64.b64decode(generated["data"])
        output_blob = bucket.blob(generated_path)
        output_blob.cache_control = "public,max-age=31536000"
        output_blob.upload_from_string(
            generated_buffer,
            content_type=generated.get("mimeType") or "image/png",
        )
        output_url = _get_signed_or_public_url(generated_path)

        logger.info(
            "Car generate output prepared | %s",
            {
                "requestId": request_id,
                "userId": user_id,
                "generatedId": generated_id,
                "outputPath": generated_path,
                "outputUrlPreview": summarize_url(output_url),
                "outputMimeType": generated.get("mimeType"),
            },
        )

        db = firestore.client()
        logger.info(
            "Car generate Firestore write started | %s",
            {
                "requestId": request_id,
                "userId": user_id,
                "collection": "users/{uid}/generatedImages",
                "docId": generated_id,
            },
        )
        db.collection("users").document(user_id).collection("generatedImages").document(generated_id).set(
            {
                "id": generated_id,
                "styleType": "car",
                "styleId": style_id or None,
                "requestId": request_id,
                "carBrand": normalize_car_brand(car_brand),
                "prompt": prompt_text,
                "inputImagePath": input_path,
                "inputImageUrl": input_url,
                "outputImagePath": generated_path,
                "outputImageUrl": output_url,
                "outputMimeType": generated.get("mimeType") or "image/png",
                "createdAt": firestore.SERVER_TIMESTAMP,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            }
        )

        logger.info(
            "Car generate record saved | %s",
            {
                "requestId": request_id,
                "userId": user_id,
                "generatedId": generated_id,
            },
        )

        response_payload = {
            "request_id": request_id,
            "style_id": style_id or None,
            "user_id": user_id,
            "input": {
                "path": input_path,
                "url": input_url,
                "car_brand": normalize_car_brand(car_brand),
                "prompt": prompt_text,
            },
            "output": {
                "id": generated_id,
                "path": generated_path,
                "url": output_url,
                "mimeType": generated.get("mimeType") or "image/png",
            },
        }

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

        logger.info(
            "Car generate response sent | %s",
            {
                "requestId": request_id,
                "userId": user_id,
                "response": response_payload,
            },
        )

        return JSONResponse(content={**response_payload})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Car generate failed | %s",
            {
                "requestId": request.headers.get("x-request-id") if request else None,
                "userId": user_id,
                "error": str(exc),
            },
        )
        return JSONResponse(
            status_code=500,
            content={"error": {"message": "Hata olustu, lutfen tekrar deneyin."}},
        )
