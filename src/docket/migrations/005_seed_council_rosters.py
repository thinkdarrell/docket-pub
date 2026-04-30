"""Seed council member rosters for Birmingham, Vestavia Hills, Mobile, Homewood.

Data sourced from official city websites and public records (April 2026).
"""

SQL_UP = """
-- ============================================================
-- BIRMINGHAM — 9 districts, 9 council members (seated Oct 2025)
-- ============================================================

INSERT INTO districts (municipality_id, name, number)
SELECT m.id, d.name, d.number
FROM municipalities m,
     (VALUES ('District 1', 1), ('District 2', 2), ('District 3', 3),
             ('District 4', 4), ('District 5', 5), ('District 6', 6),
             ('District 7', 7), ('District 8', 8), ('District 9', 9)) AS d(name, number)
WHERE m.slug = 'birmingham'
ON CONFLICT (municipality_id, name) DO NOTHING;

INSERT INTO council_members (municipality_id, district_id, name, active)
SELECT m.id, d.id, cm.name, TRUE
FROM municipalities m
JOIN districts d ON d.municipality_id = m.id
JOIN (VALUES
    ('Clinton P. Woods', 'District 1'),
    ('Hunter Williams', 'District 2'),
    ('Josh Vasa', 'District 3'),
    ('Brian Gunn', 'District 4'),
    ('Darrell O''Quinn', 'District 5'),
    ('Crystal N. Smitherman', 'District 6'),
    ('Wardine T. Alexander', 'District 7'),
    ('Sonja Q. Smith', 'District 8'),
    ('LaTonya A. Tate', 'District 9')
) AS cm(name, district_name) ON d.name = cm.district_name
WHERE m.slug = 'birmingham'
ON CONFLICT DO NOTHING;

-- ============================================================
-- VESTAVIA HILLS — at-large, 5 members (includes mayor)
-- ============================================================

INSERT INTO council_members (municipality_id, name, active)
SELECT m.id, cm.name, TRUE
FROM municipalities m,
     (VALUES ('Ashley C. Curry'), ('Rusty Weaver'), ('Kimberly Cook'),
             ('Paul Head'), ('Ali Pilcher')) AS cm(name)
WHERE m.slug = 'vestavia_hills'
ON CONFLICT DO NOTHING;

-- ============================================================
-- MOBILE — 7 districts, 7 council members
-- ============================================================

INSERT INTO districts (municipality_id, name, number)
SELECT m.id, d.name, d.number
FROM municipalities m,
     (VALUES ('District 1', 1), ('District 2', 2), ('District 3', 3),
             ('District 4', 4), ('District 5', 5), ('District 6', 6),
             ('District 7', 7)) AS d(name, number)
WHERE m.slug = 'mobile'
ON CONFLICT (municipality_id, name) DO NOTHING;

INSERT INTO council_members (municipality_id, district_id, name, active)
SELECT m.id, d.id, cm.name, TRUE
FROM municipalities m
JOIN districts d ON d.municipality_id = m.id
JOIN (VALUES
    ('Cory Penn', 'District 1'),
    ('William Carroll', 'District 2'),
    ('C.J. Small', 'District 3'),
    ('Ben Reynolds', 'District 4'),
    ('Beau Fleming', 'District 5'),
    ('Josh Woods', 'District 6'),
    ('Gina Gregory', 'District 7')
) AS cm(name, district_name) ON d.name = cm.district_name
WHERE m.slug = 'mobile'
ON CONFLICT DO NOTHING;

-- ============================================================
-- HOMEWOOD — 4 wards + mayor (mayor is council president)
-- ============================================================

INSERT INTO districts (municipality_id, name, number)
SELECT m.id, d.name, d.number
FROM municipalities m,
     (VALUES ('Ward 1', 1), ('Ward 2', 2), ('Ward 3', 3), ('Ward 4', 4)) AS d(name, number)
WHERE m.slug = 'homewood'
ON CONFLICT (municipality_id, name) DO NOTHING;

INSERT INTO council_members (municipality_id, name, active)
SELECT m.id, 'Jennifer Andress', TRUE
FROM municipalities m WHERE m.slug = 'homewood'
ON CONFLICT DO NOTHING;

INSERT INTO council_members (municipality_id, district_id, name, active)
SELECT m.id, d.id, cm.name, TRUE
FROM municipalities m
JOIN districts d ON d.municipality_id = m.id
JOIN (VALUES
    ('Paul S. Simmons II', 'Ward 1'),
    ('Nick Sims', 'Ward 2'),
    ('Chris Lane', 'Ward 3'),
    ('Winslow Armstead', 'Ward 4')
) AS cm(name, district_name) ON d.name = cm.district_name
WHERE m.slug = 'homewood'
ON CONFLICT DO NOTHING;
"""

SQL_DOWN = """
DELETE FROM council_members WHERE municipality_id IN (
    SELECT id FROM municipalities WHERE slug IN ('birmingham', 'vestavia_hills', 'mobile', 'homewood')
);
DELETE FROM districts WHERE municipality_id IN (
    SELECT id FROM municipalities WHERE slug IN ('birmingham', 'vestavia_hills', 'mobile', 'homewood')
);
"""
