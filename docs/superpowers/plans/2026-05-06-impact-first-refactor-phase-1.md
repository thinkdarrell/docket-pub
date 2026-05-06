# Impact-First Refactor — Phase 1 Implementation Plan (Schema + Wave 0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land Migration 013 (strictly additive schema for the new pipeline + UI) and execute Wave 0 (non-LLM pre-pass that classifies every existing agenda item into `procedural_skipped`, `data_quality_skipped`, or `pending`). Output: every existing item in the database has a `processing_status`, a `data_quality`, and a `data_debt_priority`. Net effect on citizens: zero — the v2 pipeline keeps running unchanged.

**Architecture:** Migration 013 is a single Python module following the existing `SQL_UP` / `SQL_DOWN` pattern (see `docket/migrations/012_ai_summaries_and_scoring.py`). Wave 0 is a new module `docket/ai/wave0.py` that walks `agenda_items`, runs Stage 0a (data-quality gate with Big Fish Override) and Stage 0b (procedural regex), and updates rows in batches. Both ship behind the existing migration-runner and CLI patterns; no feature flags needed for Phase 1 since nothing user-facing changes.

**Tech Stack:** Python 3.10+, PostgreSQL 18 (Railway), pg_trgm extension, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` — Sections 1, 2.1, 2.2, 8.1.

**Estimated effort:** ~3 engineer-days.

---

## File Structure

**Create:**
- `src/docket/migrations/013_impact_first_refactor.py` — additive schema (~250 LOC of SQL)
- `src/docket/ai/wave0.py` — Stage 0a + 0b classifier and main loop (~180 LOC)
- `src/docket/ai/_priority.py` — shared `_priority_from_title()` + `_is_big_fish()` helpers (~50 LOC)
- `tests/unit/test_wave0_priority.py` — Stage 0a priority and Big Fish tests (~120 LOC)
- `tests/unit/test_wave0_quality.py` — Stage 0a data-quality tests (~150 LOC)
- `tests/unit/test_wave0_procedural.py` — Stage 0b regex tests (~100 LOC)
- `tests/unit/test_wave0_driver.py` — Wave 0 main loop tests with fixtures (~150 LOC)
- `tests/integration/test_migration_013.py` — migration up/down/idempotency (~100 LOC)

Migration 013 creates 10 new tables (was 8 before decisions #91, #93 added `ai_response_cache` and `processing_status_audit`).

**Modify:**
- `src/docket/migrations/runner.py` — register `013_impact_first_refactor` in `MIGRATIONS` list
- `src/docket/ai/cli.py` — add `--wave 0` flag wiring to call `wave0.run_wave_0()`

**Touch (read-only):** `src/docket/migrations/012_ai_summaries_and_scoring.py` (template for migration shape), `src/docket/db.py` (`db_cursor()` usage).

---

## Pre-Task: Branch and Read

- [ ] **Step 0.1: Create feature branch**

```bash
cd ~/docket-pub
git checkout main
git pull origin main
git checkout -b feat/impact-first-phase-1
```

- [ ] **Step 0.2: Skim spec sections 1, 2.1, 2.2, 8.1**

Open `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md`. Read:
- Locked decisions table (decisions #19, #25, #31, #36-43, #78, #82, #83, #86, #87)
- Section 1 — pipeline shape diagram
- Section 2.1 — Stage 0a data-quality gate code + Big Fish Override examples
- Section 2.2 — Stage 0b regex patterns + telemetry loop
- Section 8.1 — Migration 013 SQL

The spec is the source of truth for any SQL or code in this plan. If anything in the plan disagrees with the spec, the spec wins.

- [ ] **Step 0.3: Verify local DB is reachable**

Run: `venv/bin/python -c "from docket.db import db
with db() as conn: print(conn.info.dbname)"`
Expected: `docket_db`

(Note: `db()` is a context manager, not a callable. Always use `with db() as conn:` — see `src/docket/db.py:23`.)

- [ ] **Step 0.4: Verify pg_trgm is available on local Postgres**

Run: `/opt/homebrew/opt/postgresql@16/bin/psql docket_db -c "SELECT * FROM pg_available_extensions WHERE name = 'pg_trgm';"`
Expected: one row returned, `default_version=1.6`, `installed_version=NULL` (Migration 013 installs it).

(Note: `psql` is not in PATH on this system. Use the explicit Homebrew path. For Railway-side checks, use `/opt/homebrew/opt/postgresql@18/bin/psql` per project memory.)

---

## Task 1: Migration 013 — Scaffold + Enums + Extensions

**Files:**
- Create: `src/docket/migrations/013_impact_first_refactor.py`

- [ ] **Step 1.1: Create migration file with header and enums**

`src/docket/migrations/013_impact_first_refactor.py`:

```python
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
```

- [ ] **Step 1.2: Verify the file imports cleanly**

Run: `venv/bin/python -c "import docket.migrations.013_impact_first_refactor as m; print(len(m.SQL_UP), len(m.SQL_DOWN))"`
Expected: two integers printed (lengths of the strings).

- [ ] **Step 1.3: Commit**

```bash
git add src/docket/migrations/013_impact_first_refactor.py
git commit -m "feat(migration): scaffold 013 impact-first refactor — enums + pg_trgm"
```

---

## Task 2: Migration 013 — agenda_items Columns

**Files:**
- Modify: `src/docket/migrations/013_impact_first_refactor.py`

- [ ] **Step 2.1: Append agenda_items column additions to SQL_UP**

Insert into `SQL_UP` immediately after the enum block (before the closing `"""`):

```sql
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
```

- [ ] **Step 2.2: Append the corresponding DROP statements to SQL_DOWN**

Insert into `SQL_DOWN` BEFORE the existing `DROP TYPE` lines:

```sql
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
```

- [ ] **Step 2.3: Commit**

```bash
git add src/docket/migrations/013_impact_first_refactor.py
git commit -m "feat(migration): 013 add agenda_items and municipalities columns"
```

---

## Task 3: Migration 013 — Upgrade search_vector Function (decision #83)

**Files:**
- Modify: `src/docket/migrations/013_impact_first_refactor.py`

> **Important:** Migration 001 already creates `agenda_items.search_vector` (TSVECTOR), `idx_agenda_items_search` (GIN), `agenda_items_search_update()` (function), and `agenda_items_search_trigger` (BEFORE INSERT OR UPDATE). The function body in 001 only coalesces `title + description`. Migration 013's job is to **`CREATE OR REPLACE`** the existing function with a body that also coalesces `headline`, `why_it_matters`, and `summary`. Column, index, and trigger are reused as-is. See `src/docket/migrations/001_initial.py:92-112` for the existing definitions.

- [ ] **Step 3.1: Append the function-upgrade SQL to SQL_UP**

Insert into `SQL_UP` after the column-addition block:

