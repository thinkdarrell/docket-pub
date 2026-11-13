"""docket.services.how_it_works.resolve_journey: a journey's records become links.

A journey states its facts in its own file; the resolver reads the database
only to decide which links a stop may carry, and a stop whose meeting is
missing, hidden, or another city's keeps its text and loses its links.

Every row is seeded under Birmingham (and one under Mobile) with an
``external_id`` prefix and deleted after; the throwaway database is otherwise
empty of meetings. The journeys are built here, not read from the content
directory. ``docket.services.how_it_works`` names are imported inside each
test, so the file collects before ``resolve_journey`` exists. Runs in the
services tier (DATABASE_URL names docket_test_*).

Plan ``how-it-works-explainer``, M3.
"""

from __future__ import annotations

from datetime import date

import pytest

from docket.db import db

PREFIX = "hiwres-"
PLAYER = "https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=2700"
AGENDA = "https://example.org/hiwres/agenda.pdf"
MINUTES = "https://example.org/hiwres/minutes.pdf"
WATCH = "https://www.youtube.com/watch?v=MiL1mYay0eQ"
ABSENT_ID = 2_000_000_000


def _city_id(cur, slug: str) -> int:
    cur.execute("SELECT id FROM municipalities WHERE slug = %s", (slug,))
    row = cur.fetchone()
    assert row is not None, f"city must be seeded: {slug}"
    return row[0]


def _meeting(cur, city_id: int, ext: str, *, video_url=None, agenda_url=None, minutes_url=None,
             hidden: bool = False) -> int:
    cur.execute(
        """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type,
                                 video_url, agenda_url, minutes_url, is_hidden)
           VALUES (%s, %s, 'Regular City Council Meeting', %s, 'council', %s, %s, %s, %s) RETURNING id""",
        (city_id, PREFIX + ext, date(2026, 6, 2), video_url, agenda_url, minutes_url, hidden),
    )
    return cur.fetchone()[0]


def _item(cur, meeting_id: int, external_id: str) -> int:
    cur.execute(
        """INSERT INTO agenda_items (meeting_id, external_id, item_number, title, processing_status)
           VALUES (%s, %s, '11', 'An Ordinance to amend Title 8', 'completed') RETURNING id""",
        (meeting_id, external_id),
    )
    return cur.fetchone()[0]


def _cleanup(cur) -> None:
    cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (PREFIX + "%",))


@pytest.fixture
def rows():
    with db() as conn, conn.cursor() as cur:
        _cleanup(cur)
        bhm = _city_id(cur, "birmingham")
        mobile = _city_id(cur, "mobile")
        ids = {"birmingham": bhm, "mobile": mobile}
        ids["visible"] = _meeting(cur, bhm, "visible", video_url=PLAYER, agenda_url=AGENDA, minutes_url=MINUTES)
        ids["item"] = _item(cur, ids["visible"], "371088")
        ids["event_item"] = _item(cur, ids["visible"], "event-2693-11")
        ids["hidden"] = _meeting(cur, bhm, "hidden", video_url=PLAYER, agenda_url=AGENDA, minutes_url=MINUTES,
                                 hidden=True)
        ids["hidden_item"] = _item(cur, ids["hidden"], "371099")
        ids["youtube"] = _meeting(cur, bhm, "youtube", video_url=WATCH)
        ids["bare"] = _meeting(cur, bhm, "bare")
        ids["bare_item"] = _item(cur, ids["bare"], "371077")
        ids["elsewhere"] = _meeting(cur, mobile, "elsewhere", video_url=PLAYER, agenda_url=AGENDA,
                                    minutes_url=MINUTES)
        conn.commit()
    try:
        yield ids
    finally:
        with db() as conn, conn.cursor() as cur:
            _cleanup(cur)
            conn.commit()


def _stop(**overrides):
    from docket.services.how_it_works import JourneyStop

    fields = dict(
        stops=("final_vote",), date=date(2026, 6, 2), record="minutes", text="Adopted, eight ayes.",
        quote=None, source_file=None, meeting_id=None, item_id=None, seconds=None,
        document_label=None, document_url=None, gap=None,
    )
    fields.update(overrides)
    return JourneyStop(**fields)


