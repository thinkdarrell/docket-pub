# tests/unit/test_compare_render.py
import logging

from docket.ai.transcripts.aligner import Candidate, Event
from docket.ai.transcripts.compare import (TranscriptText, build_rows, citation_match_for, nearest_event, render_judge_user,
                                           segment_at, transcript_text, transcript_window)
from docket.ai.transcripts.schemas import HuntedDiscrepancy, Verdict

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


def test_hunter_restating_an_aligner_finding_is_folded_into_one_row():
    """Meeting 15 in production: the statute-ground discrepancy arrived once from the aligner (with the judge's
    verdict) and once from the hunter, anchored to the same transcript event. One finding, one row."""
    tt = transcript_text(SEGS)
    t_ev = _ev(7, "transcript", 7, "executive_session_motion", refs=(1,), start_s=3400.0)
    m_ev = _ev(17, "minutes", 17, "executive_session_motion", refs=(1,), char_offset=0)
    cand = Candidate(1, "mismatch", "wording", t_ev, m_ev, "executive_session_motion: statute_cite differs", frozenset({1}))
    verdict = Verdict(candidate_id=1, is_real=True, category="wording", severity="material", title="Statutory ground differs",
                      description="d", transcript_quote="we will go into executive session", minutes_quote=None, confidence=0.7,
                      dismiss_reason=None)
    dup = HuntedDiscrepancy(category="wording", severity="material", title="Executive session legal ground differs",
                            description="same thing, said again", agenda_item_refs=[1], transcript_quote="we will go into executive session",
                            transcript_segment_seq=2, minutes_quote=None, minutes_page=None, confidence=0.8)
    other = HuntedDiscrepancy(category="omission", severity="material", title="Something the aligner has no event for",
                              description="d", agenda_item_refs=[1], transcript_quote="three years between the agency and Alabama power",
                              transcript_segment_seq=1, minutes_quote=None, minutes_page=None, confidence=0.6)
    rows = build_rows(99, [cand], [verdict], [dup, other], tt=tt, minutes=None, t_events=[t_ev], m_events=[m_ev], valid_item_ids={1})
    proposed = [r for r in rows if r["review_state"] == "proposed"]
    assert [(r["category"], r["origin"]) for r in proposed] == [("wording", "aligner"), ("omission", "model_initiated")]


def test_judge_assigned_vote_outcome_is_written_as_wording(caplog):
    """Issue #114: vote_outcome is reserved for the deterministic tally check; a judge verdict that picks it is wording."""
    tt = transcript_text(SEGS)
    t_ev = _ev(7, "transcript", 7, "motion", start_s=3400.0)
    m_ev = _ev(17, "minutes", 17, "motion", char_offset=0)
    cand = Candidate(1, "mismatch", "wording", t_ev, m_ev, "note", frozenset({1}))
    verdict = Verdict(candidate_id=1, is_real=True, category="vote_outcome", severity="minor", title="Voice vote recorded as roll call",
                      description="d", transcript_quote="we will go into executive session", minutes_quote=None, confidence=0.7,
                      dismiss_reason=None)
    caplog.set_level(logging.INFO, logger="docket.ai.transcripts.compare")
    rows = build_rows(99, [cand], [verdict], [], tt=tt, minutes=None, t_events=[t_ev], m_events=[m_ev], valid_item_ids={1})
    assert len(rows) == 1
    row = rows[0]
    assert row["category"] == "wording"
    assert row["severity"] == "minor"
    assert row["title"] == "Voice vote recorded as roll call"
    assert row["origin"] == "aligner"
    assert "remapped a model-assigned vote_outcome" in caplog.text


def test_hunter_assigned_vote_outcome_is_written_as_wording():
    """Issue #114, hunter path: the same remap applies to a model-initiated finding."""
    tt = transcript_text(SEGS)
    t_ev = _ev(7, "transcript", 7, "motion", start_s=3400.0)
    h = HuntedDiscrepancy(category="vote_outcome", severity="minor", title="Consent agenda shown as a roll-call vote", description="d",
                          agenda_item_refs=[1], transcript_quote="three years between the agency and Alabama power",
                          transcript_segment_seq=1, minutes_quote=None, minutes_page=None, confidence=0.8)
    rows = build_rows(99, [], [], [h], tt=tt, minutes=None, t_events=[t_ev], m_events=[], valid_item_ids={1})
    assert len(rows) == 1
    row = rows[0]
    assert row["category"] == "wording"
    assert row["severity"] == "minor"
    assert row["origin"] == "model_initiated"
    assert row["title"] == "Consent agenda shown as a roll-call vote"


def test_deterministic_vote_outcome_candidate_keeps_its_category():
    """The tally check (spec decision J) is the one producer of vote_outcome rows; it is untouched by the remap."""
    tt = transcript_text(SEGS)
    t_ev = _ev(7, "transcript", 7, "vote", start_s=3400.0)
    cand = Candidate(1, "vote_outcome", "vote_outcome", t_ev, None, "transcript says failed 3-5; minutes vote row 900 says passed 8-0",
                     frozenset({1}), vote_row={"id": 900, "result": "passed", "yeas": 8, "nays": 0, "abstentions": None,
                                               "raw_text": "the motion passed", "item_ids": [1]})
    rows = build_rows(99, [cand], [], [], tt=tt, minutes=None, t_events=[t_ev], m_events=[], valid_item_ids={1})
    assert len(rows) == 1
    row = rows[0]
    assert row["category"] == "vote_outcome"
    assert row["severity"] == "material"
    assert row["origin"] == "aligner"


def test_hunter_restating_the_deterministic_tally_row_is_folded():
    """M4: the fold-in tests the hunter's original category before the #114 remap, so a restated tally mismatch on the
    same transcript event folds into the deterministic vote_outcome row instead of becoming a second wording row."""
    tt = transcript_text(SEGS)
    t_ev = _ev(7, "transcript", 7, "vote", start_s=3400.0)
    cand = Candidate(1, "vote_outcome", "vote_outcome", t_ev, None, "transcript says failed 3-5; minutes vote row 900 says passed 8-0",
                     frozenset({1}), vote_row={"id": 900, "result": "passed", "yeas": 8, "nays": 0, "abstentions": None,
                                               "raw_text": "the motion passed", "item_ids": [1]})
    h = HuntedDiscrepancy(category="vote_outcome", severity="material", title="Vote recorded as passed but failed on video",
                          description="d", agenda_item_refs=[1], transcript_quote="three years between the agency and Alabama power",
                          transcript_segment_seq=1, minutes_quote=None, minutes_page=None, confidence=0.8)
    rows = build_rows(99, [cand], [], [h], tt=tt, minutes=None, t_events=[t_ev], m_events=[], valid_item_ids={1})
    assert [(r["category"], r["origin"], r["transcript_event_id"]) for r in rows] == [("vote_outcome", "aligner", 7)]
