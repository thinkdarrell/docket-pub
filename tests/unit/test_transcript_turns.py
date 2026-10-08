from docket.services.transcripts import Turn, group_turns, item_anchor_map


def _seg(seq, start, end, text, cluster, name=None, conf=None, item=None, silence=False):
    return dict(seq=seq, start_s=start, end_s=end, text=text, cluster_label=cluster,
                is_silence=silence, agenda_item_id=item, speaker_name=name,
                speaker_confidence=conf, speaker_member_id=None)


def test_consecutive_same_cluster_merge_into_one_turn():
    segs = [_seg(0, 0, 2, "Council,", "S0", "Darrell O'Quinn", 0.9),
            _seg(1, 2, 5, "I have a question.", "S0", "Darrell O'Quinn", 0.9),
            _seg(2, 5, 9, "Sure.", "S1", None, None)]
    turns = group_turns(segs)
    assert [t.anchor for t in turns] == ["t-0", "t-2"]
    assert turns[0].texts == ["Council,", "I have a question."]
    assert turns[0].speaker_label == "Darrell O'Quinn"
    assert turns[1].speaker_label == "Speaker 2"


def test_low_confidence_name_falls_back_to_speaker_n():
    segs = [_seg(0, 0, 2, "x", "S0", "Guess Name", 0.4)]
    assert group_turns(segs)[0].speaker_label == "Speaker 1"


def test_silence_is_its_own_turn_and_does_not_merge():
    segs = [_seg(0, 0, 2, "x", "S0", "A", 0.9), _seg(1, 2, 80, "", None, silence=True),
            _seg(2, 80, 82, "y", "S0", "A", 0.9)]
    turns = group_turns(segs)
    assert [t.is_silence for t in turns] == [False, True, False]
    assert [t.anchor for t in turns] == ["t-0", "t-1", "t-2"]


def test_item_anchor_map_takes_first_turn_per_item():
    segs = [_seg(0, 0, 2, "a", "S0", item=7), _seg(1, 2, 4, "b", "S1", item=7),
            _seg(2, 4, 6, "c", "S1", item=9)]
    turns = group_turns(segs)
    assert item_anchor_map(turns) == {7: "t-0", 9: "t-2"}


def test_seeded_ordinals_keep_whole_meeting_numbering():
    # An excerpt sees only a slice; with the meeting-wide map S2 stays "Speaker 3".
    slice_ = [_seg(40, 100, 102, "x", "S2"), _seg(41, 102, 104, "y", "S0")]
    turns = group_turns(slice_, ordinals={"S0": 1, "S1": 2, "S2": 3})
    assert [t.speaker_label for t in turns] == ["Speaker 3", "Speaker 1"]
    # A cluster the map does not know is appended, never renumbered over an existing one.
    turns = group_turns([_seg(50, 110, 112, "z", "S9")], ordinals={"S0": 1})
    assert turns[0].speaker_label == "Speaker 2"


def test_manual_name_without_confidence_is_shown():
    segs = [_seg(0, 0, 2, "x", "S0", "LaTonya Tate", None)]
    assert group_turns(segs)[0].speaker_label == "LaTonya Tate"
