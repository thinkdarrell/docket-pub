"""Migration 022 — mv_badge_volume_monthly filters on status='applied'.

Counterpart to Section B (refactor #2) — the volume-timeline materialized
view now reflects only badges visible to citizens. Without this filter,
the MV would still count flagged (admin-review-only) rows in its
n_items / n_consent / n_substantive / total_dollars aggregates, making
the timeline disagree with the base-table readers that already filter
on status='applied' (Tasks B1/B2 — list_items_by_badge, category_kpis,
badge_volume_year, badge_volume_recent).

DROP + CREATE rather than CREATE OR REPLACE because PostgreSQL doesn't
support OR REPLACE on materialized views. The unique index is recreated
explicitly — badge_volume_series and CONCURRENTLY refreshes both need it.

WITH NO DATA matches migration 013's original shape; the cron worker
refreshes the MV on its nightly cycle (or run-once via
``python -m docket.worker.scheduler --run-once refresh_volume_mv`` if
the worker grows that task). Section E's backfill explicitly refreshes
the MV after the reclassification UPDATE lands, so the citizen-facing
timeline matches the new state without waiting for the cron cycle.
"""

from __future__ import annotations

SQL_UP = r"""
DROP MATERIALIZED VIEW IF EXISTS mv_badge_volume_monthly;
CREATE MATERIALIZED VIEW mv_badge_volume_monthly AS
SELECT
    m.municipality_id AS city_id,
    aib.badge_slug,
    DATE_TRUNC('month', m.meeting_date)::date AS month,
    COUNT(*)                                          AS n_items,
    COUNT(*) FILTER (WHERE ai.is_consent = TRUE)     AS n_consent,
    COUNT(*) FILTER (WHERE ai.is_consent = FALSE)    AS n_substantive,
    COALESCE(SUM(ai.dollars_amount), 0)              AS total_dollars
FROM agenda_item_badges aib
JOIN agenda_items ai ON ai.id = aib.agenda_item_id
JOIN meetings m ON m.id = ai.meeting_id
WHERE aib.confidence >= 0.6
  AND aib.status = 'applied'
GROUP BY m.municipality_id, aib.badge_slug, month
WITH NO DATA;

CREATE UNIQUE INDEX ON mv_badge_volume_monthly (city_id, badge_slug, month);
"""

SQL_DOWN = r"""
DROP MATERIALIZED VIEW IF EXISTS mv_badge_volume_monthly;
CREATE MATERIALIZED VIEW mv_badge_volume_monthly AS
SELECT
    m.municipality_id AS city_id,
    aib.badge_slug,
    DATE_TRUNC('month', m.meeting_date)::date AS month,
    COUNT(*)                                          AS n_items,
    COUNT(*) FILTER (WHERE ai.is_consent = TRUE)     AS n_consent,
    COUNT(*) FILTER (WHERE ai.is_consent = FALSE)    AS n_substantive,
    COALESCE(SUM(ai.dollars_amount), 0)              AS total_dollars
FROM agenda_item_badges aib
JOIN agenda_items ai ON ai.id = aib.agenda_item_id
JOIN meetings m ON m.id = ai.meeting_id
WHERE aib.confidence >= 0.6
GROUP BY m.municipality_id, aib.badge_slug, month
WITH NO DATA;

CREATE UNIQUE INDEX ON mv_badge_volume_monthly (city_id, badge_slug, month);
"""
