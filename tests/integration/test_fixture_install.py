import pytest

from docket.config import DATABASE_URL
from docket.db import db_cursor
from tests.support.transcript_fixtures import install_bundle, load_bundle, pilot_bundle

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


def test_install_and_cleanup_round_trip():
    inst = install_bundle(load_bundle("transcript_2543"))
    try:
        with db_cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM transcript_segments WHERE transcript_id=%s", [inst.transcript_id])
            assert cur.fetchone()["n"] > 150
            cur.execute("SELECT status, word_count FROM transcripts WHERE id=%s", [inst.transcript_id])
            row = cur.fetchone()
            assert row["status"] == "uploaded" and row["word_count"] > 10_000
            cur.execute("SELECT count(*) AS n FROM transcript_speakers WHERE meeting_id=%s", [inst.meeting_id])
            assert cur.fetchone()["n"] >= 20
    finally:
        inst.cleanup()
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM meetings WHERE id=%s", [inst.meeting_id])
        assert cur.fetchone() is None


def test_pilot_install_has_minutes_and_item():
    inst = install_bundle(pilot_bundle(), external_id="999015")
    try:
        with db_cursor() as cur:
            cur.execute("SELECT text, page_offsets FROM minutes_texts WHERE meeting_id=%s", [inst.meeting_id])
            row = cur.fetchone()
            assert "Executive Session" in row["text"] and len(row["page_offsets"]) > 10
            cur.execute("SELECT external_id FROM agenda_items WHERE meeting_id=%s", [inst.meeting_id])
            assert cur.fetchone()["external_id"] == "1950-15"
    finally:
        inst.cleanup()
