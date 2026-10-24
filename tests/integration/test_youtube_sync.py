"""Integration tests: ``youtube_meetings.sync_city`` matches the council's YouTube recordings to meeting rows.

A fake client returns fixed ``YouTubeVideo``s (already filled), so the tests
exercise the matching ladder against a real database: attach to the day's
council row, attach to the day's one committee candidate, pair by duration on
a busy day, create a ``yt-`` row after three days, refuse to create while a
candidate clip has no stored duration, absorb a young ``yt-`` row into a
Granicus clip that arrived later, and write nothing on a dry run.

Every row here is Birmingham's (migration 040 gives it ``youtube_channel_id``),
dated June 2019 so no other test's rows share a day; Granicus-shaped rows carry
the external id prefix ``m4t-`` and every video id starts ``M4T``, which is what
the cleanup deletes by. ``sync_city`` is imported inside each test so the file
collects before the function exists.

Plan: plans/active/youtube-council-channel.md (M4).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from docket.adapters.youtube import YouTubeVideo
from docket.config import DATABASE_URL
from docket.db import db_cursor

pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Integration tests require local DB; will not run against Railway prod",
)

TODAY = date(2019, 6, 30)


def _published(days_ago: int) -> datetime:
    d = TODAY - timedelta(days=days_ago)
    return datetime(d.year, d.month, d.day, 23, 0, tzinfo=timezone.utc)


def _video(vid: str, title: str, duration_s: int, *, days_ago: int = 10, started_at=None) -> YouTubeVideo:
    return YouTubeVideo(
        video_id=f"M4T{vid}",
        title=title,
        published_at=_published(days_ago),
        duration_s=duration_s,
        started_at=started_at,
        broadcast="none",
    )


class FakeClient:
    def __init__(self, videos):
        self.videos = list(videos)
        self.listed_after = []

    def uploads_playlist_id(self, handle):
        return "UUfake"

    def list_uploads(self, playlist_id, *, published_after=None):
        self.listed_after.append(published_after)
        return list(self.videos)

    def fill_details(self, videos):
        return list(videos)


def _cleanup(bhm: int) -> None:
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM meetings WHERE municipality_id = %s AND (external_id LIKE 'm4t-%%' OR external_id LIKE 'yt-M4T%%')",
            (bhm,),
        )
        cur.execute("DELETE FROM meeting_videos WHERE video_id LIKE 'M4T%%'")


@pytest.fixture
def bhm(seeded_birmingham):
    _cleanup(seeded_birmingham)
    yield seeded_birmingham
    _cleanup(seeded_birmingham)


def _row(bhm: int, ext: str, d: date, *, title: str = "Regular City Council Meeting",
         meeting_type: str = "council", type_source: str = "title", duration_s: int | None = None,
         items: int = 0, minutes_url: str | None = None, created_days_ago: int | None = None) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type,
                                     session_kind, type_source, duration_s, minutes_url, video_url, source_url)
               VALUES (%s, %s, %s, %s, %s, 'regular', %s, %s, %s, %s, %s) RETURNING id""",
            (bhm, ext, title, d, meeting_type, type_source, duration_s, minutes_url,
             f"https://bhamal.granicus.com/MediaPlayer.php?clip_id={ext}",
             "https://bhamal.granicus.com/ViewPublisher.php?view_id=2"),
        )
        mid = cur.fetchone()["id"]
        for n in range(items):
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title, is_consent) VALUES (%s, %s, FALSE)",
                (mid, f"Item {n + 1}"),
            )
        return mid


def _meeting(mid: int) -> dict | None:
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, external_id, title, meeting_type, session_kind, body_name, type_source, is_hidden, "
            "video_url, source_url, duration_s, start_time FROM meetings WHERE id = %s",
            (mid,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def _by_ext(bhm: int, ext: str) -> dict | None:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM meetings WHERE municipality_id = %s AND external_id = %s", (bhm, ext))
        row = cur.fetchone()
    return _meeting(row["id"]) if row else None


def _videos_of(mid: int) -> list[tuple[str, bool]]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT video_id, is_primary FROM meeting_videos WHERE meeting_id = %s ORDER BY is_primary DESC, video_id",
            (mid,),
        )
        return [(r["video_id"], r["is_primary"]) for r in cur.fetchall()]


