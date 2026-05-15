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


def test_extract_facts_coerces_unknown_enum_value_to_safe_default():
    """When Haiku returns an enum value outside the schema whitelist (e.g.
    ``funding_source='grant'`` instead of ``state_grant``/``federal_grant``),
    the value is coerced to ``'unknown'`` and validation succeeds. Without
    this, ``_process_items_v3`` aborts the entire batch on the first such
    item — observed in production 2026-05-11 mid-cron after the #57 fix."""
    from docket.ai.extraction import extract_facts_for_item

    item = make_item()
    out_of_enum_input = {
        'funding_source': 'grant',  # not in enum; should coerce to 'unknown'
        'counterparty': None,
        'procurement_method': 'not_applicable',
        'location': None,
        'action_type': 'other',
        'next_steps': {},
        'parcels_affected': None,
        'acres_affected': None,
    }
    mock_response = _make_tool_response(out_of_enum_input)

    with patch('docket.ai.extraction.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_response
        with patch('docket.ai.extraction.cache_get', return_value=None), \
             patch('docket.ai.extraction.cache_put'):
            facts, _ = extract_facts_for_item(item)
    assert facts.funding_source == 'unknown'


def test_extract_facts_accepts_natural_language_dates_in_next_steps():
    """Haiku often returns natural-language strings for next_steps date fields
    ('May 5, 2026', 'the 13th'). After 2026-05-12 cron failure cluster, those
    fields are typed as ``str | None`` rather than ``date | None`` so the source
    phrasing flows through to the citizen render verbatim."""
    item = make_item()
    facts_with_text_dates = {
        **VALID_FACTS_DICT,
        'next_steps': {
            'committee_referral': None,
            'public_hearing_date': 'May 5, 2026',
            'public_hearing_time': '6:00 PM',
            'comment_period_end': 'the 13th',
            'implementation_date': None,
        },
    }
    mock_response = _make_tool_response(facts_with_text_dates)

    with patch('docket.ai.extraction.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_response
        with patch('docket.ai.extraction.cache_get', return_value=None), \
             patch('docket.ai.extraction.cache_put'):
            facts, _ = extract_facts_for_item(item)

    assert facts.next_steps.public_hearing_date == 'May 5, 2026'
    assert facts.next_steps.comment_period_end == 'the 13th'


def test_extract_facts_normalizes_whole_field_null_string():
    """Haiku occasionally returns the literal string ``"null"`` where a nested
    object is expected (observed on item 1298 in the 2026-05-12 cron). The
    pre-validate normalization pass converts string ``"null"`` / ``"None"`` to
    actual ``None`` so Pydantic accepts the row."""
    item = make_item()
    facts_with_null_string = {**VALID_FACTS_DICT, 'next_steps': 'null'}
    mock_response = _make_tool_response(facts_with_null_string)

    with patch('docket.ai.extraction.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_response
        with patch('docket.ai.extraction.cache_get', return_value=None), \
             patch('docket.ai.extraction.cache_put'):
            facts, _ = extract_facts_for_item(item)

    # Nested string-null collapses to a default NextSteps with all fields None.
    assert facts.next_steps.public_hearing_date is None
    assert facts.next_steps.committee_referral is None


def test_extract_facts_normalizes_nested_null_string():
    """String ``"null"`` inside a nested next_steps object is normalized to None."""
    item = make_item()
    facts_with_nested_null = {
        **VALID_FACTS_DICT,
        'next_steps': {
            'committee_referral': 'null',
            'public_hearing_date': 'None',
            'public_hearing_time': None,
            'comment_period_end': None,
            'implementation_date': None,
        },
    }
    mock_response = _make_tool_response(facts_with_nested_null)

    with patch('docket.ai.extraction.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_response
        with patch('docket.ai.extraction.cache_get', return_value=None), \
             patch('docket.ai.extraction.cache_put'):
            facts, _ = extract_facts_for_item(item)

    assert facts.next_steps.committee_referral is None
    assert facts.next_steps.public_hearing_date is None


def test_extract_facts_recovers_when_haiku_omits_procurement_method():
    """Pattern A from issue #34 follow-up: Haiku sometimes omits
    procurement_method for items where no procurement is happening
    (demolitions, proclamations). Stage 1 schema marks the field
    required, so before this fix the row failed_permanent. Coercion
    now fills the missing field with the standard fallback so the
    row recovers."""
    item = make_item()
    payload_missing_procurement = {
        'funding_source': 'general_fund',
        'counterparty': None,
        # procurement_method MISSING — the bug shape from issue #34 follow-up
        'location': None,
        'action_type': 'demolition',
        'next_steps': {},
        'parcels_affected': None,
        'acres_affected': None,
    }
    mock_response = _make_tool_response(payload_missing_procurement)

    with patch('docket.ai.extraction.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_response
        with patch('docket.ai.extraction.cache_get', return_value=None), \
             patch('docket.ai.extraction.cache_put'):
            facts, _ = extract_facts_for_item(item)

    # Coercion fills with 'unknown' per the existing fallback ladder
    # ('unknown' is in the enum, so it wins over 'not_applicable').
    assert facts.procurement_method == 'unknown'
    assert facts.action_type == 'demolition'  # preserved


def test_extract_facts_raises_permanent_when_coercion_cannot_recover():
    """If the schema violation isn't a top-level enum (e.g. required field
    type wrong / missing), coercion doesn't help and we surface as
    AIPermanentRowError so the worker can mark the row failed_permanent
    and continue the batch."""
    from docket.ai.extraction import extract_facts_for_item
    from docket.ai.exceptions import AIPermanentRowError

    item = make_item()
    structurally_invalid = {
        'funding_source': 'general_fund',
        'counterparty': None,
        # procurement_method missing entirely — required field
        'location': None,
        'action_type': 'other',
        'next_steps': {},
        'parcels_affected': None,
        'acres_affected': 'not_a_number',  # wrong type
    }
    mock_response = _make_tool_response(structurally_invalid)

    with patch('docket.ai.extraction.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_response
        with patch('docket.ai.extraction.cache_get', return_value=None), \
             patch('docket.ai.extraction.cache_put'):
            with pytest.raises(AIPermanentRowError):
                extract_facts_for_item(item)


def test_coerce_unknown_enums_uses_unknown_then_other_then_first():
    """Coercion fallback ladder: prefer 'unknown', else 'other', else first."""
    from docket.ai.extraction import _coerce_unknown_enums

    schema_with_unknown = {'properties': {'f': {'type': 'string', 'enum': ['a', 'b', 'unknown']}}}
    out = _coerce_unknown_enums({'f': 'bogus'}, schema_with_unknown)
    assert out['f'] == 'unknown'

    schema_with_other = {'properties': {'f': {'type': 'string', 'enum': ['a', 'b', 'other']}}}
    out = _coerce_unknown_enums({'f': 'bogus'}, schema_with_other)
    assert out['f'] == 'other'

    schema_neither = {'properties': {'f': {'type': 'string', 'enum': ['a', 'b']}}}
    out = _coerce_unknown_enums({'f': 'bogus'}, schema_neither)
    assert out['f'] == 'a'

    # Valid values pass through untouched.
    out = _coerce_unknown_enums({'f': 'a'}, schema_with_unknown)
    assert out['f'] == 'a'

    # None passes through untouched.
    out = _coerce_unknown_enums({'f': None}, schema_with_unknown)
    assert out['f'] is None


def test_coerce_unknown_enums_fills_missing_required_enum_field():
    """Pattern A from issue #34 follow-up: Haiku occasionally omits a
    required enum field entirely (e.g. ``procurement_method`` for a
    demolition or proclamation item where no procurement is happening).
    Coercion fills the gap with the same fallback ladder used for
    out-of-whitelist values so the row clears Pydantic validation
    instead of being marked failed_permanent.

    Only fills fields listed in ``required`` so optional fields aren't
    silently invented. Existing values still pass through unchanged.
    """
    from docket.ai.extraction import _coerce_unknown_enums

    schema = {
        'required': ['proc'],
        'properties': {
            'proc': {
                'type': 'string',
                'enum': ['competitive', 'sole_source', 'not_applicable', 'unknown'],
            },
        },
    }

    # Missing required enum field gets filled with the fallback.
    out = _coerce_unknown_enums({}, schema)
    assert out['proc'] == 'unknown'

    # Schema without 'unknown' falls through to 'other'.
    schema2 = {
        'required': ['kind'],
        'properties': {'kind': {'type': 'string', 'enum': ['a', 'b', 'other']}},
    }
    out = _coerce_unknown_enums({}, schema2)
    assert out['kind'] == 'other'

    # Schema without 'unknown' or 'other' falls through to first.
    schema3 = {
        'required': ['kind'],
        'properties': {'kind': {'type': 'string', 'enum': ['a', 'b']}},
    }
    out = _coerce_unknown_enums({}, schema3)
    assert out['kind'] == 'a'

    # Optional enum field (not in 'required') is NOT filled.
    schema_opt = {
        'required': [],
        'properties': {'opt': {'type': 'string', 'enum': ['x', 'unknown']}},
    }
    out = _coerce_unknown_enums({}, schema_opt)
    assert 'opt' not in out

    # Existing valid values pass through unchanged.
    out = _coerce_unknown_enums({'proc': 'competitive'}, schema)
    assert out['proc'] == 'competitive'


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
