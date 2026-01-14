from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Optional

DEFAULT_CURRENCY = "USD"
DEFAULT_PROVIDER = "gemini"


def build_base_event(
    *,
    request_id: str,
    user_id: str,
    endpoint: str,
    action: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    token_payload: Optional[Dict[str, Any]] = None,
    request: Optional[Any] = None,
    timestamp: Optional[str] = None,
    plan_snapshot: Optional[Dict[str, Any]] = None,
    subscription_type: Optional[str] = None,
    country_code: Optional[str] = None,
    user_currency: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = token_payload or {}
    timestamp = timestamp or dt.datetime.now(dt.timezone.utc).isoformat()
    subscription_type = subscription_type or payload.get("subscriptionType") or payload.get("subscription_type")
    country_code = country_code or payload.get("countryCode") or payload.get("country_code")
    user_currency = user_currency or payload.get("userCurrency") or payload.get("currency") or DEFAULT_CURRENCY
    plan_snapshot = plan_snapshot or payload.get("plan")

    meta = _merge_metadata(payload, request, metadata)

    event: Dict[str, Any] = {
        "requestId": request_id,
        "userId": user_id,
        "endpoint": endpoint,
        "action": action or endpoint,
        "provider": provider or payload.get("provider") or DEFAULT_PROVIDER,
        "model": model or payload.get("model"),
        "timestamp": timestamp,
        "subscriptionType": subscription_type,
        "countryCode": country_code,
        "userCurrency": user_currency,
        "plan": plan_snapshot,
        "metadata": meta or None,
    }
    return _compact(event)


def finalize_event(
    base_event: Dict[str, Any],
    *,
    raw_usage: Optional[Dict[str, Any]] = None,
    cached_tokens: int = 0,
    is_cache_hit: bool = False,
    latency_ms: Optional[int] = None,
    status: str = "success",
    error_code: Optional[str] = None,
    throttling_decision: Optional[Dict[str, Any]] = None,
    quotas: Optional[Dict[str, Any]] = None,
    credits: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    event: Dict[str, Any] = dict(base_event)
    event.update(
        {
            "rawUsage": raw_usage or None,
            "cachedTokens": cached_tokens,
            "isCacheHit": is_cache_hit,
            "latencyMs": latency_ms,
            "status": status,
            "errorCode": error_code,
        }
    )
    if throttling_decision:
        event["throttlingDecision"] = throttling_decision
    if quotas:
        event["quotas"] = quotas
    if credits:
        event["credits"] = credits
    return _compact(event)


def extract_gemini_usage_metadata(response_json: Dict[str, Any]) -> Dict[str, Any]:
    usage = response_json.get("usageMetadata") or response_json.get("usage_metadata") or response_json.get("usage") or {}
    return usage if isinstance(usage, dict) else {}


def _merge_metadata(
    token_payload: Dict[str, Any],
    request: Optional[Any],
    metadata: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    if request is not None:
        headers = getattr(request, "headers", {}) or {}
        meta.update(
            {
                "platform": headers.get("x-platform") or headers.get("x-client-platform"),
                "appVersion": headers.get("x-app-version") or headers.get("x-client-version"),
                "ipCountry": headers.get("x-ip-country"),
            }
        )
        if "x-ip-country-mismatch" in headers:
            raw = headers.get("x-ip-country-mismatch")
            meta["ipCountryMismatch"] = str(raw).lower() in ("1", "true", "yes")
    meta.update(
        {
            "platform": token_payload.get("platform") or meta.get("platform"),
            "appVersion": token_payload.get("appVersion") or meta.get("appVersion"),
            "ipCountry": token_payload.get("ipCountry") or meta.get("ipCountry"),
            "ipCountryMismatch": token_payload.get("ipCountryMismatch"),
        }
    )
    if metadata:
        meta.update(metadata)
    return _compact(meta)


def _compact(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}
