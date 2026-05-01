"""Set term dates on council members and add prior-term council members.

Birmingham council transition: October 28, 2025.
Continuing: Alexander, Smitherman, Tate, Williams, Woods (same people, new term)
Departed:   Abbott (D4→Gunn), Clarke (D6→C. Smitherman), Moore (D3→Vasa)
New:        Gunn (D4), Vasa (D3), O'Quinn (D5), Smith (D8)
"""

SQL_UP = """
-- Set term_start on current (active) council
UPDATE council_members SET term_start = '2025-10-28'
WHERE municipality_id = 1 AND active = TRUE AND term_start IS NULL;

-- Prior-term council members (inactive) — needed to link old votes
INSERT INTO council_members (municipality_id, name, term_start, term_end, active)
VALUES
    (1, 'Valerie A. Abbott', '2017-11-14', '2025-10-28', FALSE),
    (1, 'Lashunda Scales Clarke', '2017-11-14', '2025-10-28', FALSE),
    (1, 'Darrell W. Moore', '2017-11-14', '2025-10-28', FALSE)
ON CONFLICT DO NOTHING;
"""

SQL_DOWN = """
UPDATE council_members SET term_start = NULL
WHERE municipality_id = 1 AND active = TRUE;
DELETE FROM council_members
WHERE municipality_id = 1 AND active = FALSE;
"""
