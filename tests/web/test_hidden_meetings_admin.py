"""The admin's hidden-meetings page says why each row is hidden and lists the clips the rule held back; an unhide exempts the row for good.

`/admin/meetings/hidden` prints `meetings.hidden_reason` in words and, below
the table, the clips `non_meetings.find` would have hidden but for a
transcript with speech. Posting to `/admin/meetings/<id>/hide` writes the
reason `admin`; posting to `/admin/meetings/<id>/unhide` clears the reason
and sets `keep_visible_at`, which `hide_non_meetings` honours.

One test city, seeded here with the two metadata keys the rule needs and a
calendar read a moment ago; dates are counted back from the real today
because `hide_non_meetings()` is called as the worker calls it. The service
is imported inside the tests so the file collects before the module exists.

Pattern: tests/integration/test_admin_hide_meeting.py (the admin session),
tests/web/test_meeting_label.py (rows seeded directly in the web tier).
Plan `committee-clips-named-or-hidden`, M4.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from werkzeug.security import generate_password_hash

from docket.db import db
from docket.web import create_app

SLUG = "test_hidden_admin"
PREFIX = "hidadm-"
ADMIN = "tester_hidden_admin"
GENERIC = "Regular City Council Meeting"
TODAY = datetime.now(ZoneInfo("America/Chicago")).date()
DAY = TODAY - timedelta(days=10)
REASON_TEXT = "not a meeting: short or silent clip on a day with no calendar event"
HELD_HEADING = "Not hidden: has a transcript with speech"


def _cleanup(cur, mid: int) -> None:
    cur.execute("DELETE FROM meetings WHERE municipality_id = %s", (mid,))
    cur.execute("DELETE FROM city_calendar_events WHERE municipality_id = %s", (mid,))


@pytest.fixture
def city():
    metadata = '{"calendar_url": "https://example.test/council", "calendar_complete_from": "%s"}' % (
        TODAY - timedelta(days=30)
    ).isoformat()
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO municipalities (slug, name, state, adapter_class, adapter_config, active, metadata)
            VALUES (%s, 'Test Hidden Admin', 'AL', 'GranicusAdapter',
                    '{"view_id": 1, "base_url": "https://example.com"}'::jsonb, TRUE, %s::jsonb)
            ON CONFLICT (slug) DO UPDATE SET active = TRUE, metadata = EXCLUDED.metadata
            RETURNING id
            """,
            (SLUG, metadata),
        )
        mid = cur.fetchone()[0]
        _cleanup(cur, mid)
        cur.execute(
            """INSERT INTO city_calendar_events (municipality_id, source_event_id, title, starts_at, source_url)
               VALUES (%s, %s, 'PUBLIC SAFETY COMMITTEE MEETING', %s, 'https://example.test/events/fresh')""",
            (mid, PREFIX + "fresh", datetime.now(timezone.utc) + timedelta(days=20)),
        )
    yield mid
    with db() as conn, conn.cursor() as cur:
        _cleanup(cur, mid)
        cur.execute("UPDATE municipalities SET active = FALSE WHERE id = %s", (mid,))


@pytest.fixture
def admin_client():
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO admin_users (username, password_hash) VALUES (%s, %s)
               ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash RETURNING id""",
            (ADMIN, generate_password_hash("pw")),
        )
        uid = cur.fetchone()[0]
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key-hidden-admin"
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_user"] = ADMIN
        sess["admin_user_id"] = uid
    client.admin_id = uid
    yield client
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM admin_users WHERE id = %s", (uid,))


def _clip(mid: int, tag: str, *, day: date = DAY, duration_s: int = 240, title: str = GENERIC, **columns) -> int:
    names = ["municipality_id", "external_id", "title", "meeting_date", "meeting_type", "duration_s", *columns]
    values = [mid, PREFIX + tag, title, day, "council", duration_s, *columns.values()]
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO meetings ({', '.join(names)}) VALUES ({', '.join(['%s'] * len(names))}) RETURNING id",
            values,
        )
        return cur.fetchone()[0]


def _state(meeting_id: int) -> dict:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT is_hidden, hidden_at, hidden_by, hidden_reason, keep_visible_at FROM meetings WHERE id = %s",
            (meeting_id,),
        )
        return dict(zip(("is_hidden", "hidden_at", "hidden_by", "hidden_reason", "keep_visible_at"), cur.fetchone()))


def _hide_non_meetings() -> tuple[list[int], list[int]]:
    from docket.services.non_meetings import hide_non_meetings

    return hide_non_meetings().get(SLUG, ([], []))


def _row_of(body: str, meeting_id: int) -> str:
    """The table row that holds the link to this meeting's page."""
    for row in re.findall(r"<tr>.*?</tr>", body, re.S):
        if f"/al/{SLUG}/meetings/{meeting_id}/" in row:
            return row
    raise AssertionError(f"no row links meeting {meeting_id}")


