"""Verify migration 050: what a minutes reader stores, and Scott Jones's row from the roll calls read.

Pattern: tests/integration/test_048_migration.py and test_049_migration.py. Plan
`mobile-votes-from-minutes`, M2. The migration module and the runner's list are read inside the
test functions, so the file collects before the migration exists.

The migration adds five columns to `votes` (which reader wrote the row, the page, the caption, the
motion, the declaration), the table `minutes_files` (one row per Minutes file a reader has read),
and `council_members.aliases`; and it gives Scott Jones's row the alias "Scott" and the end of term
the roll calls show. Every meeting whose external id begins `m050-` and every member whose name
begins `M050 ` is built by a test.
"""
import importlib
from datetime import date

import psycopg2.errors
import pytest
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Migration test must not run against Railway prod.",
)

PREFIX = "m050-"
TEST_NAMES = "M050 %"
MODULE = "docket.migrations.050_minutes_votes"

VOTE_COLUMNS = {
    "minutes_reader": "text",
    "source_page": "integer",
    "caption": "text",
    "motion_text": "text",
    "declared_text": "text",
}


def _delete_test_rows() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (PREFIX + "%",))
        cur.execute("DELETE FROM council_members WHERE name LIKE %s", (TEST_NAMES,))
        cur.execute("SELECT to_regclass('minutes_files') AS t")
        if cur.fetchone()["t"] is not None:
            cur.execute("DELETE FROM minutes_files WHERE file_id LIKE %s", (PREFIX + "%",))


@pytest.fixture
def fresh_050():
    """Every migration applied, then 050 rolled back; the teardown re-applies it."""
    _delete_test_rows()
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 50)
    yield
    _delete_test_rows()
    with db() as conn:
        runner.apply_migrations(conn)


@pytest.fixture
def applied_050():
    _delete_test_rows()
    with db() as conn:
        runner.apply_migrations(conn)
    yield
    _delete_test_rows()
    with db() as conn:
        runner.apply_migrations(conn)


def _city_id(slug: str) -> int:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = %s", (slug,))
        return cur.fetchone()["id"]


def _columns(table: str) -> dict[str, tuple[str, str, str | None]]:
    """column -> (type, nullable, default) for one table."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s", (table,))
        return {r["column_name"]: (r["data_type"], r["is_nullable"], r["column_default"]) for r in cur.fetchall()}


def _table_exists() -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT to_regclass('minutes_files') AS t")
        return cur.fetchone()["t"] is not None


def _terms(slug: str = "mobile") -> list[tuple]:
    """name, term_start, term_end, active of one city's members, by name."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT cm.name, cm.term_start, cm.term_end, cm.active FROM council_members cm "
            "JOIN municipalities mu ON mu.id = cm.municipality_id WHERE mu.slug = %s ORDER BY cm.name, cm.id",
            (slug,))
        return [(r["name"], r["term_start"], r["term_end"], r["active"]) for r in cur.fetchall()]


def _aliases(slug: str = "mobile") -> dict[str, list[str]]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT cm.name, cm.aliases FROM council_members cm "
            "JOIN municipalities mu ON mu.id = cm.municipality_id WHERE mu.slug = %s", (slug,))
        return {r["name"]: r["aliases"] for r in cur.fetchall()}


def _jones() -> tuple:
    return next(row for row in _terms() if row[0] == "Scott Jones")


def _meeting(tag: str, slug: str = "mobile") -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type) "
            "VALUES (%s, %s, 'City Council', %s, 'council') RETURNING id",
            (_city_id(slug), PREFIX + tag, date(2026, 11, 3)),
        )
        return cur.fetchone()["id"]


