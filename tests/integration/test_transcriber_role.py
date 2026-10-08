"""The transcriber role can write transcript tables and nothing else."""
import pytest
import psycopg2
from docket.config import DATABASE_URL
from docket.db import db

pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Role test must not run against Railway prod.",
)

ROLE_SQL = open("scripts/sql/create_transcriber_role.sql").read()


@pytest.fixture
def transcriber_role():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP ROLE IF EXISTS transcriber")
            cur.execute(ROLE_SQL.replace(":'password'", "'test-pass'"))
    yield
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("REASSIGN OWNED BY transcriber TO CURRENT_USER")
            cur.execute("DROP OWNED BY transcriber")
            cur.execute("DROP ROLE IF EXISTS transcriber")


def _priv(table: str, priv: str) -> bool:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT has_table_privilege('transcriber', %s, %s)", [table, priv])
            return cur.fetchone()[0]


def test_can_write_transcript_tables(transcriber_role):
    for t in ("transcripts", "transcript_segments", "transcript_speakers", "producer_heartbeats"):
        assert _priv(t, "INSERT"), t
        assert _priv(t, "UPDATE"), t
        assert _priv(t, "DELETE"), t


def test_can_read_reference_tables(transcriber_role):
    for t in ("meetings", "municipalities", "council_members", "agenda_items"):
        assert _priv(t, "SELECT"), t
        assert not _priv(t, "UPDATE"), t


def test_cannot_touch_everything_else(transcriber_role):
    for t in ("votes", "ai_runs", "minutes_discrepancies", "meeting_events", "admin_users"):
        assert not _priv(t, "SELECT"), t
        assert not _priv(t, "INSERT"), t
