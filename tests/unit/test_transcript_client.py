"""StructuredClient: request shape, stop-reason handling, retry ladder, usage."""
import json
from unittest.mock import MagicMock, patch

import pytest
from anthropic import RateLimitError

from docket.ai.exceptions import AIPermanentRowError, AIRateLimited
from docket.ai.transcripts.client import StructuredClient, build_request

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
          "required": ["answer"], "additionalProperties": False}


def _message(text: str | None, stop_reason: str = "end_turn", category: str | None = None):
    msg = MagicMock()
    msg.stop_reason = stop_reason
    msg.stop_details = MagicMock(category=category) if stop_reason == "refusal" else None
    thinking = MagicMock(); thinking.type = "thinking"; thinking.thinking = ""
    blocks = [thinking]
    if text is not None:
        tb = MagicMock(); tb.type = "text"; tb.text = text
        blocks.append(tb)
    msg.content = blocks
    msg.usage = MagicMock(input_tokens=120, cache_creation_input_tokens=0,
                          cache_read_input_tokens=100, output_tokens=30)
    return msg


def _client_with(message):
    with patch("docket.ai.transcripts.client.Anthropic") as cls:
        inst = MagicMock()
        cls.return_value = inst
        inst.messages.stream.return_value.__enter__.return_value.get_final_message.return_value = message
        c = StructuredClient(api_key="k")
        return c, inst


def test_build_request_uses_output_config_and_never_tool_choice():
    req = build_request(model="claude-opus-5-5", system="S", user="U", schema=SCHEMA, effort="high")
    assert req["output_config"] == {"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}}
    assert "tool_choice" not in req and "tools" not in req and "thinking" not in req
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert req["messages"] == [{"role": "user", "content": "U"}]


def test_call_parses_first_text_block_and_skips_thinking():
    c, inst = _client_with(_message(json.dumps({"answer": "yes"})))
    res = c.call(model="claude-sonnet-5-5", system="S", user="U", schema=SCHEMA)
    assert res.data == {"answer": "yes"}
    assert res.usage.input_tokens == 120 and res.usage.cache_read_input_tokens == 100
    kwargs = inst.messages.stream.call_args.kwargs
    assert kwargs["output_config"]["format"]["schema"] is SCHEMA
    assert "tool_choice" not in kwargs


def test_refusal_stop_reason_is_permanent_row_error():
    c, _ = _client_with(_message(None, stop_reason="refusal", category="cyber"))
    with pytest.raises(AIPermanentRowError, match="refusal: cyber"):
        c.call(model="claude-opus-5-5", system="S", user="U", schema=SCHEMA)


def test_max_tokens_stop_reason_is_permanent_row_error():
    c, _ = _client_with(_message('{"answer": "trunc', stop_reason="max_tokens"))
    with pytest.raises(AIPermanentRowError, match="max_tokens"):
        c.call(model="claude-opus-5-5", system="S", user="U", schema=SCHEMA)


def test_invalid_json_is_permanent_row_error():
    c, _ = _client_with(_message("not json"))
    with pytest.raises(AIPermanentRowError, match="invalid JSON"):
        c.call(model="claude-opus-5-5", system="S", user="U", schema=SCHEMA)


def test_rate_limit_honors_retry_after_then_raises():
    with patch("docket.ai.transcripts.client.Anthropic") as cls, \
         patch("docket.ai.transcripts.client.time.sleep") as sleep:
        inst = MagicMock(); cls.return_value = inst
        resp = MagicMock(); resp.headers = {"retry-after": "7"}; resp.status_code = 429
        inst.messages.stream.side_effect = RateLimitError("rl", response=resp, body=None)
        c = StructuredClient(api_key="k")
        with pytest.raises(AIRateLimited):
            c.call(model="claude-opus-5-5", system="S", user="U", schema=SCHEMA)
        assert sleep.call_args_list[0].args[0] == 7.0
        assert inst.messages.stream.call_count == 3


def test_count_tokens_passes_system_and_user():
    with patch("docket.ai.transcripts.client.Anthropic") as cls:
        inst = MagicMock(); cls.return_value = inst
        inst.messages.count_tokens.return_value = MagicMock(input_tokens=4321)
        c = StructuredClient(api_key="k")
        assert c.count_tokens(model="claude-sonnet-5-5", system="S", user="U") == 4321
        kwargs = inst.messages.count_tokens.call_args.kwargs
        assert kwargs["model"] == "claude-sonnet-5-5"
        assert kwargs["messages"] == [{"role": "user", "content": "U"}]


def test_pricing_has_both_new_models():
    from docket.ai.pricing import PRICING, Usage, calculate_cost_usd
    for m in ("claude-sonnet-5-5", "claude-opus-5-5"):
        assert set(PRICING[m]) == {"input", "output", "cache_creation", "cache_read"}
    cost = calculate_cost_usd("claude-opus-5-5", Usage(1_000_000, 0, 0, 0))
    assert abs(cost - 4.00) < 1e-9


def test_refusal_still_emits_usage():
    c, _ = _client_with(_message(None, stop_reason="refusal", category="cyber"))
    with patch("docket.ai.transcripts.client.track_usage") as tu:
        with pytest.raises(AIPermanentRowError):
            c.call(model="claude-opus-5-5", system="S", user="U", schema=SCHEMA)
    tu.assert_called_once()