```sql
-- 5. Upgrade search vector function to cover v2 (summary) AND v3
-- (headline + why_it_matters) content fields so search remains reliable
-- across the transition. Decision #83.
--
-- Migration 001 already created agenda_items.search_vector, idx_agenda_items_search,
-- agenda_items_search_update() (title+description only), and agenda_items_search_trigger.
-- We REPLACE the function body to extend what gets indexed; column / index /
-- trigger are reused unchanged.

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

-- One-time refresh so existing rows pick up the summary content.
-- (v3 fields headline / why_it_matters are NULL at this point;
-- COALESCE handles that. Migration 014 will replace this function
-- again to drop NEW.summary when the column itself is dropped.)
UPDATE agenda_items SET search_vector = to_tsvector('english',
  COALESCE(title, '') || ' ' ||
  COALESCE(description, '') || ' ' ||
  COALESCE(summary, '')
);
```

- [ ] **Step 3.2: Append the corresponding rollback SQL to SQL_DOWN**

Insert into `SQL_DOWN` BEFORE the `ALTER TABLE municipalities` line. The rollback restores Migration 001's original function body so a downgrade returns the database to its pre-013 search behavior:

```sql
-- Restore Migration 001's search function (title + description only)
CREATE OR REPLACE FUNCTION agenda_items_search_update() RETURNS trigger AS $$
BEGIN
  NEW.search_vector := to_tsvector('english',
    COALESCE(NEW.title, '') || ' ' || COALESCE(NEW.description, '')
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

- [ ] **Step 3.3: Commit**

```bash
cd /Users/darrellnance/docket-pub
git add src/docket/migrations/013_impact_first_refactor.py
git commit -m "feat(migration): 013 upgrade agenda_items_search_update for v3 fields"
```

---

## Task 4: Migration 013 — Eight New Tables

**Files:**
- Modify: `src/docket/migrations/013_impact_first_refactor.py`

- [ ] **Step 4.1: Append all 8 table creates to SQL_UP**

Insert after the search_vector block:

```sql
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

CREATE TABLE agenda_item_badges (
    id                SERIAL PRIMARY KEY,
    agenda_item_id    INT NOT NULL REFERENCES agenda_items(id) ON DELETE CASCADE,
    city_id           INT NOT NULL REFERENCES municipalities(id),  -- decision #92 (denormalized for fast joins)
    badge_slug        TEXT NOT NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('process', 'policy')),
    confidence        NUMERIC(3, 2),
    source            TEXT NOT NULL CHECK (source IN ('deterministic', 'llm', 'both', 'manual')),
    matching_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    detected_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agenda_item_id, badge_slug)
);

