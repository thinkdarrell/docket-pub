# tests/integration/test_events_stage.py
from unittest.mock import MagicMock

import pytest

from docket.ai.exceptions import TranscriptHeld
from docket.ai.pricing import Usage
from docket.ai.transcripts import events as EV
from docket.ai.transcripts import minutes as M
from docket.ai.transcripts.client import StructuredResult
from docket.config import DATABASE_URL
from docket.db import db_cursor
from tests.support.transcript_fixtures import install_bundle, load_bundle, pilot_bundle

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


def _ev(**kw):
    base = {"event_type": "motion", "scope": "item", "agenda_item_refs": [], "actor_text": None, "actor_member_id": None,
            "summary": "s", "detail": {}, "segment_seq": None, "page": None, "quote": None}
    base.update(kw)
    return base


def _client(transcript_events, minutes_events=None, tokens=80_000):
    c = MagicMock()
    c.count_tokens.return_value = tokens
    results = [StructuredResult({"events": transcript_events}, Usage(10, 0, 0, 5), "m", "end_turn")]
    if minutes_events is not None:
        results.append(StructuredResult({"events": minutes_events}, Usage(10, 0, 0, 5), "m", "end_turn"))
    c.call.side_effect = results
    return c


def _claim(inst, status="speakers_resolved"):
    return {"id": inst.transcript_id, "meeting_id": inst.meeting_id, "status": status, "version": 1,
            "word_count": 650, "compare_skipped_reason": None}


@pytest.fixture
def pilot():
    i = install_bundle(pilot_bundle(), external_id="999015")
    yield i
    i.cleanup()


def test_both_sides_written_with_anchors_and_pages(pilot, monkeypatch):
    item = pilot.item_ids[1501]
    monkeypatch.setattr(M, "download_minutes", lambda url, timeout=30: None)   # fixture row already holds the text
    t_events = [_ev(event_type="item_opened", agenda_item_refs=[item], segment_seq=0, quote="executed a contract vendor CGI"),
                _ev(event_type="executive_session_motion", agenda_item_refs=[item], segment_seq=40,
                    detail={"stated_reason": "security plans", "statute_cite": "36, 25, a seven a four"},
                    quote=None),
                _ev(event_type="vote", agenda_item_refs=[item], segment_seq=70, detail={"result": "passed", "method": "voice"},
                    quote="Item 15 passes")]
    m_events = [_ev(event_type="vote", agenda_item_refs=[item], page=1, detail={"result": "passed"},
                    quote="said ordinance adopted"),
                _ev(event_type="executive_session_motion", agenda_item_refs=[item], page=1, actor_text="O'Quinn",
                    detail={"stated_reason": "pending litigation", "mover": "O'Quinn", "seconder": "Tate"},
                    quote="go into Executive Session at the recommendation of the City Attorney")]
    out = EV.run_events_stage(_claim(pilot), client=_client(t_events, m_events))
    assert out.next_status == "events_extracted" and out.skipped_reason is None
    with db_cursor() as cur:
        cur.execute("""SELECT source, seq, event_type, start_s, segment_id, page, char_offset, actor_member_id, agenda_item_refs, prompt_version
                         FROM meeting_events WHERE meeting_id=%s ORDER BY source, seq""", [pilot.meeting_id])
        rows = [dict(r) for r in cur.fetchall()]
    t = [r for r in rows if r["source"] == "transcript"]
    m = [r for r in rows if r["source"] == "minutes"]
    assert [r["event_type"] for r in t] == ["item_opened", "executive_session_motion", "vote"]
    assert t[0]["start_s"] == pytest.approx(3290.0) and t[0]["segment_id"] is not None
    assert all(r["prompt_version"] == 200 for r in rows)
    assert m[1]["char_offset"] is not None and m[1]["page"] >= 1          # guard found the quote; page from offsets
    assert m[1]["actor_member_id"] == pilot.member_ids[9000]              # "O'Quinn" matched to the roster id
    assert all(r["agenda_item_refs"] == [item] for r in rows)


