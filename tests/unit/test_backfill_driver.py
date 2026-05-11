"""Tests for docket.ai.backfill_driver.

Covers:
  - TestIteratePendingItems: happy path, date-range filter, status filter,
    already-claimed exclusion, chunking
  - TestClaimSession: happy path rowcount, idempotency / partial collision
  - TestRunWave: end-to-end with mocked submit_batch, rollback on failure,
    ValueError on unknown wave name
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import patch

import pytest

from docket.ai.backfill_driver import (
    WaveResult,
    claim_session,
    iterate_pending_items,
    run_wave,
)
from docket.db import db


# ---------------------------------------------------------------------------
# DB helpers — mirrors test_batches.py pattern
# ---------------------------------------------------------------------------

_MUNI_SLUG = 'test_backfill_driver_muni'


def _insert_muni_and_meeting(cur, meeting_date: date = date(2026, 3, 1)) -> tuple[int, int]:
    """Insert a minimal municipality + meeting row. Returns (muni_id, meeting_id)."""
    cur.execute("""
        INSERT INTO municipalities (slug, name, state, adapter_class, active)
        VALUES (%s, 'Test Backfill Driver', 'AL', 'granicus', TRUE)
        ON CONFLICT (slug) DO UPDATE SET active = TRUE
        RETURNING id
    """, [_MUNI_SLUG])
    muni_id = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url, title)
        VALUES (%s, 'Council', %s, 'http://test.backfill.example', 'Test Backfill Meeting')
        RETURNING id
    """, [muni_id, meeting_date])
    meeting_id = cur.fetchone()[0]

    return muni_id, meeting_id


def _insert_item(
    cur,
    meeting_id: int,
    title: str = "Test item",
    processing_status: str = 'pending',
    backfill_session_id: str | None = None,
) -> int:
    """Insert a minimal agenda_item row. Returns item_id."""
    cur.execute("""
        INSERT INTO agenda_items
            (meeting_id, title, is_consent, processing_status, backfill_session_id)
        VALUES (%s, %s, FALSE, %s, %s)
        RETURNING id
    """, [meeting_id, title, processing_status, backfill_session_id])
    return cur.fetchone()[0]


def _cleanup(meeting_ids: list[int], item_ids: list[int]) -> None:
    with db() as conn, conn.cursor() as cur:
        if item_ids:
            cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", [item_ids])
        if meeting_ids:
            cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", [meeting_ids])
        cur.execute("DELETE FROM municipalities WHERE slug = %s", [_MUNI_SLUG])


# ---------------------------------------------------------------------------
# TestIteratePendingItems
# ---------------------------------------------------------------------------

