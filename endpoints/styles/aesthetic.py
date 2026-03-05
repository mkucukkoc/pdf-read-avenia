import base64
import json
import logging
import os
import time
from typing import Any, Dict, Optional
from uuid import uuid4

import requests
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse
from firebase_admin import firestore, storage

from .fal_utils import extract_image_url_from_fal_response, fal_subscribe, get_fal_key, summarize_url
from .aesthetic_assets import get_aesthetic_prompt, normalize_aesthetic_key

logger = logging.getLogger("pdf_read_refresh.styles.aesthetic")

router = APIRouter(prefix="/api/styles", tags=["Styles"])


def _get_request_user_id(request: Request) -> str:
    payload = getattr(request.state, "token_payload", {}) or {}
    return payload.get("uid") or payload.get("userId") or payload.get("sub") or ""


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
    endpoint_value = "aesthetic"
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


def _ext_from_mime(value: str) -> str:
    normalized = (value or "").lower()
    if "png" in normalized:
        return "png"
    if "webp" in normalized:
        return "webp"
    return "jpg"


def _download_image_from_source(source: str) -> Dict[str, Any]:
    if not source:
        raise ValueError("Missing source image")
    response = requests.get(source, timeout=120)
    if not response.ok:
        raise ValueError(f"Unable to download input image ({response.status_code})")
    mime_type = (response.headers.get("content-type") or "image/jpeg").lower().strip()
    return {"buffer": response.content, "mimeType": mime_type}


def _get_signed_or_public_url(path: str) -> str:
    bucket = storage.bucket()
    blob = bucket.blob(path)
    try:
        # Always prefer signed URLs because this bucket is not public.
        return blob.generate_signed_url(version="v4", expiration=3600, method="GET")
    except Exception:
        return blob.public_url


def _generate_aesthetic_photo(
    person_image_url: str,
    prompt: str,
    model: Optional[str],
) -> Dict[str, Any]:
    resolved_model = model or os.getenv("FAL_AESTHETIC_MODEL", "fal-ai/gemini-3.1-flash-image-preview/edit")
    if not get_fal_key():
        raise ValueError("FAL_KEY is not configured")

    input_payload = {
        "prompt": prompt,
        "num_images": 1,
        "aspect_ratio": "auto",
        "output_format": "png",
        "image_urls": [person_image_url],
        "resolution": "1K",
        "limit_generations": True,
    }
    logger.info(
        "FAL aesthetic edit request prepared | %s",
        {
            "model": resolved_model,
            "input": {
                "prompt": prompt,
                "image_urls": [summarize_url(person_image_url)],
            },
        },
    )

    result = fal_subscribe(resolved_model, input_payload)
    output_url = extract_image_url_from_fal_response(result)
    if not output_url:
        raise ValueError("FAL aesthetic edit returned no output URL")

    output_response = requests.get(output_url, timeout=120)
    if not output_response.ok:
        raise ValueError(f"Unable to download generated image ({output_response.status_code})")
    output_mime = (output_response.headers.get("content-type") or "image/png").lower().strip()
    output_base64 = base64.b64encode(output_response.content).decode("utf-8")

    return {"data": output_base64, "mimeType": output_mime, "text": None}


