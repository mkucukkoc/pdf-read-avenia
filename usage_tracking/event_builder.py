from __future__ import annotations

import datetime as dt
import os
from typing import Any, Dict, Optional

from .fx import FxRateCache
from .pricing import calculate_cost_usd

DEFAULT_COST_CALCULATION_VERSION = os.getenv("COST_CALCULATION_VERSION", "pricing_v1.2")
DEFAULT_CURRENCY = "USD"
DEFAULT_PROVIDER = "gemini"

_FX_CACHE = FxRateCache()


def build_base_event(
    *,
    request_id: str,
    user_id: str,
    endpoint: str,
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
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    is_cache_hit: bool = False,
    latency_ms: Optional[int] = None,
    status: str = "success",
    error_code: Optional[str] = None,
    cost_calculation_version: Optional[str] = None,
    throttling_decision: Optional[Dict[str, Any]] = None,
    quotas: Optional[Dict[str, Any]] = None,
    credits: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    model = base_event.get("model") or ""
    currency = base_event.get("userCurrency") or DEFAULT_CURRENCY
    total_tokens = input_tokens + output_tokens

    cost_usd = _calculate_cost_usd_safe(model, input_tokens, output_tokens)
    cost_local, fx_payload = _calculate_local_cost(cost_usd, currency)

    event: Dict[str, Any] = dict(base_event)
    event.update(
        {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": total_tokens,
            "cachedTokens": cached_tokens,
            "isCacheHit": is_cache_hit,
            "latencyMs": latency_ms,
            "status": status,
            "errorCode": error_code,
            "cost": {"amount": round(cost_local, 6), "currency": currency},
            "costUSD": round(cost_usd, 6),
            "fx": fx_payload,
            "costCalculationVersion": cost_calculation_version or DEFAULT_COST_CALCULATION_VERSION,
        }
    )
    if throttling_decision:
        event["throttlingDecision"] = throttling_decision
    if quotas:
        event["quotas"] = quotas
    if credits:
        event["credits"] = credits
    return _compact(event)


def parse_gemini_usage(response_json: Dict[str, Any]) -> Dict[str, int]:
    usage = response_json.get("usageMetadata") or response_json.get("usage_metadata") or response_json.get("usage") or {}
    input_tokens = _to_int(
        usage.get("promptTokenCount")
        or usage.get("prompt_tokens")
        or usage.get("inputTokens")
        or usage.get("input_tokens")
    )
    output_tokens = _to_int(
        usage.get("candidatesTokenCount")
        or usage.get("completionTokenCount")
        or usage.get("completion_tokens")
        or usage.get("outputTokens")
        or usage.get("output_tokens")
    )
    total_tokens = _to_int(
        usage.get("totalTokenCount")
        or usage.get("total_tokens")
        or usage.get("totalTokens")
        or input_tokens + output_tokens
    )
    return {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
    }


def _calculate_cost_usd_safe(model: str, input_tokens: int, output_tokens: int) -> float:
    if not model:
        return 0.0
    normalized = _normalize_model_name(model)
    try:
        _, _, total_cost = calculate_cost_usd(normalized, input_tokens, output_tokens)
        return total_cost
    except KeyError:
        return 0.0


def _calculate_local_cost(cost_usd: float, currency: str) -> tuple[float, Optional[Dict[str, Any]]]:
    if not currency:
        return cost_usd, None
    if currency.upper() == "USD":
        return cost_usd, {
            "base": "USD",
            "quote": "USD",
            "rate": 1.0,
            "updatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
    fx = _FX_CACHE.get_or_fetch("USD", currency)
    return cost_usd * fx.rate, {
        "base": fx.base,
        "quote": fx.quote,
        "rate": fx.rate,
        "updatedAt": fx.updated_at.replace(tzinfo=dt.timezone.utc).isoformat(),
    }


def _normalize_model_name(model: str) -> str:
    return model.replace("models/", "", 1)


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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
