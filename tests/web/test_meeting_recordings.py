"""The site shows a meeting's YouTube recordings and every source host (M5).

The meeting page reads ``query.videos_for_meeting`` (the row's
``meeting_videos``, primary first) as ``recordings``: a row whose
``video_url`` is not on YouTube gains a "Watch on YouTube" rail link, a row
with more than one recording lists the others as "Part N" links, and a row
named by the ladder's ``video`` rung says "The council's YouTube recording
names it." with a link to the recording. ``briefing.city_provenance`` gains
``source_hosts``, every distinct host of the city's non-hidden rows of the
last 180 days, most rows first, which the footer and the sources paragraph
print joined by " and ".

Pattern: ``client`` from ``tests/web/conftest.py``; rows seeded directly
with an ``external_id`` prefix and deleted after (``meeting_videos`` rows go
with them by cascade). Runs in the web tier against the throwaway database.

Plan: plans/active/youtube-council-channel.md (M5).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from docket.db import db
from tests.support import briefing_seed

PREFIX = "ytrec-"
CLIP = "Regular City Council Meeting"
GRANICUS_SOURCE = "https://bhamal.granicus.com/ViewPublisher.php?view_id=2"
GRANICUS_PLAYER = "https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=2018"


def _watch(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _city_id(cur, slug: str) -> int:
    cur.execute("SELECT id FROM municipalities WHERE slug = %s", (slug,))
    row = cur.fetchone()
    assert row is not None, f"city must be seeded: {slug}"
    return row[0]


def _meeting(cur, city_id: int, ext: str, title: str, meeting_date: date, *, meeting_type: str = "council",
             body_name: str | None = None, type_source: str = "title", video_url: str | None = None,
             source_url: str | None = None) -> int:
    cur.execute(
        """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type,
                                 session_kind, body_name, type_source, video_url, source_url)
           VALUES (%s, %s, %s, %s, %s, 'regular', %s, %s, %s, %s) RETURNING id""",
        (city_id, PREFIX + ext, title, meeting_date, meeting_type, body_name, type_source,
         video_url, source_url),
    )
    return cur.fetchone()[0]


def _video(cur, meeting_id: int, video_id: str, title: str, clean: str, duration_s: int, *,
           primary: bool) -> None:
    cur.execute(
        """INSERT INTO meeting_videos (meeting_id, provider, video_id, url, title, clean_title,
                                       duration_s, is_primary)
           VALUES (%s, 'youtube', %s, %s, %s, %s, %s, %s)""",
        (meeting_id, PREFIX + video_id, _watch(PREFIX + video_id), title, clean, duration_s, primary),
    )


def _cleanup(cur) -> None:
    cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (PREFIX + "%",))


@pytest.fixture
def rows():
    """Four Birmingham rows of the last month, two hosts among them."""
    today = date.today()
    with db() as conn, conn.cursor() as cur:
        _cleanup(cur)
        bhm = _city_id(cur, "birmingham")
        attached = _meeting(cur, bhm, "2018", CLIP, today - timedelta(days=12), meeting_type="committee",
                            body_name="Budget and Finance Committee", type_source="video",
                            video_url=GRANICUS_PLAYER, source_url=GRANICUS_SOURCE)
        _video(cur, attached, "gjv", "Budget and Finance Committee Meeting 9.28.26",
               "Budget and Finance Committee Meeting", 1380, primary=True)
        parts = _meeting(cur, bhm, "2019", "Public Safety Committee Meeting", today - timedelta(days=11),
                         meeting_type="committee", body_name="Public Safety Committee",
                         video_url=GRANICUS_PLAYER, source_url=GRANICUS_SOURCE)
        _video(cur, parts, "pt2", "Public Safety Committee Meeting 2.10.26 Pt. 2",
               "Public Safety Committee Meeting", 1800, primary=True)
        _video(cur, parts, "pt1", "Public Safety Committee Meeting 2.10.26 Pt. 1",
               "Public Safety Committee Meeting", 300, primary=False)
        yt = _meeting(cur, bhm, "yt-cotw", "Committee of the Whole Meeting", today - timedelta(days=10),
                      meeting_type="committee", body_name="Committee of the Whole",
                      video_url=_watch(PREFIX + "cotw"), source_url=_watch(PREFIX + "cotw"))
        _video(cur, yt, "cotw", "Committee of the Whole Meeting 9.30.26", "Committee of the Whole Meeting",
               11400, primary=True)
        plain = _meeting(cur, bhm, "2020", CLIP, today - timedelta(days=9),
                         video_url=GRANICUS_PLAYER, source_url=GRANICUS_SOURCE)
        conn.commit()
    briefing_seed.clear_caches()
    try:
        yield {"attached": attached, "parts": parts, "yt": yt, "plain": plain}
    finally:
        with db() as conn, conn.cursor() as cur:
            _cleanup(cur)
            conn.commit()
        briefing_seed.clear_caches()


def _get(client, path: str) -> str:
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.status_code)
    return resp.get_data(as_text=True)


def _sources(html: str) -> str:
    """The meeting page's source-links section."""
    start = html.index('<section class="mtg-sources">')
    return html[start:html.index("</section>", start)]


