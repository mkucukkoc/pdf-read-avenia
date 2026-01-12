import datetime as dt
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

from google.cloud import firestore

from .dedup import acquire_request_lock

DEFAULT_EXECUTOR = ThreadPoolExecutor(max_workers=4)
LOGGER = logging.getLogger("pdf_read_refresh.usage_tracking")
DEBUG_LOGS = os.getenv("USAGE_TRACKING_DEBUG", "").lower() in ("1", "true", "yes", "on")


def log_event(db: firestore.Client, event: Dict[str, Any]) -> None:
    """Write a raw usage event document.

    Firestore path: usage_events/{YYYY-MM-DD}/events/{requestId}
    """

    request_id = event["requestId"]
    timestamp = _parse_timestamp(event["timestamp"])
    date_key = timestamp.strftime("%Y-%m-%d")

    doc_ref = (
        db.collection("usage_events")
        .document(date_key)
        .collection("events")
        .document(request_id)
    )
    payload = dict(event)
    payload.setdefault("loggedAt", firestore.SERVER_TIMESTAMP)
    if DEBUG_LOGS:
        LOGGER.info(
            "UsageTracking log_event start",
            extra={
                "requestId": request_id,
                "userId": event.get("userId"),
                "endpoint": event.get("endpoint"),
                "path": f"usage_events/{date_key}/events/{request_id}",
            },
        )
    doc_ref.set(payload, merge=True)
    if DEBUG_LOGS:
        LOGGER.info(
            "UsageTracking log_event done",
            extra={"requestId": request_id, "userId": event.get("userId")},
        )


def update_aggregates(db: firestore.Client, event: Dict[str, Any]) -> bool:
    """Update lifetime and monthly aggregates if requestId is new.

    Returns:
        True if aggregates were updated.
        False if requestId already existed (idempotent skip).
    """

    request_id = event["requestId"]
    user_id = event["userId"]
    timestamp = _parse_timestamp(event["timestamp"])
    month_key = timestamp.strftime("%Y-%m")

    if not acquire_request_lock(
        db,
        request_id,
        {
            "userId": user_id,
            "endpoint": event.get("endpoint"),
            "createdAt": firestore.SERVER_TIMESTAMP,
        },
    ):
        if DEBUG_LOGS:
            LOGGER.info(
                "UsageTracking dedup skip (requestId already exists)",
                extra={"requestId": request_id, "userId": user_id},
            )
        return False

    lifetime_ref = db.collection("user_usage").document(user_id)
    monthly_ref = db.collection("user_usage_monthly").document(f"{user_id}_{month_key}")

    @firestore.transactional
    def _txn(transaction: firestore.Transaction) -> None:
        lifetime_snapshot = lifetime_ref.get(transaction=transaction)
        monthly_snapshot = monthly_ref.get(transaction=transaction)

        lifetime_update = _build_aggregate_update(event, lifetime_snapshot)
        monthly_update = _build_aggregate_update(
            event,
            monthly_snapshot,
            month_key=month_key,
            is_monthly=True,
        )

        if DEBUG_LOGS:
            LOGGER.info(
                "UsageTracking aggregate updates prepared",
                extra={
                    "requestId": request_id,
                    "userId": user_id,
                    "month": month_key,
                    "lifetime_exists": lifetime_snapshot.exists,
                    "monthly_exists": monthly_snapshot.exists,
                },
            )

        transaction.set(lifetime_ref, lifetime_update, merge=True)
        transaction.set(monthly_ref, monthly_update, merge=True)

    transaction = db.transaction()
    _txn(transaction)
    if DEBUG_LOGS:
        LOGGER.info(
            "UsageTracking aggregate updates committed",
            extra={
                "requestId": request_id,
                "userId": user_id,
                "month": month_key,
            },
        )
    return True


def enqueue_usage_update(db: firestore.Client, event: Dict[str, Any]) -> None:
    """Fire-and-forget helper to log events and update aggregates."""

    def _work() -> None:
        try:
            log_event(db, event)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "UsageTracking log_event failed",
                extra={
                    "requestId": event.get("requestId"),
                    "userId": event.get("userId"),
                    "error": str(exc),
                },
                exc_info=DEBUG_LOGS,
            )
        try:
            update_aggregates(db, event)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "UsageTracking update_aggregates failed",
                extra={
                    "requestId": event.get("requestId"),
                    "userId": event.get("userId"),
                    "error": str(exc),
                },
                exc_info=DEBUG_LOGS,
            )

    if DEBUG_LOGS:
        LOGGER.info(
            "UsageTracking enqueue_usage_update submit",
            extra={
                "requestId": event.get("requestId"),
                "userId": event.get("userId"),
                "endpoint": event.get("endpoint"),
            },
        )
    DEFAULT_EXECUTOR.submit(_work)


