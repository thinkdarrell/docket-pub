"""Tests for Stage 1 extraction worker (`docket.ai.extraction`)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from docket.ai.extraction import (
    EXTRACTION_PROMPT_VERSION,
    build_user_message,
    extract_facts_for_item,
    persist_extraction,
)
from docket.ai.extraction_schema import NextSteps, StructuredFacts


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


def _make_tool_response(input_dict: dict, model: str = 'claude-haiku-4-5-20251001') -> MagicMock:
    """Build a mock Anthropic messages.create response shaped like a tool_use response."""
    mock_block = MagicMock()
    mock_block.type = 'tool_use'
    mock_block.name = 'submit_extracted_facts'
    mock_block.input = input_dict

    mock_response = MagicMock()
    mock_response.model = model
    mock_response.content = [mock_block]
    return mock_response


VALID_FACTS_DICT = {
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
}


def test_build_user_message_includes_required_fields():
    item = make_item()
    msg = build_user_message(item)
    assert "Award of HVAC contract" in msg
    assert "$87,500" in msg or "87500" in msg
    assert "is_consent" in msg.lower() or "consent" in msg.lower()


def test_extract_facts_returns_validated_pydantic():
    """With a mocked tool_use response, extract_facts_for_item returns a StructuredFacts."""
    item = make_item()
    mock_response = _make_tool_response(VALID_FACTS_DICT)

    with patch('docket.ai.extraction.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_response
        with patch('docket.ai.extraction.cache_get', return_value=None), \
             patch('docket.ai.extraction.cache_put'):
            facts, model_id = extract_facts_for_item(item)

    assert isinstance(facts, StructuredFacts)
    assert facts.counterparty == 'Acme HVAC Inc.'
    assert facts.funding_source == 'general_fund'
    assert model_id == 'claude-haiku-4-5-20251001'


def test_extract_facts_raises_on_schema_violation():
    """Pydantic validation error if the tool_use block input has a bad enum value."""
    item = make_item()
    bad_input = {
        'funding_source': 'WRONG_VALUE',  # not in enum
        'counterparty': None,
        'procurement_method': 'not_applicable',
        'location': None,
        'action_type': 'other',
        'next_steps': {},
        'parcels_affected': None,
        'acres_affected': None,
    }
    mock_response = _make_tool_response(bad_input)

    with patch('docket.ai.extraction.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_response
        with patch('docket.ai.extraction.cache_get', return_value=None), \
             patch('docket.ai.extraction.cache_put'):
            with pytest.raises(Exception):  # Pydantic ValidationError
                extract_facts_for_item(item)


def test_extract_facts_api_call_uses_tool_use():
    """The API call must include tools= and tool_choice= (enforces structured output)."""
    item = make_item()
    mock_response = _make_tool_response(VALID_FACTS_DICT)
    captured_calls = []

    def capture_create(**kwargs):
        captured_calls.append(kwargs)
        return mock_response

    with patch('docket.ai.extraction.anthropic_client') as mock_client:
        mock_client.messages.create.side_effect = capture_create
        with patch('docket.ai.extraction.cache_get', return_value=None), \
             patch('docket.ai.extraction.cache_put'):
            extract_facts_for_item(item)

    assert captured_calls, "API was not called"
    call = captured_calls[0]
    assert 'tools' in call, "tools= must be passed to messages.create"
    assert 'tool_choice' in call, "tool_choice= must be passed to messages.create"
    assert call['tool_choice']['type'] == 'tool'
    assert call['tool_choice']['name'] == 'submit_extracted_facts'


def test_persist_extraction_writes_jsonb_and_version():
    """persist_extraction updates extracted_facts JSONB and bumps the version."""
    facts = StructuredFacts(
        funding_source='general_fund',
        counterparty='Acme HVAC',
        procurement_method='competitive',
        location=None,
        action_type='contract_award',
        next_steps=NextSteps(),
        parcels_affected=None,
        acres_affected=None,
    )

    mock_cur = MagicMock()
    persist_extraction(mock_cur, item_id=42, facts=facts, version=1)

    # Verify the SQL parameters — flexible matching of UPDATE shape
    args, kwargs = mock_cur.execute.call_args
    sql, params = args
    assert "UPDATE agenda_items" in sql
    assert "extracted_facts" in sql
    assert "ai_extraction_version" in sql
    # Last param is item_id; first param is the JSON
    assert params[-1] == 42
    json_blob = json.loads(params[0])
    assert json_blob.get('counterparty') == 'Acme HVAC'
    assert params[1] == 1


def test_extract_facts_returns_result_even_if_cache_put_fails():
    """A transient DB error during cache_put must not drop an already-billed result."""
    item = make_item()
    mock_response = _make_tool_response(VALID_FACTS_DICT)

    with patch('docket.ai.extraction.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_response
        with patch('docket.ai.extraction.cache_get', return_value=None), \
             patch('docket.ai.extraction.cache_put',
                   side_effect=RuntimeError("simulated DB hiccup")):
            facts, model_id = extract_facts_for_item(item)

    assert isinstance(facts, StructuredFacts)
    assert facts.counterparty == 'Acme HVAC Inc.'
    assert model_id == 'claude-haiku-4-5-20251001'


def test_extract_facts_cache_hit_skips_api():
    """On cache hit, the Anthropic API is NOT called."""
    item = make_item()
    cached_payload = {
        'response': VALID_FACTS_DICT,
        'model': 'claude-haiku-4-5-20251001',
    }

    with patch('docket.ai.extraction.anthropic_client') as mock_client, \
         patch('docket.ai.extraction.cache_get', return_value=cached_payload), \
         patch('docket.ai.extraction.cache_put'):
        facts, model_id = extract_facts_for_item(item)
        mock_client.messages.create.assert_not_called()

    assert isinstance(facts, StructuredFacts)
    assert facts.counterparty == 'Acme HVAC Inc.'
    assert model_id == 'claude-haiku-4-5-20251001'


def test_extract_facts_served_model_used_for_cache_put():
    """cache_put is called with the served model id (decision #42)."""
    item = make_item()
    served = 'claude-haiku-4-5-20251001-variant'
    mock_response = _make_tool_response(VALID_FACTS_DICT, model=served)
    captured_puts = []

    with patch('docket.ai.extraction.anthropic_client') as mock_client, \
         patch('docket.ai.extraction.cache_get', return_value=None), \
         patch('docket.ai.extraction.cache_put',
               side_effect=lambda *a, **kw: captured_puts.append(kw)):
        mock_client.messages.create.return_value = mock_response
        _, model_id = extract_facts_for_item(item)

    assert model_id == served
    assert captured_puts, "cache_put was not called"
    assert captured_puts[0]['model'] == served
    assert captured_puts[0]['prompt_version'] == EXTRACTION_PROMPT_VERSION
