"""Per-model pricing for the four Anthropic billing dimensions.

Rates are in USD per token (not per million). Verified against
https://www.anthropic.com/pricing on 2026-05-01. Update with PR
review when Anthropic changes pricing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    output_tokens: int


# Per-token rates (USD). Source: anthropic.com/pricing, verified 2026-05-01.
# cache_creation = 1.25x input; cache_read = 0.10x input.
PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {
        "input":          1.00 / 1_000_000,
        "output":         5.00 / 1_000_000,
        "cache_creation": 1.25 / 1_000_000,
        "cache_read":     0.10 / 1_000_000,
    },
    "claude-sonnet-4-6": {
        "input":          3.00 / 1_000_000,
        "output":        15.00 / 1_000_000,
        "cache_creation": 3.75 / 1_000_000,
        "cache_read":     0.30 / 1_000_000,
    },
}


def calculate_cost_usd(model: str, usage: Usage) -> float:
    """Return the USD cost for a single API call's usage. Raises KeyError on unknown model."""
    rates = PRICING[model]
    return (
        usage.input_tokens * rates["input"]
        + usage.cache_creation_input_tokens * rates["cache_creation"]
        + usage.cache_read_input_tokens * rates["cache_read"]
        + usage.output_tokens * rates["output"]
    )


def usage_to_jsonb(usage: Usage) -> dict[str, int]:
    """Render usage as the JSONB shape stored in ai_runs.usage."""
    return {
        "input_tokens": usage.input_tokens,
        "cache_creation_input_tokens": usage.cache_creation_input_tokens,
        "cache_read_input_tokens": usage.cache_read_input_tokens,
        "output_tokens": usage.output_tokens,
    }


def usage_add(a: Usage, b: Usage) -> Usage:
    """Sum two Usage records (for batch accumulation)."""
    return Usage(
        input_tokens=a.input_tokens + b.input_tokens,
        cache_creation_input_tokens=a.cache_creation_input_tokens + b.cache_creation_input_tokens,
        cache_read_input_tokens=a.cache_read_input_tokens + b.cache_read_input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
    )
