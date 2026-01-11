from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class PricingConfig:
    """Pricing configuration for a single model in USD per 1M tokens."""

    model: str
    input_per_1m: float
    output_per_1m: float
    currency: str = "USD"


DEFAULT_PRICING: Dict[str, PricingConfig] = {
    "gpt-4o-mini": PricingConfig(
        model="gpt-4o-mini",
        input_per_1m=0.15,
        output_per_1m=0.60,
    ),
    "gemini-1.5-pro": PricingConfig(
        model="gemini-1.5-pro",
        input_per_1m=3.50,
        output_per_1m=10.50,
    ),
}


def calculate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    pricing: Optional[Dict[str, PricingConfig]] = None,
) -> Tuple[float, float, float]:
    """Return (input_cost_usd, output_cost_usd, total_cost_usd).

    Raises:
        KeyError: if the model does not exist in pricing config.
    """

    pricing = pricing or DEFAULT_PRICING
    config = pricing[model]
    input_cost = (input_tokens / 1_000_000) * config.input_per_1m
    output_cost = (output_tokens / 1_000_000) * config.output_per_1m
    return input_cost, output_cost, input_cost + output_cost
