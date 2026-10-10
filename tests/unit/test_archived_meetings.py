"""Tests for services.archived_meetings.backfill_archived_meetings.

Meetings that Granicus never recorded (Birmingham's 2023 Boutwell Auditorium
stretch) exist elsewhere: the council's YouTube channel has the video and
the Wayback Machine has the old council site's agenda PDFs. A manifest
lists them; the backfill creates the meeting rows and their agenda items
through the same write path ingest uses.
"""

from __future__ import annotations

from datetime import date

import pytest

from docket.db import db
from docket.services.archived_meetings import ArchivedMeeting, backfill_archived_meetings

AGENDA_TEXT = """REGULAR MEETING OF THE COUNCIL
CITY OF BIRMINGHAM, ALABAMA
August 22, 2023 – 9:30 A.M.
ROLL CALL
APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: August 1 and 8, 2023
CONSIDERATION OF CONSENT AGENDA
CONSENT ITEM 1.
An Ordinance "TO FURTHER AMEND THE GRANTS FUND BUDGET" for the fiscal year ending June 30, 2024.
(Submitted by the Mayor)
ITEM 2.
A Resolution approving a contract with Acme Paving for 9th Avenue North.
(Submitted by the Mayor)
"""

ENTRY = ArchivedMeeting(
    meeting_date=date(2023, 8, 22),
    youtube_id="mYSy3PV-BrA",
    agenda_url="https://web.archive.org/web/20240101000000id_/https://old.example/agenda-aug-22.pdf",
)


@pytest.fixture
def muni():
    with db() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO municipalities (slug, name, state, adapter_class, active)
            VALUES ('test_archived', 'Test', 'AL', 'granicus', TRUE)
            ON CONFLICT (slug) DO UPDATE SET active = TRUE RETURNING id
        """)
        muni_id = cur.fetchone()[0]
        conn.commit()
    yield muni_id
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM agenda_items WHERE meeting_id IN (SELECT id FROM meetings WHERE municipality_id = %s)", (muni_id,))
        cur.execute("DELETE FROM processing_status WHERE meeting_id IN (SELECT id FROM meetings WHERE municipality_id = %s)", (muni_id,))
        cur.execute("DELETE FROM meetings WHERE municipality_id = %s", (muni_id,))
        cur.execute("DELETE FROM municipalities WHERE id = %s", (muni_id,))
        conn.commit()


def _meeting(muni_id, external_id):
    with db() as conn, conn.cursor() as cur:
        cur.execute("""SELECT m.id, m.title, m.meeting_type, m.meeting_date, m.video_url, m.agenda_url,
                              m.minutes_url, m.source_url, ps.agenda_items_scraped
                         FROM meetings m LEFT JOIN processing_status ps ON ps.meeting_id = m.id
                        WHERE m.municipality_id = %s AND m.external_id = %s""", (muni_id, external_id))
        return cur.fetchone()


def _items(meeting_id):
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT external_id, item_number, is_consent, title FROM agenda_items "
                    "WHERE meeting_id = %s ORDER BY item_number NULLS LAST", (meeting_id,))
        return cur.fetchall()


def test_creates_meeting_with_video_and_items(muni):
    calls = []

    def fetch(url):
        calls.append(url)
        return AGENDA_TEXT

    result = backfill_archived_meetings(muni, [ENTRY], fetch_agenda_text=fetch)

    row = _meeting(muni, "yt-mYSy3PV-BrA")
    assert row is not None
    mid, title, mtype, mdate, video, agenda, minutes, source, scraped = row
    assert (title, mtype, mdate) == ("Regular City Council Meeting", "council", date(2023, 8, 22))
    assert video == "https://www.youtube.com/watch?v=mYSy3PV-BrA"
    assert source == video
    assert agenda == ENTRY.agenda_url
    assert minutes is None
    assert scraped is True
    items = _items(mid)
    assert [(i[1], i[2]) for i in items] == [("1", True), ("2", False), (None, False)]
    assert items[2][0] == "yt-mYSy3PV-BrA-minutes-approval"
    assert items[2][3].startswith("APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: August 1 and 8, 2023")
    assert calls == [ENTRY.agenda_url]
    assert result.inserted == [mid] and result.skipped == [] and result.errors == []


def test_is_idempotent_and_does_not_refetch(muni):
    calls = []
    backfill_archived_meetings(muni, [ENTRY], fetch_agenda_text=lambda u: (calls.append(u), AGENDA_TEXT)[1])

    result = backfill_archived_meetings(muni, [ENTRY], fetch_agenda_text=lambda u: (calls.append(u), AGENDA_TEXT)[1])

    assert len(calls) == 1
    assert result.inserted == [] and len(result.skipped) == 1
    assert len(_items(_meeting(muni, "yt-mYSy3PV-BrA")[0])) == 3


def test_meeting_without_video_keys_off_the_date(muni):
    entry = ArchivedMeeting(meeting_date=date(2023, 10, 17), youtube_id=None, agenda_url="https://a/oct-17.pdf")

    backfill_archived_meetings(muni, [entry], fetch_agenda_text=lambda u: AGENDA_TEXT)

    row = _meeting(muni, "archive-2023-10-17")
    assert row is not None
    assert row[4] is None                       # no video
    assert row[7] == "https://a/oct-17.pdf"     # source is the agenda


def test_skips_a_date_granicus_already_covers(muni):
    with db() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO meetings (municipality_id, external_id, title, meeting_type, meeting_date, source_url)
                       VALUES (%s, '1668', 'Regular City Council Meeting', 'council', DATE '2023-08-22', 'x')""", (muni,))
        conn.commit()
    calls = []

    result = backfill_archived_meetings(muni, [ENTRY], fetch_agenda_text=lambda u: (calls.append(u), AGENDA_TEXT)[1])

    assert _meeting(muni, "yt-mYSy3PV-BrA") is None
    assert calls == []
    assert result.inserted == [] and len(result.skipped) == 1


