"""The search-card store: `write_cards` replaces a transcript's cards and refreshes those items' search vectors.

Plan: plans/completed/search-finds-what-was-said.md (M2). Nothing here calls a
model; the cards are written by hand.

`docket.ai.transcripts.cards` and the migration module are imported inside
the fixtures and tests, not at the top of this file, so the file collects
before either exists.
"""
import importlib
from datetime import date, timedelta

import psycopg2.errors
import pytest

from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)

EXTERNAL_ID = "999941"
MODEL = "test-model"
VERSION = 200


def _cards():
    return importlib.import_module("docket.ai.transcripts.cards")


@pytest.fixture(scope="module", autouse=True)
def ensure_041_function():
    """Install 041's trigger function before this file's tests.

    `test_013_up_down_up_cycle` in `tests/integration/test_migration_013.py`
    leaves the function at migration 013's body for every file that runs
    after it, and this file sorts after it. 041's `SQL_UP` is idempotent.
    """
    m041 = importlib.import_module("docket.migrations.041_search_cards")
    with db() as conn:
        runner.apply_migrations(conn)
        with conn.cursor() as cur:
            cur.execute(m041.SQL_UP)


@pytest.fixture
def seeded():
    """A Birmingham meeting, two items with the same title, a public transcript, and segments filed under each item."""
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE external_id = %s", [EXTERNAL_ID])
        cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, external_id, video_url)
                       VALUES (%s, 'Cards store test', %s, %s, 'https://x/v') RETURNING id""",
                    [muni, date(2026, 5, 5), EXTERNAL_ID])
        mid = cur.fetchone()["id"]
        cur.execute("INSERT INTO processing_status (meeting_id) VALUES (%s)", [mid])
        items = []
        for number in ("1", "2"):
            cur.execute("""INSERT INTO agenda_items (meeting_id, item_number, title)
                           VALUES (%s, %s, 'Resolution approving a street paving contract') RETURNING id""",
                        [mid, number])
            items.append(cur.fetchone()["id"])
        cur.execute("""INSERT INTO transcripts (meeting_id, status, uploaded_at)
                       VALUES (%s, 'events_extracted', now()) RETURNING id, uploaded_at""", [mid])
        tr = cur.fetchone()
        cur.execute("""INSERT INTO transcript_segments (transcript_id, seq, start_s, end_s, text, cluster_label,
                                                        agenda_item_id, assignment_method)
                       VALUES (%s, 0, 10, 14, 'item one is a paving contract', 'S0', %s, 'index_point'),
                              (%s, 1, 14, 17, 'they flew a balloon over the site', 'S1', %s, 'index_point'),
                              (%s, 2, 17, 20, 'item two is another paving contract', 'S0', %s, 'index_point')""",
                    [tr["id"], items[0], tr["id"], items[0], tr["id"], items[1]])
    yield {"meeting_id": mid, "transcript_id": tr["id"], "uploaded_at": tr["uploaded_at"], "a": items[0], "b": items[1]}
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id = %s", [mid])


def _card(item_id: int, *, search_b: str = "", search_c: str = "", discussed: bool = True,
          start_seq=None, end_seq=None, start_s=None, end_s=None, card: dict | None = None) -> dict:
    return {"item_id": item_id, "discussed": discussed, "start_seq": start_seq, "end_seq": end_seq,
            "start_s": start_s, "end_s": end_s, "card": card if card is not None else {"aliases": []},
            "search_b": search_b, "search_c": search_c}


def _write(s: dict, cards: list[dict], *, uploaded_at=None) -> int:
    return _cards().write_cards(s["transcript_id"], uploaded_at or s["uploaded_at"], cards,
                                model=MODEL, prompt_version=VERSION)


def _matches(item_id: int, word: str) -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT search_vector @@ plainto_tsquery('english', %s) AS hit FROM agenda_items WHERE id = %s",
                    [word, item_id])
        return cur.fetchone()["hit"]


def _rank(item_id: int, word: str) -> float:
    with db_cursor() as cur:
        cur.execute("SELECT ts_rank(search_vector, plainto_tsquery('english', %s)) AS rank FROM agenda_items WHERE id = %s",
                    [word, item_id])
        return cur.fetchone()["rank"]


def _card_rows(s: dict) -> list[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM agenda_item_search_cards WHERE transcript_id = %s ORDER BY agenda_item_id",
                    [s["transcript_id"]])
        return [dict(r) for r in cur.fetchall()]


def test_a_card_word_makes_its_item_findable_and_not_its_sibling(seeded):
    assert not _matches(seeded["a"], "balloon") and not _matches(seeded["b"], "balloon")

    assert _write(seeded, [_card(seeded["a"], search_b="balloon test . kelvin felder")]) == 1

    assert _matches(seeded["a"], "balloon")
    assert _matches(seeded["a"], "kelvin felder")
    assert not _matches(seeded["b"], "balloon")
    assert _matches(seeded["a"], "paving") and _matches(seeded["b"], "paving"), "the agenda text is still searched"


def test_an_empty_list_removes_the_cards_and_their_words(seeded):
    _write(seeded, [_card(seeded["a"], search_b="balloon test . kelvin felder")])
    assert _matches(seeded["a"], "balloon")

    assert _write(seeded, []) == 0

    assert not _matches(seeded["a"], "balloon")
    assert _card_rows(seeded) == []
    assert _matches(seeded["a"], "paving")


def test_writing_again_replaces_the_set(seeded):
    """An item carded by the last run and not by this one loses its card and its words."""
    _write(seeded, [_card(seeded["a"], search_b="balloon"), _card(seeded["b"], search_c="zeppelin")])
    assert _matches(seeded["a"], "balloon") and _matches(seeded["b"], "zeppelin")

    assert _write(seeded, [_card(seeded["b"], search_b="dirigible")]) == 1

    assert [r["agenda_item_id"] for r in _card_rows(seeded)] == [seeded["b"]]
    assert not _matches(seeded["a"], "balloon")
    assert not _matches(seeded["b"], "zeppelin")
    assert _matches(seeded["b"], "dirigible")


def test_an_alias_word_outranks_the_same_word_in_a_spoken_detail(seeded):
    """search_b is weight B and search_c weight C; the two items' agenda text is identical."""
    _write(seeded, [_card(seeded["a"], search_b="zeppelin hangar"), _card(seeded["b"], search_c="zeppelin hangar")])

    assert _matches(seeded["a"], "zeppelin") and _matches(seeded["b"], "zeppelin")
    assert _rank(seeded["a"], "zeppelin") > _rank(seeded["b"], "zeppelin") > 0
    assert _rank(seeded["a"], "paving") > _rank(seeded["a"], "zeppelin"), "a title word (weight A) outranks a card word"


