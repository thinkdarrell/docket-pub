"""Migration 034 — video OCR scan state on processing_status.

Adds four columns tracking whether a meeting has been OCR-scanned, how
many attempts, when last attempted, and last error text. Two indexes:
one partial index supporting the claim CTE's selection ordering, one
unique partial index enforcing OCR idempotency in `votes`.
"""

from __future__ import annotations


SQL_UP = r"""
ALTER TABLE processing_status
    ADD COLUMN IF NOT EXISTS video_ocr_scanned          BOOLEAN     NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS video_ocr_attempts         INTEGER     NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS video_ocr_last_attempted_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS video_ocr_last_error       TEXT        NULL;

CREATE INDEX IF NOT EXISTS idx_processing_status_ocr_pending
    ON processing_status (video_ocr_last_attempted_at NULLS FIRST)
 WHERE video_ocr_scanned = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_votes_ocr_unique
    ON votes (meeting_id, video_timestamp, source)
 WHERE source = 'video_ocr';
"""

SQL_DOWN = r"""
DROP INDEX IF EXISTS idx_votes_ocr_unique;
DROP INDEX IF EXISTS idx_processing_status_ocr_pending;
ALTER TABLE processing_status
    DROP COLUMN IF EXISTS video_ocr_last_error,
    DROP COLUMN IF EXISTS video_ocr_last_attempted_at,
    DROP COLUMN IF EXISTS video_ocr_attempts,
    DROP COLUMN IF EXISTS video_ocr_scanned;
"""
