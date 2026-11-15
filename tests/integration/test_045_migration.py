"""Verify migration 045: the tables `committee_documents` and `committee_items`, and Birmingham's `committee_document_pages` metadata; down removes all three.

Pattern: tests/integration/test_044_migration.py. Plan `committee-documents`, M3.
The migration module and the adapter's committee table are read inside the
test functions so the file collects before the migration exists.
"""
import importlib

import psycopg2.errors
import pytest
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Migration test must not run against Railway prod.",
)

MODULE = "docket.migrations.045_committee_documents"
KEY = "committee_document_pages"
PAGES_ROOT = "https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/"
URL = "https://www.birminghamal.gov/m045/a.pdf"


@pytest.fixture
def fresh_045():
    """Every migration applied, then 045 rolled back; the teardown re-applies it."""
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 45)
    yield
    with db() as conn:
        runner.apply_migrations(conn)
    with db_cursor() as cur:
        cur.execute("DELETE FROM committee_documents WHERE url LIKE 'https://www.birminghamal.gov/m045/%'")


def _tables() -> set[str]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name IN ('committee_documents', 'committee_items')"
        )
        return {r["table_name"] for r in cur.fetchall()}


def _birmingham() -> dict:
    with db_cursor() as cur:
        cur.execute("SELECT id, metadata FROM municipalities WHERE slug = 'birmingham'")
        return cur.fetchone()


def _document(url: str = URL, **columns) -> int:
    names = ["municipality_id", "url", "page_url", "page_committee", *columns]
    values = [_birmingham()["id"], url, PAGES_ROOT + "public-safety-committee", "Public Safety", *columns.values()]
    with db_cursor() as cur:
        cur.execute(
            f"INSERT INTO committee_documents ({', '.join(names)}) "
            f"VALUES ({', '.join(['%s'] * len(names))}) RETURNING id",
            values,
        )
        return cur.fetchone()["id"]


def _item(document_id: int, position: int = 1, category: str = "recommended") -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO committee_items (document_id, position, owns_heading, name, action_text, action_category) "
            "VALUES (%s, %s, TRUE, 'Welcome Mart', 'Item Delayed.', %s) RETURNING id",
            (document_id, position, category),
        )
        return cur.fetchone()["id"]


def test_045_is_registered_in_order():
    versions = [int(m.rsplit(".", 1)[-1].split("_")[0]) for m in runner.MIGRATIONS]
    assert 45 in versions
    assert versions == sorted(versions)
    assert importlib.import_module(MODULE).SQL_DOWN.strip()


def test_045_up_creates_the_two_tables_and_the_eight_pages(fresh_045):
    from docket.adapters.committee_documents import COMMITTEE_SLUGS

    assert _tables() == set()
    before = _birmingham()["metadata"]
    assert KEY not in before

    with db() as conn:
        runner.apply_migrations(conn)

    assert _tables() == {"committee_documents", "committee_items"}
    after = _birmingham()["metadata"]
    assert after[KEY] == [{"committee": name, "url": PAGES_ROOT + slug} for name, slug in COMMITTEE_SLUGS.items()], (
        "one page for each of the eight committees, by the name and slug the adapter holds"
    )
    assert len(after[KEY]) == 8
    assert {k: v for k, v in after.items() if k != KEY} == before, "every other key is untouched"
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM municipalities WHERE metadata ? %s AND slug <> 'birmingham'", (KEY,))
        assert cur.fetchone()["n"] == 0, "Birmingham only"
        cur.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'committee_documents' AND indexdef LIKE '%%(meeting_id)%%'"
        )
        assert cur.fetchone() is not None, "an index on committee_documents (meeting_id)"

    # What a row is before anything has read it.
    doc = _document()
    with db_cursor() as cur:
        cur.execute("SELECT * FROM committee_documents WHERE id = %s", (doc,))
        row = cur.fetchone()
    assert (row["status"], row["fetch_attempts"], row["committees"]) == ("listed", 0, [])
    assert (row["listing_disagrees"], row["special"], row["work_session"]) == (False, False, False)
    assert row["first_seen_at"] is not None and row["last_seen_at"] is not None
    for column in ("listed_name", "listed_heading", "fetched_at", "pdf_sha256", "text", "kind", "meeting_date",
                   "date_source", "present", "trailing_lines", "parser_version", "meeting_id", "attached_by"):
        assert row[column] is None, column
    item = _item(doc)
    with db_cursor() as cur:
        cur.execute("SELECT body, heading_label, heading_text, group_text, moved_by, seconded_by "
                    "FROM committee_items WHERE id = %s", (item,))
        assert dict(cur.fetchone()) == {"body": "", "heading_label": None, "heading_text": None, "group_text": None,
                                        "moved_by": None, "seconded_by": None}


