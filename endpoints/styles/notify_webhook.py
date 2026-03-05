import logging
import os
from typing import Any, Dict

import requests

logger = logging.getLogger("pdf_read_refresh.styles.webhook")


def send_generation_webhook(payload: Dict[str, Any]) -> None:
    webhook_url = (os.getenv("GENERATION_WEBHOOK_URL") or "").strip()
    if not webhook_url:
        logger.debug("Generation webhook skipped: missing GENERATION_WEBHOOK_URL")
        return

    webhook_secret = (os.getenv("GENERATION_WEBHOOK_SECRET") or "").strip()
    headers = {"Content-Type": "application/json"}
    if webhook_secret:
        headers["x-webhook-secret"] = webhook_secret

    safe_payload = {**payload}
    if safe_payload.get("output_url"):
        safe_payload["output_url"] = "<redacted>"

    logger.info(
        "Generation webhook dispatch | %s",
        {
            "url": webhook_url,
            "payload": safe_payload,
        },
    )

    try:
        response = requests.post(webhook_url, json=payload, headers=headers, timeout=10)
        if not response.ok:
            preview = (response.text or "")[:300]
            logger.warning(
                "Generation webhook failed | %s",
                {
                    "statusCode": response.status_code,
                    "response": preview,
                    "payload": safe_payload,
                },
            )
            return
        logger.info(
            "Generation webhook delivered | %s",
            {
                "statusCode": response.status_code,
                "payload": safe_payload,
            },
        )
    except Exception as exc:
        logger.warning(
            "Generation webhook error | %s",
            {
                "error": str(exc),
                "payload": safe_payload,
            },
        )
