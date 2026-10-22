"""The site shows the meeting label in place of the clip name (M5).

The card partial prints ``meeting_label(meeting)`` (a Jinja global
registered in ``docket.web.create_app`` that reads the four classification
columns and the title and calls ``adapters._helpers.label_for``); the meeting
page makes the label its ``h1`` and ``<title>``, quotes the clip name as
provenance when the two differ, and says which rung named the body; the
meetings list carries a filter ``nav`` fed by ``query.meeting_type_counts``.

Pattern: ``render_partial`` and ``client`` from ``tests/web/conftest.py``;
rows seeded directly with an ``external_id`` prefix and deleted after, since
the provenance sentence quotes the exact title and so the title cannot carry
a prefix. Runs in the web tier against the throwaway database.

Plan: plans/active/meeting-types-name-the-body.md (M5).
"""

from __future__ import annotations

import re
from datetime import date
from types import SimpleNamespace

import pytest

from docket.db import db

PREFIX = "mtlabel-"
CLIP = "Regular City Council Meeting"


def _card(render_partial, **cols) -> str:
    m = SimpleNamespace(
        id=7,
        meeting_date=date(2026, 10, 15),
        title=cols.pop("title", CLIP),
        meeting_type=cols.pop("meeting_type", "council"),
        session_kind=cols.pop("session_kind", "regular"),
        body_name=cols.pop("body_name", None),
        summary=None,
        agenda_count=3,
        dollars_total=0,
    )
    return render_partial(
        "partials/meeting_card.html",
        meeting=m,
        variant="grid",
        municipality=SimpleNamespace(slug="birmingham"),
    )


def _h3(html: str) -> str:
    m = re.search(r'<h3 class="meeting-card__title">(.*?)</h3>', html, re.S)
    assert m, html
    return m.group(1).strip()


# --- the card ---------------------------------------------------------------


def test_card_prints_the_body_name_not_the_clip_name(render_partial):
    html = _card(render_partial, meeting_type="committee", body_name="Public Safety Committee")
    assert _h3(html) == "Public Safety Committee"
    assert CLIP not in html


def test_card_prints_the_council_label_for_a_generic_council_row(render_partial):
    html = _card(render_partial)
    assert _h3(html) == "City Council meeting"
    assert CLIP not in html


def test_card_marks_a_cancelled_council_row(render_partial):
    html = _card(render_partial, title="Regular City Council Meeting - Cancelled")
    assert _h3(html) == "City Council meeting (cancelled)"


def test_card_falls_back_to_the_title_when_the_row_carries_no_classification(render_partial):
    """A row dict without the columns (older fixtures, search rows) shows its own title."""
    m = SimpleNamespace(id=1, meeting_date=date(2026, 5, 13), title="Sample Meeting")
    html = render_partial(
        "partials/meeting_card.html", meeting=m, variant="grid",
        municipality=SimpleNamespace(slug="birmingham"),
    )
    assert _h3(html) == "Sample Meeting"


# --- the pages --------------------------------------------------------------


def _city_id(cur, slug: str) -> int:
    cur.execute("SELECT id FROM municipalities WHERE slug = %s", (slug,))
    row = cur.fetchone()
    assert row is not None, f"city must be seeded: {slug}"
    return row[0]


