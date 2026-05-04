"""Copy existing votes.agenda_item_id matches into vote_agenda_items.

Pre-N:M matches are unambiguous, so they land as provisional=FALSE.
Idempotent via ON CONFLICT.
"""

SQL_UP = """
INSERT INTO vote_agenda_items
    (vote_id, agenda_item_id, association_type, match_method,
     match_confidence, provisional, is_manual, is_active)
SELECT v.id,
       v.agenda_item_id,
       'explicit',
       v.match_method,
       COALESCE(v.match_confidence, 0.5),
       FALSE,
       FALSE,
       TRUE
FROM votes v
WHERE v.agenda_item_id IS NOT NULL
ON CONFLICT (vote_id, agenda_item_id) DO NOTHING;
"""

SQL_DOWN = """
-- Reverse: remove the migrated rows. We identify them by association_type='explicit'
-- AND match_method matching one of the original matcher methods (or NULL, for
-- legacy rows that pre-dated match_method tracking), AND provisional=FALSE.
-- This is approximate; if you've inserted other 'explicit' rows that were not
-- backfilled by SQL_UP, this DELETE may catch them too.
-- For full safety, take a backup before running --down.
DELETE FROM vote_agenda_items
WHERE association_type = 'explicit'
  AND provisional = FALSE
  AND is_manual = FALSE
  AND (match_method IS NULL
       OR match_method IN ('resolution_number', 'item_number', 'text_similarity', 'timestamp'));
"""
