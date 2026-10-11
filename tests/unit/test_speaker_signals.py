from docket.ai.transcripts.speakers import (ClusterStats, RosterMember, build_packet, cluster_stats,
                                             find_chair_addresses, find_roll_call_pairs, is_short_response,
                                             mentioned_members, render_speaker_user, sample_utterances, surname)

R = [RosterMember(1, "Darrell O'Quinn", "oquinn"), RosterMember(2, "LaTonya Tate", "tate"),
     RosterMember(3, "Crystal Smitherman", "smitherman"), RosterMember(4, "Hunter Williams", "williams")]


def seg(seq, start, text, cluster, dur=3.0, silence=False):
    return {"seq": seq, "start_s": float(start), "end_s": float(start) + dur, "text": text,
            "cluster_label": cluster, "is_silence": silence}


def test_surname_strips_suffixes_and_punctuation():
    assert surname("Darrell O'Quinn") == "oquinn"
    assert surname("J.T. Moore") == "moore"
    assert surname("Clinton Woods Jr.") == "woods"
    assert surname("Valerie A. Abbott, III") == "abbott"


def test_mentioned_members_tolerates_asr_spelling():
    assert [m.id for m in mentioned_members("Council member O Quinn", R)] == [1]
    assert [m.id for m in mentioned_members("Councilor Smithermann, you have the floor", R)] == [3]
    assert mentioned_members("the tate modern is in london", R) == [R[1]]   # surname hit; the finders add context
    assert mentioned_members("no names here", R) == []


def test_is_short_response():
    assert is_short_response("Here.") and is_short_response("Present") and is_short_response("Yes, here")
    assert not is_short_response("Here is what I think about the budget")


def test_roll_call_pairs_require_short_response_from_another_cluster():
    segs = [seg(0, 900, "Councilor O'Quinn.", "S0"), seg(1, 903, "Here.", "S7", dur=1),
            seg(2, 905, "Councilor Tate.", "S0"), seg(3, 907, "I want to talk about the budget for a while here", "S3"),
            seg(4, 920, "Councilor Smitherman.", "S0"), seg(5, 940, "Present.", "S9", dur=1)]   # 17 s gap: too late
    pairs = find_roll_call_pairs(segs, R)
    assert [(p.member.id, p.response_cluster, p.response_text) for p in pairs] == [(1, "S7", "Here.")]


def test_roll_call_ignores_same_cluster_response():
    segs = [seg(0, 900, "Councilor Williams.", "S0"), seg(1, 902, "Here.", "S0", dur=1)]
    assert find_roll_call_pairs(segs, R) == []


def test_chair_address_skips_interjections_and_needs_substance():
    segs = [seg(0, 3300, "Councilor O'Quinn, you are recognized.", "S0"),
            seg(1, 3304, "Thank you.", "S4", dur=1),                      # interjection, skipped
            seg(2, 3306, "Yeah, I would just like to hear a layman's summary of what is going on here.", "S7"),
            seg(3, 3400, "as Councilor Tate said earlier", "S7"),          # mention without title/question: not an address
            seg(4, 3405, "The budget office has eleven line items for this program this year.", "S2")]
    adds = find_chair_addresses(segs, R)
    assert [(a.member.id, a.next_cluster) for a in adds] == [(1, "S7")]


def test_cluster_stats_ignore_silence_and_order_by_first_appearance():
    segs = [seg(0, 0, "", None, dur=890, silence=True), seg(1, 900, "a b c", "S3", dur=5), seg(2, 910, "d e", "S1", dur=2),
            seg(3, 920, "f g h i", "S3", dur=4)]
    st = cluster_stats(segs)
    assert list(st) == ["S3", "S1"]
    assert st["S3"] == ClusterStats("S3", 9.0, 2, 900.0, 7)


def test_sample_utterances_spread_across_meeting_and_bounded():
    segs = [seg(i, 900 + i * 10, " ".join(["word"] * (6 + i % 5)), "S3") for i in range(60)]
    samples = sample_utterances(segs, per_cluster=6)
    s = samples["S3"]
    assert len(s) == 6
    assert s[0]["seq"] < s[2]["seq"] < s[5]["seq"]
    assert s[0]["start_s"] < 1000 and s[-1]["start_s"] > 1400
    long = [seg(0, 900, " ".join(["w"] * 200), "S1")]
    assert len(sample_utterances(long)["S1"][0]["text"].split()) <= 60


def test_render_lists_every_cluster_and_the_signals():
    segs = [seg(0, 900, "Councilor O'Quinn.", "S0"), seg(1, 903, "Here.", "S7", dur=1),
            seg(2, 910, "Good morning everyone, we are called to order for the regular meeting.", "S0"),
            seg(3, 1000, "I move approval of the consent agenda as presented this morning.", "S7")]
    packet = build_packet(segs, R)
    text = render_speaker_user(packet, {"id": 2543, "meeting_date": "2026-10-06", "title": "City Council Meeting"})
    assert "1: Darrell O'Quinn" in text
    assert "S0" in text and "S7" in text
    assert "Roll-call candidate pairs" in text and '"Here."' in text
    assert "seq=3" in text
