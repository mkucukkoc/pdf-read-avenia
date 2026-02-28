from __future__ import annotations

import logging
from typing import Optional

from google.cloud import firestore as firestore_client

from .firebase import db


logger = logging.getLogger("pdf_read_refresh.usage_limits")

FREE_DAILY_LIMIT = 2


def _date_key() -> str:
    return "total"


def _reset_iso() -> Optional[str]:
    return None


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
        transaction = db.transaction()

        @firestore_client.transactional
        def _apply(transaction_ref: firestore_client.Transaction) -> dict:
            snapshot = usage_ref.get(transaction=transaction_ref)
            data = snapshot.to_dict() or {}
            count = int(data.get("count") or 0)

            if not is_premium and count >= FREE_DAILY_LIMIT:
                result = _build_snapshot(count, is_premium)
                result["blocked"] = True
                return result

            new_count = count + 1
            payload = {
                "tier": _resolve_tier(is_premium),
                "resetAt": _reset_iso(),
                "updatedAt": firestore_client.SERVER_TIMESTAMP,
                "count": new_count,
            }
            if not snapshot.exists:
                payload["createdAt"] = firestore_client.SERVER_TIMESTAMP

            transaction_ref.set(usage_ref, payload, merge=True)
            return _build_snapshot(new_count, is_premium)

        result = _apply(transaction)
        logger.info(
            "Usage incremented",
            extra={
                "userId": user_id,
                "dateKey": date_key,
                "count": result.get("count"),
                "premium": is_premium,
                "blocked": result.get("blocked", False),
            },
        )
        return result
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Usage increment failed: %s", exc)
        return None


__all__ = ["increment_usage", "FREE_DAILY_LIMIT"]