def test_updating_the_title_keeps_the_cards_words(seeded):
    _write(seeded, [_card(seeded["a"], search_b="balloon", search_c="footage kept thirty days")])

    with db_cursor() as cur:
        cur.execute("UPDATE agenda_items SET title = 'Ordinance on club safety plans' WHERE id = %s", [seeded["a"]])

    assert _matches(seeded["a"], "balloon") and _matches(seeded["a"], "footage")
    assert _matches(seeded["a"], "safety")
    assert not _matches(seeded["a"], "paving"), "the old title's words are gone"


def test_a_stale_source_uploaded_at_returns_minus_one_and_writes_nothing(seeded):
    _write(seeded, [_card(seeded["a"], search_b="balloon")])
    before = _card_rows(seeded)

    stale = seeded["uploaded_at"] - timedelta(seconds=1)
    assert _write(seeded, [_card(seeded["b"], search_b="zeppelin")], uploaded_at=stale) == -1

    assert _card_rows(seeded) == before
    assert _matches(seeded["a"], "balloon")
    assert not _matches(seeded["b"], "zeppelin")


def test_a_reupload_makes_the_old_timestamp_stale(seeded):
    """The producer's upload sets uploaded_at = now(); a run that started before it must not write."""
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET uploaded_at = uploaded_at + interval '1 hour' WHERE id = %s",
                    [seeded["transcript_id"]])

    assert _write(seeded, [_card(seeded["a"], search_b="balloon")]) == -1

    assert _card_rows(seeded) == []
    assert not _matches(seeded["a"], "balloon")


