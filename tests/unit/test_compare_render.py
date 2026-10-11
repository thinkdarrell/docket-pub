# tests/unit/test_compare_render.py
from docket.ai.transcripts.aligner import Candidate, Event
from docket.ai.transcripts.compare import (TranscriptText, citation_match_for, nearest_event, render_judge_user, segment_at,
                                           transcript_text, transcript_window)

SEGS = [{"id": 1, "seq": 0, "start_s": 3290.0, "end_s": 3295.0, "text": "executed a contract vendor CGI access", "cluster_label": "S0",
         "speaker_name": None, "speaker_confidence": None, "is_silence": False, "agenda_item_id": 1},
        {"id": 2, "seq": 1, "start_s": 3295.0, "end_s": 3300.0, "text": "three years between the agency and Alabama power", "cluster_label": "S0",
         "speaker_name": "Clerk", "speaker_confidence": 0.9, "is_silence": False, "agenda_item_id": 1},
        {"id": 3, "seq": 2, "start_s": 3400.0, "end_s": 3405.0, "text": "we will go into executive session", "cluster_label": "S2",
         "speaker_name": None, "speaker_confidence": None, "is_silence": False, "agenda_item_id": 1}]


def test_transcript_text_maps_offsets_back_to_segments():
    tt = transcript_text(SEGS)
    off = tt.joined.index("Alabama power")
    assert segment_at(tt, off)["seq"] == 1
    assert segment_at(tt, tt.joined.index("executive"))["start_s"] == 3400.0


def test_transcript_window_is_time_bounded_and_labeled():
    w = transcript_window(SEGS, 3292.0, radius_s=10)
    assert "[seq=0 t=00:54:50 Speaker 1]" in w and "[seq=1 t=00:54:55 Clerk]" in w and "executive session" not in w


def _ev(id_, source, seq, et, refs=(1,), start_s=None, char_offset=None):
    return Event(id_, source, seq, et, "item", frozenset(refs), None, None, f"{et}", {}, start_s, None, char_offset)


def test_nearest_event_prefers_same_item_then_distance():
    evs = [_ev(1, "transcript", 0, "motion", (1,), start_s=100), _ev(2, "transcript", 1, "vote", (2,), start_s=3401),
           _ev(3, "transcript", 2, "statement", (1,), start_s=3300)]
    assert nearest_event(evs, start_s=3400, item_refs=frozenset({1})).id == 3
    assert nearest_event(evs, start_s=3400).id == 2
    assert nearest_event([], start_s=1) is None
    m = [_ev(7, "minutes", 0, "vote", char_offset=100), _ev(8, "minutes", 1, "recess", char_offset=900)]
    assert nearest_event(m, char_offset=850).id == 8


def test_citation_match_for_takes_the_worst_side():
    assert citation_match_for(["exact", "exact"]) == "exact"
    assert citation_match_for(["exact", "fuzzy"]) == "fuzzy"
    assert citation_match_for(["fuzzy", "missing"]) == "missing"
    assert citation_match_for([]) == "missing"


def test_judge_prompt_numbers_candidates_and_shows_both_windows():
    t = _ev(10, "transcript", 1, "executive_session_motion", start_s=3400.0)
    m = _ev(20, "minutes", 3, "executive_session_motion", char_offset=30)
    cand = Candidate(1, "mismatch", "wording", t, m, "statute differs", frozenset({1}))
    minutes = type("M", (), {"text": "Councilmember O'Quinn made a motion to go into Executive Session to discuss pending litigation",
                             "page_offsets": [0]})()
    user = render_judge_user([cand], [t], [m], SEGS, minutes)
    assert "### Candidate 1" in user and "wording" in user
    assert "Transcript window" in user and "we will go into executive session" in user
    assert "Minutes window (page 1)" in user and "pending litigation" in user
    assert "Transcript timeline" in user and "Minutes timeline" in user