def _count_rows(bhm: int) -> tuple[int, int]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM meetings WHERE municipality_id = %s "
            "AND (external_id LIKE 'm4t-%%' OR external_id LIKE 'yt-M4T%%')",
            (bhm,),
        )
        meetings = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM meeting_videos WHERE video_id LIKE 'M4T%%'")
        return meetings, cur.fetchone()["n"]


def _sync(videos, **kw):
    from docket.services.youtube_meetings import sync_city

    return sync_city("birmingham", client=FakeClient(videos), since=None, today=TODAY, **kw)


def _actions(report) -> list[str]:
    return [a for _d, a, _detail in report.decisions]


# --- attach -------------------------------------------------------------------


def test_committee_video_attaches_to_the_days_one_bodyless_clip_and_names_it(bhm):
    d = date(2019, 6, 3)  # Monday
    clip = _row(bhm, "m4t-1", d, meeting_type="committee", type_source="schedule_rule", duration_s=1500)

    report = _sync([_video("bf1", "Budget and Finance Committee Meeting 6.3.19", 1380)])

    assert _actions(report) == ["attach"]
    assert report.counts["attach"] == 1
    assert clip in report.touched_ids
    assert _videos_of(clip) == [("M4Tbf1", True)]
    row = _meeting(clip)
    assert row["body_name"] == "Budget and Finance Committee"
    assert row["meeting_type"] == "committee"
    assert row["type_source"] == "video"


def test_council_video_attaches_to_the_council_row_and_leaves_its_classification(bhm):
    d = date(2019, 6, 4)  # Tuesday
    council = _row(bhm, "m4t-2", d, duration_s=3000, items=12, minutes_url="https://example.com/m.pdf")
    before = _meeting(council)

    report = _sync([_video("cc1", "Birmingham City Council Meeting 6.4.19", 3100)])

    assert _actions(report) == ["attach"]
    assert _videos_of(council) == [("M4Tcc1", True)]
    after = _meeting(council)
    for key in ("meeting_type", "session_kind", "body_name", "type_source"):
        assert after[key] == before[key]


# --- create and defer -----------------------------------------------------------


def test_committee_of_the_whole_on_an_empty_day_creates_a_yt_row(bhm):
    d = date(2019, 6, 19)  # Wednesday, no rows
    started = datetime(2019, 6, 19, 15, 5, tzinfo=timezone.utc)  # 10:05 in Chicago

    report = _sync([_video("cow", "Committee of the Whole Meeting 6.19.19", 11406, days_ago=10, started_at=started)])

    assert _actions(report) == ["create"]
    row = _by_ext(bhm, "yt-M4Tcow")
    assert row is not None
    assert row["meeting_type"] == "committee"
    assert row["body_name"] == "Committee of the Whole"
    assert row["title"] == "Committee of the Whole Meeting"
    assert row["video_url"] == "https://www.youtube.com/watch?v=M4Tcow"
    assert row["source_url"] == "https://www.youtube.com/watch?v=M4Tcow"
    assert row["duration_s"] == 11406
    assert row["start_time"] == time(10, 5)
    assert _videos_of(row["id"]) == [("M4Tcow", True)]
    assert row["id"] in report.touched_ids


def test_a_video_published_yesterday_is_deferred(bhm):
    report = _sync([_video("cow", "Committee of the Whole Meeting 6.19.19", 11406, days_ago=1)])

    assert _actions(report) == ["defer"]
    assert report.counts["defer"] == 1
    assert _by_ext(bhm, "yt-M4Tcow") is None


def test_a_second_run_of_the_same_listing_changes_nothing(bhm):
    d = date(2019, 6, 3)
    _row(bhm, "m4t-1", d, meeting_type="committee", type_source="schedule_rule", duration_s=1500)
    videos = [
        _video("bf1", "Budget and Finance Committee Meeting 6.3.19", 1380),
        _video("cow", "Committee of the Whole Meeting 6.19.19", 11406),
    ]
    first = _sync(videos)
    assert sorted(_actions(first)) == ["attach", "create"]
    counts = _count_rows(bhm)

    second = _sync(videos)

    assert _actions(second) == ["skip_seen", "skip_seen"]
    assert second.counts["attach"] == 0 and second.counts["create"] == 0
    assert _count_rows(bhm) == counts