def _file(tag: str, *, status: str = "paired", meeting_id: int | None = None, slug: str = "mobile",
          extra: dict | None = None) -> int:
    """One `minutes_files` row naming only the columns that have no default; its id."""
    values = {
        "municipality_id": _city_id(slug),
        "file_id": PREFIX + tag,
        "url": "https://example.invalid/" + tag,
        "event_external_id": "499",
        "status": status,
        "meeting_id": meeting_id,
        "reader_version": 1,
        **(extra or {}),
    }
    with db_cursor() as cur:
        cur.execute(
            f"INSERT INTO minutes_files ({', '.join(values)}) VALUES ({', '.join(['%s'] * len(values))}) "
            "RETURNING id",
            list(values.values()),
        )
        return cur.fetchone()["id"]


def _file_row(file_row_id: int) -> dict:
    with db_cursor() as cur:
        cur.execute(
            "SELECT status, header_date, meeting_id, page_count, votes_stored, reader_version, attempts, error, "
            "       read_at > now() - interval '1 minute' AS fresh FROM minutes_files WHERE id = %s",
            (file_row_id,))
        return dict(cur.fetchone())


def _bystanders() -> None:
    """Members the roster statement must not touch: a Jones of another city, and Mobile names that only hold `Jones`."""
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO council_members (municipality_id, name, term_start, term_end, active) VALUES "
            "(%(v)s, 'M050 Jones', '2020-01-01', '2023-08-08', TRUE), "
            "(%(m)s, 'M050 Jonesboro', '2020-01-01', '2023-08-08', TRUE), "
            "(%(m)s, 'M050 Mcjones', '2020-01-01', '2023-08-08', TRUE)",
            {"v": _city_id("vestavia_hills"), "m": _city_id("mobile")},
        )


def test_050_up_adds_the_columns_the_table_and_the_alias(fresh_050):
    versions = [int(m.rsplit(".", 1)[-1].split("_")[0]) for m in runner.MIGRATIONS]
    assert MODULE in runner.MIGRATIONS and versions == sorted(versions)
    assert not set(VOTE_COLUMNS) & set(_columns("votes"))
    assert "aliases" not in _columns("council_members")
    assert not _table_exists()
    assert _jones() == ("Scott Jones", date(2021, 11, 2), date(2023, 8, 8), False)
    terms_before = [row for row in _terms() if row[0] != "Scott Jones"]
    others_before = [_terms(slug) for slug in ("birmingham", "vestavia_hills", "homewood")]
    _bystanders()

    with db() as conn:
        runner.apply_migrations(conn)

    votes = _columns("votes")
    assert {name: votes[name] for name in VOTE_COLUMNS} == {
        name: (kind, "YES", None) for name, kind in VOTE_COLUMNS.items()}
    kind, nullable, default = _columns("council_members")["aliases"]
    assert (kind, nullable) == ("ARRAY", "NO") and default.startswith("'{}'")
    assert _table_exists()
    # Scott Jones answers to "Scott" and his term ends with the first roll call that does not list him.
    assert _jones() == ("Scott Jones", date(2021, 11, 2), date(2023, 4, 11), False)
    aliases = _aliases()
    assert aliases.pop("Scott Jones") == ["Scott"]
    # Nobody else has an alias or a moved date: not a Mobile name that only holds `Jones`, not another city's Jones.
    assert aliases and all(value == [] for value in aliases.values()), aliases
    assert [row for row in _terms() if row[0] not in ("Scott Jones", "M050 Jonesboro", "M050 Mcjones")] == terms_before
    assert [row for row in _terms() if row[0].startswith("M050 ")] == [
        ("M050 Jonesboro", date(2020, 1, 1), date(2023, 8, 8), True),
        ("M050 Mcjones", date(2020, 1, 1), date(2023, 8, 8), True),
    ]
    assert _aliases("vestavia_hills")["M050 Jones"] == []
    assert [row for row in _terms("vestavia_hills") if row[0] == "M050 Jones"] == [
        ("M050 Jones", date(2020, 1, 1), date(2023, 8, 8), True)]
    with db_cursor() as cur:
        cur.execute("DELETE FROM council_members WHERE name LIKE %s", (TEST_NAMES,))
    assert [_terms(slug) for slug in ("birmingham", "vestavia_hills", "homewood")] == others_before


