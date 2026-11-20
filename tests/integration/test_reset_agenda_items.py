"""The supervised reset of one city's stored agenda items.

`docket.services.ingest.reset_agenda_items` counts what a city holds, refuses
a city whose items carry vote links, transcript links or minutes
discrepancies, and with ``apply=True`` deletes the city's items, clears its
meeting summaries and re-opens its meetings, in one transaction.

Every test runs against the throwaway database (DATABASE_URL names
docket_test_*). Each creates its own municipality rows, with slugs beginning
``reset_test_``, and everything under them is deleted before and after every
test. No row here is a row a city sent. The function is imported inside each
test so the file still collects where the function does not exist yet.

Only the vote-link guard has a seeded test; the guard's other two tables
(``transcript_segments`` and ``minutes_discrepancies``) are counted by the
same query.

Plan `mobile-agendas-flow-again`, M4.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from docket.db import db_cursor

SLUG = "reset_test_one"
OTHER = "reset_test_two"
_LIKE = r"reset\_test\_%"
GENERATED_AT = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
SUMMARY_COLUMNS = (
    "executive_summary",
    "executive_summary_voice",
    "ai_prompt_version",
    "ai_metadata",
    "ai_generated_at",
)


def _delete_seeded() -> None:
    with db_cursor() as cur:
        cur.execute(
            """
            DELETE FROM processing_status_audit
            WHERE agenda_item_id IN (
                SELECT a.id FROM agenda_items a
                JOIN meetings m ON m.id = a.meeting_id
                JOIN municipalities mu ON mu.id = m.municipality_id
                WHERE mu.slug LIKE %s
            )
            """,
            (_LIKE,),
        )
        cur.execute(
            "DELETE FROM meetings WHERE municipality_id IN (SELECT id FROM municipalities WHERE slug LIKE %s)",
            (_LIKE,),
        )
        cur.execute("DELETE FROM municipalities WHERE slug LIKE %s", (_LIKE,))


@pytest.fixture(autouse=True)
def _clean():
    _delete_seeded()
    yield
    _delete_seeded()


def _seed_city(slug: str) -> dict:
    """One city with three meetings.

    The first meeting is marked scraped, holds two items (the first with an
    audit row) and a summary in all five columns. The second is marked
    scraped and holds one item and no summary. The third has no
    ``processing_status`` row, no item and no summary.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO municipalities (slug, name, state, adapter_class, adapter_config, active)
            VALUES (%s, %s, 'AL', 'civicclerk', '{}'::jsonb, FALSE)
            RETURNING id
            """,
            (slug, slug),
        )
        muni = cur.fetchone()["id"]
        meetings = []
        for n, meeting_date in enumerate((date(2026, 11, 3), date(2026, 11, 10), date(2026, 11, 17)), start=1):
            cur.execute(
                """
                INSERT INTO meetings (municipality_id, title, meeting_date, external_id,
                                      meeting_type, agenda_url, minutes_url, source_url)
                VALUES (%s, %s, %s, %s, 'council', %s, %s, %s)
                RETURNING id
                """,
                (
                    muni,
                    f"{slug} meeting {n}",
                    meeting_date,
                    f"{slug}-{n}",
                    f"https://example.com/{slug}/agenda/{n}",
                    f"https://example.com/{slug}/minutes/{n}",
                    f"https://example.com/{slug}/event/{n}",
                ),
            )
            meetings.append(cur.fetchone()["id"])
        cur.execute(
            """
            UPDATE meetings
               SET executive_summary = 'A summary written from the stored items.',
                   executive_summary_voice = 'completed',
                   ai_prompt_version = 4,
                   ai_metadata = '{"model": "built-in-the-test"}'::jsonb,
                   ai_generated_at = %s
             WHERE id = %s
            """,
            (GENERATED_AT, meetings[0]),
        )
        for meeting_id in meetings[:2]:
            cur.execute(
                "INSERT INTO processing_status (meeting_id, agenda_items_scraped, votes_scanned) VALUES (%s, TRUE, TRUE)",
                (meeting_id,),
            )
        items = []
        for meeting_id, external_id in ((meetings[0], "1"), (meetings[0], "2"), (meetings[1], "3")):
            cur.execute(
                """
                INSERT INTO agenda_items (meeting_id, external_id, item_number, title, is_consent)
                VALUES (%s, %s, %s, %s, FALSE)
                RETURNING id
                """,
                (meeting_id, external_id, external_id, f"{slug} item {external_id}"),
            )
            items.append(cur.fetchone()["id"])
        cur.execute(
            """
            INSERT INTO processing_status_audit
                (agenda_item_id, from_status, to_status, action, actor, actor_role, reason)
            VALUES (%s, NULL, 'pending'::processing_status_enum, 'retry', 'test', 'admin', 'built in the test')
            """,
            (items[0],),
        )
    return {"muni": muni, "meetings": meetings, "items": items}


def _state(muni: int) -> dict:
    """What the database holds for one city, as plain values to compare."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT m.external_id, m.title, m.agenda_url, m.minutes_url,
                   m.executive_summary, m.executive_summary_voice, m.ai_prompt_version,
                   m.ai_metadata, m.ai_generated_at,
                   ps.agenda_items_scraped, ps.votes_scanned
            FROM meetings m
            LEFT JOIN processing_status ps ON ps.meeting_id = m.id
            WHERE m.municipality_id = %s
            ORDER BY m.id
            """,
            (muni,),
        )
        meetings = [dict(r) for r in cur.fetchall()]
        cur.execute(
            """
            SELECT a.id FROM agenda_items a JOIN meetings m ON m.id = a.meeting_id
            WHERE m.municipality_id = %s ORDER BY a.id
            """,
            (muni,),
        )
        items = [r["id"] for r in cur.fetchall()]
        cur.execute(
            """
            SELECT count(*) AS n FROM processing_status_audit psa
            JOIN agenda_items a ON a.id = psa.agenda_item_id
            JOIN meetings m ON m.id = a.meeting_id
            WHERE m.municipality_id = %s
            """,
            (muni,),
        )
        audit = cur.fetchone()["n"]
    return {"meetings": meetings, "items": items, "audit": audit}


COUNTS = {
    "meetings": 3,
    "meetings_scraped": 2,
    "meetings_with_summary": 1,
    "agenda_items": 3,
    "audit_rows": 1,
    "vote_links": 0,
    "transcript_segments": 0,
    "minutes_discrepancies": 0,
}


def test_a_dry_run_reports_and_changes_nothing():
    from docket.services.ingest import reset_agenda_items

    city = _seed_city(SLUG)
    before = _state(city["muni"])

    result = reset_agenda_items(SLUG)

    assert result == COUNTS
    assert _state(city["muni"]) == before
    # apply=False is the default and is the same thing said aloud.
    assert reset_agenda_items(SLUG, apply=False) == COUNTS
    assert _state(city["muni"]) == before


def test_apply_deletes_the_citys_items_and_reopens_its_meetings_only():
    from docket.services.ingest import reset_agenda_items

    city = _seed_city(SLUG)
    other = _seed_city(OTHER)
    before = _state(city["muni"])
    other_before = _state(other["muni"])

    result = reset_agenda_items(SLUG, apply=True)

    assert result == {
        **COUNTS,
        "audit_rows_deleted": 1,
        "agenda_items_deleted": 3,
        "summaries_cleared": 1,
        "meetings_reopened": 2,
    }
    after = _state(city["muni"])
    assert after["items"] == []
    assert after["audit"] == 0
    # The two marked meetings are re-opened; the third still has no row.
    assert [m["agenda_items_scraped"] for m in after["meetings"]] == [False, False, None]
    # The meetings, their links and votes_scanned are as they were.
    for key in ("external_id", "title", "agenda_url", "minutes_url", "votes_scanned"):
        assert [m[key] for m in after["meetings"]] == [m[key] for m in before["meetings"]]
    assert [m["votes_scanned"] for m in after["meetings"]] == [True, True, None]

    # The second city is untouched: items, audit row, marks and summary.
    assert _state(other["muni"]) == other_before
    assert len(other_before["items"]) == 3 and other_before["audit"] == 1

    # A second apply finds nothing left to delete or clear.
    again = reset_agenda_items(SLUG, apply=True)
    assert again == {
        "meetings": 3,
        "meetings_scraped": 0,
        "meetings_with_summary": 0,
        "agenda_items": 0,
        "audit_rows": 0,
        "vote_links": 0,
        "transcript_segments": 0,
        "minutes_discrepancies": 0,
        "audit_rows_deleted": 0,
        "agenda_items_deleted": 0,
        "summaries_cleared": 0,
        "meetings_reopened": 2,
    }
    assert _state(other["muni"]) == other_before


def test_apply_clears_the_citys_meeting_summaries_only():
    from docket.services.ingest import reset_agenda_items

    city = _seed_city(SLUG)
    other = _seed_city(OTHER)
    # A meeting with no executive_summary and one of the other four columns
    # set is cleared as well ("where any of the five is not NULL").
    with db_cursor() as cur:
        cur.execute("UPDATE meetings SET ai_prompt_version = 4 WHERE id = %s", (city["meetings"][1],))

    result = reset_agenda_items(SLUG, apply=True)

    assert result["meetings_with_summary"] == 1
    assert result["summaries_cleared"] == 2
    for meeting in _state(city["muni"])["meetings"]:
        for column in SUMMARY_COLUMNS:
            assert meeting[column] is None, column

    kept = _state(other["muni"])["meetings"][0]
    assert kept["executive_summary"] == "A summary written from the stored items."
    assert kept["executive_summary_voice"] == "completed"
    assert kept["ai_prompt_version"] == 4
    assert kept["ai_metadata"] == {"model": "built-in-the-test"}
    assert kept["ai_generated_at"] == GENERATED_AT


def test_a_city_with_vote_links_is_refused():
    from docket.services.ingest import reset_agenda_items

    city = _seed_city(SLUG)
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO votes (meeting_id, result, yeas, nays, source, raw_text)
            VALUES (%s, 'passed', 7, 0, 'minutes_text', 'built in the test')
            RETURNING id
            """,
            (city["meetings"][0],),
        )
        vote_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO vote_agenda_items (vote_id, agenda_item_id, association_type, match_confidence)
            VALUES (%s, %s, 'explicit', 1.0)
            """,
            (vote_id, city["items"][0]),
        )
    before = _state(city["muni"])

    for apply in (False, True):
        with pytest.raises(ValueError) as refused:
            reset_agenda_items(SLUG, apply=apply)
        message = str(refused.value)
        assert SLUG in message
        assert "1 vote links" in message
        assert "0 transcript segments" in message
        assert "0 minutes discrepancies" in message
        assert _state(city["muni"]) == before

    assert len(before["items"]) == 3
    assert before["meetings"][0]["executive_summary"] is not None
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM vote_agenda_items WHERE vote_id = %s", (vote_id,))
        assert cur.fetchone()["n"] == 1


def test_an_unknown_city_is_refused():
    from docket.services.ingest import reset_agenda_items

    city = _seed_city(SLUG)
    before = _state(city["muni"])

    for apply in (False, True):
        with pytest.raises(ValueError) as refused:
            reset_agenda_items("reset_test_no_such_city", apply=apply)
        assert "reset_test_no_such_city" in str(refused.value)
    assert _state(city["muni"]) == before
