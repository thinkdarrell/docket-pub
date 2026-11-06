"""The link builder's database reads: a meeting's passing recordings, its consent block, and its items' links.

Each test inserts its own Birmingham meetings and the fixture removes them
(the recordings, measurements, and agenda items go with the meeting). The
module under test is imported inside each test, so the file collects whether
or not it exists. Plan: plans/completed/video-links-land-on-the-moment.md (M4).
"""
from datetime import date

import pytest
from docket.db import db_cursor

CLIP = "99042026"
PLAYER = "https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id="


class _Seed:
    """Inserts rows for one test and remembers the meetings to delete."""

    def __init__(self) -> None:
        self.meeting_ids: list[int] = []

    def meeting(self, clip: str = CLIP, *, video_url: str | None = "player") -> int:
        if video_url == "player":
            video_url = PLAYER + clip
        with db_cursor() as cur:
            cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
            muni = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type, video_url) "
                "VALUES (%s, %s, 'Regular City Council Meeting', %s, 'council', %s) RETURNING id",
                (muni, clip, date(2026, 10, 27), video_url),
            )
            meeting_id = cur.fetchone()["id"]
        self.meeting_ids.append(meeting_id)
        return meeting_id

    def recording(self, meeting_id: int, video_id: str, *, is_primary: bool = False) -> int:
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO meeting_videos (meeting_id, provider, video_id, url, title, clean_title, "
                "duration_s, is_primary) VALUES (%s, 'youtube', %s, %s, 'Regular City Council Meeting 10.27.26', "
                "'Regular City Council Meeting', 3443, %s) RETURNING id",
                (meeting_id, video_id, "https://www.youtube.com/watch?v=" + video_id, is_primary),
            )
            return cur.fetchone()["id"]

    def measurement(self, meeting_video_id: int, *, status: str = "passed", clip: str = CLIP,
                    method_version: int = 2, offset_s=635.48, start_s=635.5, end_s=3935.5,
                    reason: str | None = None) -> None:
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO meeting_video_alignments (meeting_video_id, granicus_clip_id, method_version, "
                "status, reason, offset_s, granicus_start_s, granicus_end_s, score, runner_up, windows, "
                "windows_confirmed) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 23.6, 6.0, 12, 10)",
                (meeting_video_id, clip, method_version, status, reason, offset_s, start_s, end_s),
            )

    def item(self, meeting_id: int, number: str, external_id: str | None, *, is_consent: bool = False,
             cue_s: float | None = None) -> int:
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, item_number, title, external_id, is_consent, "
                "video_timestamp_seconds) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (meeting_id, number, "Item " + number, external_id, is_consent, cue_s),
            )
            return cur.fetchone()["id"]


@pytest.fixture
def seed():
    bag = _Seed()
    try:
        yield bag
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", (bag.meeting_ids,))


def test_for_meetings_returns_only_passed_recordings_primary_first(seed):
    from docket.services import video_links as vl

    meeting_id = seed.meeting()
    # Inserted before the primary, so "primary first" is not just insertion order.
    second_upload = seed.recording(meeting_id, "vll-upload2")
    primary = seed.recording(meeting_id, "vll-primary", is_primary=True)
    third_upload = seed.recording(meeting_id, "vll-upload3")
    rejected = seed.recording(meeting_id, "vll-rejected")
    failed = seed.recording(meeting_id, "vll-failed")
    seed.recording(meeting_id, "vll-unmeasured")
    seed.measurement(second_upload, offset_s=101.28, start_s=101.3, end_s=5050.0)
    seed.measurement(primary)
    seed.measurement(third_upload, offset_s=90.0, start_s=90.0, end_s=5000.0)
    seed.measurement(rejected, status="rejected", reason="score")
    seed.measurement(failed, status="failed", reason="AudioFetchError: refused",
                     offset_s=None, start_s=None, end_s=None)
    bare = seed.meeting("99042027")
    upcoming = seed.meeting("event-99042028", video_url=None)

    videos = vl.for_meetings([meeting_id, bare, upcoming, -1])

    assert set(videos) == {meeting_id, bare, upcoming}, "a meeting that does not exist has no entry"
    video = videos[meeting_id]
    assert video.video_url == PLAYER + CLIP
    assert video.recordings == (
        vl.Recording(video_id="vll-primary", offset_s=635.48, start_s=635.5, end_s=3935.5),
        vl.Recording(video_id="vll-upload2", offset_s=101.28, start_s=101.3, end_s=5050.0),
        vl.Recording(video_id="vll-upload3", offset_s=90.0, start_s=90.0, end_s=5000.0),
    )
    assert video.consent is None
    assert videos[bare] == vl.MeetingVideo(video_url=PLAYER + "99042027")
    assert videos[upcoming] == vl.MeetingVideo(video_url=None)

    assert vl.for_meeting(meeting_id) == video
    assert vl.for_meeting(-1) is None
    assert vl.for_meetings([]) == {}