def test_045_each_check_admits_its_values_and_nothing_else(fresh_045):
    with db() as conn:
        runner.apply_migrations(conn)
    doc = _document()
    admitted = {
        "status": ("listed", "read", "no_text", "not_committee", "fetch_failed"),
        "kind": ("agenda", "minutes", None),
        "date_source": ("header", "heading", None),
        "attached_by": ("matched", "created", None),
    }
    for column, values in admitted.items():
        for value in values:
            with db_cursor() as cur:
                cur.execute(f"UPDATE committee_documents SET {column} = %s WHERE id = %s", (value, doc))
        with pytest.raises(psycopg2.errors.CheckViolation):
            with db_cursor() as cur:
                cur.execute(f"UPDATE committee_documents SET {column} = 'test' WHERE id = %s", (doc,))
    with pytest.raises(psycopg2.errors.NotNullViolation):
        with db_cursor() as cur:
            cur.execute("UPDATE committee_documents SET status = NULL WHERE id = %s", (doc,))

    item = _item(doc)
    for category in ("recommended", "recommended_consent", "recommended_no_quorum", "no_recommendation",
                     "recommended_deny", "information_only", "withdrawn", "tabled", "delayed", "minutes_approved",
                     "adjourned", "other"):
        with db_cursor() as cur:
            cur.execute("UPDATE committee_items SET action_category = %s WHERE id = %s", (category, item))
    with pytest.raises(psycopg2.errors.CheckViolation):
        with db_cursor() as cur:
            cur.execute("UPDATE committee_items SET action_category = 'passed' WHERE id = %s", (item,))


def test_045_one_row_per_address_and_per_position_and_items_go_with_their_document(fresh_045):
    with db() as conn:
        runner.apply_migrations(conn)
    doc = _document()
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _document()
    _item(doc, position=1)
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _item(doc, position=1)
    _item(doc, position=2)

    with db_cursor() as cur:
        cur.execute("DELETE FROM committee_documents WHERE id = %s", (doc,))
        cur.execute("SELECT count(*) AS n FROM committee_items WHERE document_id = %s", (doc,))
        assert cur.fetchone()["n"] == 0


def test_045_up_twice_is_the_same_schema_and_the_same_eight_pages(fresh_045):
    module = importlib.import_module(MODULE)
    with db() as conn:
        runner.apply_migrations(conn)
    doc = _document()
    once = _birmingham()["metadata"]
    with db_cursor() as cur:
        cur.execute(module.SQL_UP)
    assert _birmingham()["metadata"] == once
    assert len(once[KEY]) == 8
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM committee_documents WHERE id = %s", (doc,))
        assert cur.fetchone()["n"] == 1, "a second up keeps the rows"
        cur.execute("SELECT count(*) AS n FROM pg_indexes WHERE tablename = 'committee_documents'")
        assert cur.fetchone()["n"] == 3, "the primary key, the unique address, and meeting_id"


def test_045_down_removes_the_tables_and_the_key_and_nothing_else(fresh_045):
    with db() as conn:
        runner.apply_migrations(conn)
    _item(_document())
    with_key = _birmingham()["metadata"]

    with db() as conn:
        runner.rollback_migration(conn, 45)

    assert _tables() == set()
    after = _birmingham()["metadata"]
    assert KEY not in after
    assert after == {k: v for k, v in with_key.items() if k != KEY}
    assert after["calendar_url"] == "https://www.birminghamal.gov/government/city-council", "038's key is untouched"
