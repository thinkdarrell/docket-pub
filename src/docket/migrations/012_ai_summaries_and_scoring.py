"""Add AI summary + scoring columns to agenda_items and meetings, plus ai_runs cost-telemetry table."""

SQL_UP = """
-- agenda_items: per-item summary + AI metadata
ALTER TABLE agenda_items
  ADD COLUMN summary             TEXT,
  ADD COLUMN ai_metadata         JSONB,
  ADD COLUMN ai_prompt_version   INTEGER,
  ADD COLUMN ai_generated_at     TIMESTAMPTZ;

CREATE INDEX idx_agenda_items_ai_prompt_version
  ON agenda_items (ai_prompt_version);

-- meetings: executive summary + AI metadata
ALTER TABLE meetings
  ADD COLUMN executive_summary   TEXT,
  ADD COLUMN ai_metadata         JSONB,
  ADD COLUMN ai_prompt_version   INTEGER,
  ADD COLUMN ai_generated_at     TIMESTAMPTZ;

CREATE INDEX idx_meetings_ai_prompt_version
  ON meetings (ai_prompt_version);

-- ai_runs: per-batch telemetry (cost, usage breakdown)
CREATE TABLE ai_runs (
    id              SERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    stage           TEXT NOT NULL,
    model           TEXT NOT NULL,
    rows_processed  INTEGER NOT NULL DEFAULT 0,
    rows_failed     INTEGER NOT NULL DEFAULT 0,
    usage           JSONB NOT NULL DEFAULT '{}'::jsonb,
    cost_usd        NUMERIC(10, 4) NOT NULL DEFAULT 0,
    notes           TEXT
);

CREATE INDEX idx_ai_runs_started_at ON ai_runs (started_at DESC);
CREATE INDEX idx_ai_runs_stage_started ON ai_runs (stage, started_at DESC);
"""

SQL_DOWN = """
DROP TABLE IF EXISTS ai_runs;

DROP INDEX IF EXISTS idx_meetings_ai_prompt_version;
ALTER TABLE meetings
  DROP COLUMN IF EXISTS ai_generated_at,
  DROP COLUMN IF EXISTS ai_prompt_version,
  DROP COLUMN IF EXISTS ai_metadata,
  DROP COLUMN IF EXISTS executive_summary;

DROP INDEX IF EXISTS idx_agenda_items_ai_prompt_version;
ALTER TABLE agenda_items
  DROP COLUMN IF EXISTS ai_generated_at,
  DROP COLUMN IF EXISTS ai_prompt_version,
  DROP COLUMN IF EXISTS ai_metadata,
  DROP COLUMN IF EXISTS summary;
"""
