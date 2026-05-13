"""Migration 025 — mv_city_backfill_ratio materialized view.

Spec: docs/superpowers/specs/2026-05-12-category-landing-redesign-design.md
      Section 2 (backfill banner) + Query/service changes.

Caches the fraction of a city's indexable agenda items that have
reached v3-completed state. Read by the category-landing volume-
timeline partial to decide which backfill-banner copy variant to
render (no banner when ratio >= 0.95, "X% processed" between 0.05
and 0.95, "most history still indexing" below 0.05).

Refreshed daily by the cron worker (worker/tasks.py — new step in
the existing scheduler). Concurrent refresh requires a UNIQUE INDEX
on the MV (added below).

NULLIF on the denominator guards against a newly-onboarded
municipality with zero indexable items (would otherwise be division-
by-zero); the route handler treats NULL as the conservative
"< 5%" banner state.
"""
from __future__ import annotations


SQL_UP = r"""
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_city_backfill_ratio AS
SELECT
    mu.id AS city_id,
    COUNT(*) FILTER (
        WHERE ai.processing_status = 'completed'
          AND ai.ai_rewrite_version = 3
    )::numeric
    / NULLIF(
        COUNT(*) FILTER (
            WHERE m.meeting_date < CURRENT_DATE
              AND ai.processing_status <> 'failed_permanent'
        ),
        0
    ) AS ratio,
    NOW() AS computed_at
FROM municipalities mu
LEFT JOIN meetings m      ON m.municipality_id = mu.id
LEFT JOIN agenda_items ai ON ai.meeting_id = m.id
GROUP BY mu.id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_city_backfill_ratio_city_id
    ON mv_city_backfill_ratio (city_id);
"""

SQL_DOWN = r"""
DROP MATERIALIZED VIEW IF EXISTS mv_city_backfill_ratio;
"""
