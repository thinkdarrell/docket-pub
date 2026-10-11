# tests/unit/test_aligner.py
from docket.ai.transcripts.aligner import (MINUTED_TYPES, Event, align, canonical_result, details_differ, effective_consent_block,
                                            mismatch_note, pair_group, sequence_candidates, vote_outcome_candidates)

_id = iter(range(1, 10_000))


def ev(source, seq, event_type, refs=(), *, actor=None, actor_text=None, detail=None, scope="item", start_s=None, page=None):
    return Event(next(_id), source, seq, event_type, scope, frozenset(refs), actor, actor_text, f"{event_type} {sorted(refs)}",
                 detail or {}, start_s, page, None)


CONSENT = {20, 21, 22}


def test_effective_consent_block_applies_pulls_and_adds():
    evs = [ev("transcript", 0, "consent_amendment", scope="consent_block", detail={"action": "pulled", "items": [21]}),
           ev("transcript", 1, "consent_amendment", scope="consent_block", detail={"action": "added", "items": [30]})]
    assert effective_consent_block(CONSENT, evs) == {20, 22, 30}


def test_consent_amendments_apply_in_sequence_order():
    def amend(seq, action):
        return ev("transcript", seq, "consent_amendment", scope="consent_block", detail={"action": action, "items": [21]})

    # Pulled (seq 0) then added back (seq 1): item is in the effective block again.
    back = [amend(0, "pulled"), amend(1, "added")]
    assert effective_consent_block(CONSENT, back) == CONSENT
    assert effective_consent_block(CONSENT, list(reversed(back))) == CONSENT   # list order is irrelevant
    # Added (seq 0) then pulled (seq 1): item ends up pulled.
    out = [amend(1, "pulled"), amend(0, "added")]
    assert effective_consent_block(CONSENT, out) == {20, 22}
    assert effective_consent_block(CONSENT, list(reversed(out))) == {20, 22}


def test_consent_vote_satisfies_the_block_and_pulled_item_gets_its_own_group():
    t = [ev("transcript", 0, "consent_amendment", scope="consent_block", detail={"action": "pulled", "items": [21]}),
         ev("transcript", 1, "motion", {20, 22}, scope="consent_block"), ev("transcript", 2, "vote", {20, 22}, scope="consent_block", detail={"result": "passed"}),
         ev("transcript", 3, "motion", {21}), ev("transcript", 4, "vote", {21}, detail={"result": "passed"})]
    m = [ev("minutes", 0, "consent_amendment", scope="consent_block", detail={"action": "pulled", "items": [21]}),
         ev("minutes", 1, "motion", {20, 22}, scope="consent_block"), ev("minutes", 2, "vote", {20, 22}, scope="consent_block", detail={"result": "passed"}),
         ev("minutes", 3, "motion", {21}), ev("minutes", 4, "vote", {21}, detail={"result": "passed"})]
    assert align(t, m, consent_items=CONSENT, votes=[]) == []           # Review Focus 5: pulled on both sides -> no candidate


def test_item_pulled_on_video_but_consented_in_minutes_is_a_candidate():
    t = [ev("transcript", 0, "consent_amendment", scope="consent_block", detail={"action": "pulled", "items": [21]}),
         ev("transcript", 1, "vote", {20, 22}, scope="consent_block", detail={"result": "passed"}),
         ev("transcript", 2, "vote", {21}, detail={"result": "passed"})]
    m = [ev("minutes", 0, "vote", {20, 21, 22}, scope="consent_block", detail={"result": "passed"})]
    cands = align(t, m, consent_items=CONSENT, votes=[])
    kinds = sorted(c.kind for c in cands)
    assert "consent_block" in kinds
    cb = next(c for c in cands if c.kind == "consent_block")
    assert cb.item_refs == frozenset({21}) and cb.category == "addition"
    # The consent vote itself must NOT also show up as an omission/addition pair mismatch.
    assert not any(c.kind in ("omission", "addition") and c.item_refs == frozenset({20, 22}) for c in cands)


