"""Tests for docket.ai.batches — Anthropic Batches API wrapper.

Covers:
  - TestBuildRequest: build_stage1_request, build_stage2_request shapes
  - TestSubmitBatch: Anthropic API call + DB recording
  - TestPollBatch: ended/in_progress status handling
  - TestGetStage1Facts: DB read with missing / present rows
  - TestPersistBatchResult: result_status update + parent batch status
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from docket.ai.batches import (
    BatchStatus,
    build_stage1_request,
    build_stage2_request,
    get_stage1_facts,
    persist_batch_result,
    poll_batch,
    record_batch,
    submit_batch,
)
from docket.ai.extraction_schema import StructuredFacts
from docket.db import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_item(**kw):
    """Lightweight duck-typed item for tests."""
    defaults = {
        'id': 1,
        'title': "Award HVAC contract to Acme",
        'description': "Full agenda item body text with enough detail for extraction.",
        'sponsor': None,
        'dollars_amount': 87500,
        'topic': 'contracts',
        'is_consent': False,
        'city_name': 'Birmingham',
    }
    defaults.update(kw)
    return type('Item', (), defaults)()


def make_facts(**kw) -> StructuredFacts:
    defaults = dict(
        funding_source='general_fund',
        counterparty='Acme HVAC Inc.',
        procurement_method='competitive',
        location=None,
        action_type='contract_award',
        next_steps={},
        parcels_affected=None,
        acres_affected=None,
    )
    defaults.update(kw)
    return StructuredFacts.model_validate(defaults)


def _insert_meeting_and_item(cur, title: str = "Test Batch Item") -> tuple[int, int]:
    """Insert a minimal meeting + agenda_item row. Returns (meeting_id, item_id)."""
    cur.execute("""
        INSERT INTO municipalities (slug, name, state, adapter_class, active)
        VALUES ('test_batches_muni', 'Test Batches', 'AL', 'granicus', TRUE)
        ON CONFLICT (slug) DO UPDATE SET active = TRUE
        RETURNING id
    """)
    muni_id = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url, title)
        VALUES (%s, 'Council', CURRENT_DATE, 'http://test.example', 'Test Meeting')
        RETURNING id
    """, [muni_id])
    meeting_id = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO agenda_items (meeting_id, title, is_consent)
        VALUES (%s, %s, FALSE)
        RETURNING id
    """, [meeting_id, title])
    item_id = cur.fetchone()[0]

    return meeting_id, item_id


# ---------------------------------------------------------------------------
# TestBuildRequest
# ---------------------------------------------------------------------------

class TestBuildRequest:
    def test_stage1_request_has_required_shape(self):
        item = make_item()
        req = build_stage1_request(item)

        assert req['model'] == 'claude-haiku-4-5-20251001'
        assert req['max_tokens'] == 1024
        # tool-use enforcement
        assert 'tools' in req, "tools= must be present for schema enforcement"
        assert len(req['tools']) == 1
        assert req['tools'][0]['name'] == 'submit_extracted_facts'
        assert 'tool_choice' in req, "tool_choice= must be present for schema enforcement"
        assert req['tool_choice'] == {'type': 'tool', 'name': 'submit_extracted_facts'}
        # system is a list with cache_control
        assert isinstance(req['system'], list)
        assert len(req['system']) == 1
        assert req['system'][0]['type'] == 'text'
        assert req['system'][0]['cache_control'] == {'type': 'ephemeral'}
        # messages
        assert req['messages'][0]['role'] == 'user'
        assert item.title in req['messages'][0]['content']

    def test_stage1_request_model_override(self):
        item = make_item()
        req = build_stage1_request(item, model='claude-sonnet-4-6')
        assert req['model'] == 'claude-sonnet-4-6'

    def test_stage2_request_has_required_shape(self):
        item = make_item()
        facts = make_facts()
        req = build_stage2_request(item, facts)

        assert req['model'] == 'claude-haiku-4-5-20251001'
        assert req['max_tokens'] == 1024
        # tool-use enforcement
        assert 'tools' in req, "tools= must be present for schema enforcement"
        assert len(req['tools']) == 1
        assert req['tools'][0]['name'] == 'submit_item_rewrite'
        assert 'tool_choice' in req, "tool_choice= must be present for schema enforcement"
        assert req['tool_choice'] == {'type': 'tool', 'name': 'submit_item_rewrite'}
        # system + messages
        assert isinstance(req['system'], list)
        assert req['system'][0]['cache_control'] == {'type': 'ephemeral'}
        assert req['messages'][0]['role'] == 'user'

    def test_stage2_request_includes_facts_in_user_message(self):
        """Counterparty from Stage 1 facts must appear in the rendered user message."""
        item = make_item()
        facts = make_facts(counterparty='FactsCoAcme')
        req = build_stage2_request(item, facts)
        user_content = req['messages'][0]['content']
        assert 'FactsCoAcme' in user_content

    def test_stage2_request_uses_empty_badges_when_none(self):
        """build_stage2_request accepts None for enabled_policy_badges without error."""
        item = make_item()
        facts = make_facts()
        req = build_stage2_request(item, facts, enabled_policy_badges=None)
        assert req['model'] == 'claude-haiku-4-5-20251001'

    def test_stage2_request_includes_policy_badges(self):
        item = make_item()
        facts = make_facts()
        req = build_stage2_request(item, facts, enabled_policy_badges=['flock-cameras', 'demolition'])
        user_content = req['messages'][0]['content']
        assert 'flock-cameras' in user_content


# ---------------------------------------------------------------------------
# TestSubmitBatch
# ---------------------------------------------------------------------------

class TestSubmitBatch:
    def test_submit_calls_batches_create_with_correct_requests(self):
        """submit_batch calls client.messages.batches.create with one entry per item."""
        items = [make_item(id=10), make_item(id=11)]

        mock_batch = MagicMock()
        mock_batch.id = 'msgbatch_test001'

        with patch('docket.ai.batches.anthropic.Anthropic') as mock_cls, \
             patch('docket.ai.batches.record_batch') as mock_record, \
             patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            mock_client = mock_cls.return_value
            mock_client.messages.batches.create.return_value = mock_batch

            result = submit_batch(items, 'stage1', 'wave0')

        assert result == 'msgbatch_test001'
        call_kwargs = mock_client.messages.batches.create.call_args
        requests_arg = call_kwargs[1]['requests'] if call_kwargs[1] else call_kwargs[0][0]
        assert len(requests_arg) == 2
        custom_ids = [r['custom_id'] for r in requests_arg]
        assert 'item-10-stage1' in custom_ids
        assert 'item-11-stage1' in custom_ids

    def test_submit_records_batch_in_db(self):
        """submit_batch writes ai_batches + ai_batch_items rows with correct metadata."""
        _batch_id = f'msgbatch_dbtest_{id(object())}'
        items = []
        meeting_ids = []
        item_ids = []

        try:
            with db() as conn, conn.cursor() as cur:
                m_id, i_id = _insert_meeting_and_item(cur, "Submit DB test item 1")
                meeting_ids.append(m_id)
                item_ids.append(i_id)
                m_id2, i_id2 = _insert_meeting_and_item(cur, "Submit DB test item 2")
                meeting_ids.append(m_id2)
                item_ids.append(i_id2)

            items = [make_item(id=item_ids[0]), make_item(id=item_ids[1])]

            mock_batch = MagicMock()
            mock_batch.id = _batch_id

            with patch('docket.ai.batches.anthropic.Anthropic') as mock_cls, \
                 patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
                mock_client = mock_cls.return_value
                mock_client.messages.batches.create.return_value = mock_batch

                returned_id = submit_batch(items, 'stage1', 'wave1')

            assert returned_id == _batch_id

            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT stage, wave, item_count, status FROM ai_batches "
                    "WHERE anthropic_batch_id = %s",
                    [_batch_id],
                )
                row = cur.fetchone()

            assert row is not None
            stage, wave, item_count, status = row
            assert stage == 'stage1'
            assert wave == 'wave1'
            assert item_count == 2
            assert status == 'submitted'

        finally:
            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM ai_batches WHERE anthropic_batch_id = %s",
                    [_batch_id],
                )
                if item_ids:
                    cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", [item_ids])
                if meeting_ids:
                    cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", [meeting_ids])
                cur.execute(
                    "DELETE FROM municipalities WHERE slug = 'test_batches_muni'"
                )

    def test_submit_batch_items_have_correct_custom_ids(self):
        """ai_batch_items rows use the item-<id>-<stage> custom_id format."""
        _batch_id = f'msgbatch_custom_id_{id(object())}'
        meeting_ids = []
        item_ids = []

        try:
            with db() as conn, conn.cursor() as cur:
                m_id, i_id = _insert_meeting_and_item(cur, "CustomID test item")
                meeting_ids.append(m_id)
                item_ids.append(i_id)

                # Provide extracted_facts so the stage2 item is not skipped
                facts_dict = {
                    'funding_source': 'general_fund',
                    'counterparty': 'CustomIDVendor',
                    'procurement_method': 'competitive',
                    'location': None,
                    'action_type': 'contract_award',
                    'next_steps': {},
                    'parcels_affected': None,
                    'acres_affected': None,
                }
                cur.execute(
                    "UPDATE agenda_items SET extracted_facts = %s::jsonb WHERE id = %s",
                    [json.dumps(facts_dict), i_id],
                )

            items = [make_item(id=item_ids[0])]

            mock_batch = MagicMock()
            mock_batch.id = _batch_id

            with patch('docket.ai.batches.anthropic.Anthropic') as mock_cls, \
                 patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
                mock_cls.return_value.messages.batches.create.return_value = mock_batch
                submit_batch(items, 'stage2', 'wave2')

            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT abi.custom_id FROM ai_batch_items abi
                    JOIN ai_batches ab ON ab.id = abi.batch_id
                    WHERE ab.anthropic_batch_id = %s
                    """,
                    [_batch_id],
                )
                rows = cur.fetchall()

            assert len(rows) == 1
            assert rows[0][0] == f'item-{item_ids[0]}-stage2'

        finally:
            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM ai_batches WHERE anthropic_batch_id = %s",
                    [_batch_id],
                )
                if item_ids:
                    cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", [item_ids])
                if meeting_ids:
                    cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", [meeting_ids])
                cur.execute(
                    "DELETE FROM municipalities WHERE slug = 'test_batches_muni'"
                )

    def test_stage2_skips_items_without_facts_and_records_only_submitted_count(self):
        """record_batch receives only actually-submitted items when some stage2 items lack facts."""
        _batch_id = f'msgbatch_skip_count_{id(object())}'
        meeting_ids = []
        item_ids = []

        try:
            with db() as conn, conn.cursor() as cur:
                # item_with_facts
                m_id1, i_id1 = _insert_meeting_and_item(cur, "Skip count item WITH facts")
                meeting_ids.append(m_id1)
                item_ids.append(i_id1)

                facts_dict = {
                    'funding_source': 'general_fund',
                    'counterparty': 'SkipTestVendor',
                    'procurement_method': 'competitive',
                    'location': None,
                    'action_type': 'contract_award',
                    'next_steps': {},
                    'parcels_affected': None,
                    'acres_affected': None,
                }
                cur.execute(
                    "UPDATE agenda_items SET extracted_facts = %s::jsonb WHERE id = %s",
                    [json.dumps(facts_dict), i_id1],
                )

                # item_without_facts (extracted_facts remains NULL)
                m_id2, i_id2 = _insert_meeting_and_item(cur, "Skip count item WITHOUT facts")
                meeting_ids.append(m_id2)
                item_ids.append(i_id2)

            item_with_facts = make_item(id=item_ids[0])
            item_without_facts = make_item(id=item_ids[1])

            mock_batch = MagicMock()
            mock_batch.id = _batch_id

            with patch('docket.ai.batches.anthropic.Anthropic') as mock_cls, \
                 patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
                mock_cls.return_value.messages.batches.create.return_value = mock_batch
                submit_batch([item_with_facts, item_without_facts], 'stage2', 'wave2')

            with db() as conn, conn.cursor() as cur:
                # item_count must reflect only the 1 submitted item, not 2
                cur.execute(
                    "SELECT item_count FROM ai_batches WHERE anthropic_batch_id = %s",
                    [_batch_id],
                )
                row = cur.fetchone()
            assert row is not None
            assert row[0] == 1, f"Expected item_count=1, got {row[0]}"

            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT abi.agenda_item_id FROM ai_batch_items abi
                    JOIN ai_batches ab ON ab.id = abi.batch_id
                    WHERE ab.anthropic_batch_id = %s
                    """,
                    [_batch_id],
                )
                rows = cur.fetchall()

            # Exactly one ai_batch_items row
            assert len(rows) == 1, f"Expected 1 ai_batch_items row, got {len(rows)}"
            # The row references the item that HAD facts
            assert rows[0][0] == item_ids[0], (
                f"Expected agenda_item_id={item_ids[0]}, got {rows[0][0]}"
            )

        finally:
            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM ai_batches WHERE anthropic_batch_id = %s",
                    [_batch_id],
                )
                if item_ids:
                    cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", [item_ids])
                if meeting_ids:
                    cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", [meeting_ids])
                cur.execute(
                    "DELETE FROM municipalities WHERE slug = 'test_batches_muni'"
                )

    def test_submit_batch_raises_when_all_items_skipped(self):
        """submit_batch raises ValueError when every stage2 item lacks Stage 1 facts."""
        meeting_ids = []
        item_ids = []

        try:
            with db() as conn, conn.cursor() as cur:
                m_id, i_id = _insert_meeting_and_item(cur, "All-skipped test item")
                meeting_ids.append(m_id)
                item_ids.append(i_id)
                # extracted_facts intentionally left NULL

            item_no_facts = make_item(id=item_ids[0])

            with patch('docket.ai.batches.anthropic.Anthropic') as mock_cls, \
                 patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
                mock_cls.return_value.messages.batches.create.return_value = MagicMock()

                with pytest.raises(ValueError, match="no items to submit"):
                    submit_batch([item_no_facts], 'stage2', 'wave2')

            # No ai_batches row must have been created
            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM ai_batches WHERE anthropic_batch_id LIKE 'msgbatch%'"
                    " AND stage = 'stage2' AND wave = 'wave2'"
                    " AND item_count = 0",
                )
                # The real check: Anthropic create was never called so no batch_id to look up.
                # Verify the mock create was NOT called.
            mock_cls.return_value.messages.batches.create.assert_not_called()

        finally:
            with db() as conn, conn.cursor() as cur:
                if item_ids:
                    cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", [item_ids])
                if meeting_ids:
                    cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", [meeting_ids])
                cur.execute(
                    "DELETE FROM municipalities WHERE slug = 'test_batches_muni'"
                )


# ---------------------------------------------------------------------------
# TestPollBatch
# ---------------------------------------------------------------------------

class TestPollBatch:
    def test_poll_ended_persists_results_and_updates_batch_status(self):
        """On 'ended', poll_batch persists result_status and sets ai_batches.status='ended'."""
        _anth_batch_id = f'msgbatch_poll_ended_{id(object())}'
        meeting_ids = []
        item_ids = []

        try:
            with db() as conn, conn.cursor() as cur:
                m_id, i_id = _insert_meeting_and_item(cur, "Poll ended test item")
                meeting_ids.append(m_id)
                item_ids.append(i_id)

            # Pre-create the ai_batches row + ai_batch_items row
            internal_batch_id = record_batch(_anth_batch_id, 'stage1', 'wave0', item_ids)

            # Build mock result
            mock_result = MagicMock()
            mock_result.custom_id = f'item-{item_ids[0]}-stage1'
            mock_result.result.type = 'succeeded'

            mock_batch = MagicMock()
            mock_batch.id = _anth_batch_id
            mock_batch.processing_status = 'ended'
            mock_batch.request_counts = MagicMock()

            with patch('docket.ai.batches.anthropic.Anthropic') as mock_cls:
                mock_client = mock_cls.return_value
                mock_client.messages.batches.retrieve.return_value = mock_batch
                mock_client.messages.batches.results.return_value = [mock_result]

                status = poll_batch(_anth_batch_id)

            assert status.status == 'ended'
            assert status.id == _anth_batch_id

            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT result_status FROM ai_batch_items "
                    "WHERE batch_id = %s AND agenda_item_id = %s",
                    [internal_batch_id, item_ids[0]],
                )
                row = cur.fetchone()
            assert row is not None
            assert row[0] == 'succeeded'

            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT status, completed_at FROM ai_batches WHERE id = %s",
                    [internal_batch_id],
                )
                row = cur.fetchone()
            assert row[0] == 'ended'
            assert row[1] is not None  # completed_at set

        finally:
            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM ai_batches WHERE anthropic_batch_id = %s",
                    [_anth_batch_id],
                )
                if item_ids:
                    cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", [item_ids])
                if meeting_ids:
                    cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", [meeting_ids])
                cur.execute(
                    "DELETE FROM municipalities WHERE slug = 'test_batches_muni'"
                )

    def test_poll_in_progress_does_not_update_db(self):
        """On 'in_progress', poll_batch does NOT call persist_batch_result or update ai_batches."""
        mock_batch = MagicMock()
        mock_batch.id = 'msgbatch_inprogress_test'
        mock_batch.processing_status = 'in_progress'
        mock_batch.request_counts = MagicMock()

        with patch('docket.ai.batches.anthropic.Anthropic') as mock_cls, \
             patch('docket.ai.batches.persist_batch_result') as mock_persist, \
             patch('docket.ai.batches.db') as mock_db:
            mock_cls.return_value.messages.batches.retrieve.return_value = mock_batch

            status = poll_batch('msgbatch_inprogress_test')

        mock_persist.assert_not_called()
        mock_db.assert_not_called()
        assert status.status == 'in_progress'

    def test_poll_returns_batch_status_dataclass(self):
        """poll_batch returns a BatchStatus dataclass regardless of processing_status."""
        mock_batch = MagicMock()
        mock_batch.id = 'msgbatch_dataclass_test'
        mock_batch.processing_status = 'in_progress'
        mock_batch.request_counts = {'succeeded': 0, 'errored': 0, 'processing': 5}

        with patch('docket.ai.batches.anthropic.Anthropic') as mock_cls, \
             patch('docket.ai.batches.db'):
            mock_cls.return_value.messages.batches.retrieve.return_value = mock_batch

            status = poll_batch('msgbatch_dataclass_test')

        assert isinstance(status, BatchStatus)
        assert status.id == 'msgbatch_dataclass_test'

    def test_poll_failed_updates_status_without_results(self):
        """On 'failed', ai_batches.status is updated but results are not iterated."""
        _anth_batch_id = f'msgbatch_fail_{id(object())}'
        meeting_ids = []
        item_ids = []

        try:
            with db() as conn, conn.cursor() as cur:
                m_id, i_id = _insert_meeting_and_item(cur, "Poll failed test item")
                meeting_ids.append(m_id)
                item_ids.append(i_id)

            internal_batch_id = record_batch(_anth_batch_id, 'stage1', 'wave0', item_ids)

            mock_batch = MagicMock()
            mock_batch.id = _anth_batch_id
            mock_batch.processing_status = 'failed'
            mock_batch.request_counts = MagicMock()

            with patch('docket.ai.batches.anthropic.Anthropic') as mock_cls, \
                 patch('docket.ai.batches.persist_batch_result') as mock_persist:
                mock_cls.return_value.messages.batches.retrieve.return_value = mock_batch

                status = poll_batch(_anth_batch_id)

            mock_persist.assert_not_called()
            assert status.status == 'failed'

            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT status FROM ai_batches WHERE id = %s",
                    [internal_batch_id],
                )
                row = cur.fetchone()
            assert row[0] == 'failed'

        finally:
            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM ai_batches WHERE anthropic_batch_id = %s",
                    [_anth_batch_id],
                )
                if item_ids:
                    cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", [item_ids])
                if meeting_ids:
                    cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", [meeting_ids])
                cur.execute(
                    "DELETE FROM municipalities WHERE slug = 'test_batches_muni'"
                )


# ---------------------------------------------------------------------------
# TestGetStage1Facts
# ---------------------------------------------------------------------------

class TestGetStage1Facts:
    def test_returns_none_when_no_row(self):
        """get_stage1_facts returns None when the item ID does not exist."""
        item = make_item(id=999999999)
        result = get_stage1_facts(item)
        assert result is None

    def test_returns_none_when_extracted_facts_is_null(self):
        """get_stage1_facts returns None when extracted_facts column is NULL."""
        meeting_ids = []
        item_ids = []

        try:
            with db() as conn, conn.cursor() as cur:
                m_id, i_id = _insert_meeting_and_item(cur, "No facts item")
                meeting_ids.append(m_id)
                item_ids.append(i_id)

            item = make_item(id=item_ids[0])
            result = get_stage1_facts(item)
            assert result is None

        finally:
            with db() as conn, conn.cursor() as cur:
                if item_ids:
                    cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", [item_ids])
                if meeting_ids:
                    cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", [meeting_ids])
                cur.execute(
                    "DELETE FROM municipalities WHERE slug = 'test_batches_muni'"
                )

    def test_returns_structured_facts_when_present(self):
        """get_stage1_facts parses extracted_facts JSONB into StructuredFacts."""
        meeting_ids = []
        item_ids = []

        try:
            with db() as conn, conn.cursor() as cur:
                m_id, i_id = _insert_meeting_and_item(cur, "Facts present item")
                meeting_ids.append(m_id)
                item_ids.append(i_id)

                facts_dict = {
                    'funding_source': 'general_fund',
                    'counterparty': 'FactsTestVendor',
                    'procurement_method': 'competitive',
                    'location': None,
                    'action_type': 'contract_award',
                    'next_steps': {},
                    'parcels_affected': None,
                    'acres_affected': None,
                }
                cur.execute(
                    "UPDATE agenda_items SET extracted_facts = %s::jsonb WHERE id = %s",
                    [json.dumps(facts_dict), i_id],
                )

            item = make_item(id=item_ids[0])
            result = get_stage1_facts(item)

            assert result is not None
            assert isinstance(result, StructuredFacts)
            assert result.counterparty == 'FactsTestVendor'
            assert result.funding_source == 'general_fund'

        finally:
            with db() as conn, conn.cursor() as cur:
                if item_ids:
                    cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", [item_ids])
                if meeting_ids:
                    cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", [meeting_ids])
                cur.execute(
                    "DELETE FROM municipalities WHERE slug = 'test_batches_muni'"
                )


# ---------------------------------------------------------------------------
# TestPersistBatchResult
# ---------------------------------------------------------------------------

class TestPersistBatchResult:
    def test_persist_updates_result_status(self):
        """persist_batch_result updates ai_batch_items.result_status."""
        _anth_batch_id = f'msgbatch_persist_{id(object())}'
        meeting_ids = []
        item_ids = []

        try:
            with db() as conn, conn.cursor() as cur:
                m_id, i_id = _insert_meeting_and_item(cur, "Persist result test item")
                meeting_ids.append(m_id)
                item_ids.append(i_id)

            internal_batch_id = record_batch(_anth_batch_id, 'stage1', 'wave0', item_ids)

            mock_result = MagicMock()
            mock_result.custom_id = f'item-{item_ids[0]}-stage1'
            mock_result.result.type = 'succeeded'

            persist_batch_result(mock_result, _anth_batch_id)

            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT result_status FROM ai_batch_items "
                    "WHERE batch_id = %s AND agenda_item_id = %s",
                    [internal_batch_id, item_ids[0]],
                )
                row = cur.fetchone()

            assert row is not None
            assert row[0] == 'succeeded'

        finally:
            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM ai_batches WHERE anthropic_batch_id = %s",
                    [_anth_batch_id],
                )
                if item_ids:
                    cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", [item_ids])
                if meeting_ids:
                    cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", [meeting_ids])
                cur.execute(
                    "DELETE FROM municipalities WHERE slug = 'test_batches_muni'"
                )

    def test_persist_logs_warning_when_batch_not_found(self, caplog):
        """persist_batch_result logs a warning when anthropic_batch_id has no DB row."""
        import logging

        mock_result = MagicMock()
        mock_result.custom_id = 'item-42-stage1'
        mock_result.result.type = 'errored'

        with caplog.at_level(logging.WARNING, logger='docket.ai.batches'):
            persist_batch_result(mock_result, 'msgbatch_does_not_exist')

        assert any('no ai_batches row' in r.message for r in caplog.records)