def test_050_a_second_up_changes_nothing(applied_050):
    meeting = _meeting("A")
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions, confidence, needs_review, "
            "                   minutes_reader, source_page, caption, motion_text, declared_text) "
            "VALUES (%s, 'minutes_text', 'passed', 7, 0, 0, 'high', FALSE, "
            "        'mobile', 5, 'A CAPTION', 'Councilmember A moved', 'the resolution adopted') RETURNING id",
            (meeting,))
        vote = cur.fetchone()["id"]
    file_row = _file("A", meeting_id=meeting, extra={"votes_stored": 40, "page_count": 61})
    before = (_terms(), _aliases(), _file_row(file_row), _columns("votes"), _columns("council_members"),
              _columns("minutes_files"))

    with db_cursor() as cur:
        cur.execute(importlib.import_module(MODULE).SQL_UP)

    assert (_terms(), _aliases(), _file_row(file_row), _columns("votes"), _columns("council_members"),
            _columns("minutes_files")) == before
    with db_cursor() as cur:
        cur.execute("SELECT minutes_reader, source_page, caption, motion_text, declared_text FROM votes WHERE id = %s",
                    (vote,))
        assert dict(cur.fetchone()) == dict(minutes_reader="mobile", source_page=5, caption="A CAPTION",
                                            motion_text="Councilmember A moved",
                                            declared_text="the resolution adopted")


def test_050_a_file_row_takes_its_defaults_and_is_one_per_city_and_file(applied_050):
    first = _file("A", status="not_minutes")
    assert _file_row(first) == dict(status="not_minutes", header_date=None, meeting_id=None, page_count=None,
                                    votes_stored=0, reader_version=1, attempts=1, error=None, fresh=True)
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _file("A", status="error")
    # The same file id under another city is another file.
    _file("A", status="error", slug="vestavia_hills")
    with pytest.raises(psycopg2.errors.CheckViolation):
        _file("B", status="read")
    for status in ("paired", "superseded", "not_minutes", "no_meeting", "error"):
        _file("status-" + status, status=status)
    for column in ("municipality_id", "file_id", "url", "event_external_id", "status", "reader_version",
                   "votes_stored", "attempts", "read_at"):
        with pytest.raises(psycopg2.errors.NotNullViolation):
            _file("null-" + column, extra={column: None})
    # A city that is deleted takes its file rows with it.
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO municipalities (slug, name, state, adapter_class, active) "
            "VALUES ('m050-city', 'M050 City', 'AL', 'CivicClerkAdapter', FALSE)")
    try:
        gone = _file("A", status="no_meeting", slug="m050-city")
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM municipalities WHERE slug = 'm050-city'")
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM minutes_files WHERE id = %s", (gone,))
        assert cur.fetchone()["n"] == 0


def test_050_a_meeting_has_one_paired_file_and_keeps_its_file_rows_when_it_goes(applied_050):
    meeting = _meeting("A")
    paired = _file("A", meeting_id=meeting)
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _file("B", meeting_id=meeting)
    # Any number of files that lost the meeting may name it.
    _file("C", status="superseded", meeting_id=meeting)
    _file("D", status="superseded", meeting_id=meeting)
    # Paired rows that name no meeting do not collide.
    with db_cursor() as cur:
        cur.execute("UPDATE minutes_files SET status = 'superseded' WHERE id = %s", (paired,))
    replacement = _file("B", meeting_id=meeting)

    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id = %s", (meeting,))
    assert _file_row(replacement)["meeting_id"] is None and _file_row(replacement)["status"] == "paired"
    assert _file_row(paired)["meeting_id"] is None


