"""Migration 033 — meetings.is_hidden + partial index + MV refresh.

Adds a soft-hide flag so operator-published "test" clips (Granicus shorts
with no chapter markers, etc.) can be suppressed from citizen surfaces
without losing the row. Ingest preserves the flag because
``_upsert_meetings`` only writes the columns it enumerates (services/
ingest.py:159), and ``is_hidden`` isn't one of them.

Partial index on (municipality_id, meeting_date DESC) WHERE is_hidden=FALSE
covers the hot city-landing query pattern without paying for hidden rows.

``mv_badge_volume_monthly`` is rebuilt to add the ``m.is_hidden = FALSE``
predicate to its existing JOIN to ``meetings`` (which already supplied
``municipality_id`` and ``meeting_date``). Category-landing volume
timelines now exclude hidden meetings. WITH NO DATA matches migration
022's shape; the next ``refresh_backfill_ratio_mv`` cron (04:30 CT daily)
repopulates. Deploy step applies the refresh manually so prod doesn't
show empty category pages between deploy and 04:30 CT.

Spec: docs/superpowers/specs/2026-05-20-hide-non-real-meetings-design.md
"""

from __future__ import annotations


SQL_UP = r"""
ALTER TABLE meetings
    ADD COLUMN IF NOT EXISTS is_hidden BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS hidden_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS hidden_by INTEGER NULL REFERENCES admin_users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_meetings_public_visible
    ON meetings (municipality_id, meeting_date DESC)
    WHERE is_hidden = FALSE;

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
  AND m.is_hidden = FALSE
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
  AND aib.status = 'applied'
GROUP BY m.municipality_id, aib.badge_slug, month
WITH NO DATA;

CREATE UNIQUE INDEX ON mv_badge_volume_monthly (city_id, badge_slug, month);

DROP INDEX IF EXISTS idx_meetings_public_visible;

ALTER TABLE meetings
    DROP COLUMN IF EXISTS hidden_by,
    DROP COLUMN IF EXISTS hidden_at,
    DROP COLUMN IF EXISTS is_hidden;
"""
