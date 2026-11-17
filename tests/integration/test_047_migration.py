"""Verify migration 047: `public_hearings`, `public_hearing_items`, and Birmingham's `coming_up` flag; down removes all three.

Pattern: tests/integration/test_043_migration.py. Nothing here says anything
about another city's metadata (`D122`). Plan `birmingham-coming-up`, M2.
"""
import importlib

import psycopg2
import pytest
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Migration test must not run against Railway prod.",
)

TABLES = ("public_hearings", "public_hearing_items")


@pytest.fixture
def fresh_047():
    """Every migration applied, then 047 rolled back; the teardown re-applies it."""
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 47)
    yield
    with db() as conn:
        runner.apply_migrations(conn)


def _tables() -> set[str]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = ANY(%s)",
            (list(TABLES),),
        )
        return {r["table_name"] for r in cur.fetchall()}


def _birmingham() -> dict:
    with db_cursor() as cur:
        cur.execute("SELECT id, metadata FROM municipalities WHERE slug = 'birmingham'")
        return dict(cur.fetchone())


def _apply() -> None:
    with db() as conn:
        runner.apply_migrations(conn)


def _rollback() -> None:
    with db() as conn:
        runner.rollback_migration(conn, 47)


def test_047_is_registered_in_order():
    versions = [int(m.rsplit(".", 1)[-1].split("_")[0]) for m in runner.MIGRATIONS]
    assert 47 in versions
    assert versions == sorted(versions)
    assert importlib.import_module("docket.migrations.047_public_hearings").SQL_DOWN.strip()


def test_047_up_creates_both_tables_and_flags_birmingham(fresh_047):
    assert _tables() == set()
    assert "coming_up" not in _birmingham()["metadata"]

    _apply()

    assert _tables() == set(TABLES)
    meta = _birmingham()["metadata"]
    assert meta["coming_up"] is True
    assert meta.get("briefing") is True, "037's key is untouched"


def test_047_kind_is_the_readers_vocabulary(fresh_047):
    """The CHECK is frozen text; its owner is `KINDS` in the reader."""
    from docket.enrichment.hearings import KINDS

    _apply()
    city = _birmingham()["id"]
    try:
        with db_cursor() as cur:
            for n, kind in enumerate(KINDS):
                cur.execute(
                    "INSERT INTO public_hearings (municipality_id, hearing_date, kind, subject, subject_key, rule_version) "
                    "VALUES (%s, '2031-01-01', %s, 'm047', %s, 1)",
                    (city, kind, f"m047{n}"),
                )
        with pytest.raises(psycopg2.errors.CheckViolation):
            with db_cursor() as cur:
                cur.execute(
                    "INSERT INTO public_hearings (municipality_id, hearing_date, kind, subject, subject_key, rule_version) "
                    "VALUES (%s, '2031-01-01', 'licence', 'm047', 'm047x', 1)",
                    (city,),
                )
        with pytest.raises(psycopg2.errors.UniqueViolation):
            with db_cursor() as cur:
                cur.execute(
                    "INSERT INTO public_hearings (municipality_id, hearing_date, kind, subject, subject_key, rule_version) "
                    "VALUES (%s, '2031-01-01', %s, 'm047 again', 'm0470', 1)",
                    (city, KINDS[0]),
                )
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM public_hearings WHERE subject LIKE 'm047%'")


def test_047_an_item_links_to_one_hearing_and_the_links_cascade(fresh_047):
    _apply()
    city = _birmingham()["id"]
    try:
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES (%s, 'm047-meeting', 'M047_TEST_ meeting', '2031-01-01') RETURNING id",
                (city,),
            )
            meeting = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, external_id, title) VALUES (%s, 'm047-a', 'a') RETURNING id",
                (meeting,),
            )
            item = cur.fetchone()["id"]
            hearings = []
            for key in ("m047a", "m047b"):
                cur.execute(
                    "INSERT INTO public_hearings (municipality_id, hearing_date, kind, subject, subject_key, rule_version) "
                    "VALUES (%s, '2031-01-01', 'other', 'm047', %s, 1) RETURNING id",
                    (city, key),
                )
                hearings.append(cur.fetchone()["id"])
            cur.execute("INSERT INTO public_hearing_items (agenda_item_id, hearing_id) VALUES (%s, %s)", (item, hearings[0]))
        with pytest.raises(psycopg2.errors.UniqueViolation):
            with db_cursor() as cur:
                cur.execute(
                    "INSERT INTO public_hearing_items (agenda_item_id, hearing_id) VALUES (%s, %s)", (item, hearings[1])
                )
        with db_cursor() as cur:
            cur.execute("DELETE FROM public_hearings WHERE id = %s", (hearings[0],))
            cur.execute("SELECT count(*) AS n FROM public_hearing_items WHERE agenda_item_id = %s", (item,))
            assert cur.fetchone()["n"] == 0, "deleting a hearing removes its links"
            cur.execute("INSERT INTO public_hearing_items (agenda_item_id, hearing_id) VALUES (%s, %s)", (item, hearings[1]))
            cur.execute("DELETE FROM meetings WHERE id = %s", (meeting,))
            cur.execute("SELECT count(*) AS n FROM public_hearing_items WHERE hearing_id = %s", (hearings[1],))
            assert cur.fetchone()["n"] == 0, "deleting an item removes its link"
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE external_id = 'm047-meeting'")
            if _tables():
                cur.execute("DELETE FROM public_hearings WHERE subject LIKE 'm047%'")


def test_047_down_removes_the_tables_and_the_key(fresh_047):
    _apply()
    _rollback()
    assert _tables() == set()
    meta = _birmingham()["metadata"]
    assert "coming_up" not in meta
    assert meta.get("briefing") is True, "037's key survives the down"
    assert "calendar_url" in meta, "038's key survives the down"


def test_047_up_down_up(fresh_047):
    _apply()
    _rollback()
    _apply()
    assert _tables() == set(TABLES)
    assert _birmingham()["metadata"]["coming_up"] is True
    _apply()
    assert _tables() == set(TABLES), "a second up changes nothing"