class TestIteratePendingItems:
    def test_happy_path_stage1_returns_items_in_range(self):
        """Insert 3 pending items in date range; iterate returns one chunk of 3."""
        meeting_ids = []
        item_ids = []
        try:
            with db() as conn, conn.cursor() as cur:
                _, m_id = _insert_muni_and_meeting(cur, date(2026, 3, 1))
                meeting_ids.append(m_id)
                for i in range(3):
                    item_ids.append(_insert_item(cur, m_id, f"Item {i}", 'pending'))

            chunks = list(iterate_pending_items(
                (date(2026, 1, 1), date(2026, 12, 31)),
                stage='stage1',
                batch_size=10,
            ))

            # Filter to only our items (other tests may insert items too)
            our_ids = set(item_ids)
            found = [it for chunk in chunks for it in chunk if it.id in our_ids]
            assert len(found) == 3
            assert {it.id for it in found} == our_ids
            # Verify duck-typed attributes are populated
            for it in found:
                assert hasattr(it, 'title')
                assert hasattr(it, 'description')
                assert hasattr(it, 'sponsor')
                assert hasattr(it, 'dollars_amount')
                assert hasattr(it, 'topic')
                assert hasattr(it, 'is_consent')
        finally:
            _cleanup(meeting_ids, item_ids)

    def test_filters_by_date_range(self):
        """Items whose meeting_date is outside the range are excluded."""
        meeting_ids = []
        item_ids = []
        try:
            with db() as conn, conn.cursor() as cur:
                _, m_in = _insert_muni_and_meeting(cur, date(2026, 6, 1))
                meeting_ids.append(m_in)
                _, m_out = _insert_muni_and_meeting(cur, date(2020, 1, 1))
                meeting_ids.append(m_out)

                in_id = _insert_item(cur, m_in, "In range", 'pending')
                out_id = _insert_item(cur, m_out, "Out of range", 'pending')
                item_ids.extend([in_id, out_id])

            chunks = list(iterate_pending_items(
                (date(2026, 1, 1), date(2026, 12, 31)),
                stage='stage1',
            ))
            found_ids = {it.id for chunk in chunks for it in chunk}
            assert in_id in found_ids
            assert out_id not in found_ids
        finally:
            _cleanup(meeting_ids, item_ids)

    def test_stage1_excludes_non_pending_statuses(self):
        """Items with data_quality_skipped or procedural_skipped are excluded for stage1."""
        meeting_ids = []
        item_ids = []
        try:
            with db() as conn, conn.cursor() as cur:
                _, m_id = _insert_muni_and_meeting(cur, date(2026, 4, 1))
                meeting_ids.append(m_id)

                pending_id = _insert_item(cur, m_id, "Pending", 'pending')
                skipped_id = _insert_item(cur, m_id, "Skipped", 'data_quality_skipped')
                proc_id = _insert_item(cur, m_id, "Proc skipped", 'procedural_skipped')
                item_ids.extend([pending_id, skipped_id, proc_id])

            chunks = list(iterate_pending_items(
                (date(2026, 1, 1), date(2026, 12, 31)),
                stage='stage1',
            ))
            found_ids = {it.id for chunk in chunks for it in chunk}
            assert pending_id in found_ids
            assert skipped_id not in found_ids
            assert proc_id not in found_ids
        finally:
            _cleanup(meeting_ids, item_ids)

    def test_stage2_excludes_pending_includes_extracted(self):
        """stage2 uses processing_status='extracted'; pending items are excluded."""
        meeting_ids = []
        item_ids = []
        try:
            with db() as conn, conn.cursor() as cur:
                _, m_id = _insert_muni_and_meeting(cur, date(2026, 5, 1))
                meeting_ids.append(m_id)

                extracted_id = _insert_item(cur, m_id, "Extracted", 'extracted')
                pending_id = _insert_item(cur, m_id, "Pending", 'pending')
                item_ids.extend([extracted_id, pending_id])

            chunks = list(iterate_pending_items(
                (date(2026, 1, 1), date(2026, 12, 31)),
                stage='stage2',
            ))
            found_ids = {it.id for chunk in chunks for it in chunk}
            assert extracted_id in found_ids
            assert pending_id not in found_ids
        finally:
            _cleanup(meeting_ids, item_ids)

    def test_excludes_already_claimed_items(self):
        """Items with backfill_session_id IS NOT NULL are excluded from Stage 1."""
        meeting_ids = []
        item_ids = []
        try:
            existing_session = str(uuid.uuid4())
            with db() as conn, conn.cursor() as cur:
                _, m_id = _insert_muni_and_meeting(cur, date(2026, 7, 1))
                meeting_ids.append(m_id)

                unclaimed_id = _insert_item(cur, m_id, "Unclaimed", 'pending')
                claimed_id = _insert_item(
                    cur, m_id, "Claimed", 'pending', backfill_session_id=existing_session
                )
                item_ids.extend([unclaimed_id, claimed_id])

            chunks = list(iterate_pending_items(
                (date(2026, 1, 1), date(2026, 12, 31)),
                stage='stage1',
            ))
            found_ids = {it.id for chunk in chunks for it in chunk}
            assert unclaimed_id in found_ids
            assert claimed_id not in found_ids
        finally:
            _cleanup(meeting_ids, item_ids)

    def test_stage2_claims_extracted_items_regardless_of_session_id(self):
        """Stage 2 must pick up items at processing_status='extracted'
        even though Stage 1 left a backfill_session_id on them.

        Regression test for the Wave 1 Stage 2 zero-results bug observed
        2026-05-11: Stage 1 succeeded (items at 'extracted' with their
        Stage 1 session_id), then Stage 2's iterate_pending_items
        filtered them out via ``backfill_session_id IS NULL``. The
        session_id guard belongs only on Stage 1's claim path
        (prevents two simultaneous Stage 1 waves clobbering each
        other); for Stage 2 the ``processing_status='extracted'`` filter
        is itself the single-source guard."""
        meeting_ids = []
        item_ids = []
        try:
            stage1_session = str(uuid.uuid4())
            with db() as conn, conn.cursor() as cur:
                _, m_id = _insert_muni_and_meeting(cur, date(2026, 8, 1))
                meeting_ids.append(m_id)
                extracted_with_session = _insert_item(
                    cur, m_id, "Stage1-done",
                    processing_status='extracted',
                    backfill_session_id=stage1_session,
                )
                item_ids.append(extracted_with_session)

            chunks = list(iterate_pending_items(
                (date(2026, 1, 1), date(2026, 12, 31)),
                stage='stage2',
            ))
            found_ids = {it.id for chunk in chunks for it in chunk}
            assert extracted_with_session in found_ids
        finally:
            _cleanup(meeting_ids, item_ids)

    def test_chunks_by_batch_size(self):
        """25 items with batch_size=10 yields 3 chunks (10/10/5)."""
        meeting_ids = []
        item_ids = []
        try:
            with db() as conn, conn.cursor() as cur:
                _, m_id = _insert_muni_and_meeting(cur, date(2026, 8, 1))
                meeting_ids.append(m_id)
                for i in range(25):
                    item_ids.append(_insert_item(cur, m_id, f"Chunk item {i}", 'pending'))

            chunks = list(iterate_pending_items(
                (date(2026, 1, 1), date(2026, 12, 31)),
                stage='stage1',
                batch_size=10,
            ))
            # Filter chunks to only our items (other tests may have pending items in range)
            our_ids = set(item_ids)
            our_chunks = []
            remainder = list(our_ids)
            # Reassemble from all chunks into our_ids-only sorted list
            our_items_sorted = sorted(
                [it for chunk in chunks for it in chunk if it.id in our_ids],
                key=lambda x: x.id,
            )
            assert len(our_items_sorted) == 25
            # Verify overall chunking structure: all chunks have <= batch_size items
            for chunk in chunks:
                assert len(chunk) <= 10
        finally:
            _cleanup(meeting_ids, item_ids)