def _insert(cur, city_id: int, ext: str, title: str, meeting_date: date, *, meeting_type: str,
            session_kind: str = "regular", body_name: str | None = None, type_source: str = "title",
            calendar_event_id: int | None = None) -> int:
    cur.execute(
        """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type,
                                 session_kind, body_name, type_source, calendar_event_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (city_id, PREFIX + ext, title, meeting_date, meeting_type, session_kind, body_name,
         type_source, calendar_event_id),
    )
    return cur.fetchone()[0]


def _cleanup(cur) -> None:
    cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (PREFIX + "%",))
    cur.execute("DELETE FROM city_calendar_events WHERE source_event_id LIKE %s", (PREFIX + "%",))


@pytest.fixture
def rows():
    """Four Birmingham rows and one Homewood row, each on a different rung."""
    with db() as conn, conn.cursor() as cur:
        _cleanup(cur)
        bhm = _city_id(cur, "birmingham")
        hwd = _city_id(cur, "homewood")
        cur.execute(
            """INSERT INTO city_calendar_events
                   (municipality_id, source_event_id, title, starts_at, source_url)
               VALUES (%s, %s, 'PUBLIC SAFETY COMMITTEE MEETING, October 14, 2026',
                       '2026-10-14 14:00-05', 'https://www.birminghamal.gov/events/public-safety')
               RETURNING id""",
            (bhm, PREFIX + "event"),
        )
        event_id = cur.fetchone()[0]
        ids = {
            "rule": _insert(cur, bhm, "rule", CLIP, date(2026, 10, 15), meeting_type="committee",
                            type_source="schedule_rule"),
            "calendar": _insert(cur, bhm, "calendar", CLIP, date(2026, 10, 14), meeting_type="committee",
                                body_name="Public Safety Committee", type_source="calendar",
                                calendar_event_id=event_id),
            "council": _insert(cur, bhm, "council", CLIP, date(2026, 10, 13), meeting_type="council"),
            "budget": _insert(cur, bhm, "budget", "Budget Hearing", date(2026, 10, 12),
                              meeting_type="council", session_kind="budget_hearing"),
            "homewood": _insert(cur, hwd, "finance", "Finance Committee", date(2026, 10, 12),
                                meeting_type="committee", body_name="Finance Committee"),
        }
        conn.commit()
    try:
        yield ids
    finally:
        with db() as conn, conn.cursor() as cur:
            _cleanup(cur)
            conn.commit()


def _get(client, path: str) -> str:
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.status_code)
    return resp.get_data(as_text=True)


PROVENANCE = "The city's archive lists this recording as “Regular City Council Meeting”."


def test_meeting_page_quotes_the_clip_name_when_the_label_differs(client, rows):
    html = _get(client, f"/al/birmingham/meetings/{rows['rule']}/")
    assert PROVENANCE in html
    assert "It is not on the council's regular meeting day and the city calendar did not name the body." in html
    assert "<title>Council committee meeting — Birmingham" in html
    assert "<title>Regular City Council Meeting" not in html
    assert '<h1 class="hero-title t-display">Council committee meeting</h1>' in html


def test_meeting_page_links_the_calendar_event_that_named_the_body(client, rows):
    html = _get(client, f"/al/birmingham/meetings/{rows['calendar']}/")
    assert PROVENANCE in html
    assert "The city's calendar names it." in html
    assert 'href="https://www.birminghamal.gov/events/public-safety"' in html
    assert "<title>Public Safety Committee — Birmingham" in html


def test_meeting_page_shows_the_session_kind_chip_when_not_regular(client, rows):
    html = _get(client, f"/al/birmingham/meetings/{rows['budget']}/")
    assert "budget hearing" in html
    assert "<title>Budget hearing — Birmingham" in html
    council = _get(client, f"/al/birmingham/meetings/{rows['council']}/")
    assert "regular</span>" not in council


def test_meeting_page_says_nothing_when_the_label_is_the_title(client, rows):
    html = _get(client, f"/al/homewood/meetings/{rows['homewood']}/")
    assert "lists this recording" not in html
    assert "<title>Finance Committee — Homewood" in html


# --- the filter row ---------------------------------------------------------


def _counts(slug: str) -> dict[str, int]:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT mt.meeting_type, count(*) FROM meetings mt
                 JOIN municipalities m ON m.id = mt.municipality_id
                WHERE m.slug = %s AND mt.is_hidden = FALSE GROUP BY 1""",
            (slug,),
        )
        return {r[0]: int(r[1]) for r in cur.fetchall()}


def test_meetings_list_carries_the_filter_nav_with_counts(client, rows):
    html = _get(client, "/al/birmingham/meetings/")
    nav = re.search(r'<nav class="type-filter"[^>]*>(.*?)</nav>', html, re.S)
    assert nav, "the meetings page carries a type-filter nav"
    nav = nav.group(1)
    counts = _counts("birmingham")
    total = sum(counts.values())
    assert re.search(r'href="/al/birmingham/meetings/"[^>]*>All\s*<span[^>]*>%d</span>' % total, nav)
    for mtype, word in (("council", "Council"), ("committee", "Committees"), ("planning", "Planning"),
                        ("board", "Boards"), ("other", "Other")):
        n = counts.get(mtype, 0)
        if n:
            assert re.search(r'href="/al/birmingham/meetings/\?type=%s"[^>]*>%s\s*<span[^>]*>%d</span>'
                             % (mtype, word, n), nav), (mtype, nav)
        else:
            assert f"?type={mtype}" not in nav, (mtype, nav)
            assert re.search(r'<span class="type-filter__item[^"]*">%s\s*<span[^>]*>0</span>' % word, nav), (mtype, nav)


def test_meetings_list_filtered_to_committee_lists_only_committee_rows(client, rows):
    html = _get(client, "/al/birmingham/meetings/?type=committee")
    assert f"/al/birmingham/meetings/{rows['rule']}/" in html
    assert f"/al/birmingham/meetings/{rows['calendar']}/" in html
    assert f"/al/birmingham/meetings/{rows['council']}/" not in html
    assert f"/al/birmingham/meetings/{rows['budget']}/" not in html


# --- the item page (review finding: the clip name leaked through its crumb and hero link) ---


@pytest.fixture
def item_on_rule_row(rows):
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO agenda_items (meeting_id, item_number, title, external_id, processing_status)
               VALUES (%s, '1', 'Sidewalk repair contract', %s, 'pending') RETURNING id""",
            (rows["rule"], PREFIX + "item"),
        )
        item_id = cur.fetchone()[0]
        conn.commit()
    return item_id


def test_item_page_names_the_meeting_by_its_label(client, rows, item_on_rule_row):
    html = _get(client, f"/al/birmingham/items/{item_on_rule_row}/")
    assert "Council committee meeting" in html
    assert CLIP not in html
