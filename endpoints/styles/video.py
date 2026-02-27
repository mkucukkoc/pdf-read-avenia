import logging
import os
from typing import Any, Dict, Optional
from uuid import uuid4
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse
from firebase_admin import firestore, storage

from .fal_utils import (
    extract_video_url_from_fal_response,
    fal_subscribe,
    get_fal_key,
    summarize_url,
)

logger = logging.getLogger("pdf_read_refresh.styles.video")

router = APIRouter(prefix="/api/styles", tags=["Styles"])

DEFAULT_VIDEO_REFERENCE_URL = (
    "https://firebasestorage.googleapis.com/v0/b/bebek-ai.firebasestorage.app/o/assets%2Fvideos%2Fucan.mp4"
    "?alt=media&token=2cfb0fc5-63aa-4a5c-9bea-51bfd78aeb28"
)
VIDEO_REFERENCE_URL_BY_STYLE_ID: Dict[str, str] = {
    "v1": "https://firebasestorage.googleapis.com/v0/b/bebek-ai.firebasestorage.app/o/assets%2Fvideos%2Fguzeloyun.mp4?alt=media",
    "v2": "https://firebasestorage.googleapis.com/v0/b/bebek-ai.firebasestorage.app/o/assets%2Fvideos%2Fhavada.mp4?alt=media",
    "v3": "https://firebasestorage.googleapis.com/v0/b/bebek-ai.firebasestorage.app/o/assets%2Fvideos%2Foyun.mp4?alt=media",
    "v4": "https://firebasestorage.googleapis.com/v0/b/bebek-ai.firebasestorage.app/o/assets%2Fvideos%2Fucan.mp4?alt=media&token=2cfb0fc5-63aa-4a5c-9bea-51bfd78aeb28",
}


def _resolve_video_reference_url(style_id: Optional[str]) -> str:
    if not style_id:
        return DEFAULT_VIDEO_REFERENCE_URL
    return VIDEO_REFERENCE_URL_BY_STYLE_ID.get(style_id) or DEFAULT_VIDEO_REFERENCE_URL


def _ext_from_video_mime(mime: str) -> str:
    if "webm" in mime:
        return "webm"
    if "quicktime" in mime or "mov" in mime:
        return "mov"
    return "mp4"


def _ext_from_image_mime(mime: str) -> str:
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
        file = bucket.file(parsed)
        exists = file.exists()
        if isinstance(exists, tuple):
            exists = exists[0]
        if exists:
            content = file.download_as_bytes()
            mime_type = "image/png" if file.name.lower().endswith(".png") else "image/jpeg"
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


def _download_video_from_source(source: str) -> Dict[str, Any]:
    if not source.startswith("http://") and not source.startswith("https://"):
        raise ValueError("Video source must be a valid URL")

    headers: Dict[str, str] = {}
    parsed = urlparse(source)
    if parsed.hostname == "generativelanguage.googleapis.com":
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required to download Gemini video files")
        headers["x-goog-api-key"] = api_key

    response = requests.get(source, headers=headers, timeout=120)
    if not response.ok:
        raise ValueError(f"Unable to download generated video ({response.status_code})")

    content_type = (response.headers.get("content-type") or "").lower().strip()
    mime_type = content_type if content_type.startswith("video/") else "video/mp4"
    return {"buffer": response.content, "mimeType": mime_type}


def _get_signed_or_public_url(file_path: str) -> str:
    bucket: Any = storage.bucket()
    file = bucket.file(file_path)
    try:
        signed_url = file.generate_signed_url(expiration="2099-12-31", method="GET")
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