def _gap(*keys: str, record: str = "none"):
    return _stop(stops=keys, date=None, record=record, text="Nothing is published.",
                 gap="The site holds no record.")


def _resolve(rows, *stops):
    from docket.services.how_it_works import Journey, resolve_journey

    journey = Journey(key="test", label="A journey", note="A note.", title="A title.", stops=tuple(stops))
    return resolve_journey(journey, rows["birmingham"], "birmingham")


def _links(rows, **stop_fields):
    return _resolve(rows, _stop(**stop_fields)).stops[0].links


def _no_links(links) -> bool:
    return (links.meeting_url, links.item_url, links.recording, links.transcript_url, links.minutes_url,
            links.agenda_url) == (None, None, None, None, None, None)


def test_a_stop_on_a_visible_meeting_with_its_item_gets_every_link_the_rows_support(rows):
    links = _links(rows, meeting_id=rows["visible"], item_id=rows["item"], seconds=5313)

    assert links.meeting_url == f"/al/birmingham/meetings/{rows['visible']}/"
    assert links.item_url == f"/al/birmingham/items/{rows['item']}/"
    assert links.recording is not None
    assert links.recording.timed is True
    assert links.recording.label == "Granicus"
    assert "meta_id=371088" in links.recording.url
    assert links.minutes_url == MINUTES
    assert links.agenda_url == AGENDA
    assert links.transcript_url is None


def test_an_item_that_does_not_exist_costs_the_item_link_and_the_chapter(rows):
    links = _links(rows, meeting_id=rows["visible"], item_id=ABSENT_ID, seconds=5313)

    assert links.item_url is None
    assert links.recording is not None
    assert links.recording.timed is False
    assert "meta_id" not in links.recording.url
    assert links.meeting_url == f"/al/birmingham/meetings/{rows['visible']}/"
    assert links.minutes_url == MINUTES
    assert links.agenda_url == AGENDA


def test_an_item_of_another_meeting_costs_the_item_link_and_the_chapter(rows):
    links = _links(rows, meeting_id=rows["visible"], item_id=rows["bare_item"], seconds=5313)

    assert links.item_url is None
    assert links.recording.timed is False
    assert "meta_id" not in links.recording.url
    assert links.meeting_url == f"/al/birmingham/meetings/{rows['visible']}/"


def test_a_stop_with_no_item_links_the_recording_untimed(rows):
    links = _links(rows, meeting_id=rows["visible"])

    assert links.item_url is None
    assert links.recording.url == PLAYER
    assert links.recording.timed is False


def test_a_stop_on_a_hidden_meeting_keeps_its_text_and_gets_no_links(rows):
    resolved = _resolve(rows, _stop(meeting_id=rows["hidden"], item_id=rows["hidden_item"], seconds=10))

    assert _no_links(resolved.stops[0].links)
    assert resolved.stops[0].stop.text == "Adopted, eight ayes."
    assert resolved.reached == {"final_vote"}


def test_a_stop_on_a_meeting_that_does_not_exist_gets_no_links(rows):
    assert _no_links(_links(rows, meeting_id=ABSENT_ID, item_id=rows["item"], seconds=10))


def test_a_stop_on_another_citys_meeting_gets_no_links(rows):
    assert _no_links(_links(rows, meeting_id=rows["elsewhere"], seconds=10))


def test_a_youtube_meeting_links_its_own_recording(rows):
    links = _links(rows, stops=("committee",), record="committee_minutes", meeting_id=rows["youtube"])

    assert links.recording.url == WATCH
    assert links.recording.label == "YouTube"
    assert links.recording.timed is False
    assert links.meeting_url == f"/al/birmingham/meetings/{rows['youtube']}/"
    assert (links.minutes_url, links.agenda_url, links.item_url) == (None, None, None)


def test_a_cue_on_a_youtube_meeting_opens_it_at_that_second(rows):
    links = _links(rows, meeting_id=rows["youtube"], seconds=90)

    assert links.recording.url == WATCH + "&t=90s"
    assert links.recording.timed is True


