"""Tests for Stage 1 extraction worker (`docket.ai.extraction`)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from docket.ai.extraction import (
    EXTRACTION_PROMPT_VERSION,
    build_user_message,
    extract_facts_for_item,
)
from docket.ai.extraction_schema import StructuredFacts


def make_item(**kw):
    """Lightweight fixture for an item view."""
    defaults = {
        'id': 1,
        'title': "Award of HVAC contract",
        'description': "Long valid body content with full agenda item description text.",
        'sponsor': None,
        'dollars_amount': 87500,
        'topic': 'contracts',
        'is_consent': False,
    }
    defaults.update(kw)
    return type('Item', (), defaults)()


def test_build_user_message_includes_required_fields():
    item = make_item()
    msg = build_user_message(item)
    assert "Award of HVAC contract" in msg
    assert "$87,500" in msg or "87500" in msg
    assert "is_consent" in msg.lower() or "consent" in msg.lower()


def test_extract_facts_returns_validated_pydantic():
    """With a mocked Anthropic response, extract_facts_for_item returns a StructuredFacts."""
    item = make_item()

    mock_response = MagicMock()
    mock_response.model = 'claude-haiku-4-5-20251001'
    mock_response.content = [
        MagicMock(text=json.dumps({
            'funding_source': 'general_fund',
            'counterparty': 'Acme HVAC Inc.',
            'procurement_method': 'competitive',
            'location': None,
            'action_type': 'contract_award',
            'next_steps': {
                'committee_referral': None,
                'public_hearing_date': None,
                'public_hearing_time': None,
                'comment_period_end': None,
                'implementation_date': None,
            },
            'parcels_affected': None,
            'acres_affected': None,
        }))
    ]

    with patch('docket.ai.extraction.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_response
        # Avoid real DB writes by mocking the cache helpers
        with patch('docket.ai.extraction.cache_get', return_value=None), \
             patch('docket.ai.extraction.cache_put'):
            facts, model_id = extract_facts_for_item(item)

    assert isinstance(facts, StructuredFacts)
    assert facts.counterparty == 'Acme HVAC Inc.'
    assert facts.funding_source == 'general_fund'
    assert model_id == 'claude-haiku-4-5-20251001'


def test_extract_facts_raises_on_invalid_json():
    item = make_item()
    mock_response = MagicMock()
    mock_response.model = 'claude-haiku-4-5-20251001'
    mock_response.content = [MagicMock(text="not json {{{")]

    with patch('docket.ai.extraction.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_response
        with patch('docket.ai.extraction.cache_get', return_value=None), \
             patch('docket.ai.extraction.cache_put'):
            with pytest.raises(ValueError):  # JSON parse error
                extract_facts_for_item(item)


def test_extract_facts_raises_on_schema_violation():
    """Pydantic validation error if the model returns a bad enum value."""
    item = make_item()
    mock_response = MagicMock()
    mock_response.model = 'claude-haiku-4-5-20251001'
    mock_response.content = [MagicMock(text=json.dumps({
        'funding_source': 'WRONG_VALUE',
        'counterparty': None,
        'procurement_method': 'not_applicable',
        'location': None,
        'action_type': 'other',
        'next_steps': {},
        'parcels_affected': None,
        'acres_affected': None,
    }))]

    with patch('docket.ai.extraction.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_response
        with patch('docket.ai.extraction.cache_get', return_value=None), \
             patch('docket.ai.extraction.cache_put'):
            with pytest.raises(Exception):  # Pydantic ValidationError or wrapper
                extract_facts_for_item(item)


def test_strip_markdown_fences_removes_json_wrapper():
    """Decision #94(b): the strip helper handles ```json ... ``` wrappers."""
    from docket.ai.extraction import _strip_markdown_fences
    wrapped = '```json\n{"x": 1}\n```'
    assert _strip_markdown_fences(wrapped) == '{"x": 1}'


def test_strip_markdown_fences_passthrough():
    """Bare JSON is unchanged."""
    from docket.ai.extraction import _strip_markdown_fences
    assert _strip_markdown_fences('{"x": 1}') == '{"x": 1}'