def _generate_styled_video_with_fal(params: Dict[str, Any]) -> Dict[str, Any]:
    style_id = params.get("styleId")
    user_image_url = params.get("userImageUrl")
    reference_video_url = params.get("referenceVideoUrl")
    request_id = params.get("requestId")
    requested_model = params.get("model")

    resolved_model = requested_model or os.getenv("FAL_VIDEO_MODEL", "fal-ai/pixverse/swap")
    pixverse_resolution = os.getenv("FAL_VIDEO_RESOLUTION", "720p")
    pixverse_keyframe_id = int(os.getenv("FAL_VIDEO_KEYFRAME_ID", "1") or 1)
    enable_background_swap = os.getenv("FAL_VIDEO_ENABLE_BACKGROUND_SWAP", "true").lower() == "true"
    baby_background_url = os.getenv("FAL_VIDEO_BABY_BACKGROUND_IMAGE_URL", "")
    framing_prompt = (
        "Keep the baby face slightly farther from camera with medium-shot framing. Avoid extreme close-up facial framing. "
        "Remove any Instagram logo, watermark, username label, or platform text overlay from the final video."
    )

    has_fal_key = bool(get_fal_key())
    logger.info(
        {
            "requestId": request_id,
            "step": "fal_video_request_prepared",
            "styleId": style_id,
            "model": resolved_model,
            "userImageUrlPreview": summarize_url(user_image_url),
            "referenceVideoUrlPreview": summarize_url(reference_video_url),
            "hasFalKey": has_fal_key,
        },
        "FAL video request prepared",
    )

    if not has_fal_key:
        return {
            "outputVideoUrl": reference_video_url,
            "providerText": "Fallback video URL used because FAL_KEY is missing.",
            "providerStatus": None,
            "usedFallback": True,
            "providerRaw": None,
        }

    def run_pixverse_swap(args: Dict[str, Any]) -> Dict[str, Any]:
        input_payload = {
            "video_url": args["videoUrl"],
            "image_url": args["imageUrl"],
            "mode": args["mode"],
            "keyframe_id": pixverse_keyframe_id,
            "resolution": pixverse_resolution,
            "original_sound_switch": True,
        }
        if args.get("prompt"):
            input_payload["prompt"] = args["prompt"]

        logger.info(
            {
                "requestId": request_id,
                "step": f"{args['step']}_started",
                "model": resolved_model,
                "input": {
                    **input_payload,
                    "video_url": summarize_url(input_payload["video_url"]),
                    "image_url": summarize_url(input_payload["image_url"]),
                },
            },
            "FAL Pixverse swap step started",
        )

        result = fal_subscribe(resolved_model, input_payload)
        output_url = extract_video_url_from_fal_response(result)
        logger.info(
            {
                "requestId": request_id,
                "step": f"{args['step']}_completed",
                "model": resolved_model,
                "outputVideoUrlPreview": summarize_url(output_url),
            },
            "FAL Pixverse swap step completed",
        )
        return {"result": result, "outputVideoUrl": output_url}

    try:
        person_swap = run_pixverse_swap(
            {
                "mode": "person",
                "videoUrl": reference_video_url,
                "imageUrl": user_image_url,
                "step": "fal_pixverse_person_swap",
                "prompt": framing_prompt,
            }
        )
        if not person_swap.get("outputVideoUrl"):
            return {
                "outputVideoUrl": reference_video_url,
                "providerText": "FAL fallback used (person swap response missing video URL)",
                "providerStatus": 200,
                "usedFallback": True,
                "providerRaw": person_swap.get("result"),
            }

        final_video_url = person_swap["outputVideoUrl"]
        provider_raw: Any = person_swap.get("result")
        provider_text: Optional[str] = None

        if enable_background_swap and baby_background_url:
            try:
                background_swap = run_pixverse_swap(
                    {
                        "mode": "background",
                        "videoUrl": final_video_url,
                        "imageUrl": baby_background_url,
                        "step": "fal_pixverse_background_swap",
                    }
                )
                if background_swap.get("outputVideoUrl"):
                    final_video_url = background_swap["outputVideoUrl"]
                    provider_raw = {
                        "personSwap": person_swap.get("result"),
                        "backgroundSwap": background_swap.get("result"),
                    }
                else:
                    provider_text = "Background swap skipped: response missing video URL, returning person swap output."
                    provider_raw = {
                        "personSwap": person_swap.get("result"),
                        "backgroundSwap": background_swap.get("result"),
                    }
            except Exception as exc:
                logger.warning(
                    {
                        "requestId": request_id,
                        "step": "fal_pixverse_background_swap_failed",
                        "message": str(exc),
                    },
                    "Pixverse background swap failed; returning person swap output",
                )
                provider_text = "Background swap failed; returning person swap output."

        return {
            "outputVideoUrl": final_video_url,
            "providerText": provider_text,
            "providerStatus": 200,
            "usedFallback": False,
            "providerRaw": provider_raw,
        }
    except Exception as exc:
        logger.error(
            {
                "requestId": request_id,
                "step": "fal_video_request_failed",
                "message": str(exc),
            },
            "FAL video request failed; using fallback video URL",
        )
        return {
            "outputVideoUrl": reference_video_url,
            "providerText": f"FAL request failed: {str(exc) or 'unknown error'}",
            "providerStatus": None,
            "usedFallback": True,
            "providerRaw": None,
        }