def test_a_meeting_with_no_recording_and_no_documents_links_only_itself(rows):
    links = _links(rows, meeting_id=rows["bare"])

    assert links.meeting_url == f"/al/birmingham/meetings/{rows['bare']}/"
    assert (links.item_url, links.recording, links.transcript_url, links.minutes_url, links.agenda_url) == (
        None, None, None, None, None)


def test_an_external_id_that_is_not_a_chapter_id_leaves_the_recording_untimed(rows):
    links = _links(rows, meeting_id=rows["visible"], item_id=rows["event_item"])

    assert links.item_url == f"/al/birmingham/items/{rows['event_item']}/"
    assert links.recording.timed is False
    assert "meta_id" not in links.recording.url
    assert links.recording.url == PLAYER


def test_a_stop_with_no_record_gets_no_links_and_carries_its_reason(rows):
    resolved = _resolve(rows, _gap("mayor"))

    assert _no_links(resolved.stops[0].links)
    assert resolved.stops[0].stop.gap == "The site holds no record."
    assert resolved.not_in_record == {"mayor"}
    assert resolved.reached == frozenset()


def test_a_public_transcript_is_linked_and_an_unpublished_one_is_not(rows):
    with db() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO transcripts (meeting_id, status, uploaded_at) VALUES (%s, 'events_extracted', now())",
                    (rows["visible"],))
        cur.execute("INSERT INTO transcripts (meeting_id, status) VALUES (%s, 'claimed')", (rows["youtube"],))
        conn.commit()

    assert _links(rows, meeting_id=rows["visible"]).transcript_url == (
        f"/al/birmingham/meetings/{rows['visible']}/transcript/")
    assert _links(rows, meeting_id=rows["youtube"]).transcript_url is None


def test_the_city_slug_passed_in_is_the_one_in_every_site_address(rows):
    from docket.services.how_it_works import Journey, resolve_journey

    journey = Journey(key="t", label="l", note="n", title="t",
                      stops=(_stop(meeting_id=rows["elsewhere"]),))
    links = resolve_journey(journey, rows["mobile"], "mobile").stops[0].links

    assert links.meeting_url == f"/al/mobile/meetings/{rows['elsewhere']}/"


def test_the_resolved_stops_are_the_journeys_stops_in_order(rows):
    first = _gap("submitted")
    second = _stop(stops=("committee",), meeting_id=rows["youtube"])
    third = _stop(meeting_id=rows["visible"], item_id=rows["item"])
    resolved = _resolve(rows, first, second, third)

    assert [r.stop for r in resolved.stops] == [first, second, third]
    assert resolved.journey.stops == (first, second, third)


def test_a_key_with_a_recorded_stop_and_a_gap_is_reached_and_not_missing(rows):
    resolved = _resolve(
        rows,
        _stop(stops=("committee",), meeting_id=rows["youtube"]),
        _gap("committee"),
        _gap("mayor", "in_effect"),
    )

    assert resolved.reached == {"committee"}
    assert resolved.not_in_record == {"mayor", "in_effect"}
    assert resolved.not_on_route == frozenset()


def test_the_three_sets_do_not_overlap(rows):
    resolved = _resolve(
        rows,
        _stop(stops=("agenda", "hearing", "final_vote"), record="video", meeting_id=rows["visible"]),
        _gap("final_vote", "mayor"),
        _gap("first_reading", "mayor", "agenda", record="not_on_route"),
    )

    assert resolved.reached == {"agenda", "hearing", "final_vote"}
    assert resolved.not_in_record == {"mayor"}
    assert resolved.not_on_route == {"first_reading"}
    assert isinstance(resolved.reached, frozenset)
    assert isinstance(resolved.not_in_record, frozenset)
    assert isinstance(resolved.not_on_route, frozenset)


def test_a_stop_whose_meeting_has_gone_is_still_reached(rows):
    """The fact is in the journey file; a missing row costs the links, not the stop."""
    resolved = _resolve(rows, _stop(meeting_id=ABSENT_ID))

    assert resolved.reached == {"final_vote"}
    assert _no_links(resolved.stops[0].links)
