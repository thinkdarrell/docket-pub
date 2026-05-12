"""Migration 023 — add ``'withdrawn'`` to processing_status_enum.

Refactor #2 follow-up. Items the council formally withdraws, defers,
or postpones aren't substantive (no action taken) but they aren't
"procedural" in the same sense as Pledge of Allegiance / Roll Call.
Lumping them under ``'procedural_skipped'`` pollutes the procedural-
queue admin view with hundreds of rows that don't belong there.

This migration adds a new status value the Wave 0 classifier routes
the WITHDRAWN/DEFERRED/POSTPONED family to. PR #20 had used
``'procedural_skipped'`` as a stopgap; this migration plus the Wave 0
split corrects the semantics.

Idempotent — ``ADD VALUE IF NOT EXISTS`` is safe to re-run. SQL_DOWN
is a no-op because Postgres can't remove enum values without
recreating the type and rewriting every column that uses it, which
isn't worth the risk for a one-line addition. The value is also baked
into migration 013's ``CREATE TYPE`` so fresh installs include it.
"""

from __future__ import annotations

SQL_UP = r"""
ALTER TYPE processing_status_enum ADD VALUE IF NOT EXISTS 'withdrawn';
"""

SQL_DOWN = r"""
-- No-op: dropping an enum value requires recreating the type +
-- rewriting every column reference. The value is harmless when unused.
SELECT 1;
"""
