"""Add columns to support vote-to-agenda-item matching.

agenda_items gets video_timestamp_seconds (from Granicus player page).
votes gets resolution_number, match_context, match_confidence, match_method.
"""

SQL_UP = """
ALTER TABLE agenda_items ADD COLUMN IF NOT EXISTS video_timestamp_seconds REAL;
ALTER TABLE votes ADD COLUMN IF NOT EXISTS resolution_number TEXT;
ALTER TABLE votes ADD COLUMN IF NOT EXISTS match_context TEXT;
ALTER TABLE votes ADD COLUMN IF NOT EXISTS match_confidence REAL;
ALTER TABLE votes ADD COLUMN IF NOT EXISTS match_method TEXT;
"""

SQL_DOWN = """
ALTER TABLE agenda_items DROP COLUMN IF EXISTS video_timestamp_seconds;
ALTER TABLE votes DROP COLUMN IF EXISTS resolution_number;
ALTER TABLE votes DROP COLUMN IF EXISTS match_context;
ALTER TABLE votes DROP COLUMN IF EXISTS match_confidence;
ALTER TABLE votes DROP COLUMN IF EXISTS match_method;
"""
