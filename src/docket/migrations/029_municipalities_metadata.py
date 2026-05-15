"""Migration 029 — add metadata JSONB column to municipalities + seed 6 cities.

Powers the new CityLead eyebrow (council type · county · population).
Future cities INSERT with their metadata payload at onboarding — no
schema or code change needed per city.

Population figures are 2020 US Census estimates.
"""
from __future__ import annotations


SQL_UP = r"""
ALTER TABLE municipalities
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE municipalities SET metadata = '{
  "council_type": "Mayor-council",
  "county": "Jefferson County",
  "population": 196910,
  "population_year": 2020
}'::jsonb WHERE slug = 'birmingham';

UPDATE municipalities SET metadata = '{
  "council_type": "Mayor-council",
  "county": "Mobile County",
  "population": 187041,
  "population_year": 2020
}'::jsonb WHERE slug = 'mobile';

UPDATE municipalities SET metadata = '{
  "council_type": "Mayor-council",
  "county": "Montgomery County",
  "population": 200603,
  "population_year": 2020
}'::jsonb WHERE slug = 'montgomery';

UPDATE municipalities SET metadata = '{
  "council_type": "Mayor-council",
  "county": "Jefferson County",
  "population": 92606,
  "population_year": 2020
}'::jsonb WHERE slug = 'hoover';

UPDATE municipalities SET metadata = '{
  "council_type": "Mayor-council",
  "county": "Jefferson County",
  "population": 26414,
  "population_year": 2020
}'::jsonb WHERE slug = 'homewood';

UPDATE municipalities SET metadata = '{
  "council_type": "Mayor-council",
  "county": "Jefferson County",
  "population": 39102,
  "population_year": 2020
}'::jsonb WHERE slug = 'vestavia_hills';
"""

SQL_DOWN = r"""
ALTER TABLE municipalities DROP COLUMN IF EXISTS metadata;
"""
