from datetime import date, timedelta
from unittest.mock import patch

import pytest

from docket.ai.transcripts import alerts as A
from docket.config import DATABASE_URL
from docket.db import db_cursor

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


@pytest.fixture(scope="module", autouse=True)
def preserve_heartbeats():
    """Snapshot producer_heartbeats and restore it after the module (a test ages every row)."""
    with db_cursor() as cur:
        cur.execute("SELECT host, last_seen_at, last_status, last_meeting_id, producer_version FROM producer_heartbeats")
        rows = cur.fetchall()
    yield
    with db_cursor() as cur:
        cur.execute("DELETE FROM producer_heartbeats")
        for r in rows:
            cur.execute(
                """INSERT INTO producer_heartbeats (host, last_seen_at, last_status, last_meeting_id, producer_version)
                   VALUES (%s, %s, %s, %s, %s)""",
                [r["host"], r["last_seen_at"], r["last_status"], r["last_meeting_id"], r["producer_version"]],
            )


@pytest.fixture
def old_meeting_without_transcript():
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, external_id, video_url)
                       VALUES (%s, 'stall test', %s, '999777', 'https://bhamal.granicus.com/MediaPlayer.php?clip_id=999777') RETURNING id""",
                    [muni, date.today() - timedelta(days=10)])
        mid = cur.fetchone()["id"]
        cur.execute("DELETE FROM producer_heartbeats WHERE host LIKE 'pytest-%%'")
    yield mid
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id=%s", [mid])
        cur.execute("DELETE FROM producer_heartbeats WHERE host LIKE 'pytest-%%'")


def test_stalled_when_no_recent_heartbeat(old_meeting_without_transcript, monkeypatch):
    with db_cursor() as cur:
        cur.execute("UPDATE producer_heartbeats SET last_seen_at = now() - interval '30 days'")   # any real rows are old for this test
    s = A.producer_stalled()
    assert s is not None and s["meeting_id"] == old_meeting_without_transcript
    monkeypatch.setattr(A, "ALERT_WEBHOOK_URL", "https://hooks.example/abc")
    with patch("docket.ai.transcripts.alerts.requests.post") as post:
        post.return_value.ok = True
        assert A.alert_if_producer_stalled() is True
        assert "no transcript" in post.call_args.kwargs["json"]["text"]


def test_recent_heartbeat_means_not_stalled(old_meeting_without_transcript):
    with db_cursor() as cur:
        cur.execute("INSERT INTO producer_heartbeats (host, last_seen_at, last_status) VALUES ('pytest-legion', now(), 'idle')")
    assert A.producer_stalled() is None
    assert A.alert_if_producer_stalled() is False