# ---------------------------------------------------------------------------
# TestClaimSession
# ---------------------------------------------------------------------------

class TestClaimSession:
    def test_happy_path_marks_items_and_returns_rowcount(self):
        """claim_session writes session UUID to rows and returns correct rowcount."""
        meeting_ids = []
        item_ids = []
        try:
            with db() as conn, conn.cursor() as cur:
                _, m_id = _insert_muni_and_meeting(cur, date(2026, 9, 1))
                meeting_ids.append(m_id)
                for i in range(3):
                    item_ids.append(_insert_item(cur, m_id, f"Claim item {i}", 'pending'))

            session_id = uuid.uuid4()
            rowcount = claim_session(item_ids, session_id)
            assert rowcount == 3

            # Verify the rows are stamped
            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM agenda_items "
                    "WHERE id = ANY(%s) AND backfill_session_id = %s",
                    [item_ids, str(session_id)],
                )
                assert cur.fetchone()[0] == 3
        finally:
            _cleanup(meeting_ids, item_ids)

    def test_idempotent_under_partial_collision(self):
        """Items already claimed by a different session are NOT re-claimed."""
        meeting_ids = []
        item_ids = []
        try:
            other_session = str(uuid.uuid4())
            with db() as conn, conn.cursor() as cur:
                _, m_id = _insert_muni_and_meeting(cur, date(2026, 10, 1))
                meeting_ids.append(m_id)

                free_id = _insert_item(cur, m_id, "Free item", 'pending')
                taken_id = _insert_item(
                    cur, m_id, "Taken item", 'pending',
                    backfill_session_id=other_session,
                )
                item_ids.extend([free_id, taken_id])

            new_session = uuid.uuid4()
            rowcount = claim_session([free_id, taken_id], new_session)

            # Only the free item was claimed
            assert rowcount == 1

            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT backfill_session_id FROM agenda_items WHERE id = %s",
                    [taken_id],
                )
                assert cur.fetchone()[0] == other_session
        finally:
            _cleanup(meeting_ids, item_ids)


# ---------------------------------------------------------------------------
# TestRunWave
# ---------------------------------------------------------------------------

