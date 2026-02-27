import logging
import os
import json
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("pdf_read_refresh.styles.fal_utils")

try:
    import fal_client  # type: ignore
except Exception as exc:  # pragma: no cover - optional dependency
    fal_client = None  # type: ignore
    logger.warning("fal_client import failed: %s", exc)


def get_fal_key() -> str:
    return os.getenv("FAL_KEY") or os.getenv("FAL_API_KEY") or ""


def ensure_fal_configured() -> bool:
    if fal_client is None:
        return False
    key = get_fal_key()
    if not key:
        return False
    # fal_client uses module-level api_key in recent versions.
    if hasattr(fal_client, "api_key"):
        setattr(fal_client, "api_key", key)
    # Backward compat for older versions.
    if hasattr(fal_client, "config"):
        try:
            fal_client.config({"credentials": key})
        except Exception:
            pass
    return True


def fal_subscribe(
    model: str,
    input_payload: Dict[str, Any],
    on_queue_update: Optional[Callable[[Any], None]] = None,
) -> Any:
    if fal_client is None:
        raise RuntimeError("fal_client is not installed")
    ensure_fal_configured()
    try:
        logger.info(
            "FAL subscribe started | %s",
            {
                "model": model,
                "payloadPreview": summarize_payload(input_payload),
            },
        )
    except Exception:
        logger.info("FAL subscribe started (payload preview failed)")
    # Support multiple client signatures across versions.
    try:
        result = fal_client.subscribe(
            model,
            arguments=input_payload,
            with_logs=True,
            on_queue_update=on_queue_update,
        )
    except TypeError:
        result = fal_client.subscribe(
            model,
            input=input_payload,
            logs=True,
            on_queue_update=on_queue_update,
        )
    try:
        logger.info(
            "FAL subscribe completed | %s",
            {
                "model": model,
                "resultPreview": summarize_payload(result),
            },
        )
    except Exception:
        logger.info("FAL subscribe completed (result preview failed)")
    return result


def extract_video_url_from_fal_response(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    direct = (
        payload.get("video", {}).get("url")
        or payload.get("videoUrl")
        or payload.get("output", {}).get("url")
        or payload.get("result", {}).get("video", {}).get("url")
        or payload.get("response", {}).get("video", {}).get("url")
        or payload.get("response", {}).get("videoUrl")
        or payload.get("response", {}).get("output", {}).get("url")
        or payload.get("response", {}).get("result", {}).get("video", {}).get("url")
        or payload.get("data", {}).get("video", {}).get("url")
        or payload.get("response", {}).get("data", {}).get("video", {}).get("url")
        or payload.get("result", {}).get("data", {}).get("video", {}).get("url")
    )
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    return None


def extract_image_url_from_fal_response(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    url = (
        payload.get("data", {}).get("image", {}).get("url")
        or payload.get("image", {}).get("url")
        or (payload.get("data", {}).get("images") or [{}])[0].get("url")
        or (payload.get("images") or [{}])[0].get("url")
    )
    if isinstance(url, str) and url.strip():
        return url.strip()
    return None


def summarize_url(value: Optional[str], max_len: int = 180) -> Optional[str]:
    if not value:
        return None
    return value[:max_len]


def summarize_payload(payload: Any, max_len: int = 2000) -> Any:
    try:
        serialized = json.dumps(payload, default=str)
    except Exception:
        return str(payload)[:max_len]
    if len(serialized) <= max_len:
        return payload
    return f"{serialized[:max_len]}...[len={len(serialized)}]"
