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

from .family_assets import get_family_prompt, resolve_family_style_id
from .fal_utils import extract_image_url_from_fal_response, fal_subscribe, get_fal_key, summarize_url

logger = logging.getLogger("pdf_read_refresh.styles.family")

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
    endpoint_value = "family"
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


def _generate_family_lifestyle_photo(
    mother_image_url: str,
    father_image_url: str,
    baby_image_url: str,
    prompt: str,
    model: Optional[str],
) -> Dict[str, Any]:
    resolved_model = model or os.getenv("FAL_LIFESTYLE_MODEL", "fal-ai/gemini-3.1-flash-image-preview/edit")
    if not get_fal_key():
        raise ValueError("FAL_KEY is not configured")

    input_payload = {
        "prompt": prompt,
        "num_images": 1,
        "aspect_ratio": "auto",
        "output_format": "png",
        "image_urls": [mother_image_url, father_image_url, baby_image_url],
        "resolution": "1K",
        "limit_generations": True,
    }
    logger.info(
        "FAL family lifestyle request prepared | %s",
        {
            "model": resolved_model,
            "input": {
                "prompt": prompt,
                "image_urls": [
                    summarize_url(mother_image_url),
                    summarize_url(father_image_url),
                    summarize_url(baby_image_url),
                ],
            },
        },
    )

    result = fal_subscribe(resolved_model, input_payload)
    output_url = extract_image_url_from_fal_response(result)
    if not output_url:
        raise ValueError("FAL family lifestyle returned no output URL")

    output_response = requests.get(output_url, timeout=120)
    if not output_response.ok:
        raise ValueError(f"Unable to download generated image ({output_response.status_code})")
    output_mime = (output_response.headers.get("content-type") or "image/png").lower().strip()
    output_base64 = base64.b64encode(output_response.content).decode("utf-8")

    return {"data": output_base64, "mimeType": output_mime, "text": None}


@router.post("/family/generate-photo")
async def generate_family_photo(payload: Dict[str, Any] = Body(...), request: Request = None):
    started_at = time.perf_counter()
    user_id = _get_request_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail={"error": "access_denied", "message": "Authentication required"})

    request_id = request.headers.get("x-request-id")
    try:
        style_id = payload.get("style_id") if isinstance(payload.get("style_id"), str) else None
        mother_source = payload.get("mother_image_url") if isinstance(payload.get("mother_image_url"), str) else ""
        father_source = payload.get("father_image_url") if isinstance(payload.get("father_image_url"), str) else ""
        baby_source = payload.get("baby_image_url") if isinstance(payload.get("baby_image_url"), str) else ""
        request_id = payload.get("request_id") if isinstance(payload.get("request_id"), str) else request_id
        requested_model = payload.get("model") if isinstance(payload.get("model"), str) else None
        prompt_override = payload.get("prompt") if isinstance(payload.get("prompt"), str) else None
        resolved_style_id = resolve_family_style_id(style_id)
        prompt_text = get_family_prompt(resolved_style_id, prompt_override)

        _log_json_block(
            "Request",
            request,
            request_id,
            {
                "style_id": style_id,
                "resolved_style_id": resolved_style_id,
                "user_id": user_id,
                "mother_image_url": summarize_url(mother_source),
                "father_image_url": summarize_url(father_source),
                "baby_image_url": summarize_url(baby_source),
                "model": requested_model,
                "prompt": prompt_text,
            },
        )

        logger.info(
            "Family lifestyle request received | %s",
            {
                "requestId": request_id,
                "userId": user_id,
                "styleId": style_id,
                "resolvedStyleId": resolved_style_id,
                "motherImagePreview": summarize_url(mother_source),
                "fatherImagePreview": summarize_url(father_source),
                "babyImagePreview": summarize_url(baby_source),
                "model": requested_model,
            },
        )

        if not mother_source or not father_source or not baby_source or not prompt_text:
            raise ValueError("Missing required fields")

        bucket: Any = storage.bucket()
        resolved_mother = _download_image_from_source(mother_source)
        resolved_father = _download_image_from_source(father_source)
        resolved_baby = _download_image_from_source(baby_source)

        input_upload_id = str(uuid4())
        mother_ext = _ext_from_mime(resolved_mother.get("mimeType") or "image/jpeg")
        father_ext = _ext_from_mime(resolved_father.get("mimeType") or "image/jpeg")
        baby_ext = _ext_from_mime(resolved_baby.get("mimeType") or "image/jpeg")
        mother_path = f"image/{input_upload_id}/mother.{mother_ext}"
        father_path = f"image/{input_upload_id}/father.{father_ext}"
        baby_path = f"image/{input_upload_id}/baby.{baby_ext}"

        for path, resolved in (
            (mother_path, resolved_mother),
            (father_path, resolved_father),
            (baby_path, resolved_baby),
        ):
            blob = bucket.blob(path)
            blob.cache_control = "public,max-age=31536000"
            blob.upload_from_string(
                resolved["buffer"],
                content_type=resolved.get("mimeType") or "image/jpeg",
            )

        mother_url = _get_signed_or_public_url(mother_path)
        father_url = _get_signed_or_public_url(father_path)
        baby_url = _get_signed_or_public_url(baby_path)

        logger.info(
            "Family lifestyle inputs stored | %s",
            {
                "requestId": request_id,
                "userId": user_id,
                "motherPath": mother_path,
                "fatherPath": father_path,
                "babyPath": baby_path,
            },
        )

        generated = _generate_family_lifestyle_photo(mother_url, father_url, baby_url, prompt_text, requested_model)

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
            "Family lifestyle output prepared | %s",
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
        db.collection("users").document(user_id).collection("generatedImages").document(generated_id).set(
            {
                "id": generated_id,
                "styleType": "lifestyle",
                "styleId": resolved_style_id or style_id or None,
                "requestId": request_id,
                "prompt": prompt_text,
                "inputMotherImagePath": mother_path,
                "inputMotherImageUrl": mother_url,
                "inputFatherImagePath": father_path,
                "inputFatherImageUrl": father_url,
                "inputBabyImagePath": baby_path,
                "inputBabyImageUrl": baby_url,
                "outputImagePath": generated_path,
                "outputImageUrl": output_url,
                "outputMimeType": generated.get("mimeType") or "image/png",
                "createdAt": firestore.SERVER_TIMESTAMP,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            }
        )

        response_payload = {
            "request_id": request_id,
            "style_id": resolved_style_id or style_id or None,
            "user_id": user_id,
            "prompt": prompt_text,
            "input": {
                "mother_path": mother_path,
                "mother_url": mother_url,
                "father_path": father_path,
                "father_url": father_url,
                "baby_path": baby_path,
                "baby_url": baby_url,
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

        return JSONResponse(content=response_payload)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Family lifestyle generate failed | %s", {"error": str(exc), "requestId": request_id, "userId": user_id})
        return JSONResponse(
            status_code=500,
            content={"error": {"message": "Hata olustu, lutfen tekrar deneyin."}},
        )
