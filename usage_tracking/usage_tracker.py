import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

import requests  # type: ignore[import-unresolved]

DEFAULT_EXECUTOR = ThreadPoolExecutor(max_workers=4)
LOGGER = logging.getLogger("pdf_read_refresh.usage_tracking")
DEBUG_LOGS = os.getenv("USAGE_TRACKING_DEBUG", "1").lower() in ("1", "true", "yes", "on")
USAGE_SERVICE_URL = os.getenv("USAGE_SERVICE_URL", "https://usage-service.onrender.com").strip().rstrip("/")
USAGE_SERVICE_INTERNAL_KEY = os.getenv("USAGE_SERVICE_INTERNAL_KEY", "usageservice2025aveniaaichat.com").strip()
_RAW_TIMEOUT = os.getenv("USAGE_SERVICE_TIMEOUT_S", "30")
try:
    _CONFIGURED_TIMEOUT = float(_RAW_TIMEOUT)
except ValueError:
    _CONFIGURED_TIMEOUT = 30.0

# Enforce a sensible floor so very small timeouts don't cause silent drops.
USAGE_SERVICE_TIMEOUT_S = max(_CONFIGURED_TIMEOUT, 30.0)


def enqueue_usage_update(_db: Any, event: Dict[str, Any]) -> None:
    """Fire-and-forget helper to forward usage events to usage-service."""

    LOGGER.info(
        "UsageTracking enqueue_usage_update received event",
        extra={
            "requestId": event.get("requestId"),
            "userId": event.get("userId"),
            "endpoint": event.get("endpoint"),
        },
    )

    def _work() -> None:
        LOGGER.info(
            "UsageTracking worker starting _post_usage_event",
            extra={
                "requestId": event.get("requestId"),
                "userId": event.get("userId"),
                "endpoint": event.get("endpoint"),
            },
        )
        _post_usage_event(event)

    DEFAULT_EXECUTOR.submit(_work)
    LOGGER.info(
        "UsageTracking enqueue_usage_update submitted to executor",
        extra={
            "requestId": event.get("requestId"),
            "userId": event.get("userId"),
            "endpoint": event.get("endpoint"),
        },
    )


def _post_usage_event(event: Dict[str, Any]) -> None:
    _log_env_config()

    if not USAGE_SERVICE_URL:
        LOGGER.info(
            "UsageTracking usage-service URL missing; event dropped",
            extra={
                "requestId": event.get("requestId"),
                "userId": event.get("userId"),
            },
        )
        return

    headers = {"Content-Type": "application/json"}
    if USAGE_SERVICE_INTERNAL_KEY:
        headers["X-Internal-Key"] = USAGE_SERVICE_INTERNAL_KEY

    url = f"{USAGE_SERVICE_URL}/v1/usage/events"
    LOGGER.info(
        "UsageTracking sending event to usage-service",
        extra={
            "requestId": event.get("requestId"),
            "userId": event.get("userId"),
            "endpoint": event.get("endpoint"),
            "url": url,
            "timeout_s": USAGE_SERVICE_TIMEOUT_S,
            "payload": event,
        },
    )
    try:
        response = requests.post(
            url, json=event, headers=headers, timeout=USAGE_SERVICE_TIMEOUT_S
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            "UsageTracking usage-service request failed",
            extra={
                "requestId": event.get("requestId"),
                "userId": event.get("userId"),
                "error": str(exc),
            },
            exc_info=DEBUG_LOGS,
        )
        return

    if response.status_code >= 400:
        LOGGER.warning(
            "UsageTracking usage-service rejected event",
            extra={
                "requestId": event.get("requestId"),
                "userId": event.get("userId"),
                "statusCode": response.status_code,
                "responseBody": (response.text or "")[:1000],
            },
        )
    else:
        LOGGER.info(
            "UsageTracking usage-service accepted event",
            extra={
                "requestId": event.get("requestId"),
                "userId": event.get("userId"),
                "statusCode": response.status_code,
                "responseBody": (response.text or "")[:1000],
            },
        )


def _log_env_config() -> None:
    """Log current usage-service client configuration (with masked key)."""

    LOGGER.info(
        "UsageTracking env configuration",
        extra={
            "usageServiceUrl": USAGE_SERVICE_URL or "<empty>",
            "hasInternalKey": bool(USAGE_SERVICE_INTERNAL_KEY),
            "internalKeyPreview": _mask_secret(USAGE_SERVICE_INTERNAL_KEY),
            "timeoutSeconds": USAGE_SERVICE_TIMEOUT_S,
        },
    )


def _mask_secret(value: str, visible: int = 3) -> str:
    if not value:
        return "<empty>"
    return f"{value[:visible]}***"