def test_a_measurement_below_the_trusted_method_version_is_ignored(seed):
    from docket.services import video_links as vl

    meeting_id = seed.meeting()
    # Method 1 covered the outer parts of its first and last windows without
    # checking them (decision 0081), so the site does not use its measurements.
    old = seed.recording(meeting_id, "vll-version1", is_primary=True)
    seed.measurement(old, method_version=1)

    assert vl.MIN_METHOD_VERSION == 2
    assert vl.for_meeting(meeting_id).recordings == ()
    assert vl.link_for(vl.for_meeting(meeting_id), seconds=2256.0, chapter_id="371164").site == "granicus"

    # The version is a floor: a later method's measurement is trusted.
    newer = seed.recording(meeting_id, "vll-version3")
    seed.measurement(newer, method_version=3)
    assert [r.video_id for r in vl.for_meeting(meeting_id).recordings] == ["vll-version3"]


def test_a_measurement_against_another_clip_is_ignored(seed):
    from docket.services import video_links as vl

    # The recording was measured against clip 99042000 and then moved to this
    # meeting (or this meeting's upcoming event became another clip).
    meeting_id = seed.meeting()
    moved = seed.recording(meeting_id, "vll-moved", is_primary=True)
    seed.measurement(moved, clip="99042000")

    assert vl.for_meeting(meeting_id).recordings == ()

    with db_cursor() as cur:
        cur.execute("UPDATE meeting_video_alignments SET granicus_clip_id = %s WHERE meeting_video_id = %s",
                    (CLIP, moved))
    assert [r.video_id for r in vl.for_meeting(meeting_id).recordings] == ["vll-moved"]


def test_the_consent_block_is_computed_from_the_meetings_consent_cue_points(seed):
    from docket.services import video_links as vl

    meeting_id = seed.meeting()
    # Inserted out of cue order; the first of the run by its second is 371101.
    seed.item(meeting_id, "2", "371102", is_consent=True, cue_s=2000.0)
    seed.item(meeting_id, "1", "371101", is_consent=True, cue_s=1990.0)
    seed.item(meeting_id, "3", "371103", is_consent=True, cue_s=2010.0)
    # Shares the run's first second with item 1 and was inserted after it:
    # cue points that tie are taken in row order, so 371101 stays first.
    seed.item(meeting_id, "1a", "371100", is_consent=True, cue_s=1990.0)
    seed.item(meeting_id, "4", "event-2715-4", is_consent=True)               # never cued
    seed.item(meeting_id, "5", "371105", is_consent=True, cue_s=3000.0)       # pulled, discussed later
    seed.item(meeting_id, "64", "371164", is_consent=False, cue_s=2100.0)     # 90 s after the run, not consent
    other = seed.meeting("99042027")
    seed.item(other, "1", "371201", is_consent=True, cue_s=2020.0)
    seed.item(other, "2", "371202", is_consent=True, cue_s=2030.0)

    videos = vl.for_meetings([meeting_id, other])

    assert videos[meeting_id].consent == vl.ConsentBlock(start_s=1990.0, end_s=2010.0, chapter_id="371101")
    assert videos[other].consent is None, "two cue points make no block, and meetings do not share cue points"


def test_item_links_on_meeting_3184s_shape(seed):
    from docket.services import video_links as vl

    meeting_id = seed.meeting()
    recording = seed.recording(meeting_id, "FR84h22hQvA-vll", is_primary=True)
    seed.measurement(recording, offset_s=635.48, start_s=635.5, end_s=3935.5)
    first = seed.item(meeting_id, "1", "371101", is_consent=True, cue_s=1990.0)
    middle = seed.item(meeting_id, "2", "371102", is_consent=True, cue_s=2040.0)
    last = seed.item(meeting_id, "6", "371106", is_consent=True, cue_s=2085.0)
    uncued = seed.item(meeting_id, "7", "event-2715-7", is_consent=True)
    item_3 = seed.item(meeting_id, "3", "371103", is_consent=False, cue_s=2145.0)
    item_64 = seed.item(meeting_id, "64", "371164", is_consent=False, cue_s=2256.0)
    after = seed.item(meeting_id, "70", "371170", is_consent=False, cue_s=4000.0)

    links = vl.item_links(meeting_id)

    watch = "https://www.youtube.com/watch?v=FR84h22hQvA-vll&t="
    assert set(links) == {first, middle, last, uncued, item_3, item_64, after}
    assert links[first].url == watch + "1354s"
    assert links[middle].url == watch + "1354s"
    assert links[last].url == watch + "1354s"
    assert links[uncued].url == watch + "1354s"
    assert links[item_3].url == watch + "1509s"
    assert links[item_64].url == watch + "1620s"
    assert links[item_64].phrase == "video on YouTube"
    # Past the recording's coverage the item opens its Granicus chapter.
    assert links[after].url == PLAYER + CLIP + "&meta_id=371170"
    assert links[after].phrase == "video chapter on Granicus"

    # With the measurement gone every item is back on Granicus: a consent item
    # on the consent agenda's first chapter, the others on their own.
    with db_cursor() as cur:
        cur.execute("DELETE FROM meeting_video_alignments WHERE meeting_video_id = %s", (recording,))
    links = vl.item_links(meeting_id)
    assert links[middle].url == PLAYER + CLIP + "&meta_id=371101"
    assert links[uncued].url == PLAYER + CLIP + "&meta_id=371101"
    assert links[item_64].url == PLAYER + CLIP + "&meta_id=371164"

    assert vl.item_links(-1) == {}
    upcoming = seed.meeting("event-99042028", video_url=None)
    seed.item(upcoming, "1", "event-99042028-1")
    assert vl.item_links(upcoming) == {}, "a meeting with no video has no video links"
