"""Verify migration 041: `agenda_item_search_cards`, `transcript_card_runs`, and the search trigger function that folds a card's hidden text into `agenda_items.search_vector`; down removes the tables and restores migration 015's function.

Pattern: tests/integration/test_040_migration.py. Plan: plans/completed/search-finds-what-was-said.md (M2).

The migration module is imported inside the fixtures and tests, not at the
top of this file, so the file collects before the migration exists.
"""
import importlib
import re
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

PREFIX = "m041-"
TABLES = ("agenda_item_search_cards", "transcript_card_runs")
FUNCTION = "agenda_items_search_update"


def _m041():
    return importlib.import_module("docket.migrations.041_search_cards")


def _m015():
    return importlib.import_module("docket.migrations.015_search_vector_v3")


@pytest.fixture(scope="module", autouse=True)
def ensure_041_function():
    """Install 041's function body before this file's tests.

    `test_013_up_down_up_cycle` rolls migration 013 back and re-applies only
    what is missing from `schema_migrations`, which leaves the trigger
    function at 013's body for every file that runs after it;
    `tests/integration/test_search_vector_v3.py` re-executes 015 for the same
    reason. 041's `SQL_UP` is idempotent, so executing it again is safe.
    """
    with db() as conn:
        runner.apply_migrations(conn)
        with conn.cursor() as cur:
            cur.execute(_m041().SQL_UP)


def _cleanup() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (PREFIX + "%",))


@pytest.fixture
def fresh_041():
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 41)
    yield
    with db() as conn:
        runner.apply_migrations(conn)
    _cleanup()


@pytest.fixture
def seeded():
    """One Birmingham meeting with a public transcript and two agenda items, on the migrated schema."""
    with db() as conn:
        runner.apply_migrations(conn)
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
            "VALUES (%s, %s, 'M041 test meeting', %s) RETURNING id",
            (muni, PREFIX + "seeded", date(2026, 5, 5)),
        )
        meeting_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO transcripts (meeting_id, status, uploaded_at) VALUES (%s, 'events_extracted', now()) "
            "RETURNING id, uploaded_at",
            (meeting_id,),
        )
        transcript = cur.fetchone()
        items = []
        for title in ("Resolution approving a paving contract", "Ordinance amending the zoning map"):
            cur.execute("INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id", (meeting_id, title))
            items.append(cur.fetchone()["id"])
    yield {"meeting_id": meeting_id, "transcript_id": transcript["id"], "uploaded_at": transcript["uploaded_at"],
           "items": items}
    _cleanup()


def _tables_present() -> set[str]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = ANY(%s)",
            (list(TABLES),),
        )
        return {r["table_name"] for r in cur.fetchall()}


def _function_source() -> str:
    with db_cursor() as cur:
        cur.execute("SELECT prosrc FROM pg_proc WHERE proname = %s", (FUNCTION,))
        rows = cur.fetchall()
    assert len(rows) == 1, "exactly one function of that name"
    return rows[0]["prosrc"]


def _insert_card(s: dict, item_id: int, *, start_seq=None, end_seq=None, search_b="", search_c="") -> None:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO agenda_item_search_cards "
            "(agenda_item_id, transcript_id, source_uploaded_at, prompt_version, model, discussed, "
            " start_seq, end_seq, card, search_b, search_c) "
            "VALUES (%s, %s, %s, 200, 'test-model', TRUE, %s, %s, '{}'::jsonb, %s, %s)",
            (item_id, s["transcript_id"], s["uploaded_at"], start_seq, end_seq, search_b, search_c),
        )


def _card_count(item_id: int) -> int:
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM agenda_item_search_cards WHERE agenda_item_id = %s", (item_id,))
        return cur.fetchone()["n"]


def _vector_text(item_id: int) -> str:
    with db_cursor() as cur:
        cur.execute("SELECT search_vector::text AS v FROM agenda_items WHERE id = %s", (item_id,))
        return cur.fetchone()["v"]


def _terms(sql: str) -> list[str]:
    """The `setweight(...)` terms of the trigger function in a migration's SQL, whitespace collapsed, in order."""
    body = sql.split("$$")[1]
    assignment = body.split("NEW.search_vector :=", 1)[1].split(";", 1)[0]
    return [re.sub(r"\s+", " ", t).strip() for t in assignment.split("||")]


def test_041_is_registered_directly_after_040():
    # Registered in number order; later migrations (042 onward) may follow it.
    i = runner.MIGRATIONS.index("docket.migrations.041_search_cards")
    assert runner.MIGRATIONS[i - 1] == "docket.migrations.040_youtube_recordings"


def test_041_function_keeps_every_015_term_and_adds_two():
    """The up body is 015's, term for term, with the card's two texts appended at B and C."""
    old, new = _terms(_m015().SQL_UP), _terms(_m041().SQL_UP)
    assert len(old) == 10
    assert new[:len(old)] == old
    assert new[len(old):] == [
        "setweight(to_tsvector('english', coalesce(card_b, '')), 'B')",
        "setweight(to_tsvector('english', coalesce(card_c, '')), 'C')",
    ]


def test_041_holds_no_update_of_existing_rows():
    assert not re.search(r"^\s*(UPDATE|DELETE|INSERT)\b", _m041().SQL_UP, flags=re.MULTILINE | re.IGNORECASE)


