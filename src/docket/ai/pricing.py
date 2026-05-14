"""Per-model pricing for the four Anthropic billing dimensions.

Rates are in USD per token (not per million). Verified against
https://www.anthropic.com/pricing on 2026-05-01. Update with PR
review when Anthropic changes pricing.

Also defines the cross-cutting usage-capture machinery (issue #33):
``track_usage`` lets producers (extraction.py, rewrite.py) emit a
``Usage`` record after every Anthropic call without changing their
return signatures; ``usage_capture`` lets consumers (the v3 worker)
collect those emissions per item and roll them into ``ai_runs.cost_usd``
so ``AI_DAILY_BUDGET_USD`` can actually enforce a cap on v3 spend.
"""

from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass
from typing import Iterator


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


# ---------------------------------------------------------------------------
# Usage capture — cross-cutting side channel for v3 cost telemetry (#33)
# ---------------------------------------------------------------------------
#
# extraction.py and rewrite.py call ``track_usage(model, usage)`` after every
# Anthropic API response. When a caller wraps a block of work in
# ``usage_capture()``, the emissions inside that block land in the yielded
# list. Outside a capture block, ``track_usage`` is a no-op — so tests,
# admin paths, and one-off CLI calls that don't care about telemetry don't
# pay any cost.
#
# Why a ContextVar rather than a module-level list:
#   - Nested captures (worker → process_item → capture inside a sub-task)
#     stay isolated. The inner capture won't double-count into the outer.
#   - Async-safe out of the box (asyncio.run propagates the context).
#   - Threading-safe — each thread sees its own value.
#
# The producer side (extraction/rewrite) just calls ``track_usage`` without
# knowing or caring whether a capture is active. The consumer side decides
# when to start a capture and what to do with the emissions.

_usage_sink: contextvars.ContextVar[list[tuple[str, Usage]] | None] = (
    contextvars.ContextVar("docket_ai_usage_sink", default=None)
)


def track_usage(model: str, usage: Usage) -> None:
    """Emit a ``(model, usage)`` pair into the active ``usage_capture`` block.

    No-op when no capture is active (the default outside the v3 worker
    loop). Producers call this once per Anthropic API response so the
    consumer can accumulate per-model totals.
    """
    sink = _usage_sink.get()
    if sink is not None:
        sink.append((model, usage))


@contextlib.contextmanager
def usage_capture() -> Iterator[list[tuple[str, Usage]]]:
    """Collect every ``track_usage`` emission inside this block.

    Yields a list that gets appended to as producers emit. The list is
    scoped to the active ``contextvars`` context, so nested captures stay
    isolated and concurrent workers don't cross-pollinate. Always reset
    on block exit even if the inner code raises.
    """
    sink: list[tuple[str, Usage]] = []
    token = _usage_sink.set(sink)
    try:
        yield sink
    finally:
        _usage_sink.reset(token)