def test_omission_and_addition_only_for_minuted_types():
    t = [ev("transcript", 0, "item_opened", {5}), ev("transcript", 1, "public_comment", scope="meeting"),
         ev("transcript", 2, "statement", {5}, detail={"kind": "legal_position", "as_stated": "x"}),
         ev("transcript", 3, "motion", {5}, detail={"action": "approve"})]
    m = [ev("minutes", 0, "motion", {5}, detail={"action": "approve"}), ev("minutes", 1, "recusal", {5}, detail={"member": "Tate"})]
    cands = align(t, m, consent_items=set(), votes=[])
    assert [(c.kind, c.transcript_event.event_type if c.transcript_event else None,
             c.minutes_event.event_type if c.minutes_event else None) for c in cands] == [
        ("omission", "statement", None), ("addition", None, "recusal")]
    assert "item_opened" not in MINUTED_TYPES and "public_comment" not in MINUTED_TYPES


def test_reopened_item_is_one_group_and_pairs_in_order():
    t = [ev("transcript", 0, "item_opened", {7}), ev("transcript", 1, "motion", {7}, detail={"action": "table"}),
         ev("transcript", 5, "item_opened", {7}), ev("transcript", 6, "motion", {7}, detail={"action": "approve"}),
         ev("transcript", 7, "vote", {7}, detail={"result": "passed"})]
    m = [ev("minutes", 0, "motion", {7}, detail={"action": "table"}), ev("minutes", 1, "motion", {7}, detail={"action": "approve"}),
         ev("minutes", 2, "vote", {7}, detail={"result": "passed"})]
    assert align(t, m, consent_items=set(), votes=[]) == []


def test_floor_added_item_groups_by_unlisted_text_not_meeting_bucket():
    t = [ev("transcript", 1, "motion", detail={"action": "approve", "unlisted_item": "Resolution honoring Coach Smith"}),
         ev("transcript", 2, "vote", detail={"result": "passed", "unlisted_item": "Resolution honoring Coach Smith"}),
         ev("transcript", 3, "adjourn", scope="meeting")]
    m = [ev("minutes", 1, "motion", detail={"action": "approve", "unlisted_item": "resolution honoring coach smith"}),
         ev("minutes", 2, "vote", detail={"result": "passed", "unlisted_item": "resolution honoring coach smith"}),
         ev("minutes", 3, "adjourn", scope="meeting")]
    assert align(t, m, consent_items=set(), votes=[]) == []
    # Without the unlisted text the motion would fall into the meeting bucket and pair with nothing.
    only_t = [ev("transcript", 1, "motion", detail={"action": "approve", "unlisted_item": "Resolution honoring Coach Smith"})]
    cands = align(only_t, [], consent_items=set(), votes=[])
    assert len(cands) == 1 and cands[0].kind == "omission" and cands[0].item_refs == frozenset()


def test_tabled_vs_postponed_is_a_wording_mismatch():
    t = ev("transcript", 1, "item_deferred", {7}, detail={"action": "table"})
    m = ev("minutes", 1, "item_deferred", {7}, detail={"action": "postpone", "to_date": "2026-03-03"})
    assert details_differ(t, m) == "wording"


def test_statute_cite_compares_canonically_and_differs_when_grounds_differ():
    same = (ev("transcript", 1, "executive_session_motion", {15}, detail={"statute_cite": "36, 25, a seven a four", "stated_reason": "security plans"}),
            ev("minutes", 1, "executive_session_motion", {15}, detail={"statute_cite": "36-25A-7(a)(4)", "stated_reason": "security plans and measures"}))
    assert details_differ(*same) is None
    diff = (same[0], ev("minutes", 1, "executive_session_motion", {15}, detail={"stated_reason": "pending litigation, controversies not yet litigated"}))
    assert details_differ(*diff) == "wording"


def test_actor_mismatch_by_member_id_is_speaker_and_unresolved_actors_do_not_match_phonetically():
    t = ev("transcript", 1, "motion", {7}, actor=101, detail={"action": "approve"})
    m = ev("minutes", 1, "motion", {7}, actor=102, detail={"action": "approve"})
    assert details_differ(t, m) == "speaker"
    m2 = ev("minutes", 1, "motion", {7}, actor=None, actor_text="Councilor Smythe", detail={"action": "approve"})
    assert details_differ(t, m2) is None


def test_vote_tally_mismatch_is_vote_outcome():
    t = ev("transcript", 1, "vote", {7}, detail={"result": "passed", "yeas": 8, "nays": 1})
    m = ev("minutes", 1, "vote", {7}, detail={"result": "passed", "yeas": 9, "nays": 0})
    assert details_differ(t, m) == "vote_outcome"
    assert details_differ(t, ev("minutes", 1, "vote", {7}, detail={"result": "passed"})) is None   # no tally recorded: not a mismatch


