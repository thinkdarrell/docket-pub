from pathlib import Path

import pytest

from docket.ai.transcripts import minutes as M
from docket.config import DATABASE_URL
from docket.db import db_cursor

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)
PDF = Path("tests/fixtures/granicus_bham_agenda_2026_05_19.pdf").read_bytes()
URL = "https://bhamal.granicus.com/MinutesViewer.php?view_id=2&clip_id=999"


@pytest.fixture
def meeting():
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, external_id, minutes_url)
                       VALUES (%s, 'MC test', '2026-09-03', '999903', %s) RETURNING id""", [muni, URL])
        mid = cur.fetchone()["id"]
    yield mid
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id=%s", [mid])


def test_capture_inserts_then_detects_change(meeting, monkeypatch):
    monkeypatch.setattr(M, "download_minutes", lambda url, timeout=30: PDF)
    c1 = M.capture_minutes(meeting, URL)
    assert c1.is_new and not c1.changed and len(c1.page_offsets) >= 1 and len(c1.sha256) == 64
    c2 = M.capture_minutes(meeting, URL)
    assert not c2.is_new and not c2.changed and c2.minutes_text_id == c1.minutes_text_id
    monkeypatch.setattr(M, "download_minutes", lambda url, timeout=30: PDF + b"\n% corrected")
    c3 = M.capture_minutes(meeting, URL)
    assert c3.changed and c3.sha256 != c1.sha256 and c3.minutes_text_id == c1.minutes_text_id
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM minutes_texts WHERE meeting_id=%s", [meeting])
        assert cur.fetchone()["n"] == 1
    assert M.recheck_minutes(meeting) is False


def test_html_page_instead_of_pdf_returns_none_and_writes_nothing(meeting, monkeypatch):
    monkeypatch.setattr(M, "download_minutes", lambda url, timeout=30: None)
    assert M.capture_minutes(meeting, URL) is None
    assert M.load_minutes(meeting) is None
    assert M.recheck_minutes(meeting) is None