def test_fetch_failure_keeps_meeting_but_leaves_items_for_a_retry(muni):
    def boom(url):
        raise OSError("wayback 503")

    result = backfill_archived_meetings(muni, [ENTRY], fetch_agenda_text=boom)

    row = _meeting(muni, "yt-mYSy3PV-BrA")
    assert row is not None
    assert not row[8]                              # agenda_items_scraped not set
    assert _items(row[0]) == []
    assert len(result.errors) == 1 and "wayback 503" in result.errors[0]

    # a later run fetches again and fills the items
    backfill_archived_meetings(muni, [ENTRY], fetch_agenda_text=lambda u: AGENDA_TEXT)
    assert len(_items(row[0])) == 3


def test_dry_run_writes_nothing_and_fetches_nothing(muni):
    calls = []

    result = backfill_archived_meetings(muni, [ENTRY], fetch_agenda_text=lambda u: (calls.append(u), AGENDA_TEXT)[1],
                                        dry_run=True)

    assert _meeting(muni, "yt-mYSy3PV-BrA") is None
    assert calls == []
    assert result.planned == ["yt-mYSy3PV-BrA"]


# --- Wayback fetch -----------------------------------------------------------

class _Resp:
    def __init__(self, status, content=b""):
        self.status_code = status
        self.content = content
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)


def test_fetch_retries_rate_limits_with_backoff(monkeypatch):
    """The Wayback Machine answers bursts with 429; wait and retry rather than fail the meeting."""
    from docket.services import archived_meetings as am

    responses = [_Resp(429), _Resp(503), _Resp(200, b"%PDF-1.4 ...")]
    sleeps = []
    monkeypatch.setattr(am.requests, "get", lambda url, **kw: responses.pop(0))
    monkeypatch.setattr(am.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(am, "extract_text_from_pdf", lambda b: "ITEM 1.\nA Resolution.\n")

    assert am.fetch_agenda_text("https://web.archive.org/web/1id_/https://x/a.pdf") == "ITEM 1.\nA Resolution.\n"
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0]     # backed off, growing


def test_fetch_gives_up_after_the_retry_budget(monkeypatch):
    from docket.services import archived_meetings as am
    import requests

    monkeypatch.setattr(am.requests, "get", lambda url, **kw: _Resp(429))
    monkeypatch.setattr(am.time, "sleep", lambda s: None)

    with pytest.raises(requests.HTTPError):
        am.fetch_agenda_text("https://web.archive.org/web/1id_/https://x/a.pdf")


def test_fetch_rejects_non_pdf_without_retrying(monkeypatch):
    from docket.services import archived_meetings as am

    calls = []
    monkeypatch.setattr(am.requests, "get", lambda url, **kw: (calls.append(url), _Resp(200, b"<html>"))[1])
    monkeypatch.setattr(am.time, "sleep", lambda s: None)

    with pytest.raises(ValueError):
        am.fetch_agenda_text("https://x/a.pdf")
    assert len(calls) == 1


def test_fetch_caches_the_pdf_on_disk_and_reuses_it(monkeypatch, tmp_path):
    """One Wayback fetch per agenda, ever: the validation run fills the cache,
    the live run reads from it."""
    from docket.services import archived_meetings as am

    calls = []
    monkeypatch.setattr(am.requests, "get", lambda url, **kw: (calls.append(url), _Resp(200, b"%PDF-1.4 cached"))[1])
    monkeypatch.setattr(am.time, "sleep", lambda s: None)
    monkeypatch.setattr(am, "extract_text_from_pdf", lambda b: b.decode())

    url = "https://web.archive.org/web/1id_/https://x/a.pdf"
    assert am.fetch_agenda_text(url, cache_dir=tmp_path) == "%PDF-1.4 cached"
    assert am.fetch_agenda_text(url, cache_dir=tmp_path) == "%PDF-1.4 cached"
    assert len(calls) == 1
    assert len(list(tmp_path.glob("*.pdf"))) == 1
