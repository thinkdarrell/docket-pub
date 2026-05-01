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