def test_041_down_removes_tables_and_restores_015_function(fresh_041):
    assert _tables_present() == set()
    source = _function_source()
    assert source == _m015().SQL_UP.split("$$")[1], "the function body is migration 015's, exactly"
    assert "agenda_item_search_cards" not in source

    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
            "VALUES (%s, %s, 'M041 down meeting', %s) RETURNING id",
            (muni, PREFIX + "down", date(2026, 5, 5)),
        )
        meeting_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO agenda_items (meeting_id, title, headline) "
            "VALUES (%s, 'Resolution on zeppelin moorings', 'Council funds dirigible hangar') RETURNING id",
            (meeting_id,),
        )
        item_id = cur.fetchone()["id"]
        cur.execute(
            "SELECT search_vector @@ plainto_tsquery('english', 'zeppelin') AS title_hit, "
            "       search_vector @@ plainto_tsquery('english', 'dirigible') AS headline_hit "
            "FROM agenda_items WHERE id = %s",
            (item_id,),
        )
        row = cur.fetchone()
    assert row["title_hit"] and row["headline_hit"], "an item insert still fills search_vector after the down"


def test_041_up_creates_tables_index_and_function(fresh_041):
    assert _tables_present() == set()

    with db() as conn:
        runner.apply_migrations(conn)

    assert _tables_present() == set(TABLES)
    assert "agenda_item_search_cards" in _function_source()
    with db_cursor() as cur:
        cur.execute("SELECT to_regclass('public.idx_search_cards_transcript') AS idx")
        assert cur.fetchone()["idx"] is not None
        cur.execute("SELECT count(*) AS n FROM pg_trigger WHERE tgrelid = 'agenda_items'::regclass AND NOT tgisinternal")
        assert cur.fetchone()["n"] == 1, "still the only trigger on agenda_items"


def test_041_sql_up_can_be_executed_again_and_keeps_rows(seeded):
    item_id = seeded["items"][0]
    _insert_card(seeded, item_id, search_b="zeppelin")
    with db() as conn, conn.cursor() as cur:
        cur.execute(_m041().SQL_UP)
        cur.execute(_m041().SQL_UP)
    assert _card_count(item_id) == 1
    assert _tables_present() == set(TABLES)


def test_041_check_refuses_a_card_with_only_one_bound(seeded):
    first, second = seeded["items"]
    with pytest.raises(psycopg2.errors.CheckViolation):
        _insert_card(seeded, first, start_seq=5)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _insert_card(seeded, first, end_seq=9)
    _insert_card(seeded, first, start_seq=5, end_seq=9)
    _insert_card(seeded, second)
    assert _card_count(first) == 1 and _card_count(second) == 1


def test_041_one_card_per_item(seeded):
    item_id = seeded["items"][0]
    _insert_card(seeded, item_id)
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _insert_card(seeded, item_id)


def test_041_deleting_an_agenda_item_removes_its_card(seeded):
    first, second = seeded["items"]
    _insert_card(seeded, first)
    _insert_card(seeded, second)
    with db_cursor() as cur:
        cur.execute("DELETE FROM agenda_items WHERE id = %s", (first,))
    assert _card_count(first) == 0
    assert _card_count(second) == 1


def test_041_deleting_a_transcript_removes_its_cards_and_its_run(seeded):
    item_id = seeded["items"][0]
    _insert_card(seeded, item_id)
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO transcript_card_runs (transcript_id, meeting_id, source_uploaded_at, prompt_version, status) "
            "VALUES (%s, %s, %s, 200, 'done')",
            (seeded["transcript_id"], seeded["meeting_id"], seeded["uploaded_at"]),
        )
        cur.execute("DELETE FROM transcripts WHERE id = %s", (seeded["transcript_id"],))
        cur.execute("SELECT count(*) AS n FROM transcript_card_runs WHERE transcript_id = %s", (seeded["transcript_id"],))
        assert cur.fetchone()["n"] == 0
    assert _card_count(item_id) == 0


def test_041_run_status_is_one_of_four(seeded):
    with pytest.raises(psycopg2.errors.CheckViolation), db_cursor() as cur:
        cur.execute(
            "INSERT INTO transcript_card_runs (transcript_id, meeting_id, source_uploaded_at, prompt_version, status) "
            "VALUES (%s, %s, %s, 200, 'compared')",
            (seeded["transcript_id"], seeded["meeting_id"], seeded["uploaded_at"]),
        )
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO transcript_card_runs (transcript_id, meeting_id, source_uploaded_at, prompt_version, status) "
            "VALUES (%s, %s, %s, 200, 'claimed') RETURNING attempts, counts, last_error",
            (seeded["transcript_id"], seeded["meeting_id"], seeded["uploaded_at"]),
        )
        row = cur.fetchone()
    assert row["attempts"] == 0 and row["counts"] == {} and row["last_error"] is None


def test_041_trigger_folds_card_text_into_the_vector_at_b_and_c(seeded):
    """The function reads the item's card row whenever the item row is written."""
    item_id = seeded["items"][0]
    assert "zeppelin" not in _vector_text(item_id)
    _insert_card(seeded, item_id, search_b="zeppelin moorings", search_c="dirigible hangar")
    assert "zeppelin" not in _vector_text(item_id), "writing a card row alone does not touch the item"

    with db_cursor() as cur:
        cur.execute("UPDATE agenda_items SET search_vector = search_vector WHERE id = %s", (item_id,))
    vector = _vector_text(item_id)
    assert re.search(r"'zeppelin':\d+B", vector), vector
    assert re.search(r"'hangar':\d+C", vector), vector
    assert re.search(r"'resolut':\d+A", vector), "the title stays at weight A"

    with db_cursor() as cur:
        cur.execute("DELETE FROM agenda_item_search_cards WHERE agenda_item_id = %s", (item_id,))
        cur.execute("UPDATE agenda_items SET search_vector = search_vector WHERE id = %s", (item_id,))
    assert "zeppelin" not in _vector_text(item_id)
