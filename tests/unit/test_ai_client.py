# tests/unit/test_ai_client.py
"""Tests for AIClient: success, retries, validation, cost tracking."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from docket.ai.client import AIClient
from docket.ai.contexts import AgendaItemContext, MeetingContext
from docket.ai.exceptions import AIFatalError, AIRateLimited, AITransientError, AIPermanentRowError
from docket.ai.pricing import Usage


def _stub_anthropic_message(json_payload: dict, usage: dict | None = None):
    """Return a MagicMock matching the relevant parts of anthropic.types.Message."""
    msg = MagicMock()
    msg.stop_reason = "tool_use"
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = json_payload
    msg.content = [tool_block]
    u = MagicMock()
    u.input_tokens = (usage or {}).get("input_tokens", 100)
    u.cache_creation_input_tokens = (usage or {}).get("cache_creation_input_tokens", 0)
    u.cache_read_input_tokens = (usage or {}).get("cache_read_input_tokens", 0)
    u.output_tokens = (usage or {}).get("output_tokens", 50)
    msg.usage = u
    return msg


def _item_ctx() -> AgendaItemContext:
    return AgendaItemContext.from_row({
        "id": 1, "title": "Test", "description": "x", "sponsor": "y",
        "dollars_amount": Decimal("100.00"), "topic": "Other", "is_consent": False,
    })


def _meeting_ctx() -> MeetingContext:
    return MeetingContext(
        meeting_id=1, meeting_type="Council", meeting_date=date(2026, 4, 1),
        phase="provisional", item_summaries=["item summary 1", "item summary 2"],
    )


@patch("docket.ai.client.Anthropic")
def test_summarize_item_success(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _stub_anthropic_message({
        "is_substantive": True,
        "significance_rationale": "ok",
        "significance_score": 5.0,
        "consent_placement_rationale": "ok",
        "consent_placement_score": 5.0,
        "summary": "ok",
        "confidence": "high",
    })

    client = AIClient(api_key="test-key")
    result, usage = client.summarize_item(_item_ctx())
    assert result.summary == "ok"
    assert result.significance_score == 5.0
    assert isinstance(usage, Usage)
    assert usage.input_tokens == 100


@patch("docket.ai.client.Anthropic")
def test_summarize_meeting_success(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _stub_anthropic_message({
        "is_substantive": True,
        "substantive_item_count": 2,
        "executive_summary": "Council considered two items.",
        "phase": "provisional",
        "confidence": "high",
    })

    client = AIClient(api_key="test-key")
    result, usage = client.summarize_meeting(_meeting_ctx())
    assert result.executive_summary == "Council considered two items."


import httpx
from anthropic import APIStatusError


def _make_status_error(code: int):
    """Construct an APIStatusError with a given status code.

    anthropic >= 0.39 requires APIStatusError(message, *, response, body) where
    response is an httpx.Response. The response itself needs an associated
    httpx.Request or the SDK raises RuntimeError on attribute access.
    """
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code=code, request=req)
    return APIStatusError(message="x", response=response, body=None)


@patch("docket.ai.client.Anthropic")
def test_401_raises_fatal(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.side_effect = _make_status_error(401)
    with pytest.raises(AIFatalError):
        AIClient(api_key="bad").summarize_item(_item_ctx())


@patch("docket.ai.client.Anthropic")
def test_400_raises_permanent(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.side_effect = _make_status_error(400)
    with pytest.raises(AIPermanentRowError):
        AIClient(api_key="ok").summarize_item(_item_ctx())


@patch("docket.ai.client.Anthropic")
@patch("docket.ai.client.time.sleep", lambda _: None)
def test_5xx_retries_then_transient(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.side_effect = _make_status_error(503)
    with pytest.raises(AITransientError):
        AIClient(api_key="ok").summarize_item(_item_ctx())
    assert mock_client.messages.create.call_count == 3


@patch("docket.ai.client.Anthropic")
@patch("docket.ai.client.time.sleep", lambda _: None)
def test_5xx_then_success(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    success_msg = _stub_anthropic_message({
        "is_substantive": True, "significance_rationale": "ok", "significance_score": 5.0,
        "consent_placement_rationale": "ok", "consent_placement_score": 5.0,
        "summary": "ok", "confidence": "high",
    })
    mock_client.messages.create.side_effect = [_make_status_error(503), success_msg]
    result, _ = AIClient(api_key="ok").summarize_item(_item_ctx())
    assert result.summary == "ok"
    assert mock_client.messages.create.call_count == 2


@patch("docket.ai.client.Anthropic")
def test_validation_error_is_permanent(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _stub_anthropic_message({
        "is_substantive": True, "significance_rationale": "x", "significance_score": None,
        "consent_placement_rationale": "x", "consent_placement_score": None,
        "summary": "ok", "confidence": "high",
    })
    with pytest.raises(AIPermanentRowError):
        AIClient(api_key="ok").summarize_item(_item_ctx())


def test_no_api_key_raises_fatal():
    with pytest.raises(AIFatalError):
        AIClient(api_key="")
