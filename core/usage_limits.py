from __future__ import annotations

import logging
from typing import Optional

from google.cloud import firestore as firestore_client

from .firebase import db


logger = logging.getLogger("pdf_read_refresh.usage_limits")

FREE_DAILY_LIMIT = 3


def _date_key() -> str:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d")


def _reset_iso() -> str:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    reset = now + timedelta(days=1)
    return reset.isoformat()


def _resolve_tier(is_premium: bool) -> str:
    return "premium" if is_premium else "free"


def _build_snapshot(count: int, is_premium: bool) -> dict:
    limit = float("inf") if is_premium else FREE_DAILY_LIMIT
    remaining = float("inf") if is_premium else max(limit - count, 0)
    return {
        "count": count,
        "limit": limit,
        "remaining": remaining,
        "tier": _resolve_tier(is_premium),
    }


def increment_usage(user_id: str, *, is_premium: bool) -> Optional[dict]:
    """
    Increment usage counter for a user (per-day) in Firestore.
    Returns snapshot dict or None if Firestore is unavailable.
    """
    if not db:
        logger.warning("Skipping usage increment; Firestore not initialized")
        return None
    if not user_id:
        logger.warning("Skipping usage increment; missing user_id")
        return None

    date_key = _date_key()
    usage_ref = (
        db.collection("usage_limits")
        .document(date_key)
        .collection("users")
        .document(user_id)
    )

    try:
        usage_ref.set(
            {
                "tier": _resolve_tier(is_premium),
                "resetAt": _reset_iso(),
                "updatedAt": firestore_client.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        usage_ref.set({"count": firestore_client.Increment(1)}, merge=True)
        snapshot = usage_ref.get()
        data = snapshot.to_dict() or {}
        count = data.get("count", 0)
        result = _build_snapshot(count, is_premium)
        logger.info(
            "Usage incremented",
            extra={
                "userId": user_id,
                "dateKey": date_key,
                "count": count,
                "premium": is_premium,
            },
        )
        return result
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Usage increment failed: %s", exc)
        return None


__all__ = ["increment_usage", "FREE_DAILY_LIMIT"]



