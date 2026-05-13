"""Migration 026 — mv_city_backfill_ratio: count v3+ rewrites, not just v3.

Follow-up to migration 025. The MV originally filtered on
``ai_rewrite_version = 3`` because that was the current rewrite prompt
version when migration 025 shipped. ``ITEM_REWRITE_PROMPT_VERSION``
has since been bumped to 4 (see ``src/docket/ai/rewrite.py`` and
migration 020's headline-cap raise that triggered the bump), so the
MV is silently undercounting v4-completed rows as "not yet processed."

The smart-brevity schema (``headline`` + ``why_it_matters`` +
``extracted_facts``) landed at v3; v4 is a prompt iteration on the
same column shape — same rendering path on the citizen side, same
"this item is backfilled" semantics on the banner side. Switching the
predicate to ``>= 3`` keeps the contract version-bump-resilient.

Postgres has no ``CREATE OR REPLACE MATERIALIZED VIEW``, so this is a
DROP-and-recreate (the unique index dependency drops with the MV).
The whole migration runs in a single transaction (the runner's
default), so concurrent readers never see a missing relation. We also
refresh inline so the category-landing banner reflects the corrected
denominator/numerator immediately after deploy — without this, the
cron worker's daily refresh would be the first time the corrected
values land.
"""

from __future__ import annotations


SQL_UP = r"""
DROP MATERIALIZED VIEW IF EXISTS mv_city_backfill_ratio;

CREATE MATERIALIZED VIEW mv_city_backfill_ratio AS
SELECT
    mu.id AS city_id,
    COUNT(*) FILTER (
        WHERE ai.processing_status = 'completed'
          AND ai.ai_rewrite_version IS NOT NULL
          AND ai.ai_rewrite_version >= 3
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

CREATE UNIQUE INDEX idx_mv_city_backfill_ratio_city_id
    ON mv_city_backfill_ratio (city_id);

REFRESH MATERIALIZED VIEW mv_city_backfill_ratio;
"""

SQL_DOWN = r"""
DROP MATERIALIZED VIEW IF EXISTS mv_city_backfill_ratio;

CREATE MATERIALIZED VIEW mv_city_backfill_ratio AS
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

CREATE UNIQUE INDEX idx_mv_city_backfill_ratio_city_id
    ON mv_city_backfill_ratio (city_id);

REFRESH MATERIALIZED VIEW mv_city_backfill_ratio;
"""