def test_no_minutes_url_skips_minutes_side_without_failing(monkeypatch):
    inst = install_bundle(load_bundle("transcript_2543"), status="speakers_resolved")
    try:
        with db_cursor() as cur:
            cur.execute("UPDATE meetings SET minutes_url=NULL WHERE id=%s", [inst.meeting_id])
        c = _client([_ev(event_type="adjourn", scope="meeting", segment_seq=5, quote="x")])
        out = EV.run_events_stage(_claim(inst), client=c)
        assert out.next_status == "events_extracted" and out.skipped_reason == "no_minutes"
        assert c.call.call_count == 1
    finally:
        inst.cleanup()


def test_unavailable_minutes_is_a_skip_not_a_failure(pilot, monkeypatch):
    with db_cursor() as cur:
        cur.execute("DELETE FROM minutes_texts WHERE meeting_id=%s", [pilot.meeting_id])
    monkeypatch.setattr(M, "download_minutes", lambda url, timeout=30: None)   # Review Focus 1: an HTML page came back
    out = EV.run_events_stage(_claim(pilot), client=_client([_ev(event_type="adjourn", scope="meeting", segment_seq=5, quote="x")]))
    assert out.skipped_reason == "minutes_unavailable" and out.next_status == "events_extracted"


def test_item_opened_events_reassign_segments(pilot, monkeypatch):
    item = pilot.item_ids[1501]
    monkeypatch.setattr(M, "download_minutes", lambda url, timeout=30: None)
    with db_cursor() as cur:   # pretend the index point put the first segments on nothing
        cur.execute("UPDATE transcript_segments SET agenda_item_id=NULL, assignment_method=NULL WHERE transcript_id=%s", [pilot.transcript_id])
        cur.execute("UPDATE transcript_segments SET assignment_method='manual', agenda_item_id=NULL WHERE transcript_id=%s AND seq=3",
                    [pilot.transcript_id])
    EV.run_events_stage(_claim(pilot), client=_client(
        [_ev(event_type="item_opened", agenda_item_refs=[item], segment_seq=2, quote="x")], []))
    with db_cursor() as cur:
        cur.execute("SELECT seq, agenda_item_id, assignment_method FROM transcript_segments WHERE transcript_id=%s ORDER BY seq", [pilot.transcript_id])
        rows = cur.fetchall()
    assert rows[1]["agenda_item_id"] is None                                   # before the opening
    assert (rows[2]["agenda_item_id"], rows[2]["assignment_method"]) == (item, "event")
    assert (rows[3]["agenda_item_id"], rows[3]["assignment_method"]) == (None, "manual")   # manual untouched
    assert rows[10]["assignment_method"] == "event"


def test_invalid_item_refs_are_dropped_and_ceiling_holds(pilot, monkeypatch):
    monkeypatch.setattr(M, "download_minutes", lambda url, timeout=30: None)
    EV.run_events_stage(_claim(pilot), client=_client([_ev(event_type="motion", agenda_item_refs=[123456789], segment_seq=2, quote="x")], []))
    with db_cursor() as cur:
        cur.execute("SELECT agenda_item_refs FROM meeting_events WHERE meeting_id=%s AND source='transcript'", [pilot.meeting_id])
        assert cur.fetchone()["agenda_item_refs"] == []
    with pytest.raises(TranscriptHeld) as ei:
        EV.run_events_stage(_claim(pilot), client=_client([], [], tokens=700_000))
    assert ei.value.reason == "token_ceiling"


