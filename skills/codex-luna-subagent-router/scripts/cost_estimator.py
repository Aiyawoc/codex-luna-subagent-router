"""Versioned, non-billing token-cost estimates for v2.8 shadow economics."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


PROFILE_VERSION = "openai-standard-2026-09-30"
LONG_CONTEXT_THRESHOLD = 272_000
MILLION = Decimal(1_000_000)

# USD per 1M text tokens. Cache writes, tool fees, regional premiums and other
# processing tiers are intentionally excluded because Router usage does not
# safely reconstruct those billing inputs.
RATES = {
    "gpt-6-luna": {
        "short": {"input": Decimal("0.10"), "cached": Decimal("0.01"), "output": Decimal("0.50")},
        "long": {"input": Decimal("0.20"), "cached": Decimal("0.02"), "output": Decimal("0.75")},
    },
    "gpt-6.1-sol": {
        "short": {"input": Decimal("2.00"), "cached": Decimal("0.10"), "output": Decimal("10.00")},
        "long": {"input": Decimal("4.00"), "cached": Decimal("0.20"), "output": Decimal("15.00")},
    },
    "gpt-6-astra": {
        "short": {"input": Decimal("10.00"), "cached": Decimal("1.00"), "output": Decimal("50.00")},
        "long": {"input": Decimal("20.00"), "cached": Decimal("2.00"), "output": Decimal("75.00")},
    },
    # Historical v2.7 route only. Kept for retrospective reporting, never as a
    # current automatic Worker candidate.
    "gpt-6-sol": {
        "short": {"input": Decimal("2.00"), "cached": Decimal("0.20"), "output": Decimal("10.00")},
        "long": {"input": Decimal("4.00"), "cached": Decimal("0.40"), "output": Decimal("15.00")},
    },
}


class CostEstimateError(ValueError):
    pass


def _counter(counts, field):
    value = counts.get(field) if isinstance(counts, dict) else None
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise CostEstimateError(f"{field} must be a non-negative integer or null")
    return value


def estimate(model, counts):
    """Estimate Standard text-token cost; never present the result as a bill."""
    if model not in RATES:
        return {
            "status": "unsupported_model",
            "model": model,
            "pricing_profile": PROFILE_VERSION,
            "estimated_usd": None,
            "reason": "no_versioned_rate",
        }
    input_tokens = _counter(counts, "input_tokens")
    cached_tokens = _counter(counts, "cached_input_tokens")
    output_tokens = _counter(counts, "output_tokens")
    if input_tokens is None or cached_tokens is None or output_tokens is None:
        return {
            "status": "incomplete_usage",
            "model": model,
            "pricing_profile": PROFILE_VERSION,
            "estimated_usd": None,
            "reason": "input_cached_output_required",
        }
    if cached_tokens > input_tokens:
        raise CostEstimateError("cached_input_tokens cannot exceed input_tokens")
    context_class = "long" if input_tokens > LONG_CONTEXT_THRESHOLD else "short"
    rate = RATES[model][context_class]
    uncached = input_tokens - cached_tokens
    amount = (
        Decimal(uncached) * rate["input"]
        + Decimal(cached_tokens) * rate["cached"]
        + Decimal(output_tokens) * rate["output"]
    ) / MILLION
    return {
        "status": "estimated",
        "model": model,
        "pricing_profile": PROFILE_VERSION,
        "context_class": context_class,
        "estimated_usd": float(amount.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)),
        "counts_used": {
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_tokens,
            "output_tokens": output_tokens,
        },
        "rates_per_million_usd": {key: float(value) for key, value in rate.items()},
        "excluded_costs": [
            "cache_writes", "tool_call_fees", "regional_premium", "processing_tier_adjustments", "non_text_modalities",
        ],
        "reason": "standard_text_token_estimate_only",
    }
