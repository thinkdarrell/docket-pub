"""LIVE smoke test — calls real Anthropic API. Run with: pytest -m live tests/live/."""

import os
from datetime import date
from decimal import Decimal

import pytest

from docket.ai.client import AIClient
from docket.ai.contexts import AgendaItemContext, MeetingContext


pytestmark = pytest.mark.live


@pytest.fixture
def client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    return AIClient(api_key=key)


def test_haiku_item_smoke(client):
    ctx = AgendaItemContext.from_row({
        "id": 1,
        "title": "Authorize a $4,200,000 contract with ABC Construction for downtown street resurfacing",
        "description": "Three-year contract with optional one-year extension",
        "sponsor": "Public Works Department",
        "dollars_amount": Decimal("4200000.00"),
        "topic": "Public Works",
        "is_consent": False,
    })
    result, usage = client.summarize_item(ctx)
    assert result.is_substantive
    assert result.summary
    assert 0 <= result.significance_score <= 10
    assert usage.input_tokens > 0
    print(f"\nItem result: {result.summary}")
    print(f"Scores: sig={result.significance_score} consent={result.consent_placement_score}")


def test_sonnet_meeting_smoke(client):
    ctx = MeetingContext(
        meeting_id=1,
        meeting_type="Council Meeting",
        meeting_date=date(2026, 4, 1),
        phase="provisional",
        item_summaries=[
            "Approves $4.2M road resurfacing contract.",
            "Authorizes 3-year IT support agreement worth $850K.",
            "Defers vote on short-term rental ordinance to next meeting.",
        ],
    )
    result, usage = client.summarize_meeting(ctx)
    assert result.is_substantive
    assert result.executive_summary
    assert result.phase == "provisional"
    print(f"\nMeeting result: {result.executive_summary}")
