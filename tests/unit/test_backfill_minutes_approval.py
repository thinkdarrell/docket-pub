"""Tests for the one-off repair that restores minutes-approval agenda lines.

Meetings ingested from agenda PDFs between 2026-05-19 and the parser fix have
no "APPROVAL OF MINUTES FROM PREVIOUS MEETINGS" item, and ingest never
re-scrapes a meeting it has already scraped.
"""

from datetime import date

import psycopg2.extras
import pytest

from docket.db import db, db_cursor
from docket.services.maintenance import backfill_minutes_approval_items

AGENDA_WITH_APPROVAL = (
    "ROLL CALL\n"
    "APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3 – 24, 2097\n"
    "MINUTES NOT READY: March 3, 2097 – May 12, 2097\n"
    "ITEM 1.\nA Resolution doing a thing.\n"
)
AGENDA_WITHOUT_APPROVAL = (
    "ROLL CALL\n"
    "MINUTES NOT READY: March 3, 2097 – May 19, 2097\n"
    "ITEM 1.\nA Resolution doing a thing.\n"
)


@pytest.fixture
def scraped_meetings():
    """Two already-scraped meetings: one whose agenda PDF carries an approval
    line, one whose agenda doesn't. Each has its numbered item but no approval item."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE title = 'TEST_APPROVAL_BACKFILL'")
        conn.commit()

    ids = {}
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM municipalities ORDER BY id LIMIT 1")
            muni_id = cur.fetchone()["id"]
            for key, d in [("with", "2097-05-19"), ("without", "2097-05-26")]:
                cur.execute(
                    """INSERT INTO meetings (municipality_id, external_id, title, meeting_date,
                                             meeting_type, agenda_url)
                       VALUES (%s, %s, 'TEST_APPROVAL_BACKFILL', %s, 'council', %s) RETURNING id""",
                    (muni_id, f"test-backfill-{key}", d, f"https://example.test/agenda/{key}"),
                )
                ids[key] = cur.fetchone()["id"]
                cur.execute(
                    """INSERT INTO agenda_items (meeting_id, external_id, item_number, title, is_consent)
                       VALUES (%s, 'event-1-1', '1', 'A Resolution doing a thing.', FALSE)""",
                    (ids[key],),
                )
        conn.commit()

    texts = {
        "https://example.test/agenda/with": AGENDA_WITH_APPROVAL,
        "https://example.test/agenda/without": AGENDA_WITHOUT_APPROVAL,
    }
    fetched: list[str] = []

    def fetch(url: str) -> str | None:
        fetched.append(url)
        return texts.get(url)

    yield {"municipality_id": muni_id, "ids": ids, "fetch": fetch, "fetched": fetched}

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", (list(ids.values()),))
        conn.commit()


def _approval_titles(meeting_id: int) -> list[str]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT title FROM agenda_items WHERE meeting_id = %s AND item_number IS NULL",
            (meeting_id,),
        )
        return [r["title"] for r in cur.fetchall()]


def _run(s, **kwargs):
    return backfill_minutes_approval_items(
        s["municipality_id"], since=date(2097, 1, 1), fetch_agenda_text=s["fetch"], **kwargs
    )


def test_inserts_approval_item_for_meeting_whose_agenda_has_one(scraped_meetings):
    s = scraped_meetings
    added = _run(s)

    line = "APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3 – 24, 2097"
    assert added == [(s["ids"]["with"], line)]
    assert _approval_titles(s["ids"]["with"]) == [line]
    assert _approval_titles(s["ids"]["without"]) == []


def test_second_run_adds_nothing_and_skips_the_repaired_meeting(scraped_meetings):
    s = scraped_meetings
    _run(s)
    s["fetched"].clear()

    assert _run(s) == []
    assert len(_approval_titles(s["ids"]["with"])) == 1
    assert "https://example.test/agenda/with" not in s["fetched"]


def test_dry_run_reports_without_writing(scraped_meetings):
    s = scraped_meetings
    added = _run(s, dry_run=True)

    assert [mid for mid, _ in added] == [s["ids"]["with"]]
    assert _approval_titles(s["ids"]["with"]) == []


def test_skips_meetings_before_since(scraped_meetings):
    s = scraped_meetings
    added = backfill_minutes_approval_items(
        s["municipality_id"], since=date(2097, 5, 20), fetch_agenda_text=s["fetch"]
    )
    assert added == []
    assert "https://example.test/agenda/with" not in s["fetched"]
