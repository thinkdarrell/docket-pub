"""Migration 016 — relax agenda_item_badges_audit FK to ON DELETE SET NULL.

Migration 013 created agenda_item_badges_audit with
agenda_item_id INT NOT NULL REFERENCES agenda_items(id) — defaulting to
RESTRICT semantics, which means agenda_items deletes are BLOCKED while
audit rows reference them. Audit tables conventionally outlive their
referent entities; this migration aligns the schema with that
convention so the LEFT JOIN in query.list_badge_audit_log becomes
load-bearing for real and operators can prune agenda_items without
hitting FK violations.

Decision authored 2026-05-10 by user as part of the G3 review packet
(Decision 1 = option (a); Decision 2 = slot 016 for this fix, slot 017
held for G2's pending requires_manual_review column).

After this migration:
- agenda_item_id becomes nullable.
- ON DELETE SET NULL preserves the audit row with a NULL
  agenda_item_id when the referenced item is deleted.
- The helper's LEFT JOIN now correctly returns NULL item_title /
  meeting_date / municipality_* for orphaned audit rows.

Note: existing audit rows with non-NULL agenda_item_id are unchanged.
"""

from __future__ import annotations


SQL_UP = r"""
-- Drop the existing RESTRICT FK and recreate with ON DELETE SET NULL.
-- Postgres requires the column be nullable to allow SET NULL semantics.
ALTER TABLE agenda_item_badges_audit
    DROP CONSTRAINT agenda_item_badges_audit_agenda_item_id_fkey;

ALTER TABLE agenda_item_badges_audit
    ALTER COLUMN agenda_item_id DROP NOT NULL;

ALTER TABLE agenda_item_badges_audit
    ADD CONSTRAINT agenda_item_badges_audit_agenda_item_id_fkey
        FOREIGN KEY (agenda_item_id)
        REFERENCES agenda_items(id)
        ON DELETE SET NULL;
"""


SQL_DOWN = r"""
-- Reverse: enforce NOT NULL again and restore RESTRICT semantics.
-- WARNING: any audit rows with NULL agenda_item_id (created after the
-- UP migration if items were deleted) will block this rollback. Clean
-- those rows out first if you need to roll back:
--   DELETE FROM agenda_item_badges_audit WHERE agenda_item_id IS NULL;
ALTER TABLE agenda_item_badges_audit
    DROP CONSTRAINT agenda_item_badges_audit_agenda_item_id_fkey;

ALTER TABLE agenda_item_badges_audit
    ALTER COLUMN agenda_item_id SET NOT NULL;

ALTER TABLE agenda_item_badges_audit
    ADD CONSTRAINT agenda_item_badges_audit_agenda_item_id_fkey
        FOREIGN KEY (agenda_item_id)
        REFERENCES agenda_items(id);
"""
