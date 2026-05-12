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

-- 3. New columns on agenda_items
ALTER TABLE agenda_items
  ADD COLUMN extracted_facts        JSONB                       DEFAULT NULL,
  ADD COLUMN headline               TEXT                        DEFAULT NULL,
  ADD COLUMN why_it_matters         TEXT                        DEFAULT NULL,
  ADD COLUMN source_anchor          JSONB                       DEFAULT NULL,
  ADD COLUMN data_quality           data_quality_enum           DEFAULT NULL,
  ADD COLUMN data_debt_priority     data_debt_priority_enum     DEFAULT NULL,
  ADD COLUMN processing_status      processing_status_enum      DEFAULT 'pending',
  ADD COLUMN processing_attempts    INT                         DEFAULT 0,
  ADD COLUMN last_error_at          TIMESTAMPTZ                 DEFAULT NULL,
  ADD COLUMN last_error_message     TEXT                        DEFAULT NULL,
  ADD COLUMN score_overrides        JSONB                       DEFAULT NULL,
  ADD COLUMN ai_extraction_version  INT                         DEFAULT NULL,
  ADD COLUMN ai_rewrite_version     INT                         DEFAULT NULL,
  ADD COLUMN ai_confidence          TEXT                        DEFAULT NULL,
  ADD COLUMN backfill_session_id    UUID                        DEFAULT NULL,
  ADD CONSTRAINT chk_ai_confidence CHECK (
      ai_confidence IS NULL OR ai_confidence IN ('high', 'medium', 'low')
  ),
  ADD CONSTRAINT chk_headline_length CHECK (
      headline IS NULL OR length(headline) <= 60
  ),
  ADD CONSTRAINT chk_why_it_matters_length CHECK (
      why_it_matters IS NULL OR length(why_it_matters) <= 200
  );

-- 4. New column on municipalities
ALTER TABLE municipalities
  ADD COLUMN master_calendar_url TEXT DEFAULT NULL;

-- 5. Upgrade search vector function to cover v2 (summary) AND v3
-- (headline + why_it_matters) content fields so search remains reliable
-- across the transition. Decision #83.
--
-- Migration 001 already created agenda_items.search_vector, idx_agenda_items_search,
-- agenda_items_search_update() (title+description only), and agenda_items_search_trigger.
-- We REPLACE the function body to extend what gets indexed; column / index /
-- trigger are ensured to exist (idempotent DROP/CREATE in case they were lost).

