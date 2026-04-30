"""Add topic column to agenda_items for keyword-based classification."""

SQL_UP = """
ALTER TABLE agenda_items ADD COLUMN topic TEXT;
CREATE INDEX idx_agenda_items_topic ON agenda_items(topic) WHERE topic IS NOT NULL;
"""

SQL_DOWN = """
DROP INDEX IF EXISTS idx_agenda_items_topic;
ALTER TABLE agenda_items DROP COLUMN IF EXISTS topic;
"""