def test_a_transcript_that_does_not_exist_or_is_not_uploaded_returns_minus_one(seeded):
    assert _cards().write_cards(-1, seeded["uploaded_at"], [_card(seeded["a"], search_b="balloon")],
                                model=MODEL, prompt_version=VERSION) == -1
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET uploaded_at = NULL WHERE id = %s", [seeded["transcript_id"]])
    assert _write(seeded, [_card(seeded["a"], search_b="balloon")]) == -1
    assert _card_rows(seeded) == []


def test_the_stored_row_holds_what_was_passed(seeded):
    body = {"aliases": ["late night establishment rules"], "names": [{"name": "Kelvyn Felder Ordinance",
                                                                       "variants": ["Kelvin Felder Ordinance"]}]}
    _write(seeded, [_card(seeded["a"], search_b="late night establishment rules", search_c="footage",
                          start_seq=0, end_seq=1, start_s=10.0, end_s=17.0, card=body),
                    _card(seeded["b"], discussed=False)])

    first, second = _card_rows(seeded)
    assert first["agenda_item_id"] == seeded["a"] and first["transcript_id"] == seeded["transcript_id"]
    assert first["source_uploaded_at"] == seeded["uploaded_at"]
    assert (first["prompt_version"], first["model"], first["discussed"]) == (VERSION, MODEL, True)
    assert (first["start_seq"], first["end_seq"], first["start_s"], first["end_s"]) == (0, 1, 10.0, 17.0)
    assert first["card"] == body
    assert (first["search_b"], first["search_c"]) == ("late night establishment rules", "footage")
    assert first["generated_at"] is not None
    assert second["discussed"] is False
    assert (second["start_seq"], second["end_seq"], second["start_s"], second["end_s"]) == (None, None, None, None)
    assert (second["search_b"], second["search_c"]) == ("", "")


def test_a_write_that_fails_leaves_the_earlier_cards_in_place(seeded):
    """Delete, insert, and refresh are one transaction: two cards for one item roll the whole write back."""
    _write(seeded, [_card(seeded["a"], search_b="balloon")])
    before = _card_rows(seeded)

    with pytest.raises(psycopg2.errors.UniqueViolation):
        _write(seeded, [_card(seeded["b"], search_b="zeppelin"), _card(seeded["b"], search_b="dirigible")])

    assert _card_rows(seeded) == before
    assert _matches(seeded["a"], "balloon")
    assert not _matches(seeded["b"], "zeppelin")


def test_touch_search_vectors_recomputes_the_named_items_only(seeded):
    """The refresh is one statement over the ids given; an empty list runs no statement."""
    with db_cursor() as cur:
        cur.execute("""INSERT INTO agenda_item_search_cards (agenda_item_id, transcript_id, source_uploaded_at,
                                                             prompt_version, model, discussed, card, search_b)
                       VALUES (%s, %s, %s, %s, %s, TRUE, '{}'::jsonb, 'balloon'),
                              (%s, %s, %s, %s, %s, TRUE, '{}'::jsonb, 'zeppelin')""",
                    [seeded["a"], seeded["transcript_id"], seeded["uploaded_at"], VERSION, MODEL,
                     seeded["b"], seeded["transcript_id"], seeded["uploaded_at"], VERSION, MODEL])
    assert not _matches(seeded["a"], "balloon") and not _matches(seeded["b"], "zeppelin")

    class Recorder:
        def __init__(self, cur):
            self.cur, self.statements = cur, []

        def execute(self, sql, params=None):
            self.statements.append(sql)
            return self.cur.execute(sql, params)

    with db_cursor() as cur:
        rec = Recorder(cur)
        _cards().touch_search_vectors(rec, [])
        assert rec.statements == []
        _cards().touch_search_vectors(rec, [seeded["a"]])
        assert len(rec.statements) == 1

    assert _matches(seeded["a"], "balloon")
    assert not _matches(seeded["b"], "zeppelin"), "an item that was not named keeps its old vector"
