"""Tests for record_badge_action helper (docket.services.badges).

Coverage:
- Happy path: all fields populated
- Minimal args: actor/reason default to NULL
- Both rejection paths (invalid action, invalid actor_role)
- All three actor_roles (admin, cron, on_write)
- Caller-owns-transaction: rollback leaves no row

DB tests use the same try/finally pattern as test_badges_process.py and
test_badges_policy.py.  A real agenda_items row is needed for the FK;
the audit table has no FK to agenda_item_badges, so no badge row is needed.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from docket.services.badges import record_badge_action


# ===========================================================================
# Helpers / fixtures
# ===========================================================================

TEST_CITY_SLUG = 'test_badges_audit_city'


def _setup_city(cur):
    """Insert or reuse test municipality. Returns city_id."""
    cur.execute(
        """
        INSERT INTO municipalities (slug, name, state, county, adapter_class, adapter_config)
        VALUES (%s, 'Test Audit City', 'AL', 'Test', 'TestAdapter', '{}')
        ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        (TEST_CITY_SLUG,),
    )
    return cur.fetchone()[0]


def _setup_meeting(cur, city_id, *, external_id='test-audit-mtg-1',
                   meeting_date='2025-06-01'):
    """Insert a test meeting. Returns meeting_id."""
    cur.execute(
        """
        INSERT INTO meetings (municipality_id, external_id, title, meeting_date)
        VALUES (%s, %s, 'Test Audit Meeting', %s)
        ON CONFLICT (municipality_id, external_id) DO UPDATE SET title = EXCLUDED.title
        RETURNING id
        """,
        (city_id, external_id, meeting_date),
    )
    return cur.fetchone()[0]


