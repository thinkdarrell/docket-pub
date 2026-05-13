"""Tests for Stage 2 rewrite worker (`docket.ai.rewrite`)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from docket.ai.rewrite import (
    ITEM_REWRITE_PROMPT_VERSION,
    build_user_message,
    rewrite_item,
)
from docket.ai.rewrite_schema import ItemRewrite
from docket.ai.extraction_schema import NextSteps, StructuredFacts


def make_item(**kw):
    """Lightweight fixture for an item view (mirrors test_extraction.py)."""
    defaults = {
        'id': 1,
        'city_name': 'Birmingham',
        'title': "Award of HVAC contract to Acme Industries",
        'description': "Long valid body content with full agenda item description text.",
        'sponsor': None,
        'dollars_amount': 4200000,
        'topic': 'contracts',
        'is_consent': False,
    }
    defaults.update(kw)
    return type('Item', (), defaults)()


def make_facts(**kw) -> StructuredFacts:
    """Minimal valid StructuredFacts for use in tests."""
    defaults = dict(
        funding_source='general_fund',
        counterparty='Acme Industries',
        procurement_method='competitive',
        location=None,
        action_type='contract_award',
        next_steps=NextSteps(),
        parcels_affected=None,
        acres_affected=None,
    )
    defaults.update(kw)
    return StructuredFacts(**defaults)


VALID_SUBSTANTIVE_RESPONSE = {
    'is_substantive': True,
    'headline': 'Council awards $4.2M HVAC contract to Acme',
    'why_it_matters': 'Better climate control in public buildings starting fall 2026.',
    'significance_rationale': 'Major capital expenditure with long-term operational impact.',
    'significance_score': 7,
    'consent_placement_rationale': 'High-dollar contract warrants full council debate.',
    'consent_placement_score': 2,
    'suggested_badge_slugs': [],
    'confidence': 'high',
}

VALID_PROCEDURAL_RESPONSE = {
    'is_substantive': False,
    'headline': None,
    'why_it_matters': None,
    'significance_rationale': '',
    'significance_score': None,
    'consent_placement_rationale': '',
    'consent_placement_score': None,
    'suggested_badge_slugs': [],
    'confidence': 'high',
}


def _mock_api_response(payload: dict, model: str = 'claude-haiku-4-5-20251001') -> MagicMock:
    """Build a mock Anthropic messages.create response shaped like a tool_use response."""
    mock_block = MagicMock()
    mock_block.type = 'tool_use'
    mock_block.name = 'submit_item_rewrite'
    mock_block.input = payload

    mock_response = MagicMock()
    mock_response.model = model
    mock_response.content = [mock_block]
    return mock_response


class TestBuildUserMessage:
    def test_includes_city_name(self):
        item = make_item()
        msg = build_user_message(item, make_facts(), [])
        assert "City: Birmingham" in msg

    def test_includes_title(self):
        item = make_item()
        msg = build_user_message(item, make_facts(), [])
        assert "Award of HVAC contract" in msg

    def test_includes_badge_slugs(self):
        item = make_item()
        msg = build_user_message(item, make_facts(), ['police-oversight', 'contracts'])
        assert "police-oversight" in msg
        assert "contracts" in msg

    def test_includes_facts_json(self):
        item = make_item()
        facts = make_facts()
        msg = build_user_message(item, facts, [])
        assert "Stage 1 structured facts:" in msg
        assert "Acme Industries" in msg  # counterparty appears in JSON

    def test_extra_instruction_appended(self):
        item = make_item()
        msg = build_user_message(item, make_facts(), [],
                                  extra_instruction="RETRY: Force is_substantive=true.")
        assert "RETRY: Force is_substantive=true." in msg

    def test_no_extra_instruction_no_trailing_blank(self):
        item = make_item()
        msg = build_user_message(item, make_facts(), [])
        assert not msg.endswith("\n")
        assert not msg.endswith(" ")

    def test_city_name_fallback_when_attribute_missing(self):
        """Items without city_name fall back to 'Unknown' gracefully."""
        item = type('Item', (), {
            'id': 99, 'title': 'Test', 'description': '', 'sponsor': None,
            'dollars_amount': 0, 'topic': None, 'is_consent': False,
        })()
        msg = build_user_message(item, make_facts(), [])
        assert "City: Unknown" in msg


class TestRewriteItemHappyPathSubstantive:
    def test_returns_itemrewrite_and_model_id(self):
        """With mocked tool_use response, rewrite_item returns a valid ItemRewrite."""
        item = make_item()
        facts = make_facts()

        mock_response = _mock_api_response(VALID_SUBSTANTIVE_RESPONSE)

        with patch('docket.ai.rewrite.anthropic_client') as mock_client, \
             patch('docket.ai.rewrite.cache_get', return_value=None), \
             patch('docket.ai.rewrite.cache_put'):
            mock_client.messages.create.return_value = mock_response
            rewrite, model_id = rewrite_item(item, facts, [])

        assert isinstance(rewrite, ItemRewrite)
        assert rewrite.is_substantive is True
        assert rewrite.headline == 'Council awards $4.2M HVAC contract to Acme'
        assert rewrite.significance_score == 7
        assert model_id == 'claude-haiku-4-5-20251001'

    def test_api_call_uses_tool_use(self):
        """The API call must include tools= and tool_choice= (enforces structured output)."""
        item = make_item()
        facts = make_facts()
        mock_response = _mock_api_response(VALID_SUBSTANTIVE_RESPONSE)
        captured_calls = []

        def capture_create(**kwargs):
            captured_calls.append(kwargs)
            return mock_response

        with patch('docket.ai.rewrite.anthropic_client') as mock_client, \
             patch('docket.ai.rewrite.cache_get', return_value=None), \
             patch('docket.ai.rewrite.cache_put'):
            mock_client.messages.create.side_effect = capture_create
            rewrite_item(item, facts, [])

        assert captured_calls, "API was not called"
        call = captured_calls[0]
        assert 'tools' in call, "tools= must be passed to messages.create"
        assert 'tool_choice' in call, "tool_choice= must be passed to messages.create"
        assert call['tool_choice']['type'] == 'tool'
        assert call['tool_choice']['name'] == 'submit_item_rewrite'

    def test_passes_badge_slugs_to_user_message(self):
        """enabled_policy_badges appear in the user message sent to the API."""
        item = make_item()
        facts = make_facts()
        badges = ['police-oversight', 'tax-abatement']

        mock_response = _mock_api_response(VALID_SUBSTANTIVE_RESPONSE)
        captured_calls = []

        def capture_create(**kwargs):
            captured_calls.append(kwargs)
            return mock_response

        with patch('docket.ai.rewrite.anthropic_client') as mock_client, \
             patch('docket.ai.rewrite.cache_get', return_value=None), \
             patch('docket.ai.rewrite.cache_put'):
            mock_client.messages.create.side_effect = capture_create
            rewrite_item(item, facts, badges)

        assert captured_calls, "API was not called"
        user_content = captured_calls[0]['messages'][0]['content']
        assert 'police-oversight' in user_content

    def test_served_model_used_for_cache_put(self):
        """cache_put is called with the served model id (decision #42)."""
        item = make_item()
        facts = make_facts()

        served = 'claude-haiku-4-5-20251001-variant'
        mock_response = _mock_api_response(VALID_SUBSTANTIVE_RESPONSE, model=served)
        captured_puts = []

        with patch('docket.ai.rewrite.anthropic_client') as mock_client, \
             patch('docket.ai.rewrite.cache_get', return_value=None), \
             patch('docket.ai.rewrite.cache_put', side_effect=lambda *a, **kw: captured_puts.append(kw)):
            mock_client.messages.create.return_value = mock_response
            _, model_id = rewrite_item(item, facts, [])

        assert model_id == served
        assert captured_puts, "cache_put was not called"
        assert captured_puts[0]['model'] == served
        assert captured_puts[0]['prompt_version'] == ITEM_REWRITE_PROMPT_VERSION


class TestRewriteItemHappyPathProcedural:
    def test_procedural_returns_valid_itemrewrite(self):
        """Procedural shape (is_substantive=false) passes Pydantic validation."""
        item = make_item(
            title="Roll Call",
            description="",
            dollars_amount=0,
            topic=None,
        )
        facts = make_facts(action_type='other', counterparty=None)
        mock_response = _mock_api_response(VALID_PROCEDURAL_RESPONSE)

        with patch('docket.ai.rewrite.anthropic_client') as mock_client, \
             patch('docket.ai.rewrite.cache_get', return_value=None), \
             patch('docket.ai.rewrite.cache_put'):
            mock_client.messages.create.return_value = mock_response
            rewrite, model_id = rewrite_item(item, facts, [])

        assert isinstance(rewrite, ItemRewrite)
        assert rewrite.is_substantive is False
        assert rewrite.headline is None
        assert rewrite.why_it_matters is None
        assert rewrite.significance_score is None
        assert rewrite.consent_placement_score is None
        assert rewrite.suggested_badge_slugs == []


class TestRewriteItemErrorPaths:
    def test_raises_on_schema_violation(self):
        """Pydantic ValidationError if tool_use block input violates ItemRewrite constraints."""
        item = make_item()
        facts = make_facts()

        # Substantive item with headline too short (< 10 chars) — violates decision #87
        bad_payload = {
            'is_substantive': True,
            'headline': 'Approved',  # 8 chars — fails >= 10 check
            'why_it_matters': 'Some impact.',
            'significance_rationale': 'Minor.',
            'significance_score': 5,
            'consent_placement_rationale': 'Routine.',
            'consent_placement_score': 8,
            'suggested_badge_slugs': [],
            'confidence': 'medium',
        }
        mock_response = _mock_api_response(bad_payload)

        with patch('docket.ai.rewrite.anthropic_client') as mock_client, \
             patch('docket.ai.rewrite.cache_get', return_value=None), \
             patch('docket.ai.rewrite.cache_put'):
            mock_client.messages.create.return_value = mock_response
            with pytest.raises(Exception):  # Pydantic ValidationError
                rewrite_item(item, facts, [])

    def test_procedural_with_headline_raises(self):
        """Procedural item with non-null headline violates procedural_consistency."""
        item = make_item(title="Approval of Minutes")
        facts = make_facts()

        bad_payload = {
            'is_substantive': False,
            'headline': 'Should be null',  # violates procedural constraint
            'why_it_matters': None,
            'significance_rationale': '',
            'significance_score': None,
            'consent_placement_rationale': '',
            'consent_placement_score': None,
            'suggested_badge_slugs': [],
            'confidence': 'high',
        }
        mock_response = _mock_api_response(bad_payload)

        with patch('docket.ai.rewrite.anthropic_client') as mock_client, \
             patch('docket.ai.rewrite.cache_get', return_value=None), \
             patch('docket.ai.rewrite.cache_put'):
            mock_client.messages.create.return_value = mock_response
            with pytest.raises(Exception):  # ValidationError from procedural_consistency
                rewrite_item(item, facts, [])


class TestRewriteItemCacheBehavior:
    def test_cache_hit_skips_api_call(self):
        """On cache hit, the Anthropic API is NOT called."""
        item = make_item()
        facts = make_facts()

        cached_payload = {
            'response': VALID_SUBSTANTIVE_RESPONSE,
            'model': 'claude-haiku-4-5-20251001',
        }

        with patch('docket.ai.rewrite.anthropic_client') as mock_client, \
             patch('docket.ai.rewrite.cache_get', return_value=cached_payload), \
             patch('docket.ai.rewrite.cache_put'):
            rewrite, model_id = rewrite_item(item, facts, [])
            mock_client.messages.create.assert_not_called()

        assert isinstance(rewrite, ItemRewrite)
        assert rewrite.is_substantive is True
        assert model_id == 'claude-haiku-4-5-20251001'

    def test_extra_instruction_changes_cache_key(self):
        """extra_instruction changes user_msg, which changes the cache key."""
        item = make_item()
        facts = make_facts()
        mock_response = _mock_api_response(VALID_SUBSTANTIVE_RESPONSE)

        cache_keys_seen = []

        def capture_cache_get(key):
            cache_keys_seen.append(key)
            return None

        with patch('docket.ai.rewrite.anthropic_client') as mock_client, \
             patch('docket.ai.rewrite.cache_get', side_effect=capture_cache_get), \
             patch('docket.ai.rewrite.cache_put'):
            mock_client.messages.create.return_value = mock_response
            rewrite_item(item, facts, [])
            rewrite_item(item, facts, [], extra_instruction="RETRY: override")

        assert len(cache_keys_seen) == 2
        assert cache_keys_seen[0] != cache_keys_seen[1], \
            "extra_instruction must produce a distinct cache key"

    def test_returns_result_even_if_cache_put_fails(self):
        """A transient DB error during cache_put must not drop an already-billed result."""
        item = make_item()
        facts = make_facts()
        mock_response = _mock_api_response(VALID_SUBSTANTIVE_RESPONSE)

        with patch('docket.ai.rewrite.anthropic_client') as mock_client, \
             patch('docket.ai.rewrite.cache_get', return_value=None), \
             patch('docket.ai.rewrite.cache_put',
                   side_effect=RuntimeError("simulated DB hiccup")):
            mock_client.messages.create.return_value = mock_response
            rewrite, model_id = rewrite_item(item, facts, [])

        assert isinstance(rewrite, ItemRewrite)
        assert rewrite.is_substantive is True
        assert model_id == 'claude-haiku-4-5-20251001'

    def test_overlong_headline_is_truncated_to_max_length(self):
        """Haiku occasionally returns a >80-char headline. Truncation lets the
        item complete rather than failing permanent — observed in production
        2026-05-11 in the FINAL-3 verification cron. Prompt-v4 raised the
        cap from 60 to 80; this test uses a 90+ char header to still exercise
        the truncate path."""
        item = make_item()
        facts = make_facts()
        overlong = dict(VALID_SUBSTANTIVE_RESPONSE)
        # 95 chars — exceeds the 80-char Field(max_length=80) cap.
        overlong['headline'] = (
            'City awards $326,741 drainage and stormwater management contract '
            'to Southeastern Sealcoating Inc'
        )
        mock_response = _mock_api_response(overlong)

        with patch('docket.ai.rewrite.anthropic_client') as mock_client, \
             patch('docket.ai.rewrite.cache_get', return_value=None), \
             patch('docket.ai.rewrite.cache_put'):
            mock_client.messages.create.return_value = mock_response
            rewrite, _ = rewrite_item(item, facts, [])

        assert len(rewrite.headline) <= 80
        assert rewrite.headline.startswith('City awards $326,741 drainage')


def test_truncate_overlong_strings_uses_max_length_from_ctx():
    """Direct helper exercise — only top-level fields are touched.
    Prompt v4 raised the headline cap from 60 to 80; this test exercises
    the helper against the new cap with a 100-char input."""
    from docket.ai.extraction import _truncate_overlong_strings
    from pydantic import ValidationError

    # Build a real ValidationError so the helper sees genuine .errors() shape.
    try:
        ItemRewrite.model_validate({
            **VALID_SUBSTANTIVE_RESPONSE,
            'headline': 'x' * 100,
        })
    except ValidationError as e:
        validation_error = e
    else:
        pytest.fail("expected ValidationError")

    payload = dict(VALID_SUBSTANTIVE_RESPONSE)
    payload['headline'] = 'x' * 100
    out = _truncate_overlong_strings(payload, validation_error)
    assert len(out['headline']) == 80


# ---------------------------------------------------------------------------
# Stage 2 assertion-error retry path
# Issue #26: Haiku occasionally returns is_substantive=True with null
# scores (violates procedural_consistency validator). The retry path
# re-prompts Haiku once with the bad payload + error as feedback.
# ---------------------------------------------------------------------------


# A payload that passes the JSON schema but fails the procedural_consistency
# @model_validator (substantive items must have non-null scores).
ASSERTION_FAILING_PAYLOAD = {
    'is_substantive': True,
    'headline': 'Council approves new HVAC contract',
    'why_it_matters': 'Better climate control in public buildings.',
    'significance_rationale': 'Capital project with operational impact.',
    'significance_score': None,  # null score on substantive item → assert fires
    'consent_placement_rationale': 'Routine high-dollar contract.',
    'consent_placement_score': None,
    'suggested_badge_slugs': [],
    'confidence': 'medium',
}


class TestRewriteItemAssertionRetry:
    """Stage 2 assertion-error retry — issue #26."""

    def test_retries_assertion_error_then_succeeds(self):
        """Bad payload (null scores on substantive) → re-prompts Haiku → valid."""
        item = make_item()
        facts = make_facts()
        bad_resp = _mock_api_response(ASSERTION_FAILING_PAYLOAD)
        good_resp = _mock_api_response(VALID_SUBSTANTIVE_RESPONSE)

        with patch('docket.ai.rewrite.anthropic_client') as mock_client, \
             patch('docket.ai.rewrite.cache_get', return_value=None), \
             patch('docket.ai.rewrite.cache_put'):
            mock_client.messages.create.side_effect = [bad_resp, good_resp]
            rewrite, _ = rewrite_item(item, facts, [])

        assert mock_client.messages.create.call_count == 2, \
            "expected exactly one retry after the initial assertion failure"
        assert isinstance(rewrite, ItemRewrite)
        assert rewrite.significance_score == 7

    def test_raises_when_retry_also_fails(self):
        """Two consecutive assertion-failing responses → AIPermanentRowError."""
        from docket.ai.exceptions import AIPermanentRowError
        item = make_item()
        facts = make_facts()
        bad_resp = _mock_api_response(ASSERTION_FAILING_PAYLOAD)

        with patch('docket.ai.rewrite.anthropic_client') as mock_client, \
             patch('docket.ai.rewrite.cache_get', return_value=None), \
             patch('docket.ai.rewrite.cache_put'):
            mock_client.messages.create.side_effect = [bad_resp, bad_resp]
            with pytest.raises(AIPermanentRowError, match="assertion-error retry"):
                rewrite_item(item, facts, [])

        assert mock_client.messages.create.call_count == 2, \
            "retry should fire exactly once, not loop"

    def test_retry_feedback_includes_bad_payload_and_error(self):
        """Retry's extra_instruction should include the bad payload and the
        validation error so Haiku can self-correct."""
        item = make_item()
        facts = make_facts()
        bad_resp = _mock_api_response(ASSERTION_FAILING_PAYLOAD)
        good_resp = _mock_api_response(VALID_SUBSTANTIVE_RESPONSE)

        with patch('docket.ai.rewrite.anthropic_client') as mock_client, \
             patch('docket.ai.rewrite.cache_get', return_value=None), \
             patch('docket.ai.rewrite.cache_put'):
            mock_client.messages.create.side_effect = [bad_resp, good_resp]
            rewrite_item(item, facts, [])

        # The retry call's user message should mention the failure
        retry_call = mock_client.messages.create.call_args_list[1]
        retry_user_msg = retry_call.kwargs['messages'][0]['content']
        assert 'failed validation' in retry_user_msg.lower()
        assert 'significance_score' in retry_user_msg
