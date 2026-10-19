"""Migration 037 — city_briefing_facts table; Birmingham gets the briefing flag.

city_briefing_facts holds the precomputed heavy facts the city briefing page
reads in one query: one row per city per fact set (`split_votes`,
`member_counts`), rebuilt in place by the worker task `briefing_facts`
(src/docket/services/briefing.py) with one INSERT ... ON CONFLICT statement
per city. The page's opener runs only where municipalities.metadata carries
`"briefing": true`; this migration sets that key for Birmingham alone and
removes it on the way down. Plan: plans/active/birmingham-city-briefing.md.
"""

from __future__ import annotations


SQL_UP = r"""
CREATE TABLE IF NOT EXISTS city_briefing_facts (
    municipality_id INTEGER NOT NULL REFERENCES municipalities(id) ON DELETE CASCADE,
    fact_set        TEXT NOT NULL CHECK (fact_set IN ('split_votes', 'member_counts')),
    payload         JSONB NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (municipality_id, fact_set)
);

UPDATE municipalities
   SET metadata = metadata || '{"briefing": true}'::jsonb
 WHERE slug = 'birmingham';
"""

SQL_DOWN = r"""
UPDATE municipalities
   SET metadata = metadata - 'briefing'
 WHERE slug = 'birmingham';

DROP TABLE IF EXISTS city_briefing_facts;
"""