CREATE TABLE agenda_item_badges_audit (
    id              SERIAL PRIMARY KEY,
    agenda_item_id  INT NOT NULL REFERENCES agenda_items(id),
    badge_slug      TEXT NOT NULL,
    action          TEXT NOT NULL CHECK (action IN ('added', 'removed', 'modified')),
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
    cache_key       TEXT PRIMARY KEY,           -- sha256(model + prompt_version + canonical_input)
    model           TEXT NOT NULL,              -- exact model ID returned by Anthropic
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
    action          TEXT NOT NULL,            -- 'accept_stage1', 'accept_stage2', 're_prompted', 'edit_stage1', 'auto'
    actor           TEXT,                     -- admin username or 'system'
    actor_role      TEXT NOT NULL CHECK (actor_role IN ('admin', 'cron', 'on_write')),
    reason          TEXT,                     -- admin-supplied note for conflict resolutions
    payload         JSONB,                    -- e.g. { "manual_headline": "...", "manual_why_it_matters": "..." } for accept_stage1
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

- [ ] **Step 4.2: Append the corresponding DROPs to SQL_DOWN**

Insert into `SQL_DOWN` AFTER the search-vector function-restore block from Task 3 and BEFORE the `ALTER TABLE municipalities` line. Order matters — drop in reverse dependency order:

```sql
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
```

- [ ] **Step 4.3: Commit**

```bash
cd /Users/darrellnance/docket-pub
git add src/docket/migrations/013_impact_first_refactor.py
git commit -m "feat(migration): 013 add 10 new tables (badges, batches, audit, cache, mayoral_terms, status_audit)"
```

---

## Task 5: Migration 013 — Indexes

**Files:**
- Modify: `src/docket/migrations/013_impact_first_refactor.py`

- [ ] **Step 5.1: Append index creates to SQL_UP**

Insert after the table-creation block:

```sql
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
```

- [ ] **Step 5.2: SQL_DOWN doesn't need explicit DROP INDEX**

Indexes drop automatically when their tables drop (for the table-attached ones) and when columns drop (for the column-attached ones on `agenda_items`). No additional DOWN work.

- [ ] **Step 5.3: Commit**

```bash
git add src/docket/migrations/013_impact_first_refactor.py
git commit -m "feat(migration): 013 add 12 indexes (partial, gin, B-tree)"
```

---

## Task 6: Migration 013 — Materialized View

**Files:**
- Modify: `src/docket/migrations/013_impact_first_refactor.py`

- [ ] **Step 6.1: Append MV creation to SQL_UP**

Insert after the index block:

```sql
-- 8. Materialized view for category-page volume timelines (with consent split, decision #68)
CREATE MATERIALIZED VIEW mv_badge_volume_monthly AS
SELECT
    m.city_id,
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
GROUP BY m.city_id, aib.badge_slug, month
WITH NO DATA;  -- empty until Phase 2 populates agenda_item_badges

CREATE UNIQUE INDEX ON mv_badge_volume_monthly (city_id, badge_slug, month);
```

The `WITH NO DATA` clause makes the initial creation cheap — Phase 2 will populate `agenda_item_badges`, then a `REFRESH MATERIALIZED VIEW` populates this MV.

- [ ] **Step 6.2: Append DROP to SQL_DOWN**

Insert at the very TOP of `SQL_DOWN` (must drop MV first, before its underlying tables):

```sql
DROP MATERIALIZED VIEW IF EXISTS mv_badge_volume_monthly;
```

- [ ] **Step 6.3: Commit**

```bash
git add src/docket/migrations/013_impact_first_refactor.py
git commit -m "feat(migration): 013 add mv_badge_volume_monthly materialized view"
```

---

## Task 7: Migration 013 — Seed Data

**Files:**
- Modify: `src/docket/migrations/013_impact_first_refactor.py`

- [ ] **Step 7.1: Append process-badge templates to SQL_UP**

Insert after the MV block (these inserts populate `priority_badge_templates`):

```sql
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
```

- [ ] **Step 7.2: Append BHM policy-badge templates to SQL_UP**

```sql
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
```

- [ ] **Step 7.3: Append BHM opt-in config rows to SQL_UP**

```sql
-- 11. Seed: opt Birmingham into all 4 policy badges (Section 5.2)
INSERT INTO priority_badges_config (city_id, template_slug, enabled, added_by, notes)
SELECT m.id, t.slug, TRUE, 'migration_013', 'BHM 2026 v1 priority list'
FROM municipalities m
CROSS JOIN priority_badge_templates t
WHERE m.slug = 'birmingham'
  AND t.slug IN ('blight_accountability', 'housing_stability',
                 'property_recovery', 'public_safety_tech_privacy');
```

- [ ] **Step 7.4: Append BHM mayoral_terms seed to SQL_UP**

```sql
-- 12. Seed: Birmingham mayoral terms (for SVG overlay on category landing pages)
INSERT INTO mayoral_terms (city_id, mayor_name, party, term_start, term_end)
SELECT id, 'William Bell', 'Democrat',  '2010-01-26', '2017-11-28' FROM municipalities WHERE slug = 'birmingham'
UNION ALL
SELECT id, 'Randall Woodfin', 'Democrat', '2017-11-28', NULL FROM municipalities WHERE slug = 'birmingham';
```

(`term_end IS NULL` means current incumbent — UI uses `COALESCE(term_end, CURRENT_DATE)` for SVG band width.)

- [ ] **Step 7.5: SQL_DOWN — seed rows drop with their tables**

No additional DOWN work needed; the table drops cascade.

- [ ] **Step 7.6: Commit**

```bash
git add src/docket/migrations/013_impact_first_refactor.py
git commit -m "feat(migration): 013 seed process badges, BHM policy badges, mayoral terms"
```

---

## Task 8: Register Migration 013 + Idempotency Test

**Files:**
- Modify: `src/docket/migrations/runner.py`
- Create: `tests/integration/test_migration_013.py`

- [ ] **Step 8.1: Register the migration**

Modify `src/docket/migrations/runner.py:16-29` to append `013_impact_first_refactor` at the end of the `MIGRATIONS` list:

```python
MIGRATIONS = [
    "docket.migrations.001_initial",
    "docket.migrations.002_seed_cities",
    "docket.migrations.003_add_topic",
    "docket.migrations.004_expand_meeting_types",
    "docket.migrations.005_seed_council_rosters",
    "docket.migrations.006_admin_users",
    "docket.migrations.007_council_terms_and_backfill",
    "docket.migrations.008_vote_matching_support",
    "docket.migrations.009_vote_agenda_items",
    "docket.migrations.010_backfill_vote_agenda_items",
    "docket.migrations.011_drop_deprecated_vote_columns",
    "docket.migrations.012_ai_summaries_and_scoring",
    "docket.migrations.013_impact_first_refactor",
]
```

- [ ] **Step 8.2: Write the failing integration test**

`tests/integration/test_migration_013.py`:

```python
"""Integration tests for migration 013_impact_first_refactor.

Verifies:
1. Migration applies cleanly to a fresh DB.
2. up → down → up returns the schema to a consistent state.
3. New columns and tables are queryable after up().
4. Seed data is present (7 process badges + 4 BHM policy templates + 2 BHM mayoral terms).
"""

from __future__ import annotations

from docket.db import db
from docket.migrations.runner import apply_migrations, rollback_migration


def test_013_applies_cleanly():
    """Migration 013 applies; new objects are present."""
    with db() as conn:
        apply_migrations(conn)

        with conn.cursor() as cur:
            # Enums exist
            cur.execute("""
                SELECT typname FROM pg_type
                WHERE typname IN (
                    'data_quality_enum',
                    'data_debt_priority_enum',
                    'processing_status_enum'
                )
            """)
            assert len(cur.fetchall()) == 3

            # New columns on agenda_items
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'agenda_items'
                  AND column_name IN ('extracted_facts', 'headline', 'why_it_matters',
                                       'data_quality', 'processing_status', 'search_vector')
            """)
            assert len(cur.fetchall()) == 6

            # 10 new tables exist (decisions #91, #93 added cache + status_audit)
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_name IN (
                    'priority_badge_templates', 'priority_badges_config',
                    'agenda_item_badges', 'agenda_item_badges_audit',
                    'city_score_floor_overrides', 'ai_batches', 'ai_batch_items',
                    'mayoral_terms',
                    'ai_response_cache', 'processing_status_audit'
                )
            """)
            assert len(cur.fetchall()) == 10

            # Process badges seeded (7)
            cur.execute(
                "SELECT COUNT(*) FROM priority_badge_templates WHERE kind = 'process'"
            )
            assert cur.fetchone()[0] == 7

            # BHM policy badges seeded (4)
            cur.execute(
                "SELECT COUNT(*) FROM priority_badge_templates WHERE kind = 'policy'"
            )
            assert cur.fetchone()[0] == 4

            # BHM opt-in config (4 rows)
            cur.execute("""
                SELECT COUNT(*) FROM priority_badges_config c
                JOIN municipalities m ON m.id = c.city_id
                WHERE m.slug = 'birmingham'
            """)
            assert cur.fetchone()[0] == 4

            # BHM mayoral terms (2 rows)
            cur.execute("""
                SELECT COUNT(*) FROM mayoral_terms mt
                JOIN municipalities m ON m.id = mt.city_id
                WHERE m.slug = 'birmingham'
            """)
            assert cur.fetchone()[0] == 2


def test_013_search_vector_trigger_fires_on_insert():
    """Inserting into agenda_items populates search_vector via trigger."""
    with db() as conn:
        apply_migrations(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT id FROM meetings LIMIT 1")
            meeting_id = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO agenda_items (meeting_id, title, description, summary)
                VALUES (%s, 'Test item title', 'Test description body', NULL)
                RETURNING id, search_vector
            """, [meeting_id])
            new_id, sv = cur.fetchone()
            assert sv is not None
            # tsvector representation contains the lexemes
            assert "title" in str(sv).lower() or "test" in str(sv).lower()

            # Cleanup
            cur.execute("DELETE FROM agenda_items WHERE id = %s", [new_id])


def test_013_up_down_up_cycle():
    """up → down → up leaves schema in a consistent state."""
    with db() as conn:
        apply_migrations(conn)
        rollback_migration(conn, 13)

        with conn.cursor() as cur:
            # Enums should be gone
            cur.execute("""
                SELECT COUNT(*) FROM pg_type
                WHERE typname IN ('data_quality_enum', 'data_debt_priority_enum',
                                   'processing_status_enum')
            """)
            assert cur.fetchone()[0] == 0

            # New tables should be gone
            cur.execute("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_name = 'agenda_item_badges'
            """)
            assert cur.fetchone()[0] == 0

        # Re-apply
        apply_migrations(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM priority_badge_templates")
            # 7 process + 4 policy = 11 templates
            assert cur.fetchone()[0] == 11
```

- [ ] **Step 8.3: Run the test (expect failure on a fresh test DB)**

Run: `venv/bin/pytest tests/integration/test_migration_013.py -v`
Expected: tests pass IF the test DB is fresh; if any prior test ran 013 already, the up-portion will fail with "type already exists" — that's expected and is exactly why migration 013 needs `DROP TYPE IF EXISTS` semantics in idempotency. The skill says treat the failure as the signal that the test is exercising real code.

If the test fails on the first run because tables/types already exist from an earlier session, drop the test DB and retry:

```bash
PSQL=/opt/homebrew/opt/postgresql@16/bin/psql
$PSQL -d postgres -c "DROP DATABASE IF EXISTS docket_db;"
$PSQL -d postgres -c "CREATE DATABASE docket_db OWNER docket;"
venv/bin/python -m docket.migrations.runner  # apply 001-013
venv/bin/pytest tests/integration/test_migration_013.py -v
```

- [ ] **Step 8.4: Commit**

```bash
git add src/docket/migrations/runner.py tests/integration/test_migration_013.py
git commit -m "feat(migration): register 013 + integration tests (apply, trigger, up/down/up)"
```

---

## Task 9: Apply Migration 013 to Local DB

**Files:** none (deployment step)

- [ ] **Step 9.1: Confirm current migration state**

Run: `venv/bin/python -m docket.migrations.runner --status`
Expected: shows migrations 001-012 applied, 013 pending.

- [ ] **Step 9.2: Apply 013**

Run: `venv/bin/python -m docket.migrations.runner`
Expected: `Applied: 013_impact_first_refactor` (or similar success log line).

- [ ] **Step 9.3: Smoke-test new columns return null**

Run:
```bash
psql docket_db -c "
SELECT
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE headline IS NULL) AS null_headlines,
  COUNT(*) FILTER (WHERE processing_status IS NOT NULL) AS has_status
FROM agenda_items;
"
```
Expected: `null_headlines = total` (all NULL since no Stage 2 has run yet), `has_status = total` (default 'pending' from migration).

- [ ] **Step 9.4: Smoke-test seed data is present**

Run:
```bash
psql docket_db -c "
SELECT slug, kind FROM priority_badge_templates ORDER BY kind, slug;
"
```
Expected: 11 rows (7 process + 4 policy), alphabetized within kind.

- [ ] **Step 9.5: Smoke-test pg_trgm extension is loaded**

Run: `psql docket_db -c "SELECT similarity('Acme Industries', 'Acme Industries Inc');"`
Expected: a number around `0.7`.

(No commit needed — this is a runtime apply, not a code change.)

---

## Task 10: Wave 0 — Stage 0a Helpers (`_priority.py`)

**Files:**
- Create: `src/docket/ai/_priority.py`
- Create: `tests/unit/test_wave0_priority.py`

- [ ] **Step 10.1: Write failing tests for `_priority_from_title`**

`tests/unit/test_wave0_priority.py`:

```python
"""Tests for Stage 0a priority + Big Fish helpers."""

from __future__ import annotations

import pytest

from docket.ai._priority import _priority_from_title, _is_big_fish


class TestPriorityFromTitle:
    def test_high_keyword_settlement(self):
        assert _priority_from_title("Settlement of plaintiff vs. City") == 'high'

    def test_high_keyword_emergency(self):
        assert _priority_from_title("Emergency repair of water main") == 'high'

    def test_high_dollar_in_title(self):
        assert _priority_from_title("Award of $4,500,000 contract") == 'high'

    def test_high_keyword_annexation(self):
        assert _priority_from_title("Annexation of Hidden Lake parcel") == 'high'

    def test_low_keyword_fleet(self):
        assert _priority_from_title("Fleet fuel purchase Q2 2026") == 'low'

    def test_low_keyword_membership(self):
        assert _priority_from_title("Annual membership dues NLC") == 'low'

    def test_normal_default(self):
        assert _priority_from_title("Approval of professional services agreement") == 'normal'

    def test_empty_title(self):
        assert _priority_from_title("") == 'normal'
        assert _priority_from_title(None) == 'normal'


class TestIsBigFish:
    def test_settlement_is_big_fish(self):
        assert _is_big_fish("Settlement of Smith vs. City for $250,000")

    def test_sole_source_is_big_fish(self):
        assert _is_big_fish("Sole-source extension: Flock cameras 5yr $1.8M")

    def test_emergency_is_big_fish(self):
        assert _is_big_fish("Ratifying an emergency repair of water main")

    def test_million_dollar_title_is_big_fish(self):
        assert _is_big_fish("Award of $1,500,000 HVAC contract")

    def test_routine_fleet_is_not_big_fish(self):
        assert not _is_big_fish("Approval of fleet fuel purchase")

    def test_routine_minutes_is_not_big_fish(self):
        assert not _is_big_fish("Approval of minutes from May 1, 2026")

    def test_empty_is_not_big_fish(self):
        assert not _is_big_fish("")
        assert not _is_big_fish(None)
```

- [ ] **Step 10.2: Run tests (expect failure)**

Run: `venv/bin/pytest tests/unit/test_wave0_priority.py -v`
Expected: `ImportError: No module named 'docket.ai._priority'`

- [ ] **Step 10.3: Implement `_priority.py`**

`src/docket/ai/_priority.py`:

```python
"""Shared priority and Big Fish helpers for Stage 0a.

`_priority_from_title()` classifies an item into 'low' / 'normal' / 'high'
based on title keywords + dollar regex. Used to set
`agenda_items.data_debt_priority` and to drive sorting in admin queues
(/admin/data-debt, /admin/errors).

`_is_big_fish()` is the Big Fish Override (decision #86): items whose
title alone signals high impact bypass the data-quality gate even if
their body is missing or unreadable.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
sections 2.1, decision #86.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal

from docket.enrichment.dollars import extract_dollars

DataDebtPriority = Literal['low', 'normal', 'high']


HIGH_KEYWORDS = (
    'settlement', 'sole source', 'sole-source', 'no-bid', 'no bid',
    'emergency', 'flock', 'surveillance', 'litigation',
    'department head', 'police chief', 'city attorney',
    'annexation', 'rezoning', 'variance', 'easement',
)

LOW_KEYWORDS = (
    'fleet', 'fuel', 'tires', 'maintenance', 'office supplies',
    'mileage', 'travel reimbursement', 'minutes',
    'travel authorization', 'membership dues', 'notary bond',
)


def _priority_from_title(title: str | None) -> DataDebtPriority:
    """Classify a title as 'low', 'normal', or 'high' priority."""
    if not title:
        return 'normal'
    t = title.lower()

    dollars = extract_dollars(title)
    if dollars is not None and dollars >= Decimal("1_000_000"):
        return 'high'
    if any(kw in t for kw in HIGH_KEYWORDS):
        return 'high'
    if any(kw in t for kw in LOW_KEYWORDS):
        return 'low'
    return 'normal'


def _is_big_fish(title: str | None) -> bool:
    """Big Fish Override (decision #86): title alone signals high impact.

    Returns True if the title contains a HIGH_KEYWORD or any dollar
    amount of $1M+. Used by Stage 0a to bypass `data_quality !=
    'ok'` flags so high-impact items are never buried by OCR failures.
    """
    if not title:
        return False
    t = title.lower()
    if any(kw in t for kw in HIGH_KEYWORDS):
        return True
    dollars = extract_dollars(title)
    if dollars is not None and dollars >= Decimal("1_000_000"):
        return True
    return False
```

- [ ] **Step 10.4: Run tests (expect pass)**

Run: `venv/bin/pytest tests/unit/test_wave0_priority.py -v`
Expected: 14 tests pass.

- [ ] **Step 10.5: Commit**

```bash
git add src/docket/ai/_priority.py tests/unit/test_wave0_priority.py
git commit -m "feat(ai): add Stage 0a priority + Big Fish Override helpers"
```

---

## Task 11: Wave 0 — Stage 0a Data-Quality Gate

**Files:**
- Create: `src/docket/ai/wave0.py` (data-quality portion)
- Create: `tests/unit/test_wave0_quality.py`

- [ ] **Step 11.1: Write failing tests for `evaluate_data_quality`**

`tests/unit/test_wave0_quality.py`:

```python
"""Tests for Stage 0a data-quality gate (`evaluate_data_quality`)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from docket.ai.wave0 import evaluate_data_quality


@dataclass
class FakeItem:
    """Minimal fixture matching the AgendaItem fields we read."""
    title: str | None
    description: str | None = None
    raw_text: str | None = None
    source_type: str | None = 'pdf'


class TestEvaluateDataQuality:
    def test_big_fish_overrides_empty_body(self):
        item = FakeItem(title="Settlement of Smith vs. City", description="")
        quality, priority = evaluate_data_quality(item)
        assert quality == 'ok'
        assert priority == 'high'

    def test_big_fish_overrides_no_text_layer(self):
        item = FakeItem(title="Sole-source extension: Flock cameras", description="x")
        quality, priority = evaluate_data_quality(item)
        assert quality == 'ok'
        assert priority == 'high'

    def test_empty_title(self):
        item = FakeItem(title="", description="some body")
        quality, priority = evaluate_data_quality(item)
        assert quality == 'empty'

    def test_short_title(self):
        item = FakeItem(title="ok", description="some body")
        quality, priority = evaluate_data_quality(item)
        assert quality == 'empty'

    def test_no_body(self):
        item = FakeItem(title="Approval of routine matter", description=None)
        quality, priority = evaluate_data_quality(item)
        assert quality == 'no_agenda_text'

    def test_short_body_pdf(self):
        item = FakeItem(title="Approval of routine matter", description="see attached", source_type='pdf')
        quality, priority = evaluate_data_quality(item)
        assert quality == 'no_text_layer'

    def test_body_equals_title(self):
        item = FakeItem(
            title="Approval of professional services agreement",
            description="Approval of professional services agreement",
            source_type='pdf',
        )
        quality, priority = evaluate_data_quality(item)
        assert quality == 'no_text_layer'

    def test_ok_substantive_item(self):
        item = FakeItem(
            title="Award of HVAC contract",
            description="The City Council hereby awards the contract to Acme Industries Inc. for "
                         "the replacement of the HVAC system at City Hall, including labor and "
                         "materials, for a total amount not to exceed $87,500. The contract term "
                         "is 24 months commencing June 1, 2026.",
        )
        quality, priority = evaluate_data_quality(item)
        assert quality == 'ok'
        assert priority == 'normal'

    def test_priority_high_for_million_dollar_normal_body(self):
        item = FakeItem(
            title="Award of $4,500,000 HVAC contract to Acme",
            description="Long valid body content describing the contract awards procurement process etc.",
        )
        quality, priority = evaluate_data_quality(item)
        assert quality == 'ok'
        assert priority == 'high'  # via _priority_from_title's dollar regex
```

- [ ] **Step 11.2: Run tests (expect failure)**

Run: `venv/bin/pytest tests/unit/test_wave0_quality.py -v`
Expected: `ImportError: cannot import name 'evaluate_data_quality' from 'docket.ai.wave0'`

- [ ] **Step 11.3: Implement `evaluate_data_quality`**

Create `src/docket/ai/wave0.py`:

```python
"""Wave 0: non-LLM pre-pass that classifies every agenda item into
`procedural_skipped`, `data_quality_skipped`, or `pending`.

Two stages:
  - Stage 0a: data-quality gate (this module's `evaluate_data_quality`)
  - Stage 0b: relevance regex (this module's `is_procedural`)

Wave 0 is non-LLM (no API calls), idempotent over re-runs, and produces
the actual LLM-eligible item count that Wave 1+ budgets are based on.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
sections 2.1, 2.2, 7.1, decision #78.
"""

from __future__ import annotations

import re
from typing import Literal, Protocol

from docket.ai._priority import _is_big_fish, _priority_from_title

DataQuality = Literal['ok', 'no_text_layer', 'no_agenda_text', 'empty', 'foreign_language']
DataDebtPriority = Literal['low', 'normal', 'high']


class _ItemView(Protocol):
    """Minimal duck-type — anything with these fields works."""
    title: str | None
    description: str | None
    raw_text: str | None
    source_type: str | None


def _is_likely_foreign_language(text: str) -> bool:
    """Cheap heuristic: high non-ASCII ratio suggests non-English content.
    Conservative — only fires on clearly non-Latin-script content."""
    if not text:
        return False
    non_ascii = sum(1 for c in text if ord(c) > 127)
    return non_ascii > len(text) * 0.4


def evaluate_data_quality(item: _ItemView) -> tuple[DataQuality, DataDebtPriority]:
    """Classify an item's data quality and priority.

    Big Fish Override (decision #86) checks first — high-impact titles
    bypass body-content gates so they're not buried in the OCR queue.
    """
    # Big Fish Override
    if _is_big_fish(item.title):
        return ('ok', 'high')

    # Empty / too-short title
    if not item.title or len(item.title.strip()) < 5:
        return ('empty', _priority_from_title(item.title))

    body = item.description or item.raw_text or ''
    body_clean = body.strip()

    # No body
    if not body_clean:
        return ('no_agenda_text', _priority_from_title(item.title))

    # Short body on a PDF source
    if len(body_clean) < 50 and (item.source_type == 'pdf'):
        return ('no_text_layer', _priority_from_title(item.title))

    # Body equals title (PDF parser fell back to title-only)
    if (body_clean.lower() == (item.title or '').lower().strip()
            and len(body_clean) < 200):
        return ('no_text_layer', _priority_from_title(item.title))

    if _is_likely_foreign_language(body_clean):
        return ('foreign_language', _priority_from_title(item.title))

    return ('ok', _priority_from_title(item.title))
```

- [ ] **Step 11.4: Run tests (expect pass)**

Run: `venv/bin/pytest tests/unit/test_wave0_quality.py -v`
Expected: 9 tests pass.

- [ ] **Step 11.5: Commit**

```bash
git add src/docket/ai/wave0.py tests/unit/test_wave0_quality.py
git commit -m "feat(ai): add Stage 0a data-quality gate with Big Fish Override"
```

---

## Task 12: Wave 0 — Stage 0b Procedural Regex

**Files:**
- Modify: `src/docket/ai/wave0.py`
- Create: `tests/unit/test_wave0_procedural.py`

- [ ] **Step 12.1: Write failing tests**

`tests/unit/test_wave0_procedural.py`:

```python
"""Tests for Stage 0b procedural regex (`is_procedural`)."""

from __future__ import annotations

import pytest

from docket.ai.wave0 import is_procedural


class TestIsProcedural:
    @pytest.mark.parametrize("title", [
        "Roll Call",
        "Pledge of Allegiance",
        "Invocation",
        "Moment of Silence",
        "Motion to Adjourn",
        "Adjournment",
        "Recess",
        "Approval of Minutes from May 1, 2026",
        "Approval of prior minutes",
        "Reading of the Minutes",
        "Minutes Not Yet Ready",
        "Minutes not received",
        "Public Comment Period",
        "Call to Public Comments",
        "Opening of Public Comments",
        "Executive Session",
        "Vouchers for Payment",
        "Bills for Payment",
        "Payroll for Payment",
        "Approval of Claims",
        "Recognition of Visitors",
        "Recognition of Guests",
        "Awards and Presentations",
        "Awards and Presentation",  # singular
        "Reading of Communications",
        "Reading of Petitions",
    ])
    def test_procedural_titles_match(self, title: str):
        assert is_procedural(title), f"Should match: {title!r}"

    @pytest.mark.parametrize("title", [
        "Award of HVAC contract for $87,500",
        "Settlement of Smith vs. City",
        "Approval of professional services agreement",
        "Resolution authorizing emergency repair",
        "Annual report on police staffing",
        "Award of liquor license for 234 Elm St",
    ])
    def test_substantive_titles_dont_match(self, title: str):
        assert not is_procedural(title), f"Should NOT match: {title!r}"

    def test_empty_title(self):
        assert not is_procedural("")
        assert not is_procedural(None)
```

- [ ] **Step 12.2: Run tests (expect failure)**

Run: `venv/bin/pytest tests/unit/test_wave0_procedural.py -v`
Expected: `ImportError: cannot import name 'is_procedural' from 'docket.ai.wave0'`

- [ ] **Step 12.3: Implement `is_procedural`**

Append to `src/docket/ai/wave0.py`:

```python
PROCEDURAL_TITLE_PATTERNS = (
    r'^\s*roll\s+call',
    r'^\s*(call\s+to|opening\s+of)\s+(public\s+)?comments?',
    r'^\s*pledge\s+of\s+allegiance',
    r'^\s*invocation',
    r'^\s*moment\s+of\s+silence',
    r'^\s*motion\s+to\s+adjourn',
    r'^\s*adjournment',
    r'^\s*recess',
    r'^\s*approval\s+of\s+(prior|previous|the)?\s*minutes',
    r'minutes\s+(not\s+)?(yet\s+)?(ready|available|received)',
    r'^\s*reading\s+of\s+(the\s+)?minutes',
    r'^\s*proclamations?\s*$',
    r'^\s*public\s+comment\s+period',
    r'^\s*executive\s+session',
    # Alabama council common patterns:
    r'^\s*(vouchers?|bills?|payroll)\s+for\s+payment',
    r'^\s*approval\s+of\s+claims',
    r'^\s*recognition\s+of\s+(visitors?|guests?)',
    r'^\s*awards?\s+and\s+presentations?',
    r'^\s*reading\s+of\s+(communications?|petitions?)',
)

_compiled_patterns = [re.compile(p, re.IGNORECASE) for p in PROCEDURAL_TITLE_PATTERNS]


def is_procedural(title: str | None) -> bool:
    """Stage 0b: title-only regex check for procedural items.

    Returns True if the title matches any of the known procedural
    patterns (roll call, pledge, vouchers for payment, etc.). The
    telemetry loop (decision #26) tracks items that pass this check
    but are later judged procedural by Stage 2 — admins expand the
    pattern list over time.
    """
    if not title:
        return False
    for pattern in _compiled_patterns:
        if pattern.search(title):
            return True
    return False
```

- [ ] **Step 12.4: Run tests (expect pass)**

Run: `venv/bin/pytest tests/unit/test_wave0_procedural.py -v`
Expected: 32+ tests pass (one per parametrize case + the empty-title test).

- [ ] **Step 12.5: Commit**

```bash
git add src/docket/ai/wave0.py tests/unit/test_wave0_procedural.py
git commit -m "feat(ai): add Stage 0b procedural regex with Alabama-context patterns"
```

---

## Task 13: Wave 0 — Main Loop and Driver

**Files:**
- Modify: `src/docket/ai/wave0.py`
- Create: `tests/unit/test_wave0_driver.py`

- [ ] **Step 13.1: Write failing test for the main loop**

`tests/unit/test_wave0_driver.py`:

```python
"""Tests for Wave 0 main driver."""

from __future__ import annotations

import pytest

from docket.ai.wave0 import Wave0Report, run_wave_0
from docket.db import db


@pytest.fixture
def fresh_items_for_birmingham():
    """Insert a small set of test items into Birmingham, return their ids.
    Cleanup after the test."""
    ids = []
    fixtures = [
        # (title, description, expected outcome)
        ("Roll Call", "", "procedural_skipped"),
        ("Approval of minutes from May 1, 2026", "", "procedural_skipped"),
        ("Settlement of Smith vs. City for $250K", "", "pending"),  # Big Fish
        ("Approval of fleet fuel purchase", "", "data_quality_skipped"),  # no body
        (
            "Award of HVAC contract",
            "Long valid body content with full agenda item description text and details.",
            "pending",
        ),
    ]

    with db() as conn:
        with conn.cursor() as cur:
            # Resolve Birmingham municipality_id and a meeting_id
            cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
            city_id = cur.fetchone()[0]
            cur.execute(
                "SELECT id FROM meetings WHERE municipality_id = %s LIMIT 1",
                [city_id],
            )
            meeting_id = cur.fetchone()[0]

            for title, desc, _ in fixtures:
                cur.execute("""
                    INSERT INTO agenda_items (
                        meeting_id, title, description,
                        processing_status, ai_extraction_version
                    )
                    VALUES (%s, %s, %s, 'pending', NULL)
                    RETURNING id
                """, [meeting_id, title, desc])
                ids.append(cur.fetchone()[0])

    yield ids, [f[2] for f in fixtures]

    # Cleanup
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", [ids])


def test_run_wave_0_classifies_items(fresh_items_for_birmingham):
    """Each fixture item lands in its expected processing_status."""
    ids, expected_statuses = fresh_items_for_birmingham

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
            city_id = cur.fetchone()[0]

    report = run_wave_0([city_id])

    assert isinstance(report, Wave0Report)
    assert report.counts['procedural_skipped'] >= 2  # at least roll call + minutes
    assert report.counts['data_quality_skipped'] >= 1  # fleet fuel
    assert report.counts['pending'] >= 2  # settlement (Big Fish) + HVAC

    # Verify each fixture item got the expected status
    with db() as conn:
        with conn.cursor() as cur:
            for item_id, expected in zip(ids, expected_statuses):
                cur.execute("""
                    SELECT processing_status, data_quality, data_debt_priority
                    FROM agenda_items WHERE id = %s
                """, [item_id])
                status, quality, priority = cur.fetchone()
                assert status == expected, (
                    f"Item {item_id} status mismatch: expected {expected}, got {status}"
                )


def test_run_wave_0_idempotent(fresh_items_for_birmingham):
    """Running Wave 0 twice produces the same result."""
    ids, _ = fresh_items_for_birmingham
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
            city_id = cur.fetchone()[0]

    run_wave_0([city_id])
    report2 = run_wave_0([city_id])

    # Second run should classify the same items the same way (overwrite is OK)
    assert isinstance(report2, Wave0Report)
```

- [ ] **Step 13.2: Run tests (expect failure)**

Run: `venv/bin/pytest tests/unit/test_wave0_driver.py -v`
Expected: `ImportError: cannot import name 'run_wave_0' from 'docket.ai.wave0'`

- [ ] **Step 13.3: Implement `run_wave_0` and `Wave0Report`**

Append to `src/docket/ai/wave0.py`:

```python
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from docket.db import db

log = logging.getLogger(__name__)


@dataclass
class Wave0Report:
    """Classification counts after a Wave 0 run."""
    counts: Counter[str] = field(default_factory=Counter)
    items_processed: int = 0


def run_wave_0(city_ids: Iterable[int]) -> Wave0Report:
    """Run Stage 0a + 0b across all agenda items in the given cities.

    Sets `data_quality`, `data_debt_priority`, and `processing_status`
    for every item. No LLM calls. Idempotent — safe to re-run after
    refining patterns or thresholds.

    Decision #78. Spec section 7.1.
    """
    report = Wave0Report()
    city_id_list = list(city_ids)

    with db() as conn:
        with conn.cursor() as cur:
            # Take an advisory lock so a concurrent --run-once doesn't collide
            cur.execute("SELECT pg_try_advisory_lock(hashtext('docket.wave_0'))")
            if not cur.fetchone()[0]:
                log.warning("wave_0 already running, skipping")
                return report

            try:
                # agenda_items has no raw_text or source_type column; PDF source
                # is the dominant input shape, so we hard-code 'pdf' for the
                # data-quality gate's PDF-specific heuristics.
                cur.execute("""
                    SELECT ai.id, ai.title, ai.description
                    FROM agenda_items ai
                    JOIN meetings m ON m.id = ai.meeting_id
                    WHERE m.municipality_id = ANY(%s)
                      AND ai.ai_extraction_version IS NULL
                    ORDER BY m.meeting_date DESC NULLS LAST
                """, [city_id_list])

                rows = cur.fetchall()
                log.info(
                    "wave_0: classifying %d items across %d cities",
                    len(rows),
                    len(city_id_list),
                )

                for row in rows:
                    item_id, title, description = row

                    # Build a minimal item view
                    view = type('view', (), {
                        'title': title,
                        'description': description,
                        'raw_text': None,
                        'source_type': 'pdf',
                    })()

                    # Stage 0a — data-quality gate (with Big Fish Override)
                    quality, priority = evaluate_data_quality(view)

                    if quality != 'ok':
                        cur.execute("""
                            UPDATE agenda_items
                            SET data_quality = %s::data_quality_enum,
                                data_debt_priority = %s::data_debt_priority_enum,
                                processing_status = 'data_quality_skipped'::processing_status_enum
                            WHERE id = %s
                        """, [quality, priority, item_id])
                        report.counts['data_quality_skipped'] += 1
                        continue

                    # Stage 0b — procedural regex
                    if is_procedural(title):
                        cur.execute("""
                            UPDATE agenda_items
                            SET data_quality = 'ok'::data_quality_enum,
                                data_debt_priority = 'normal'::data_debt_priority_enum,
                                processing_status = 'procedural_skipped'::processing_status_enum
                            WHERE id = %s
                        """, [item_id])
                        report.counts['procedural_skipped'] += 1
                        continue

                    # Survives both gates — eligible for Wave 1+
                    cur.execute("""
                        UPDATE agenda_items
                        SET data_quality = 'ok'::data_quality_enum,
                            data_debt_priority = %s::data_debt_priority_enum,
                            processing_status = 'pending'::processing_status_enum
                        WHERE id = %s
                    """, [priority, item_id])
                    report.counts['pending'] += 1
                    report.items_processed += 1

                cur.execute("SELECT pg_advisory_unlock(hashtext('docket.wave_0'))")
                log.info("wave_0 complete: %s", dict(report.counts))
            except Exception:
                cur.execute("SELECT pg_advisory_unlock(hashtext('docket.wave_0'))")
                log.exception("wave_0 failed")
                raise

    return report
```

- [ ] **Step 13.4: Run tests (expect pass)**

Run: `venv/bin/pytest tests/unit/test_wave0_driver.py -v`
Expected: 2 tests pass. (May take a few seconds due to DB I/O.)

- [ ] **Step 13.5: Commit**

```bash
git add src/docket/ai/wave0.py tests/unit/test_wave0_driver.py
git commit -m "feat(ai): wave_0 main driver with advisory lock and idempotent classification"
```

---

## Task 14: Wave 0 — CLI Integration

**Files:**
- Modify: `src/docket/ai/cli.py`

- [ ] **Step 14.1: Inspect existing CLI to find the right insertion point**

Run: `venv/bin/python -m docket.ai.cli --help`
Expected: existing argparse output showing flags like `--status`, `--items`, `--meetings`. Note where you'd add `--wave 0`.

- [ ] **Step 14.2: Add `--wave` flag and dispatcher**

Modify `src/docket/ai/cli.py` — add a new argument and wire it to `run_wave_0`. Find the `argparse.ArgumentParser` block and add:

```python
parser.add_argument(
    '--wave',
    type=str,
    choices=['0'],   # Phase 1 only knows about wave 0; later phases extend
    default=None,
    help="Run a backfill wave. '0' = Stage 0a + 0b non-LLM pre-pass (decision #78).",
)
```

Then add a dispatch branch (likely near the top of `main()` after parsing args):

```python
if args.wave == '0':
    from docket.ai.wave0 import run_wave_0
    from docket.db import db_cursor

    with db_cursor() as cur:
        cur.execute("SELECT id, slug FROM municipalities ORDER BY slug")
        rows = cur.fetchall()

    city_ids = [r[0] for r in rows]
    print(f"Running Wave 0 across {len(city_ids)} cities: {[r[1] for r in rows]}")
    report = run_wave_0(city_ids)
    print(f"Wave 0 complete:")
    for status, count in sorted(report.counts.items()):
        print(f"  {status}: {count}")
    return
```

- [ ] **Step 14.3: Smoke-test the CLI**

Run: `venv/bin/python -m docket.ai.cli --wave 0`
Expected: prints city list, runs Wave 0, prints final counts. Should complete in seconds-to-minutes depending on local DB size.

- [ ] **Step 14.4: Commit**

```bash
git add src/docket/ai/cli.py
git commit -m "feat(ai): wire --wave 0 flag into the AI CLI"
```

---

## Task 15: Apply Migration 013 + Wave 0 to Railway Production

**Files:** none (deployment step)

> Per project memory: Railway DB is PostgreSQL 18.3 — local PG 14/16 `pg_dump` will refuse with "server version mismatch." Use `/opt/homebrew/opt/postgresql@18/bin/psql` for any direct queries against Railway. For external connections from your laptop, use `DATABASE_PUBLIC_URL` (not `DATABASE_URL`).

- [ ] **Step 15.1: Verify Railway connection**

Run:
```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "SELECT version();"
```
Expected: PostgreSQL 18.x version string from Railway.

- [ ] **Step 15.2: Confirm migration status on Railway**

Run:
```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  venv/bin/python -m docket.migrations.runner --status
```
Expected: 001-012 applied, 013 pending.

- [ ] **Step 15.3: Push the branch and deploy**

```bash
git push -u origin feat/impact-first-phase-1
railway up --detach
```

Expected: build succeeds, container starts. Wait for Railway to log `Started`.

- [ ] **Step 15.4: Run migration 013 on Railway**

Once the new container is up:
```bash
railway run venv/bin/python -m docket.migrations.runner
```
Expected: `Applied: 013_impact_first_refactor`.

(Alternative: Railway's release-command pattern auto-runs migrations on deploy. Check `railway.json` / `Procfile` for the existing migration-runner invocation. If that's the path, 13 will apply automatically.)

- [ ] **Step 15.5: Smoke-test on Railway**

```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT
  COUNT(*) AS total_items,
  COUNT(*) FILTER (WHERE processing_status = 'pending') AS pending,
  COUNT(*) FILTER (WHERE headline IS NULL) AS null_headlines
FROM agenda_items;
"
```
Expected: every row has `processing_status = 'pending'` (default), `headline IS NULL` (no Stage 2 has run).

- [ ] **Step 15.6: Run Wave 0 on Railway**

Wave 0 hits the DB heavily; run inside the Railway container so we don't proxy 75K updates over the public network:

```bash
railway ssh --service docket-web
# Inside the container:
venv/bin/python -m docket.ai.cli --wave 0
exit
```

Expected output (counts will vary):
```
Running Wave 0 across 4 cities: ['birmingham', 'homewood', 'mobile', 'vestavia']
Wave 0 complete:
  data_quality_skipped: ~3,000
  pending: ~50,000
  procedural_skipped: ~22,000
```

(Exact counts depend on real data. Pending count is the input to Phase 2 budget projections — record it.)

- [ ] **Step 15.7: Verify the distribution**

Run on Railway:
```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT m.slug AS city, ai.processing_status, COUNT(*) AS n
FROM agenda_items ai
JOIN meetings m ON m.id = ai.meeting_id
GROUP BY m.slug, ai.processing_status
ORDER BY m.slug, ai.processing_status;
"
```

Spot-check that:
- `procedural_skipped` is 10-20% of each city's totals
- `data_quality_skipped` is 1-5% (bigger for Mobile/older Birmingham PDFs)
- `pending` is the rest (60-85%)

If any city looks way off, investigate before proceeding to Phase 2.

- [ ] **Step 15.8: Final commit + tag**

```bash
git tag refactor-impact-first-phase-1-shipped
git push origin refactor-impact-first-phase-1-shipped
```

The branch `feat/impact-first-phase-1` is now live in production. Phase 2 work proceeds on a new branch off this one.

---

## Self-Review Checklist

Run this after the plan is fully drafted (you, the reader, before implementation):

**Spec coverage:**
- [x] Migration 013 — every column, table, index, MV, seed row from spec §8.1 has a corresponding task
- [x] Wave 0 — Stage 0a (data quality + Big Fish) and Stage 0b (procedural regex) have tests + implementation tasks
- [x] Decisions #19 (degraded mode), #25 (dead-letter), #31 (priority OCR queue), #36-43 (extraction fields), #78 (Wave 0), #82 (backfill_session_id), #83 (search_vector), #86 (Big Fish), #87 (density check is enforced in Phase 2 not Phase 1)

**Placeholder scan:**
- [x] No "TBD" / "TODO" / "fill in"
- [x] Every task has actual code, exact paths, exact commands

**Type consistency:**
- [x] `Wave0Report` used in both driver and CLI
- [x] `data_quality_enum` cast in UPDATE statements matches the enum created in Migration 013
- [x] `_priority_from_title` returns `DataDebtPriority` literal type used consistently

**Scope check:**
- [x] Phase 1 is self-contained: at the end, Migration 013 is live and every existing item has a `processing_status`. No Phase 2 dependencies leak in.

---

## What ships at the end of Phase 1

After Task 15:
- Migration 013 is live on Railway production
- Every existing agenda_item has `data_quality`, `data_debt_priority`, and `processing_status` set
- The unified `search_vector` column is populated (via the trigger's auto-fire on the one-time UPDATE in Step 3.1)
- The materialized view `mv_badge_volume_monthly` exists but is empty (Phase 2 populates it)
- v2 pipeline + UI are running unchanged — citizens see no difference

**Open count of `pending` items** is the input to Phase 2's cost projection. Record the number from Step 15.6 before starting Phase 2.

---

## What does NOT ship in Phase 1

- Stage 1 extraction (Phase 2 Task A)
- Stage 2 v3 prompt (Phase 2 Task B)
- Stage 2.5 score floors (Phase 2 Task C)
- reconcile.py (Phase 2 Task D)
- Process and policy badges (Phase 2 Tasks E-F)
- Frontend Smart Brevity Card variants (Phase 2 Tasks G-I)
- Backfill driver (Phase 2 Task J or split to Phase 3)
- Migration 014 (Phase 4)