def _build_aggregate_update(
    event: Dict[str, Any],
    snapshot: firestore.DocumentSnapshot,
    month_key: Optional[str] = None,
    is_monthly: bool = False,
) -> Dict[str, Any]:
    now = firestore.SERVER_TIMESTAMP
    started_at = snapshot.get("startedAt") if snapshot.exists else None
    existing_usage = snapshot.get("usage") or {}
    previous_total_requests = existing_usage.get("totalRequests", 0)

    total_requests = 1
    input_tokens = event.get("inputTokens", 0)
    output_tokens = event.get("outputTokens", 0)
    total_tokens = event.get("totalTokens", input_tokens + output_tokens)
    cached_tokens = event.get("cachedTokens", 0)
    is_cache_hit = bool(event.get("isCacheHit", False))
    cache_hit_count = 1 if is_cache_hit else 0

    endpoint = event.get("endpoint")
    provider = event.get("provider")
    model = event.get("model")
    currency = event.get("userCurrency")

    cost_local = event.get("cost", {}).get("amount", 0.0)
    cost_usd = event.get("costUSD", 0.0)

    update: Dict[str, Any] = {
        "userId": event["userId"],
        "lastRequestAt": event["timestamp"],
        "updatedAt": now,
        "subscriptionType": event.get("subscriptionType"),
        "countryCode": event.get("countryCode"),
        "userCurrency": currency,
    }

    if is_monthly:
        update["month"] = month_key
        update.setdefault("startedAt", _month_start(event["timestamp"]))
    else:
        update["startedAt"] = started_at or event["timestamp"]

    update.setdefault("usage", {})
    update["usage"].update(
        {
            "totalRequests": firestore.Increment(total_requests),
            "inputTokens": firestore.Increment(input_tokens),
            "outputTokens": firestore.Increment(output_tokens),
            "totalTokens": firestore.Increment(total_tokens),
            "cachedTokens": firestore.Increment(cached_tokens),
            "cacheHitCount": firestore.Increment(cache_hit_count),
        }
    )

    if endpoint:
        update.setdefault("usage", {}).setdefault("endpoints", {})[
            endpoint
        ] = firestore.Increment(1)
        update.setdefault("usage", {}).setdefault("endpointTokens", {})[
            endpoint
        ] = {
            "input": firestore.Increment(input_tokens),
            "output": firestore.Increment(output_tokens),
            "total": firestore.Increment(total_tokens),
        }

    update.setdefault("financials", {})
    update["financials"].update(
        {
            "cost": {"amount": firestore.Increment(cost_local), "currency": currency},
            "costUSD": firestore.Increment(cost_usd),
            "costCalculationVersion": event.get("costCalculationVersion"),
            "fx": event.get("fx"),
        }
    )
    if endpoint:
        update["financials"].setdefault("endpointCost", {})[endpoint] = {
            "amount": firestore.Increment(cost_local),
            "currency": currency,
        }

    if provider:
        update.setdefault("providers", {}).setdefault(provider, {})
        update["providers"][provider].update(
            {
                "requests": firestore.Increment(1),
                "inputTokens": firestore.Increment(input_tokens),
                "outputTokens": firestore.Increment(output_tokens),
                "costTRY": firestore.Increment(cost_local),
            }
        )

    if model:
        update.setdefault("models", {}).setdefault(model, {})
        update["models"][model].update(
            {
                "requests": firestore.Increment(1),
                "inputTokens": firestore.Increment(input_tokens),
                "outputTokens": firestore.Increment(output_tokens),
                "costTRY": firestore.Increment(cost_local),
            }
        )

    if event.get("status") == "error":
        update.setdefault("stats", {})
        update["stats"].update(
            {
                "errorCount": firestore.Increment(1),
                "lastErrorAt": event["timestamp"],
            }
        )

    latency_ms = event.get("latencyMs")
    if latency_ms is not None:
        prev_avg = (snapshot.get("stats", {}) or {}).get("avgLatencyMs")
        prev_p95 = (snapshot.get("stats", {}) or {}).get("p95LatencyMs", 0)
        prev_count = previous_total_requests
        new_avg = latency_ms if prev_avg is None else ((prev_avg * prev_count) + latency_ms) / max(prev_count + 1, 1)
        update.setdefault("stats", {})
        update["stats"].update(
            {
                "avgLatencyMs": new_avg,
                "p95LatencyMs": max(latency_ms, prev_p95),
            }
        )

    metadata = event.get("metadata") or {}
    if metadata:
        update.setdefault("metadata", {}).update(
            {
                "lastPlatform": metadata.get("platform"),
                "lastAppVersion": metadata.get("appVersion"),
                "lastIpCountryMismatch": metadata.get("ipCountryMismatch"),
            }
        )

    plan_snapshot = event.get("plan")
    if plan_snapshot:
        update["plan"] = plan_snapshot

    quotas = event.get("quotas")
    if quotas:
        update["quotas"] = quotas

    credits = event.get("credits")
    if credits:
        update["credits"] = credits

    throttling = event.get("throttlingDecision")
    if throttling:
        update.setdefault("quotas", {}).update(
            {
                "softLimitReached": throttling.get("softLimitReached"),
                "isThrottled": throttling.get("isThrottled"),
                "blockedUntil": throttling.get("blockedUntil"),
                "blockReason": throttling.get("blockReason"),
            }
        )

    return update


def _parse_timestamp(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, (int, float)):
        return dt.datetime.utcfromtimestamp(value / 1000)
    return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _month_start(value: Any) -> str:
    dt_value = _parse_timestamp(value)
    return dt.datetime(dt_value.year, dt_value.month, 1, tzinfo=dt.timezone.utc).isoformat()
