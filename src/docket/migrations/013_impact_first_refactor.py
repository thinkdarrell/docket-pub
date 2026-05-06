"""Impact-First Refactor — additive schema.

Adds new columns to agenda_items and municipalities, ten new tables
(agenda_item_badges, priority_badge_templates, priority_badges_config,
agenda_item_badges_audit, city_score_floor_overrides, ai_batches,
ai_batch_items, mayoral_terms, ai_response_cache, processing_status_audit),
the search_vector tsvector + trigger, indexes, the mv_badge_volume_monthly
materialized view, and seed data for process badges, BHM policy badges,
and BHM mayoral terms.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md

Strictly additive — no destructive changes. v2 pipeline + UI keep
running unchanged after this migration applies.
"""

SQL_UP = r"""
-- 1. Required extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. Enums
CREATE TYPE data_quality_enum AS ENUM (
    'ok', 'no_text_layer', 'no_agenda_text', 'empty', 'foreign_language'
);

CREATE TYPE data_debt_priority_enum AS ENUM ('low', 'normal', 'high');

CREATE TYPE processing_status_enum AS ENUM (
    'pending', 'procedural_skipped', 'data_quality_skipped',
    'extracted', 'rewritten', 'badged', 'completed',
    'failed_retry', 'failed_permanent', 'cross_stage_conflict'
);
"""

SQL_DOWN = r"""
DROP TYPE IF EXISTS processing_status_enum;
DROP TYPE IF EXISTS data_debt_priority_enum;
DROP TYPE IF EXISTS data_quality_enum;
-- pg_trgm extension intentionally left in place.
"""