def test_sequence_detects_the_pilot_shape():
    t = [ev("transcript", 0, "motion", {15}), ev("transcript", 1, "executive_session_motion", {15}, detail={"stated_reason": "security"}),
         ev("transcript", 2, "recess", scope="meeting"), ev("transcript", 3, "reconvene", scope="meeting"),
         ev("transcript", 4, "vote", {15}, detail={"result": "passed"})]
    m = [ev("minutes", 0, "motion", {15}), ev("minutes", 1, "vote", {15}, detail={"result": "passed"}),
         ev("minutes", 2, "executive_session_motion", {15}, detail={"stated_reason": "security"}),
         ev("minutes", 3, "recess", scope="meeting"), ev("minutes", 4, "reconvene", scope="meeting")]
    cands = align(t, m, consent_items=set(), votes=[])
    seq = [c for c in cands if c.kind == "sequence"]
    assert len(seq) == 1
    assert {seq[0].transcript_event.event_type, seq[0].minutes_event.event_type} <= {"vote", "executive_session_motion"}


def test_sequence_candidates_use_longest_increasing_subsequence():
    pairs = [(ev("transcript", i, "motion", {i}), ev("minutes", j, "motion", {i})) for i, j in [(0, 0), (1, 2), (2, 1), (3, 3)]]
    out = sequence_candidates(pairs)
    assert len(out) == 1 and out[0][0].seq in (1, 2)


def test_vote_outcome_against_votes_rows():
    t = [ev("transcript", 4, "vote", {15}, detail={"result": "failed", "yeas": 3, "nays": 5})]
    votes = [{"id": 900, "result": "passed", "yeas": 8, "nays": 0, "abstentions": None, "raw_text": "...adopted", "item_ids": [15]},
             {"id": 901, "result": "passed", "yeas": 8, "nays": 0, "abstentions": None, "raw_text": "...", "item_ids": [16]}]
    cands = align(t, [], consent_items=set(), votes=votes)
    vo = [c for c in cands if c.kind == "vote_outcome"]
    assert len(vo) == 1 and vo[0].vote_row["id"] == 900 and vo[0].category == "vote_outcome"
    assert vo[0].minutes_event is None and vo[0].transcript_event.seq == 4


def test_candidate_ids_are_stable_and_start_at_one():
    t = [ev("transcript", 0, "motion", {1}, detail={"action": "approve"})]
    cands = align(t, [], consent_items=set(), votes=[])
    assert [c.candidate_id for c in cands] == [1]


def _vrow(i, result, items, yeas=None, nays=None):
    return {"id": i, "result": result, "yeas": yeas, "nays": nays, "abstentions": None, "raw_text": "", "item_ids": list(items)}


def test_two_votes_on_one_item_pair_in_order_with_two_rows():
    t = [ev("transcript", 1, "vote", {7}, detail={"result": "failed"}), ev("transcript", 2, "vote", {7}, detail={"result": "passed"})]
    rows = [_vrow(10, "failed", [7]), _vrow(11, "passed", [7])]
    assert not [c for c in align(t, [], consent_items=set(), votes=rows) if c.kind == "vote_outcome"]


def test_two_votes_second_row_swapped_gives_one_candidate_on_second_vote():
    t = [ev("transcript", 1, "vote", {7}, detail={"result": "failed"}), ev("transcript", 2, "vote", {7}, detail={"result": "passed"})]
    rows = [_vrow(10, "failed", [7]), _vrow(11, "failed", [7])]
    vo = [c for c in align(t, [], consent_items=set(), votes=rows) if c.kind == "vote_outcome"]
    assert len(vo) == 1 and vo[0].transcript_event.seq == 2 and vo[0].vote_row["id"] == 11


def test_consent_vote_compares_only_against_overlapping_row():
    t = [ev("transcript", 1, "vote", {20, 22}, scope="consent_block", detail={"result": "passed"})]
    rows = [_vrow(5, "failed", [5]), _vrow(6, "failed", [20, 21, 22])]
    vo = [c for c in align(t, [], consent_items=set(), votes=rows) if c.kind == "vote_outcome"]
    assert len(vo) == 1 and vo[0].vote_row["id"] == 6
    rows_ok = [_vrow(5, "failed", [5]), _vrow(6, "passed", [20, 21, 22])]
    assert not [c for c in align(t, [], consent_items=set(), votes=rows_ok) if c.kind == "vote_outcome"]