def _setup_agenda_item(cur, meeting_id, *, item_number='1', title='Test audit item'):
    """Insert a minimal test agenda item. Returns agenda_item_id."""
    cur.execute(
        """
        INSERT INTO agenda_items (meeting_id, item_number, title)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (meeting_id, item_number, title),
    )
    return cur.fetchone()[0]


def _audit_row(cur, agenda_item_id, badge_slug):
    """Return the audit row dict, or None if absent."""
    cur.execute(
        """
        SELECT agenda_item_id, badge_slug, action, actor, actor_role, reason
          FROM agenda_item_badges_audit
         WHERE agenda_item_id = %s AND badge_slug = %s
        """,
        (agenda_item_id, badge_slug),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip(
        ['agenda_item_id', 'badge_slug', 'action', 'actor', 'actor_role', 'reason'],
        row,
    ))


def _cleanup(cur, city_id):
    """Remove test data in FK dependency order."""
    cur.execute("SELECT id FROM meetings WHERE municipality_id = %s", (city_id,))
    meeting_ids = [r[0] for r in cur.fetchall()]
    if meeting_ids:
        cur.execute(
            "SELECT id FROM agenda_items WHERE meeting_id = ANY(%s)",
            (meeting_ids,),
        )
        item_ids = [r[0] for r in cur.fetchall()]
        if item_ids:
            cur.execute(
                "DELETE FROM agenda_item_badges_audit WHERE agenda_item_id = ANY(%s)",
                (item_ids,),
            )
            cur.execute(
                "DELETE FROM agenda_item_badges WHERE agenda_item_id = ANY(%s)",
                (item_ids,),
            )
            cur.execute(
                "DELETE FROM agenda_items WHERE id = ANY(%s)", (item_ids,)
            )
    cur.execute("DELETE FROM meetings WHERE municipality_id = %s", (city_id,))
    cur.execute("DELETE FROM municipalities WHERE slug = %s", (TEST_CITY_SLUG,))


# ===========================================================================
# Rejection tests — no DB needed, MagicMock cursor is fine
# ===========================================================================

class TestRecordBadgeActionRejectsInvalidAction:
    """record_badge_action raises ValueError on unknown action before touching DB."""

    def test_rejects_deleted(self):
        cur = MagicMock()
        with pytest.raises(ValueError, match="added|removed|modified"):
            record_badge_action(cur, 1, 'sole_source', 'deleted', 'cron')
        cur.execute.assert_not_called()

    def test_rejects_empty_string(self):
        cur = MagicMock()
        with pytest.raises(ValueError):
            record_badge_action(cur, 1, 'sole_source', '', 'cron')
        cur.execute.assert_not_called()

    def test_rejects_uppercase_added(self):
        """Validation is case-sensitive."""
        cur = MagicMock()
        with pytest.raises(ValueError):
            record_badge_action(cur, 1, 'sole_source', 'Added', 'cron')
        cur.execute.assert_not_called()


class TestRecordBadgeActionRejectsInvalidActorRole:
    """record_badge_action raises ValueError on unknown actor_role before touching DB."""

    def test_rejects_robot(self):
        cur = MagicMock()
        with pytest.raises(ValueError, match="admin|cron|on_write"):
            record_badge_action(cur, 1, 'sole_source', 'added', 'robot')
        cur.execute.assert_not_called()

    def test_rejects_system(self):
        cur = MagicMock()
        with pytest.raises(ValueError):
            record_badge_action(cur, 1, 'sole_source', 'added', 'system')
        cur.execute.assert_not_called()

    def test_rejects_empty_string(self):
        cur = MagicMock()
        with pytest.raises(ValueError):
            record_badge_action(cur, 1, 'sole_source', 'added', '')
        cur.execute.assert_not_called()


# ===========================================================================
# DB integration tests
# ===========================================================================

class TestRecordBadgeActionInsertsRow:
    """Happy path: all fields populated."""

    def test_inserts_row_with_all_fields(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id)
                    item_id = _setup_agenda_item(cur, mtg_id)

                    record_badge_action(
                        cur, item_id, 'sole_source', 'added', 'on_write',
                        actor='process_badges_task',
                        reason='procurement_method=sole_source detected',
                    )

                    row = _audit_row(cur, item_id, 'sole_source')
                    assert row is not None
                    assert row['agenda_item_id'] == item_id
                    assert row['badge_slug'] == 'sole_source'
                    assert row['action'] == 'added'
                    assert row['actor'] == 'process_badges_task'
                    assert row['actor_role'] == 'on_write'
                    assert row['reason'] == 'procurement_method=sole_source detected'
                finally:
                    _cleanup(cur, city_id)


class TestRecordBadgeActionMinimalArgs:
    """Minimal required positional args — actor and reason both NULL in the DB."""

    def test_actor_and_reason_default_to_null(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-audit-mtg-minimal')
                    item_id = _setup_agenda_item(cur, mtg_id, item_number='2')

                    record_badge_action(cur, item_id, 'blight', 'added', 'cron')

                    row = _audit_row(cur, item_id, 'blight')
                    assert row is not None
                    assert row['actor'] is None
                    assert row['reason'] is None
                finally:
                    _cleanup(cur, city_id)


class TestRecordBadgeActionWithActorAndReason:
    """Both optional kwargs populated — row reflects them."""

    def test_actor_and_reason_stored(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-audit-mtg-kwargs')
                    item_id = _setup_agenda_item(cur, mtg_id, item_number='3')

                    record_badge_action(
                        cur, item_id, 'hidden_on_consent', 'modified', 'admin',
                        actor='admin@docket.pub',
                        reason='manual override: misclassified',
                    )

                    row = _audit_row(cur, item_id, 'hidden_on_consent')
                    assert row['actor'] == 'admin@docket.pub'
                    assert row['reason'] == 'manual override: misclassified'
                finally:
                    _cleanup(cur, city_id)


class TestRecordBadgeActionActorRoles:
    """Happy path for each of the three actor_roles."""

    def test_admin_manually_adds_badge(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-audit-mtg-admin')
                    item_id = _setup_agenda_item(cur, mtg_id, item_number='4')

                    record_badge_action(
                        cur, item_id, 'sole_source', 'added', 'admin',
                        actor='admin@docket.pub',
                    )

                    row = _audit_row(cur, item_id, 'sole_source')
                    assert row is not None
                    assert row['actor_role'] == 'admin'
                    assert row['action'] == 'added'
                finally:
                    _cleanup(cur, city_id)

    def test_cron_removes_stale_badge(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-audit-mtg-cron')
                    item_id = _setup_agenda_item(cur, mtg_id, item_number='5')

                    record_badge_action(
                        cur, item_id, 'emergency_action', 'removed', 'cron',
                        actor='process_badges_task',
                        reason='re-evaluation: no longer qualifies',
                    )

                    row = _audit_row(cur, item_id, 'emergency_action')
                    assert row is not None
                    assert row['actor_role'] == 'cron'
                    assert row['action'] == 'removed'
                finally:
                    _cleanup(cur, city_id)

    def test_on_write_modifies_badge(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-audit-mtg-onwrite')
                    item_id = _setup_agenda_item(cur, mtg_id, item_number='6')

                    record_badge_action(
                        cur, item_id, 'contested', 'modified', 'on_write',
                        actor='process_badges_task',
                    )

                    row = _audit_row(cur, item_id, 'contested')
                    assert row is not None
                    assert row['actor_role'] == 'on_write'
                    assert row['action'] == 'modified'
                finally:
                    _cleanup(cur, city_id)


class TestRecordBadgeActionCallerOwnsTransaction:
    """Rollback leaves no row — helper does NOT auto-commit."""

    def test_rollback_leaves_no_row(self):
        from docket.db import db
        # We need a real item_id to satisfy the FK.  Use a separate committed
        # transaction to create fixtures, then roll back only the audit insert.
        with db() as conn_setup:
            with conn_setup.cursor() as cur_setup:
                city_id = _setup_city(cur_setup)
                mtg_id = _setup_meeting(cur_setup, city_id, external_id='test-audit-mtg-txn')
                item_id = _setup_agenda_item(cur_setup, mtg_id, item_number='7')

        # Now open a second connection, call the helper, then roll back.
        import psycopg2
        from docket.config import DATABASE_URL
        conn_test = psycopg2.connect(DATABASE_URL)
        conn_test.autocommit = False
        try:
            with conn_test.cursor() as cur_test:
                record_badge_action(
                    cur_test, item_id, 'split_vote', 'added', 'on_write',
                    actor='process_badges_task',
                )
                # Roll back — the insert should vanish.
                conn_test.rollback()

            # Verify with yet another cursor on the same rolled-back connection
            # (now in idle state after rollback).
            with conn_test.cursor() as cur_verify:
                cur_verify.execute(
                    """
                    SELECT 1 FROM agenda_item_badges_audit
                     WHERE agenda_item_id = %s AND badge_slug = 'split_vote'
                    """,
                    (item_id,),
                )
                assert cur_verify.fetchone() is None, (
                    "Audit row should not persist after rollback"
                )
        finally:
            conn_test.close()
            # Clean up the fixture rows.
            with db() as conn_cleanup:
                with conn_cleanup.cursor() as cur_cleanup:
                    _cleanup(cur_cleanup, city_id)