# --- busy days -------------------------------------------------------------------


def test_two_bodyless_clips_and_one_video_pair_by_duration_and_list_the_day(bhm):
    d = date(2019, 6, 10)  # Monday
    short = _row(bhm, "m4t-3", d, meeting_type="committee", type_source="schedule_rule", duration_s=360)
    long_ = _row(bhm, "m4t-4", d, meeting_type="committee", type_source="schedule_rule", duration_s=1500)

    report = _sync([_video("bf2", "Budget and Finance Committee Meeting 6.10.19", 1380)])

    assert _actions(report) == ["attach"]
    assert _videos_of(long_) == [("M4Tbf2", True)]
    assert _videos_of(short) == []
    assert d in report.ambiguous_days
    assert report.counts["ambiguous"] == 1


def test_zero_item_council_clip_beside_a_council_row_with_items_takes_the_committee_video(bhm):
    d = date(2019, 6, 18)  # Tuesday
    council = _row(bhm, "m4t-5", d, duration_s=4000, items=8)
    clip = _row(bhm, "m4t-6", d, duration_s=1300)

    report = _sync([_video("ps1", "Public Safety Committee Meeting 6.18.19", 1250)])

    assert _actions(report) == ["attach"]
    assert _videos_of(clip) == [("M4Tps1", True)]
    assert _videos_of(council) == []
    row = _meeting(clip)
    assert row["meeting_type"] == "committee"
    assert row["body_name"] == "Public Safety Committee"
    assert row["type_source"] == "video"


def test_the_october_13_shape_creates_two_rows_and_leaves_the_short_clip(bhm):
    d = date(2019, 6, 11)  # Tuesday
    council = _row(bhm, "m4t-7", d, duration_s=1800, items=10)
    clip = _row(bhm, "m4t-8", d, duration_s=300)

    report = _sync([
        _video("ps2", "6.11.19 Public Safety Committee meeting", 2220),
        _video("pz2", "Planning and Zoning Committee Meeting 6.11.19", 1320),
    ])

    assert sorted(_actions(report)) == ["create", "create"]
    assert _by_ext(bhm, "yt-M4Tps2")["body_name"] == "Public Safety Committee"
    assert _by_ext(bhm, "yt-M4Tpz2")["body_name"] == "Planning and Zoning Committee"
    assert _videos_of(clip) == []
    assert _videos_of(council) == []
    assert _meeting(clip)["meeting_type"] == "council"
    assert d in report.ambiguous_days


def test_a_two_part_group_is_compared_by_its_total(bhm):
    d = date(2019, 6, 24)  # Monday
    clip = _row(bhm, "m4t-9", d, meeting_type="committee", type_source="schedule_rule", duration_s=2100)
    other = _row(bhm, "m4t-10", d, meeting_type="committee", type_source="schedule_rule", duration_s=600)

    report = _sync([
        _video("ap1", "Arts and Parks Committee Meeting 6.24.19 Pt. 1", 300),
        _video("ap2", "Arts and Parks Committee Meeting 6.24.19 Pt. 2", 1800),
    ])

    assert _actions(report) == ["attach"]
    assert _videos_of(clip) == [("M4Tap2", True), ("M4Tap1", False)]
    assert _videos_of(other) == []


def test_a_candidate_clip_without_a_duration_blocks_the_day(bhm):
    d = date(2019, 6, 17)  # Monday
    clip = _row(bhm, "m4t-11", d, meeting_type="committee", type_source="schedule_rule", duration_s=None)

    report = _sync([_video("cd1", "Community Development Committee Meeting 6.17.19", 1500)])

    assert _actions(report) == ["no_duration"]
    assert report.counts["no_duration"] == 1
    assert _videos_of(clip) == []
    assert _by_ext(bhm, "yt-M4Tcd1") is None