CREATE OR REPLACE FUNCTION agenda_items_search_update() RETURNS trigger AS $$
BEGIN
  NEW.search_vector := to_tsvector('english',
    COALESCE(NEW.title, '')          || ' ' ||
    COALESCE(NEW.description, '')    || ' ' ||
    COALESCE(NEW.headline, '')       || ' ' ||
    COALESCE(NEW.why_it_matters, '') || ' ' ||
    COALESCE(NEW.summary, '')
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Ensure trigger exists (idempotent — safe even if migration 001 already created it).
DROP TRIGGER IF EXISTS agenda_items_search_trigger ON agenda_items;
CREATE TRIGGER agenda_items_search_trigger
    BEFORE INSERT OR UPDATE ON agenda_items
    FOR EACH ROW EXECUTE FUNCTION agenda_items_search_update();

-- One-time refresh so existing rows pick up the summary content.
-- (v3 fields headline / why_it_matters are NULL at this point;
-- COALESCE handles that. Migration 014 will replace this function
-- again to drop NEW.summary when the column itself is dropped.)
UPDATE agenda_items SET search_vector = to_tsvector('english',
  COALESCE(title, '') || ' ' ||
  COALESCE(description, '') || ' ' ||
  COALESCE(summary, '')
);

-- 6. New tables in dependency order

CREATE TABLE priority_badge_templates (
    slug                  TEXT PRIMARY KEY,
    name                  TEXT NOT NULL,
    description           TEXT NOT NULL,
    icon                  TEXT NOT NULL,
    kind                  TEXT NOT NULL CHECK (kind IN ('process', 'policy')),
    default_matcher_hints JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE priority_badges_config (
    id                     SERIAL PRIMARY KEY,
    city_id                INT NOT NULL REFERENCES municipalities(id) ON DELETE CASCADE,
    template_slug          TEXT NOT NULL REFERENCES priority_badge_templates(slug) ON DELETE CASCADE,
    name_override          TEXT,
    description_override   TEXT,
    matcher_hints_override JSONB,
    enabled                BOOLEAN NOT NULL DEFAULT TRUE,
    added_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    added_by               TEXT,
    notes                  TEXT,
    UNIQUE (city_id, template_slug)
);

-- Note: status TEXT NOT NULL DEFAULT 'applied' is the post-021 shape.
-- Migration 021 (refactor #2) added this column so LLM-only badge
-- suggestions could land at 'flagged' instead of being auto-applied to
-- citizen-facing surfaces. Baking the post-021 shape directly into 013
-- preserves the up→down→up cycle invariant: a 013-only rollback drops
-- the table, and 13's re-apply has to leave a schema with the same
-- columns the rest of the migration list expects to find. Migration 021
-- remains idempotent against an already-shipped DB (ADD COLUMN IF NOT
-- EXISTS) and is a no-op against a fresh install built from this 013 UP.
CREATE TABLE agenda_item_badges (
    id                SERIAL PRIMARY KEY,
    agenda_item_id    INT NOT NULL REFERENCES agenda_items(id) ON DELETE CASCADE,
    city_id           INT NOT NULL REFERENCES municipalities(id),
    badge_slug        TEXT NOT NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('process', 'policy')),
    confidence        NUMERIC(3, 2),
    source            TEXT NOT NULL CHECK (source IN ('deterministic', 'llm', 'both', 'manual')),
    matching_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    detected_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status            TEXT NOT NULL DEFAULT 'applied'
                        CHECK (status IN ('applied', 'flagged', 'rejected')),
    UNIQUE (agenda_item_id, badge_slug)
);

-- Note: agenda_item_id is nullable + ON DELETE SET NULL (post-016 shape).
-- Migration 016 originally relaxed this from NOT NULL/RESTRICT after the
-- pre-016 shape caused operational issues (deletes of agenda_items were
-- blocked while audit rows referenced them). Baking the post-016 shape
-- directly into 013 makes the migration cycle (down → up) reproduce the
-- correct shape, since 015 + 016 are not re-applied after a 013-only
-- rollback. Migration 016 remains idempotent against an already-shipped
-- DB and is a no-op against a fresh install built from this 013 UP.
--
-- The action CHECK is also the post-021 shape: refactor #2 added
-- 'flagged'/'approved'/'rejected' so /admin/badge-review can record
-- status changes through the existing audit pipeline. Same bake-in
-- reasoning as the status column above.
CREATE TABLE agenda_item_badges_audit (
    id              SERIAL PRIMARY KEY,
    agenda_item_id  INT REFERENCES agenda_items(id) ON DELETE SET NULL,
    badge_slug      TEXT NOT NULL,
    action          TEXT NOT NULL CHECK (action IN ('added', 'removed', 'modified',
                                                    'flagged', 'approved', 'rejected')),
    actor           TEXT,
    actor_role      TEXT NOT NULL CHECK (actor_role IN ('admin', 'cron', 'on_write')),
    reason          TEXT,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE city_score_floor_overrides (
    city_id                   INT NOT NULL REFERENCES municipalities(id),
    trigger_name              TEXT NOT NULL,
    override_threshold_amount NUMERIC,
    override_min_score        INT,
    reason                    TEXT,
    added_by                  TEXT,
    added_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (city_id, trigger_name)
);

CREATE TABLE ai_batches (
    id                 SERIAL PRIMARY KEY,
    anthropic_batch_id TEXT NOT NULL UNIQUE,
    stage              TEXT NOT NULL CHECK (stage IN ('stage1', 'stage2')),
    wave               TEXT NOT NULL,
    item_count         INT NOT NULL,
    submitted_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at       TIMESTAMPTZ,
    cost_usd           NUMERIC(10, 4),
    status             TEXT NOT NULL CHECK (
                         status IN ('submitted', 'in_progress', 'ended', 'failed', 'expired')
                       )
);

CREATE TABLE ai_batch_items (
    batch_id        INT NOT NULL REFERENCES ai_batches(id) ON DELETE CASCADE,
    agenda_item_id  INT NOT NULL REFERENCES agenda_items(id) ON DELETE CASCADE,
    custom_id       TEXT NOT NULL,
    result_status   TEXT CHECK (result_status IN ('succeeded', 'errored', 'expired')),
    PRIMARY KEY (batch_id, agenda_item_id)
);

CREATE TABLE mayoral_terms (
    id           SERIAL PRIMARY KEY,
    city_id      INT NOT NULL REFERENCES municipalities(id),
    mayor_name   TEXT NOT NULL,
    party        TEXT,
    term_start   DATE NOT NULL,
    term_end     DATE
);

-- Decision #91: DB-backed AI response cache (replaces file cache)
CREATE TABLE ai_response_cache (
    cache_key       TEXT PRIMARY KEY,
    model           TEXT NOT NULL,
    prompt_version  INT NOT NULL,
    response_json   JSONB NOT NULL,
    cached_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accessed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Decision #93: status-change audit (separate from agenda_item_badges_audit which is badge-only)
CREATE TABLE processing_status_audit (
    id              SERIAL PRIMARY KEY,
    agenda_item_id  INT NOT NULL REFERENCES agenda_items(id),
    from_status     processing_status_enum,
    to_status       processing_status_enum NOT NULL,
    action          TEXT NOT NULL,
    actor           TEXT,
    actor_role      TEXT NOT NULL CHECK (actor_role IN ('admin', 'cron', 'on_write')),
    reason          TEXT,
    payload         JSONB,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 7. Indexes

CREATE INDEX idx_agenda_items_processing_status
    ON agenda_items (processing_status)
    WHERE processing_status NOT IN ('completed', 'failed_permanent');

CREATE INDEX idx_agenda_items_extraction_version
    ON agenda_items (ai_extraction_version);

CREATE INDEX idx_agenda_items_rewrite_version
    ON agenda_items (ai_rewrite_version);

CREATE INDEX idx_agenda_items_backfill_session
    ON agenda_items (backfill_session_id)
    WHERE backfill_session_id IS NOT NULL;

CREATE INDEX idx_agenda_items_data_debt
    ON agenda_items (data_debt_priority, meeting_id)
    WHERE data_quality IS NOT NULL AND data_quality != 'ok';

CREATE INDEX idx_agenda_items_counterparty_trgm
    ON agenda_items USING gin ((extracted_facts->>'counterparty') gin_trgm_ops);

CREATE INDEX idx_agenda_item_badges_slug
    ON agenda_item_badges (badge_slug, kind);

CREATE INDEX idx_agenda_item_badges_item
    ON agenda_item_badges (agenda_item_id);

-- Post-021 shape: partial index for the admin review queue.
CREATE INDEX idx_agenda_item_badges_status_slug
    ON agenda_item_badges (status, city_id, badge_slug)
    WHERE status = 'flagged';

CREATE INDEX idx_priority_badges_config_city
    ON priority_badges_config (city_id) WHERE enabled = TRUE;

CREATE INDEX idx_badge_audit_recent
    ON agenda_item_badges_audit (occurred_at DESC, badge_slug, action)
    WHERE actor_role = 'admin';

CREATE INDEX idx_ai_batches_status
    ON ai_batches (status, submitted_at DESC)
    WHERE status IN ('submitted', 'in_progress');

CREATE INDEX idx_mayoral_terms_city
    ON mayoral_terms (city_id, term_start DESC);

-- Decision #92: composite index for category landing pages (significance gate is render-time)
CREATE INDEX idx_agenda_item_badges_city_slug_conf
    ON agenda_item_badges (city_id, badge_slug, confidence DESC);

-- Cache lookup hot path
CREATE INDEX idx_ai_response_cache_accessed
    ON ai_response_cache (accessed_at);

-- Audit log lookup by item
CREATE INDEX idx_processing_status_audit_item
    ON processing_status_audit (agenda_item_id, occurred_at DESC);

-- Conflict resolution queue: open items only, sorted recent-first
CREATE INDEX idx_processing_status_audit_open_conflicts
    ON processing_status_audit (occurred_at DESC)
    WHERE action IN ('accept_stage1', 'accept_stage2', 're_prompted', 'edit_stage1');

-- 8. Materialized view for category-page volume timelines (with consent split, decision #68)
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

-- 9. Seed: process badge templates (Section 4.2)
INSERT INTO priority_badge_templates (slug, name, description, icon, kind) VALUES
  ('hidden_on_consent', 'Hidden on consent',
   'Item the AI judged should NOT be on consent (high public interest), but is on consent anyway.',
   '💰', 'process'),
  ('sole_source', 'Sole-source / no-bid',
   'Procurement that bypassed competitive bidding.',
   '🤝', 'process'),
  ('legal_settlement', 'Legal settlement',
   'Item resolves a legal claim — often closed-session-resolved.',
   '⚖️', 'process'),
  ('split_vote', 'Split vote',
   'Council was not unanimous — at least one no or abstain.',
   '🪧', 'process'),
  ('contested', 'Contested',
   'Genuinely divided — 2+ dissenters and >20% of votes cast.',
   '🔥', 'process'),
  ('amends_prior_contract', 'Amends prior contract',
   'Modifies a prior contract with this vendor; may or may not increase total cost.',
   '↩️', 'process'),
  ('emergency_action', 'Emergency action',
   'Declared emergency or emergency procurement; usually skips standard procurement rules.',
   '🚨', 'process');

-- 10. Seed: Birmingham 2026 policy badge templates (Section 5.2)
INSERT INTO priority_badge_templates
  (slug, name, description, icon, kind, default_matcher_hints) VALUES
  (
    'blight_accountability',
    'Blight Accountability',
    'Blighted property registration, demolition orders, tax penalties on neglected property, BPRA enforcement.',
    '🏚️',
    'policy',
    '{
      "keywords": ["blight", "blighted", "blighted property", "BPRA", "Blighted Property Registration",
                   "condemnation order", "unsafe structure", "nuisance abatement", "demolition order",
                   "tax penalty for neglect", "code enforcement"],
      "action_types": ["demolition", "weed_abatement"],
      "topics": ["blight"],
      "excluded_action_types": ["liquor_license", "proclamation", "appointment_advisory", "right_of_way"],
      "min_significance": 3
    }'::jsonb
  ),
  (
    'housing_stability',
    'Housing Stability',
    'Housing Trust Fund allocations, affordable-housing initiatives, eviction protections, tenant rights.',
    '🏠',
    'policy',
    '{
      "keywords": ["housing trust", "affordable housing", "eviction protection", "tenant rights",
                   "down payment assistance", "rental assistance", "low income housing",
                   "fair housing", "homestead exemption"],
      "action_types": ["appropriation", "ordinance"],
      "topics": ["housing"],
      "excluded_action_types": ["liquor_license", "proclamation", "appointment_advisory"],
      "min_significance": 3
    }'::jsonb
  ),
  (
    'property_recovery',
    'Property Recovery',
    'Land Bank Act acquisitions, tax-delinquency reclamation, derelict-parcel return to productive use.',
    '🏗️',
    'policy',
    '{
      "keywords": ["Land Bank", "Jefferson County Land Bank", "tax delinquent", "tax sale",
                   "redevelopment authority", "quiet title", "derelict parcel", "tax foreclosure"],
      "action_types": ["resolution", "ordinance"],
      "topics": ["land", "property"],
      "excluded_action_types": ["liquor_license", "proclamation", "appointment_advisory"],
      "min_significance": 3
    }'::jsonb
  ),
  (
    'public_safety_tech_privacy',
    'Public-Safety Tech & Privacy',
    'Surveillance deployments, police technology, body cameras, predictive policing, facial recognition, ALPRs.',
    '🛡️',
    'policy',
    '{
      "keywords": ["Flock", "ALPR", "license plate reader", "body cam", "body-worn camera",
                   "predictive policing", "facial recognition", "surveillance camera",
                   "audit log", "gunshot detection", "ShotSpotter", "Axon"],
      "action_types": ["contract_award", "contract_amendment", "ordinance", "appropriation"],
      "topics": ["public_safety"],
      "excluded_action_types": ["liquor_license", "proclamation", "appointment_advisory"],
      "min_significance": 3
    }'::jsonb
  );

-- 11. Seed: opt Birmingham into all 4 policy badges (Section 5.2)
INSERT INTO priority_badges_config (city_id, template_slug, enabled, added_by, notes)
SELECT m.id, t.slug, TRUE, 'migration_013', 'BHM 2026 v1 priority list'
FROM municipalities m
CROSS JOIN priority_badge_templates t
WHERE m.slug = 'birmingham'
  AND t.slug IN ('blight_accountability', 'housing_stability',
                 'property_recovery', 'public_safety_tech_privacy');

-- 12. Seed: Birmingham mayoral terms (for SVG overlay on category landing pages)
INSERT INTO mayoral_terms (city_id, mayor_name, party, term_start, term_end)
SELECT id, 'William Bell', 'Democrat',  '2010-01-26'::date, '2017-11-28'::date FROM municipalities WHERE slug = 'birmingham'
UNION ALL
SELECT id, 'Randall Woodfin', 'Democrat', '2017-11-28'::date, NULL FROM municipalities WHERE slug = 'birmingham';
"""

SQL_DOWN = r"""
DROP MATERIALIZED VIEW IF EXISTS mv_badge_volume_monthly;

-- Restore Migration 001's search function (title + description only)
CREATE OR REPLACE FUNCTION agenda_items_search_update() RETURNS trigger AS $$
BEGIN
  NEW.search_vector := to_tsvector('english',
    COALESCE(NEW.title, '') || ' ' || COALESCE(NEW.description, '')
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TABLE IF EXISTS processing_status_audit;
DROP TABLE IF EXISTS ai_response_cache;
DROP TABLE IF EXISTS mayoral_terms;
DROP TABLE IF EXISTS ai_batch_items;
DROP TABLE IF EXISTS ai_batches;
DROP TABLE IF EXISTS city_score_floor_overrides;
DROP TABLE IF EXISTS agenda_item_badges_audit;
DROP TABLE IF EXISTS agenda_item_badges;
DROP TABLE IF EXISTS priority_badges_config;
DROP TABLE IF EXISTS priority_badge_templates;

ALTER TABLE municipalities DROP COLUMN IF EXISTS master_calendar_url;

ALTER TABLE agenda_items
  DROP CONSTRAINT IF EXISTS chk_why_it_matters_length,
  DROP CONSTRAINT IF EXISTS chk_headline_length,
  DROP CONSTRAINT IF EXISTS chk_ai_confidence,
  DROP COLUMN IF EXISTS backfill_session_id,
  DROP COLUMN IF EXISTS ai_confidence,
  DROP COLUMN IF EXISTS ai_rewrite_version,
  DROP COLUMN IF EXISTS ai_extraction_version,
  DROP COLUMN IF EXISTS score_overrides,
  DROP COLUMN IF EXISTS last_error_message,
  DROP COLUMN IF EXISTS last_error_at,
  DROP COLUMN IF EXISTS processing_attempts,
  DROP COLUMN IF EXISTS processing_status,
  DROP COLUMN IF EXISTS data_debt_priority,
  DROP COLUMN IF EXISTS data_quality,
  DROP COLUMN IF EXISTS source_anchor,
  DROP COLUMN IF EXISTS why_it_matters,
  DROP COLUMN IF EXISTS headline,
  DROP COLUMN IF EXISTS extracted_facts;

DROP TYPE IF EXISTS processing_status_enum;
DROP TYPE IF EXISTS data_debt_priority_enum;
DROP TYPE IF EXISTS data_quality_enum;
-- pg_trgm extension intentionally left in place.
"""