def test_050_roster_sql_alone_puts_the_row_right(applied_050):
    """`ROSTER_SQL` is what tests/integration/test_049_migration.py runs after it re-applies 049."""
    with db_cursor() as cur:
        cur.execute(
            "UPDATE council_members SET aliases = '{}', term_end = DATE '2023-08-08' "
            "WHERE municipality_id = %s AND name = 'Scott Jones'", (_city_id("mobile"),))
        assert cur.rowcount == 1
    _bystanders()
    module = importlib.import_module(MODULE)
    assert module.ROSTER_SQL.strip() and module.ROSTER_SQL in module.SQL_UP

    with db_cursor() as cur:
        cur.execute(module.ROSTER_SQL)
        assert cur.rowcount == 1

    assert _jones() == ("Scott Jones", date(2021, 11, 2), date(2023, 4, 11), False)
    assert _aliases()["Scott Jones"] == ["Scott"]
    assert _aliases()["M050 Jonesboro"] == [] and _aliases("vestavia_hills")["M050 Jones"] == []

    # The row is found by its whole-word surname however it is spelled, as migration 049 finds it.
    mobile = _city_id("mobile")
    try:
        for spelling in ("Jones", "Scott Jones Jr."):
            with db_cursor() as cur:
                cur.execute(
                    "UPDATE council_members SET name = %s, aliases = '{}', term_end = DATE '2023-08-08' "
                    "WHERE municipality_id = %s AND 'Scott' = ANY(aliases)", (spelling, mobile))
                assert cur.rowcount == 1, spelling
                cur.execute(module.ROSTER_SQL)
                assert cur.rowcount == 1, spelling
            assert next(row for row in _terms() if row[0] == spelling) == (
                spelling, date(2021, 11, 2), date(2023, 4, 11), False)
            assert _aliases()[spelling] == ["Scott"]
    finally:
        with db_cursor() as cur:
            cur.execute(
                "UPDATE council_members SET name = 'Scott Jones', aliases = ARRAY['Scott'], "
                "term_end = DATE '2023-04-11' WHERE municipality_id = %s AND name IN ('Jones', 'Scott Jones Jr.')",
                (mobile,))
    assert _jones() == ("Scott Jones", date(2021, 11, 2), date(2023, 4, 11), False)


def test_050_down_removes_all_of_it_and_the_up_applies_again(applied_050):
    meeting = _meeting("A")
    _file("A", meeting_id=meeting)
    _bystanders()
    # Another city's Jones, on a date of his own: the down moves no date outside Mobile.
    with db_cursor() as cur:
        cur.execute("UPDATE council_members SET term_end = DATE '2024-01-01' WHERE name = 'M050 Jones'")
        assert cur.rowcount == 1
    terms_before = _terms()

    with db() as conn:
        runner.rollback_migration(conn, 50)
    assert [row for row in _terms("vestavia_hills") if row[0] == "M050 Jones"] == [
        ("M050 Jones", date(2020, 1, 1), date(2024, 1, 1), True)]

    with db() as conn:
        assert 50 not in runner.applied_versions(conn)
    assert not set(VOTE_COLUMNS) & set(_columns("votes"))
    assert "aliases" not in _columns("council_members")
    assert not _table_exists()
    assert _jones() == ("Scott Jones", date(2021, 11, 2), date(2023, 8, 8), False)
    # Only his date moved back.
    assert [row for row in _terms() if row[0] != "Scott Jones"] == [
        row for row in terms_before if row[0] != "Scott Jones"]
    # The down is harmless to repeat on a database that no longer holds any of it.
    with db_cursor() as cur:
        cur.execute(importlib.import_module(MODULE).SQL_DOWN)
    assert _jones() == ("Scott Jones", date(2021, 11, 2), date(2023, 8, 8), False)

    with db() as conn:
        runner.apply_migrations(conn)

    assert _terms() == terms_before
    assert _aliases()["Scott Jones"] == ["Scott"]
    assert set(VOTE_COLUMNS) <= set(_columns("votes")) and _table_exists()
    _file("A", meeting_id=meeting)   # the down dropped the rows with the table
