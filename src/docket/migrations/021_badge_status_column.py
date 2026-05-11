"""Migration 021 — agenda_item_badges.status (applied/flagged/rejected).

Refactor #2 from the Wave 1 evaluation: badges suggested by Haiku
alone (no deterministic keyword/action-type signal) need to land in a
review state instead of going straight to citizens. The new ``status``
column gates that — citizen-facing readers filter ``status='applied'``;
admin queue reads ``status='flagged'``.

Default ``'applied'`` preserves legacy semantics — every existing row
(set before the audit caught the over-tagging) keeps rendering until
the backfill script (Section E) reclassifies them.

The audit table's ``action`` CHECK constraint is widened to include
the new admin actions (``approved`` / ``rejected``) so /admin/badge-review
can record status changes through the existing audit pipeline.
"""

from __future__ import annotations

SQL_UP = r"""
ALTER TABLE agenda_item_badges
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'applied'
    CHECK (status IN ('applied', 'flagged', 'rejected'));

CREATE INDEX IF NOT EXISTS idx_agenda_item_badges_status_slug
    ON agenda_item_badges (status, city_id, badge_slug)
    WHERE status = 'flagged';

-- Widen the audit-action enum so admin status changes are recorded.
ALTER TABLE agenda_item_badges_audit
    DROP CONSTRAINT IF EXISTS agenda_item_badges_audit_action_check;
ALTER TABLE agenda_item_badges_audit
    ADD CONSTRAINT agenda_item_badges_audit_action_check
    CHECK (action IN ('added', 'removed', 'modified',
                      'flagged', 'approved', 'rejected'));
"""

SQL_DOWN = r"""
ALTER TABLE agenda_item_badges_audit
    DROP CONSTRAINT IF EXISTS agenda_item_badges_audit_action_check;
ALTER TABLE agenda_item_badges_audit
    ADD CONSTRAINT agenda_item_badges_audit_action_check
    CHECK (action IN ('added', 'removed', 'modified'));

DROP INDEX IF EXISTS idx_agenda_item_badges_status_slug;
ALTER TABLE agenda_item_badges DROP COLUMN IF EXISTS status;
"""