@router.post("/video/generate")
async def generate_video(payload: Dict[str, Any] = Body(...), request: Request = None):
    user_id = _get_request_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail={"error": "access_denied", "message": "Authentication required"})

    style_id = payload.get("style_id") if isinstance(payload.get("style_id"), str) else None
    user_image_source = ""
    if isinstance(payload.get("user_image_url"), str):
        user_image_source = payload.get("user_image_url") or ""
    elif isinstance(payload.get("user_image_path"), str):
        user_image_source = payload.get("user_image_path") or ""
    request_id = payload.get("request_id") if isinstance(payload.get("request_id"), str) else request.headers.get("x-request-id")
    requested_model = payload.get("model") if isinstance(payload.get("model"), str) else None

    reference_video_url = _resolve_video_reference_url(style_id)
    if not reference_video_url:
        raise HTTPException(status_code=400, detail={"error": "invalid_request", "message": "Video URL could not be resolved"})

    if not user_image_source:
        raise HTTPException(status_code=400, detail={"error": "invalid_request", "message": "user_image_url is required"})

    bucket: Any = storage.bucket()
    resolved_user_image = _download_image_from_source(user_image_source)
    input_ext = _ext_from_image_mime(resolved_user_image.get("mimeType") or "image/jpeg")
    input_path = f"users_video/{user_id}/uploads/{uuid4()}-input.{input_ext}"
    bucket.file(input_path).save(
        resolved_user_image["buffer"],
        content_type=resolved_user_image.get("mimeType") or "image/jpeg",
        resumable=False,
        metadata={"cacheControl": "public,max-age=31536000"},
    )
    input_url = _get_signed_or_public_url(input_path)

    provider_result = _generate_styled_video_with_fal(
        {
            "styleId": style_id,
            "userImageUrl": input_url,
            "referenceVideoUrl": reference_video_url,
            "requestId": request_id,
            "model": requested_model,
        }
    )

    generated_id = str(uuid4())
    output_video_url = provider_result.get("outputVideoUrl")
    output_video_path: Optional[str] = None
    output_mime_type = "video/mp4"

    if not provider_result.get("usedFallback"):
        downloaded = _download_video_from_source(output_video_url)
        output_mime_type = downloaded.get("mimeType") or "video/mp4"
        video_ext = _ext_from_video_mime(output_mime_type)
        output_video_path = f"users_video/{user_id}/generatevideos/{generated_id}.{video_ext}"
        bucket.file(output_video_path).save(
            downloaded["buffer"],
            content_type=output_mime_type,
            resumable=False,
            metadata={"cacheControl": "public,max-age=31536000"},
        )
        output_video_url = _get_signed_or_public_url(output_video_path)

    db = firestore.client()
    db.collection("users").doc(user_id).collection("generatedVideos").doc(generated_id).set(
        {
            "id": generated_id,
            "styleType": "video",
            "styleId": style_id,
            "requestId": request_id,
            "inputImagePath": input_path,
            "inputImageUrl": input_url,
            "outputVideoUrl": output_video_url,
            "outputVideoPath": output_video_path,
            "outputImageUrl": None,
            "outputMimeType": output_mime_type,
            "providerText": provider_result.get("providerText"),
            "providerStatus": provider_result.get("providerStatus"),
            "providerRaw": provider_result.get("providerRaw"),
            "usedFallback": provider_result.get("usedFallback"),
            "createdAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
    )

    return JSONResponse(
        content={
            "request_id": request_id,
            "style_id": style_id,
            "user_id": user_id,
            "input": {"path": input_path, "url": input_url},
            "output": {
                "id": generated_id,
                "path": output_video_path,
                "url": output_video_url,
                "mimeType": output_mime_type,
            },
            "provider": {
                "text": provider_result.get("providerText"),
                "status": provider_result.get("providerStatus"),
                "used_fallback": provider_result.get("usedFallback"),
            },
        }
    )
