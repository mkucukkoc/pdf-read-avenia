from typing import Any, Dict, Optional


def map_revenuecat_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Map RevenueCat webhook payload to the plan snapshot schema.

    Expected fields:
      - commission_percentage
      - tax_percentage
      - takehome_percentage
      - price_in_purchased_currency
      - currency
      - country_code
    """

    commission = _to_float(event.get("commission_percentage"))
    tax = _to_float(event.get("tax_percentage"))
    takehome = _to_float(event.get("takehome_percentage"))

    list_price = _to_float(event.get("price_in_purchased_currency"))
    currency = event.get("currency")

    net_revenue_amount = list_price * takehome if list_price is not None else None
    platform_fee_amount = (
        list_price - net_revenue_amount
        if list_price is not None and net_revenue_amount is not None
        else None
    )

    return {
        "productId": event.get("product_id"),
        "period": event.get("period_type"),
        "listPrice": _amount(currency, list_price),
        "netRevenueEstimate": _amount(currency, net_revenue_amount),
        "platformFeeEstimate": _amount(currency, platform_fee_amount),
        "commissionPercentage": commission,
        "taxPercentage": tax,
        "store": event.get("store"),
        "renewalNumber": event.get("renewal_number"),
        "expiresAt": event.get("expiration_at_ms"),
        "lastRevenueCatEventAt": event.get("event_timestamp_ms"),
        "countryCode": event.get("country_code"),
        "currency": currency,
    }


def _amount(currency: Optional[str], amount: Optional[float]) -> Optional[Dict[str, Any]]:
    if amount is None or currency is None:
        return None
    return {"amount": round(amount, 2), "currency": currency}


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