def test_videos_for_meeting_lists_primary_first(rows):
    from docket.services import query

    videos = query.videos_for_meeting(rows["parts"])
    assert [v["video_id"] for v in videos] == [PREFIX + "pt2", PREFIX + "pt1"]
    assert videos[0]["is_primary"] is True
    assert videos[0]["provider"] == "youtube"
    assert videos[0]["url"] == _watch(PREFIX + "pt2")
    assert videos[0]["duration_s"] == 1800
    assert [v["part"] for v in videos] == [2, 1]
    assert query.videos_for_meeting(rows["plain"]) == []


def test_granicus_row_with_a_youtube_recording_shows_both_links(client, rows):
    rail = _sources(_get(client, f"/al/birmingham/meetings/{rows['attached']}/"))
    assert "Granicus player" in rail
    assert ">Watch on YouTube</div>" in rail
    assert "council channel" in rail
    assert f'href="{_watch(PREFIX + "gjv")}"' in rail


def test_yt_row_shows_one_watch_link(client, rows):
    rail = _sources(_get(client, f"/al/birmingham/meetings/{rows['yt']}/"))
    assert "Watch on YouTube" not in rail
    assert rail.count(">Watch video</div>") == 1
    assert "YouTube (council channel)" in rail


def test_row_without_recordings_is_unchanged(client, rows):
    rail = _sources(_get(client, f"/al/birmingham/meetings/{rows['plain']}/"))
    assert "Watch on YouTube" not in rail
    assert "Part " not in rail


def test_other_recordings_are_listed_as_parts(client, rows):
    rail = _sources(_get(client, f"/al/birmingham/meetings/{rows['parts']}/"))
    assert f'href="{_watch(PREFIX + "pt1")}"' in rail
    assert ">Part 1</a>" in rail
    assert ">Part 2</a>" not in rail


def test_video_rung_row_names_the_recording_as_its_source(client, rows):
    html = _get(client, f"/al/birmingham/meetings/{rows['attached']}/")
    assert "The council's YouTube recording names it." in html
    provenance = html[html.index('class="t-meta meeting-provenance"'):]
    provenance = provenance[:provenance.index("</p>")]
    assert f'href="{_watch(PREFIX + "gjv")}"' in provenance


def test_city_provenance_lists_every_recent_host_most_rows_first(rows):
    from docket.services import briefing

    prov = briefing.city_provenance(rows_city_id())
    hosts = [h["host"] for h in prov["source_hosts"]]
    assert hosts[:2] == ["bhamal.granicus.com", "www.youtube.com"]
    assert prov["source_host"] == "bhamal.granicus.com"
    youtube = prov["source_hosts"][1]
    assert youtube["source_url"] == _watch(PREFIX + "cotw")
    assert youtube["rows"] >= 1


def test_footer_and_sources_name_both_hosts(client, rows):
    html = _get(client, f"/al/birmingham/meetings/{rows['plain']}/")
    assert "Source</span><div>bhamal.granicus.com and www.youtube.com · public domain</div>" in html
    assert ('The records on this page come from <a class="page-sources-host" '
            f'href="{GRANICUS_SOURCE}" rel="external noopener">bhamal.granicus.com</a> and '
            f'<a class="page-sources-host" href="{_watch(PREFIX + "cotw")}" '
            'rel="external noopener">www.youtube.com</a>.') in html


def test_source_health_lists_both_hosts(client, rows):
    html = _get(client, "/al/birmingham/source-health/")
    assert f'href="{GRANICUS_SOURCE}"' in html
    assert ">bhamal.granicus.com</a>" in html
    assert ">www.youtube.com</a>" in html


def rows_city_id() -> int:
    with db() as conn, conn.cursor() as cur:
        return _city_id(cur, "birmingham")


def test_yt_row_provenance_names_the_youtube_channel_not_the_archive(client, rows):
    # Review record, severe: a YouTube-only row's title comes from the
    # council's channel; the page must not say the city's archive listed it.
    html = _get(client, f"/al/birmingham/meetings/{rows['yt']}/")
    provenance = html[html.index('class="t-meta meeting-provenance"'):]
    provenance = provenance[:provenance.index("</p>")]
    assert "The city's archive" not in provenance
    assert "The council's YouTube channel titles this recording “Committee of the Whole Meeting”." in provenance
