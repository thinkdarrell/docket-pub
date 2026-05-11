"""Migration 018 — add ai_batches.ingested_at for Phase 3 backfill ingest.

Phase 3 (Wave 1/2/3 backfill) submits items to Anthropic Batches API; the
results need to be downloaded and persisted into ``agenda_items``. The
ingest orchestrator (``docket.ai.batch_ingest``) uses
``status='ended' AND ingested_at IS NULL`` as the work queue predicate.
Setting ``ingested_at = NOW()`` after a successful pass marks the batch
done; the orchestrator is then idempotent on re-runs.

Decision authored 2026-05-11: slot 017 is held for G2's
``requires_manual_review`` column (see migration 016's docstring +
admin.py reference), so this column lands at 018.

Down migration drops the column. Existing batch records lose ingest
timestamps but the batch results in Anthropic's storage are unaffected.
"""

from __future__ import annotations


SQL_UP = r"""
ALTER TABLE ai_batches
    ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS idx_ai_batches_status_ingested_at
    ON ai_batches (status, ingested_at)
    WHERE ingested_at IS NULL;
"""


SQL_DOWN = r"""
DROP INDEX IF EXISTS idx_ai_batches_status_ingested_at;
ALTER TABLE ai_batches
    DROP COLUMN IF EXISTS ingested_at;
"""