def test_paired_minutes_vote_mismatch_suppresses_row_candidate():
    t = [ev("transcript", 1, "vote", {7}, detail={"result": "failed"})]
    m = [ev("minutes", 1, "vote", {7}, detail={"result": "passed"})]
    cands = align(t, m, consent_items=set(), votes=[_vrow(10, "passed", [7])])
    assert [c.kind for c in cands] == ["mismatch"] and cands[0].category == "vote_outcome"


def test_mismatch_note_names_both_sides_for_a_reviewer():
    """Vote rows never pass through the judge, so the aligner's note is the reviewer's whole description."""
    t = ev("transcript", 3, "vote", [40], detail={"result": "approved", "yeas": 6, "nays": 1})
    m = ev("minutes", 3, "vote", [40], detail={"result": "approved", "yeas": 7, "nays": 0})
    assert mismatch_note(t, m, "vote_outcome") == "vote: transcript says approved 6-1; minutes say approved 7-0"
    t2 = ev("transcript", 4, "vote", [41], detail={"result": "failed"})
    m2 = ev("minutes", 4, "vote", [41], detail={})
    assert mismatch_note(t2, m2, "vote_outcome") == "vote: transcript says failed; minutes say no result recorded"
    a = ev("transcript", 5, "motion", [42], actor=1, actor_text="Smitherman")
    b = ev("minutes", 5, "motion", [42], actor=2, actor_text="Williams")
    assert mismatch_note(a, b, "speaker") == "motion: transcript attributes it to Smitherman; minutes to Williams"
    x = ev("transcript", 6, "executive_session_motion", [43], detail={"statute_cite": "36-25A-7(a)(4)"})
    y = ev("minutes", 6, "executive_session_motion", [43], detail={"statute_cite": "36-25A-7(a)(3)"})
    assert mismatch_note(x, y, "wording").startswith("executive_session_motion: statute_cite differs; transcript: 36-25A-7(a)(4); minutes: 36-25A-7(a)(3)")
    # align() carries the note onto the candidate that becomes the row's description.
    cands = align([t], [m], consent_items=set(), votes=[])
    assert [c.note for c in cands if c.category == "vote_outcome"] == ["vote: transcript says approved 6-1; minutes say approved 7-0"]


def test_vote_vocabulary_is_not_a_vote_outcome_discrepancy():
    """First production run (meeting 15): 'approved' vs 'adopted 9-0' and 'passes' vs 'adopted' were raised as
    material vote_outcome rows. They are the same outcome; the spec calls that wording at most."""
    assert canonical_result("approved") == canonical_result("adopted") == canonical_result("That item passes.") == "pass"
    assert canonical_result("failed") == canonical_result("This item fails.") == canonical_result("denied") == "fail"
    assert canonical_result("motion to approve NOT adopted; resolution adopted") == "fail"     # the Birmingham denial pattern
    assert canonical_result("") is None and canonical_result("deferred two weeks") is None
    same = [("approved", "adopted"), ("passed", "adopted"), ("failed", "motion to approve NOT adopted; resolution adopted")]
    for a, b in same:
        t = ev("transcript", 1, "vote", [40], detail={"result": a})
        m = ev("minutes", 1, "vote", [40], detail={"result": b})
        assert details_differ(t, m) is None, (a, b)
    t = ev("transcript", 2, "vote", [41], detail={"result": "approved"})
    m = ev("minutes", 2, "vote", [41], detail={"result": "not adopted"})
    assert details_differ(t, m) == "vote_outcome"
    # Tallies still count even when the words agree.
    t = ev("transcript", 3, "vote", [42], detail={"result": "approved", "yeas": 8, "nays": 1})
    m = ev("minutes", 3, "vote", [42], detail={"result": "adopted", "yeas": 9, "nays": 0})
    assert details_differ(t, m) == "vote_outcome"
    # The OCR vote-row check uses the same vocabulary: 'approved' against a 'passed' row is not a candidate.
    tv = ev("transcript", 4, "vote", [43], detail={"result": "approved"})
    assert vote_outcome_candidates([tv], [{"id": 1, "item_ids": [43], "result": "passed", "yeas": None, "nays": None}]) == []
    assert len(vote_outcome_candidates([tv], [{"id": 1, "item_ids": [43], "result": "failed", "yeas": None, "nays": None}])) == 1
