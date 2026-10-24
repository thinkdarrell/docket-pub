"""Verify migration 040: `meeting_videos`, `meetings.duration_s`, the `video` type source, and Birmingham's YouTube metadata; down removes all of them.

Pattern: tests/integration/test_038_migration.py. Plan: plans/active/youtube-council-channel.md (M2).
"""
from datetime import date

import psycopg2.errors
import pytest
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Migration test must not run against Railway prod.",
)

PREFIX = "m040-"


@pytest.fixture
def fresh_040():
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 40)
    yield
    with db() as conn:
        runner.apply_migrations(conn)
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (PREFIX + "%",))


def _table_exists() -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT to_regclass('public.meeting_videos') AS t")
        return cur.fetchone()["t"] is not None


def _has_duration_column() -> bool:
    with db_cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM information_schema.columns "
            "WHERE table_name = 'meetings' AND column_name = 'duration_s'"
        )
        return cur.fetchone()["n"] == 1


def _birmingham() -> dict:
    with db_cursor() as cur:
        cur.execute("SELECT id, metadata FROM municipalities WHERE slug = 'birmingham'")
        return cur.fetchone()


def _insert_with_source(source: str, external_id: str) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type, type_source) "
            "VALUES (%s, %s, 'Regular City Council Meeting', %s, 'council', %s) RETURNING id",
            (_birmingham()["id"], external_id, date(2026, 9, 28), source),
        )
        return cur.fetchone()["id"]


def test_040_up_adds_table_column_constraint_and_metadata(fresh_040):
    assert not _table_exists()
    assert not _has_duration_column()
    meta = _birmingham()["metadata"]
    assert "youtube_channel" not in meta and "youtube_channel_id" not in meta
    with pytest.raises(psycopg2.errors.CheckViolation):
        _insert_with_source("video", PREFIX + "before")

    with db() as conn:
        runner.apply_migrations(conn)

    assert _table_exists()
    assert _has_duration_column()
    meta = _birmingham()["metadata"]
    assert meta["youtube_channel"] == "citycouncilbham"
    assert meta["youtube_channel_id"] == "UCxKV8MgjDbqw9PMGTsF_NUw"
    assert meta["council_schedule"] == {"weekday": 1}, "038's keys survive the up"
    assert _insert_with_source("video", PREFIX + "after") > 0
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM municipalities WHERE metadata ? 'youtube_channel_id'")
        assert cur.fetchone()["n"] == 1, "only Birmingham carries a channel"


def test_040_down_removes_all(fresh_040):
    with db() as conn:
        runner.apply_migrations(conn)
    _insert_with_source("video", PREFIX + "video-row")
    with db() as conn:
        runner.rollback_migration(conn, 40)

    assert not _table_exists()
    assert not _has_duration_column()
    meta = _birmingham()["metadata"]
    assert "youtube_channel" not in meta and "youtube_channel_id" not in meta
    assert meta["council_schedule"] == {"weekday": 1}, "038's keys survive the down"
    with db_cursor() as cur:
        cur.execute("SELECT type_source FROM meetings WHERE external_id = %s", (PREFIX + "video-row",))
        assert cur.fetchone()["type_source"] == "title", "a video-sourced row falls back to title"
    with pytest.raises(psycopg2.errors.CheckViolation):
        _insert_with_source("video", PREFIX + "after-down")


class TestMeetingVideos:
    """The table's constraints: provider vocabulary, one row per video, one primary per meeting and provider, cascade."""

    @pytest.fixture
    def meeting_id(self):
        with db() as conn:
            runner.apply_migrations(conn)
        mid = _insert_with_source("title", PREFIX + "videos")
        yield mid
        with db_cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (PREFIX + "%",))

    @staticmethod
    def _video(meeting_id: int, video_id: str, *, provider: str = "youtube", primary: bool = False) -> None:
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO meeting_videos (meeting_id, provider, video_id, url, title, clean_title, duration_s, is_primary) "
                "VALUES (%s, %s, %s, %s, 'Budget and Finance Committee Meeting 9.28.26', "
                "'Budget and Finance Committee Meeting', 1380, %s)",
                (meeting_id, provider, video_id, f"https://www.youtube.com/watch?v={video_id}", primary),
            )

    def test_unknown_provider_is_refused(self, meeting_id):
        with pytest.raises(psycopg2.errors.CheckViolation):
            self._video(meeting_id, "m040-vimeo", provider="vimeo")

    def test_a_video_belongs_to_one_meeting(self, meeting_id):
        self._video(meeting_id, "m040-gjvBCa3zcnU", primary=True)
        with pytest.raises(psycopg2.errors.UniqueViolation):
            self._video(meeting_id, "m040-gjvBCa3zcnU")

    def test_one_primary_per_meeting_and_provider(self, meeting_id):
        self._video(meeting_id, "m040-pt2", primary=True)
        self._video(meeting_id, "m040-pt1")
        with pytest.raises(psycopg2.errors.UniqueViolation):
            self._video(meeting_id, "m040-other", primary=True)

    def test_deleting_the_meeting_deletes_its_videos(self, meeting_id):
        self._video(meeting_id, "m040-cascade", primary=True)
        with db_cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = %s", (meeting_id,))
            cur.execute("SELECT count(*) AS n FROM meeting_videos WHERE video_id = 'm040-cascade'")
            assert cur.fetchone()["n"] == 0