@router.post("/aesthetic/generate-photo")
async def generate_aesthetic_photo(payload: Dict[str, Any] = Body(...), request: Request = None):
    started_at = time.perf_counter()
    user_id = _get_request_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail={"error": "access_denied", "message": "Authentication required"})

    try:
        style_id = payload.get("style_id") if isinstance(payload.get("style_id"), str) else None
        category_key = payload.get("category") if isinstance(payload.get("category"), str) else None
        request_id = payload.get("request_id") if isinstance(payload.get("request_id"), str) else request.headers.get("x-request-id")
        requested_model = payload.get("model") if isinstance(payload.get("model"), str) else None
        prompt_override = payload.get("prompt") if isinstance(payload.get("prompt"), str) else None

        user_image_source = ""
        if isinstance(payload.get("user_image_url"), str):
            user_image_source = payload.get("user_image_url") or ""
        elif isinstance(payload.get("user_image_path"), str):
            user_image_source = payload.get("user_image_path") or ""

        resolved_key = normalize_aesthetic_key(category_key or style_id or "")

        _log_json_block(
            "Request",
            request,
            request_id,
            {
                "style_id": style_id,
                "category": resolved_key,
                "user_id": user_id,
                "user_image_url": summarize_url(user_image_source),
                "model": requested_model,
                "prompt": prompt_override,
            },
        )

        if not user_image_source or not resolved_key:
            raise ValueError("Missing required fields")

        mapped_prompt = get_aesthetic_prompt(resolved_key)
        prompt_text = mapped_prompt or prompt_override or (
            "Yuz estetigini gelistirirken ayni kimligi koruyun. Kisinin yuzunu net ve dogal gosterin."
        )

        bucket: Any = storage.bucket()
        resolved_user_image = _download_image_from_source(user_image_source)
        input_ext = _ext_from_mime(resolved_user_image.get("mimeType") or "image/jpeg")
        input_upload_id = str(uuid4())
        input_path = f"image_coin/{user_id}/upload/{input_upload_id}/input.{input_ext}"
        input_blob = bucket.blob(input_path)
        input_blob.cache_control = "public,max-age=31536000"
        input_blob.upload_from_string(
            resolved_user_image["buffer"],
            content_type=resolved_user_image.get("mimeType") or "image/jpeg",
        )
        input_url = _get_signed_or_public_url(input_path)

        generated = _generate_aesthetic_photo(input_url, prompt_text, requested_model)

        generated_ext = _ext_from_mime(generated.get("mimeType") or "image/png")
        generated_id = str(uuid4())
        generated_path = f"image_coin/{user_id}/estetik/{generated_id}/output.{generated_ext}"
        generated_buffer = base64.b64decode(generated["data"])
        output_blob = bucket.blob(generated_path)
        output_blob.cache_control = "public,max-age=31536000"
        output_blob.upload_from_string(
            generated_buffer,
            content_type=generated.get("mimeType") or "image/png",
        )
        output_url = _get_signed_or_public_url(generated_path)

        db = firestore.client()
        doc_ref = (
            db.collection("users")
            .document(user_id)
            .collection("generatedImages")
            .document(generated_id)
        )
        now_value = firestore.SERVER_TIMESTAMP
        doc_ref.set(
            {
                "styleType": "aesthetic",
                "styleId": resolved_key,
                "prompt": prompt_text,
                "outputImageUrl": output_url,
                "outputImagePath": generated_path,
                "outputVideoUrl": None,
                "outputVideoPath": None,
                "outputMimeType": generated.get("mimeType") or "image/png",
                "inputImageUrl": input_url,
                "inputImagePath": input_path,
                "createdAt": now_value,
                "updatedAt": now_value,
            }
        )

        response_payload = {
            "request_id": request_id,
            "style_id": resolved_key,
            "user_id": user_id,
            "prompt": prompt_text,
            "input": {"path": input_path, "url": input_url},
            "output": {
                "id": generated_id,
                "path": generated_path,
                "url": output_url,
                "mimeType": generated.get("mimeType") or "image/png",
            },
        }

        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _log_json_block(
            "Response",
            request,
            request_id,
            response_payload,
            {"statusCode": 200, "durationMs": duration_ms},
        )

        return JSONResponse(content=response_payload)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.error("Aesthetic generate failed | %s", {"error": str(exc)})
        _log_json_block(
            "Response",
            request,
            request_id,
            {"error": {"message": "Hata olustu, lutfen tekrar deneyin."}},
            {"statusCode": 500, "durationMs": duration_ms},
        )
        raise HTTPException(status_code=500, detail={"error": {"message": "Hata olustu, lutfen tekrar deneyin."}})