def test_rerun_replaces_only_that_source(pilot, monkeypatch):
    monkeypatch.setattr(M, "download_minutes", lambda url, timeout=30: None)
    EV.run_events_stage(_claim(pilot), client=_client([_ev(event_type="adjourn", scope="meeting", segment_seq=5, quote="x")],
                                                      [_ev(event_type="adjourn", scope="meeting", page=1, quote="y")]))
    EV.run_events_stage(_claim(pilot), client=_client([_ev(event_type="recess", scope="meeting", segment_seq=5, quote="x")],
                                                      [_ev(event_type="adjourn", scope="meeting", page=1, quote="y")]))
    with db_cursor() as cur:
        cur.execute("SELECT source, event_type FROM meeting_events WHERE meeting_id=%s ORDER BY source", [pilot.meeting_id])
        assert [(r["source"], r["event_type"]) for r in cur.fetchall()] == [("minutes", "adjourn"), ("transcript", "recess")]


def _reset_segments(pilot):
    with db_cursor() as cur:
        cur.execute("UPDATE transcript_segments SET agenda_item_id=NULL, assignment_method=NULL WHERE transcript_id=%s", [pilot.transcript_id])


def _assign(pilot):
    with db_cursor() as cur:
        cur.execute("SELECT seq, agenda_item_id, assignment_method FROM transcript_segments WHERE transcript_id=%s AND is_silence=FALSE ORDER BY seq",
                    [pilot.transcript_id])
        return {r["seq"]: r for r in cur.fetchall()}


def test_multi_ref_item_opened_is_a_boundary_but_not_written(pilot):
    _reset_segments(pilot)
    a, b = pilot.item_ids[1501], pilot.item_ids[1501]
    rows = [{"event_type": "item_opened", "segment_seq": 2, "agenda_item_refs": [a]},
            {"event_type": "item_opened", "segment_seq": 6, "agenda_item_refs": [a, a + 1, a + 2]},
            {"event_type": "item_opened", "segment_seq": 10, "agenda_item_refs": [b]}]
    EV.reassign_segments_from_events(pilot.transcript_id, rows)
    seg = _assign(pilot)
    for s in (2, 3, 4, 5):
        if s in seg:
            assert seg[s]["assignment_method"] == "event"
    for s in (6, 7, 8, 9):
        if s in seg:
            assert seg[s]["assignment_method"] is None and seg[s]["agenda_item_id"] is None
    assert seg[10]["assignment_method"] == "event"


def test_adjourn_caps_last_range(pilot):
    _reset_segments(pilot)
    a = pilot.item_ids[1501]
    rows = [{"event_type": "item_opened", "segment_seq": 10, "agenda_item_refs": [a]},
            {"event_type": "adjourn", "segment_seq": 20, "agenda_item_refs": []}]
    EV.reassign_segments_from_events(pilot.transcript_id, rows)
    seg = _assign(pilot)
    assert seg[19]["assignment_method"] == "event"
    for s, r in seg.items():
        if s >= 20:
            assert r["assignment_method"] is None


def test_minutes_without_a_text_layer_hold_instead_of_comparing_against_nothing(pilot, monkeypatch):
    """A scanned PDF downloads fine and pdfplumber returns no text. That is a person's problem (OCR or a new
    URL), not a skip that retries daily and not an empty minutes side that calls every vote an omission."""
    with db_cursor() as cur:
        cur.execute("DELETE FROM minutes_texts WHERE meeting_id=%s", [pilot.meeting_id])
    monkeypatch.setattr(M, "download_minutes", lambda url, timeout=30, **kw: b"%PDF-scanned")
    monkeypatch.setattr(M, "extract_pages", lambda pdf: ("\n\n  \n", [0, 1, 2]))
    c = _client([_ev(event_type="adjourn", scope="meeting", segment_seq=5, quote="x")])
    with pytest.raises(TranscriptHeld) as ei:
        EV.run_events_stage(_claim(pilot), client=c)
    assert ei.value.reason == "minutes_no_text"
    assert c.call.call_count == 1                        # the transcript side ran; the minutes side never reached the model
    with db_cursor() as cur:                             # the transcript-side events are kept for the retry
        cur.execute("SELECT count(*) AS n FROM meeting_events WHERE meeting_id=%s AND source='transcript'", [pilot.meeting_id])
        assert cur.fetchone()["n"] == 1