def _tables(body: str) -> tuple[str, str]:
    """The page above the held-back heading and the page from it down."""
    assert HELD_HEADING in body
    above, below = body.split(HELD_HEADING, 1)
    return above, below


def test_the_page_says_why_each_row_is_hidden(admin_client, city):
    auto = _clip(city, "auto")
    assert _hide_non_meetings() == ([auto], [])
    by_admin = _clip(city, "admin", day=DAY - timedelta(days=1), is_hidden=True, hidden_reason="admin")
    absorbed = _clip(city, "absorbed", day=DAY - timedelta(days=2), is_hidden=True, hidden_reason="absorbed")
    old = _clip(city, "old", day=DAY - timedelta(days=3), is_hidden=True)

    rv = admin_client.get("/admin/meetings/hidden")

    assert rv.status_code == 200
    above, _ = _tables(rv.get_data(as_text=True))
    assert "<th>Reason</th>" in above
    assert REASON_TEXT in _row_of(above, auto)
    assert "by an admin" in _row_of(above, by_admin)
    assert "merged into another row" in _row_of(above, absorbed)
    old_row = _row_of(above, old)
    for text in (REASON_TEXT, "by an admin", "merged into another row", "None"):
        assert text not in old_row, "a row hidden before the column has no reason to print"
    assert f'action="/admin/meetings/{auto}/unhide"' in _row_of(above, auto)


def test_the_page_lists_the_clips_the_brake_held_back(admin_client, city):
    held = _clip(city, "held")
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO transcripts (meeting_id, status, uploaded_at) VALUES (%s, 'compared', now())", (held,)
        )
    hidden = _clip(city, "auto", day=DAY - timedelta(days=1))
    assert _hide_non_meetings() == ([hidden], [held])

    body = admin_client.get("/admin/meetings/hidden").get_data(as_text=True)

    above, below = _tables(body)
    row = _row_of(below, held)
    assert DAY.isoformat() in row and GENERIC in row
    assert "240 s" in row, "the clip's length"
    assert "compared" in row
    assert f"/al/{SLUG}/meetings/{held}/" not in above, "a held-back clip is not in the hidden table"
    assert f"/al/{SLUG}/meetings/{hidden}/" not in below, "a hidden clip is not in the held-back table"
    assert "/unhide" not in below, "the held-back table has no unhide button; its rows are visible"


def test_the_held_back_table_says_so_when_it_is_empty(admin_client, city):
    with db() as conn, conn.cursor() as cur:
        cur.execute("UPDATE municipalities SET active = FALSE WHERE id = %s", (city,))

    _, below = _tables(admin_client.get("/admin/meetings/hidden").get_data(as_text=True))

    assert f"/al/{SLUG}/" not in below


def test_an_admins_hide_writes_the_reason(admin_client, city):
    clip = _clip(city, "tohide", duration_s=3600)

    rv = admin_client.post(f"/admin/meetings/{clip}/hide")

    assert rv.status_code in (302, 303)
    state = _state(clip)
    assert (state["is_hidden"], state["hidden_reason"], state["hidden_by"]) == (True, "admin", admin_client.admin_id)
    assert state["keep_visible_at"] is None


def test_an_unhide_exempts_the_row_for_good(admin_client, city):
    clip = _clip(city, "auto")
    assert _hide_non_meetings() == ([clip], [])

    rv = admin_client.post(f"/admin/meetings/{clip}/unhide")

    assert rv.status_code in (302, 303)
    state = _state(clip)
    assert state["is_hidden"] is False
    assert (state["hidden_at"], state["hidden_by"], state["hidden_reason"]) == (None, None, None)
    assert state["keep_visible_at"] is not None

    assert _hide_non_meetings() == ([], [])
    assert _state(clip)["is_hidden"] is False, "the next morning's run leaves it visible"
    body = admin_client.get("/admin/meetings/hidden").get_data(as_text=True)
    assert f"/al/{SLUG}/meetings/{clip}/" not in body