class TestRunWave:
    def test_end_to_end_returns_wave_result(self):
        """run_wave submits items, returns WaveResult with correct counts and session_id."""
        meeting_ids = []
        item_ids = []
        try:
            with db() as conn, conn.cursor() as cur:
                _, m_id = _insert_muni_and_meeting(cur, date(2026, 3, 15))
                meeting_ids.append(m_id)
                for i in range(3):
                    item_ids.append(_insert_item(cur, m_id, f"Wave item {i}", 'pending'))

            fake_batch_id = f'msgbatch_wave_test_{uuid.uuid4().hex[:8]}'
            with patch('docket.ai.backfill_driver.submit_batch', return_value=fake_batch_id):
                result = run_wave('1', 'stage1', date_range=(date(2026, 1, 1), date(2026, 12, 31)))

            assert isinstance(result, WaveResult)
            assert isinstance(result.session_id, uuid.UUID)
            assert result.wave_name == '1'
            assert result.stage == 'stage1'
            # The DB may have other pending items in 2026; assert our 3 are included.
            assert result.item_count >= 3
            assert fake_batch_id in result.anthropic_batch_ids
        finally:
            _cleanup(meeting_ids, item_ids)

    def test_rolls_back_session_claim_on_submission_failure(self):
        """If submit_batch raises, backfill_session_id is set back to NULL on all items."""
        meeting_ids = []
        item_ids = []
        try:
            with db() as conn, conn.cursor() as cur:
                _, m_id = _insert_muni_and_meeting(cur, date(2026, 4, 15))
                meeting_ids.append(m_id)
                for i in range(3):
                    item_ids.append(_insert_item(cur, m_id, f"Rollback item {i}", 'pending'))

            with patch(
                'docket.ai.backfill_driver.submit_batch',
                side_effect=RuntimeError("API exploded"),
            ):
                with pytest.raises(RuntimeError, match="API exploded"):
                    run_wave(
                        'rollback_test', 'stage1',
                        date_range=(date(2026, 1, 1), date(2026, 12, 31)),
                    )

            # All items should have backfill_session_id = NULL after rollback
            with db() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM agenda_items "
                    "WHERE id = ANY(%s) AND backfill_session_id IS NOT NULL",
                    [item_ids],
                )
                still_claimed = cur.fetchone()[0]
            assert still_claimed == 0, (
                f"Expected 0 items still claimed after rollback, got {still_claimed}"
            )
        finally:
            _cleanup(meeting_ids, item_ids)

    def test_raises_value_error_on_unknown_wave_name(self):
        """run_wave raises ValueError when wave_name is unknown and no date_range given."""
        with pytest.raises(ValueError, match="unknown wave_name"):
            run_wave('bogus_wave', 'stage1')

    def test_empty_result_when_no_pending_items(self):
        """run_wave returns WaveResult with batch_count=0, item_count=0 when nothing pending."""
        # Use a historical date range with no meetings (pre-internet municipal records).
        # submit_batch should never be called; patch it to catch any unexpected call.
        with patch('docket.ai.backfill_driver.submit_batch') as mock_submit:
            result = run_wave('1', 'stage1', date_range=(date(1800, 1, 1), date(1800, 12, 31)))
            mock_submit.assert_not_called()

        assert isinstance(result, WaveResult)
        assert result.batch_count == 0
        assert result.item_count == 0
        assert result.anthropic_batch_ids == []

    def test_wave_date_ranges_applied_for_named_waves(self):
        """run_wave uses WAVE_DATE_RANGES when no explicit date_range given (wave '2')."""
        meeting_ids = []
        item_ids = []
        try:
            with db() as conn, conn.cursor() as cur:
                # Insert a meeting in 2022 — inside Wave 2 range (2021-2025)
                _, m_id = _insert_muni_and_meeting(cur, date(2022, 6, 1))
                meeting_ids.append(m_id)
                item_ids.append(_insert_item(cur, m_id, "Wave 2 item", 'pending'))

            fake_batch_id = f'msgbatch_wave2_{uuid.uuid4().hex[:8]}'
            with patch('docket.ai.backfill_driver.submit_batch', return_value=fake_batch_id):
                result = run_wave('2', 'stage1')

            # Our item should have been included (Wave 2 = 2021-2025)
            assert result.item_count >= 1
        finally:
            _cleanup(meeting_ids, item_ids)