# --- absorption ------------------------------------------------------------------


def _yt_row(bhm: int, vid: str, d: date, duration_s: int, title: str) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type,
                                     session_kind, body_name, type_source, duration_s, video_url, source_url)
               VALUES (%s, %s, %s, %s, 'committee', 'regular', %s, 'title', %s, %s, %s) RETURNING id""",
            (bhm, f"yt-M4T{vid}", title, d, title.replace(" Meeting", ""), duration_s,
             f"https://www.youtube.com/watch?v=M4T{vid}", f"https://www.youtube.com/watch?v=M4T{vid}"),
        )
        mid = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO meeting_videos (meeting_id, provider, video_id, url, title, clean_title, duration_s, is_primary)
               VALUES (%s, 'youtube', %s, %s, %s, %s, %s, TRUE)""",
            (mid, f"M4T{vid}", f"https://www.youtube.com/watch?v=M4T{vid}", f"{title} {d:%m.%d.%y}", title, duration_s),
        )
        return mid


def test_a_young_yt_row_is_absorbed_by_a_clip_that_arrived_later(bhm):
    d = TODAY - timedelta(days=5)
    yt = _yt_row(bhm, "tr1", d, 1400, "Transportation Committee Meeting")
    clip = _row(bhm, "m4t-12", d, meeting_type="committee", type_source="schedule_rule", duration_s=1500)
    listing = [_video("tr1", f"Transportation Committee Meeting {d.month}.{d.day}.19", 1400, days_ago=4)]

    report = _sync(listing)

    assert "absorb" in _actions(report)
    assert report.counts["absorb"] == 1
    assert _meeting(yt) is None
    assert _videos_of(clip) == [("M4Ttr1", True)]
    assert _meeting(clip)["body_name"] == "Transportation Committee"
    assert clip in report.touched_ids


def test_a_yt_row_with_a_transcript_is_hidden_instead_of_deleted(bhm):
    d = TODAY - timedelta(days=5)
    yt = _yt_row(bhm, "tr2", d, 1400, "Transportation Committee Meeting")
    clip = _row(bhm, "m4t-13", d, meeting_type="committee", type_source="schedule_rule", duration_s=1500)
    with db_cursor() as cur:
        cur.execute("INSERT INTO transcripts (meeting_id, status) VALUES (%s, 'uploaded')", (yt,))

    report = _sync([])

    assert _actions(report) == ["absorb"]
    row = _meeting(yt)
    assert row is not None and row["is_hidden"] is True
    assert _videos_of(yt) == []
    assert _videos_of(clip) == [("M4Ttr2", True)]


# --- dry run ---------------------------------------------------------------------


def test_dry_run_writes_nothing(bhm):
    d = date(2019, 6, 3)
    clip = _row(bhm, "m4t-1", d, meeting_type="committee", type_source="schedule_rule", duration_s=1500)
    yt_day = TODAY - timedelta(days=5)
    yt = _yt_row(bhm, "tr3", yt_day, 1400, "Transportation Committee Meeting")
    _row(bhm, "m4t-14", yt_day, meeting_type="committee", type_source="schedule_rule", duration_s=1500)
    before_counts = _count_rows(bhm)
    before_clip = _meeting(clip)

    report = _sync(
        [
            _video("bf1", "Budget and Finance Committee Meeting 6.3.19", 1380),
            _video("cow", "Committee of the Whole Meeting 6.19.19", 11406),
        ],
        dry_run=True,
    )

    assert sorted(_actions(report)) == ["absorb", "attach", "create"]
    assert _count_rows(bhm) == before_counts
    assert _meeting(clip) == before_clip
    assert _videos_of(clip) == []
    assert _meeting(yt) is not None


def test_no_client_returns_an_empty_report(bhm, caplog):
    from docket.services.youtube_meetings import sync_city

    with caplog.at_level("WARNING"):
        report = sync_city("birmingham", client=None, since=None, today=TODAY)
    assert report.decisions == [] and report.touched_ids == []
    assert any("YOUTUBE_API_KEY" in r.getMessage() for r in caplog.records)
