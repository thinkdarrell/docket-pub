"""Verify migration 029 (municipalities.metadata JSONB column) + seed data.

Local dev DB may only have a subset of the 6 production cities (e.g. no
montgomery / hoover rows). Tests that touch seed data assert on cities
that are guaranteed to exist locally (birmingham, homewood, mobile,
vestavia_hills) and only check that *any* seeded city has valid metadata.
The all-six-cities check queries by slug and asserts on whatever rows
are present rather than hard-coding a count of 6.
"""
import importlib

from docket.db import db_cursor


_m029 = importlib.import_module("docket.migrations.029_municipalities_metadata")

# Slugs written by the migration — local DB may be missing montgomery/hoover.
_ALL_SEEDED_SLUGS = (
    "birmingham",
    "mobile",
    "montgomery",
    "hoover",
    "homewood",
    "vestavia_hills",
)


def test_029_metadata_column_exists_and_is_jsonb():
    """After migrations applied, municipalities.metadata is JSONB NOT NULL DEFAULT '{}'."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'municipalities' AND column_name = 'metadata'
        """)
        row = cur.fetchone()
    assert row is not None, "metadata column missing"
    assert row["data_type"] == "jsonb"
    assert row["is_nullable"] == "NO"
    assert "'{}'" in (row["column_default"] or "")


def test_029_birmingham_metadata_seeded():
    """Birmingham has council_type / county / population populated."""
    with db_cursor() as cur:
        cur.execute("SELECT metadata FROM municipalities WHERE slug = 'birmingham'")
        row = cur.fetchone()
    assert row is not None
    md = row["metadata"]
    assert md.get("council_type") == "Mayor-council"
    assert md.get("county") == "Jefferson County"
    assert md.get("population") == 196910
    assert md.get("population_year") == 2020


def test_029_seeded_cities_have_metadata():
    """All seeded cities present in this DB have non-empty metadata.

    Local dev may only have a subset of the 6 production cities, so we
    assert on whatever rows are present rather than checking count == 6.
    At least 1 city (birmingham) must be present.
    """
    with db_cursor() as cur:
        cur.execute("""
            SELECT slug, metadata FROM municipalities
            WHERE slug = ANY(%s)
            ORDER BY slug
        """, (list(_ALL_SEEDED_SLUGS),))
        rows = cur.fetchall()
    assert len(rows) >= 1, "expected at least birmingham in the DB"
    for r in rows:
        md = r["metadata"]
        assert "council_type" in md, f"{r['slug']} missing council_type"
        assert "county" in md, f"{r['slug']} missing county"
        assert "population" in md, f"{r['slug']} missing population"


def test_029_sql_down_drops_column():
    """SQL_DOWN string contains the DROP statement."""
    assert "DROP COLUMN" in _m029.SQL_DOWN.upper()
    assert "metadata" in _m029.SQL_DOWN.lower()
