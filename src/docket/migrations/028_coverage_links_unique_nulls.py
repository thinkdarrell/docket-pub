"""Migration 028 — fix coverage_subject_links UNIQUE NULL semantics.

PostgreSQL's default UNIQUE constraint treats NULL values as distinct: two
rows with the same (coverage_id, subject_type, subject_slug, NULL) or
(coverage_id, subject_type, NULL, subject_id) values bypass the UNIQUE.
This silently allowed duplicate subject_links on either branch of the
polymorphic shape.

PG 15+ supports NULLS NOT DISTINCT. Both local (PG 16) and Railway (PG 18)
qualify. Drop the broken auto-named constraint and add a named replacement.
"""
from __future__ import annotations


SQL_UP = r"""
ALTER TABLE coverage_subject_links
    DROP CONSTRAINT IF EXISTS coverage_subject_links_coverage_id_subject_type_subject_id__key;

-- Defensive secondary drop in case the auto-name differs by a character
DO $$
DECLARE
    cname text;
BEGIN
    SELECT conname INTO cname
      FROM pg_constraint
     WHERE conrelid = 'coverage_subject_links'::regclass
       AND contype = 'u'
     LIMIT 1;
    IF cname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE coverage_subject_links DROP CONSTRAINT %I', cname);
    END IF;
END $$;

ALTER TABLE coverage_subject_links
    ADD CONSTRAINT coverage_subject_links_unique
    UNIQUE NULLS NOT DISTINCT (coverage_id, subject_type, subject_id, subject_slug);
"""

SQL_DOWN = r"""
ALTER TABLE coverage_subject_links
    DROP CONSTRAINT IF EXISTS coverage_subject_links_unique;

ALTER TABLE coverage_subject_links
    ADD CONSTRAINT coverage_subject_links_unique_legacy
    UNIQUE (coverage_id, subject_type, subject_id, subject_slug);
"""
