"""Tests for AI pricing math."""

import pytest

from docket.ai.pricing import PRICING, calculate_cost_usd, Usage


def test_haiku_uncached_only():
    """1000 input tokens uncached, 500 output, no cache."""
    usage = Usage(input_tokens=1000, cache_creation_input_tokens=0,
                  cache_read_input_tokens=0, output_tokens=500)
    cost = calculate_cost_usd("claude-haiku-4-5-20251001", usage)
    rates = PRICING["claude-haiku-4-5-20251001"]
    expected = (1000 * rates["input"]) + (500 * rates["output"])
    assert cost == pytest.approx(expected, rel=1e-9)


def test_haiku_cache_read_dominates():
    """38900 cache-read tokens cost 90% less than regular input."""
    usage = Usage(input_tokens=200, cache_creation_input_tokens=0,
                  cache_read_input_tokens=38900, output_tokens=300)
    cost = calculate_cost_usd("claude-haiku-4-5-20251001", usage)
    rates = PRICING["claude-haiku-4-5-20251001"]
    expected = (200 * rates["input"]) + (38900 * rates["cache_read"]) + (300 * rates["output"])
    assert cost == pytest.approx(expected, rel=1e-9)
    assert rates["cache_read"] == pytest.approx(rates["input"] * 0.1, rel=0.01)


def test_cache_creation_premium():
    """Cache creation tokens cost 1.25x regular input."""
    rates = PRICING["claude-haiku-4-5-20251001"]
    assert rates["cache_creation"] == pytest.approx(rates["input"] * 1.25, rel=0.01)


def test_unknown_model_raises():
    usage = Usage(input_tokens=100, cache_creation_input_tokens=0,
                  cache_read_input_tokens=0, output_tokens=50)
    with pytest.raises(KeyError):
        calculate_cost_usd("not-a-model", usage)


# ===========================================================================
# Usage capture (issue #33): tracks per-model LLM usage emitted by the v3
# pipeline so worker._process_items_v3 can populate ai_runs.cost_usd and
# enforce AI_DAILY_BUDGET_USD.
# ===========================================================================


def test_usage_capture_collects_emitted_usage():
    from docket.ai.pricing import track_usage, usage_capture

    with usage_capture() as sink:
        track_usage("claude-haiku-4-5-20251001",
                    Usage(input_tokens=1000, cache_creation_input_tokens=0,
                          cache_read_input_tokens=0, output_tokens=500))
        track_usage("claude-haiku-4-5-20251001",
                    Usage(input_tokens=200, cache_creation_input_tokens=0,
                          cache_read_input_tokens=0, output_tokens=100))

    assert len(sink) == 2
    assert sink[0][0] == "claude-haiku-4-5-20251001"
    assert sink[0][1].input_tokens == 1000
    assert sink[1][1].output_tokens == 100


def test_track_usage_outside_capture_is_a_no_op():
    from docket.ai.pricing import track_usage

    # Should not raise. Called from extraction.py/rewrite.py at module
    # init time (test imports, admin paths) where no capture is active.
    track_usage("claude-haiku-4-5-20251001",
                Usage(input_tokens=1, cache_creation_input_tokens=0,
                      cache_read_input_tokens=0, output_tokens=1))


def test_usage_capture_isolates_nested_blocks():
    """Inner capture sees inner emits; outer capture sees its own only."""
    from docket.ai.pricing import track_usage, usage_capture

    outer_usage = Usage(input_tokens=100, cache_creation_input_tokens=0,
                        cache_read_input_tokens=0, output_tokens=10)
    inner_usage = Usage(input_tokens=200, cache_creation_input_tokens=0,
                        cache_read_input_tokens=0, output_tokens=20)

    with usage_capture() as outer:
        track_usage("claude-haiku-4-5-20251001", outer_usage)
        with usage_capture() as inner:
            track_usage("claude-haiku-4-5-20251001", inner_usage)

        assert len(inner) == 1
        assert inner[0][1].input_tokens == 200
        # Outer must NOT see the inner emit.
        assert len(outer) == 1
        assert outer[0][1].input_tokens == 100


def test_sonnet_present():
    """Sonnet 4.6 has a pricing entry."""
    assert "claude-sonnet-4-6" in PRICING
    rates = PRICING["claude-sonnet-4-6"]
    assert rates["input"] > 0
    assert rates["output"] > rates["input"]
