import pytest
from transcriber.contract import Segment
from transcriber.engine import (
    LOW_SPEECH_FLOOR_S, DiarTurn, RawSegment, assign_clusters, insert_silence_markers,
    is_low_speech, speech_seconds,
)


def test_assign_clusters_majority_overlap():
    raw = [RawSegment(0.0, 10.0, "a", -0.1, 0.0), RawSegment(10.0, 12.0, "b", -0.1, 0.0),
           RawSegment(500.0, 501.0, "c", -0.1, 0.0)]
    turns = [DiarTurn(0.0, 4.0, "SPEAKER_00"), DiarTurn(4.0, 12.0, "SPEAKER_01")]
    assert assign_clusters(raw, turns) == ["SPEAKER_01", "SPEAKER_01", None]


def test_insert_silence_markers_adds_rows_for_long_gaps_only():
    segs = [Segment(0, 0.0, 5.0, "x", "S0", None, None),
            Segment(1, 5.0, 8.0, "y", "S0", None, None),
            Segment(2, 100.0, 103.0, "z", "S1", None, None)]
    out = insert_silence_markers(segs, audio_duration_s=200.0, min_gap_s=60.0)
    assert [s.seq for s in out] == [0, 1, 2, 3, 4]
    assert out[2].is_silence and out[2].start_s == 8.0 and out[2].end_s == 100.0
    assert out[4].is_silence and out[4].start_s == 103.0 and out[4].end_s == 200.0
    assert not out[1].is_silence  # 5.0 -> 5.0 gap of zero


def test_speech_seconds_sums_segments():
    raw = [RawSegment(0.0, 10.0, "a", None, None), RawSegment(20.0, 25.5, "b", None, None)]
    assert speech_seconds(raw) == pytest.approx(15.5)


def test_low_speech_is_absolute_floor():
    assert LOW_SPEECH_FLOOR_S == 180.0
    assert is_low_speech(120.0)       # under three minutes of speech: dead or near-empty stream
    assert not is_low_speech(180.0)   # a 10-minute emergency session with 3 min of business uploads
    assert not is_low_speech(10_000.0)


# --- cleaning: hallucinations and prompt leaks (plan transcriber-clean-speaker-segments, M1) ---

from transcriber.engine import build_output, clean_segments  # noqa: E402
from transcriber.prompt import build_initial_prompt  # noqa: E402

OLD_TERMS = ("ALEA", "CJI", "APC", "Alabama Power", "BJCC", "Woodlawn", "Ensley", "Avondale", "Pratt City",
             "Norwood", "Smithfield", "Titusville", "ADECA", "ALDOT", "BJCTA", "Granicus", "Birmingham-Jefferson",
             "Railroad Park", "Red Mountain", "Protective Stadium", "Legion Field", "Crossplex", "Flock Safety",
             "license plate reader", "Mayor Woodfin", "City Attorney", "Pro Tem", "ordinance", "resolution",
             "consent agenda", "executive session")
OLD_PROMPT = "Birmingham City Council. Terms: " + ", ".join(OLD_TERMS) + "."
LEAKED_ROW_38 = ("ALEA, CJI, APC, Alabama Power, BJCC, Woodlawn, Ensley, Avondale, Pratt City, "
                 "Norwood, Smithfield,")


class _FakeEngine:
    name = "fake"; asr_model = "tiny"; diarization_model = None


def test_hallucination_drops_short_low_logprob_segment():
    kept, dropped = clean_segments([RawSegment(100.0, 101.0, "Thank you for joining us.", -1.1, 0.002)], "")
    assert kept == [] and dropped == {"hallucination": 1, "prompt_leak": 0}


def test_hallucination_keeps_long_low_logprob_segment():
    r = RawSegment(100.0, 110.0, "We will now move to item twelve on the consent agenda for today.", -1.1, 0.002)
    kept, dropped = clean_segments([r], "")
    assert kept == [r] and dropped == {"hallucination": 0, "prompt_leak": 0}


def test_hallucination_drops_phrase_only_repetition_over_word_cap():
    r = RawSegment(100.0, 103.0, "Thank you. Thank you. Thank you. Thank you. Thank you.", -1.0, 0.002)
    assert len(r.text.split()) == 10
    kept, dropped = clean_segments([r], "")
    assert kept == [] and dropped["hallucination"] == 1


def test_hallucination_keeps_short_confident_segment():
    r = RawSegment(100.0, 100.5, "Here.", -0.1, 0.001)
    kept, dropped = clean_segments([r], "")
    assert kept == [r] and dropped == {"hallucination": 0, "prompt_leak": 0}


def test_prompt_leak_drops_reproduced_vocabulary():
    r = RawSegment(300.0, 318.2, LEAKED_ROW_38, -0.36, 0.01)
    kept, dropped = clean_segments([r], OLD_PROMPT)
    assert kept == [] and dropped == {"hallucination": 0, "prompt_leak": 1}


def test_prompt_leak_keeps_short_prompt_substring():
    r = RawSegment(300.0, 302.0, "the Birmingham City Council.", -0.2, 0.01)
    kept, dropped = clean_segments([r], OLD_PROMPT)
    assert kept == [r] and dropped == {"hallucination": 0, "prompt_leak": 0}


def test_prompt_leak_drops_echo_with_filler_attached():
    prompt = build_initial_prompt([])
    echo = "Thank you. ALEA, CJI, and APC reported. Alabama Power and ALDOT spoke at the BJCC."
    kept, dropped = clean_segments([RawSegment(10.0, 15.0, echo, -0.3, 0.01)], prompt)
    assert kept == [] and dropped == {"hallucination": 0, "prompt_leak": 1}
    # The plan's kept variant replaced only "reported"; but "Alabama Power and ALDOT spoke at the
    # BJCC" is itself eight consecutive prompt words, so the kept variant must also break that
    # sentence (Decision Log, 2026-10-16, M1 session).
    genuine = RawSegment(10.0, 15.0, echo.replace("reported", "spoke").replace("BJCC", "stadium"), -0.3, 0.01)
    kept, dropped = clean_segments([genuine], prompt)
    assert kept == [genuine] and dropped == {"hallucination": 0, "prompt_leak": 0}


def test_hallucination_drops_punctuation_only_segment():
    raw = [RawSegment(10.0, 11.0, "...", -0.1, 0.001), RawSegment(12.0, 12.0, "", None, None)]
    kept, dropped = clean_segments(raw, "")
    assert kept == [] and dropped == {"hallucination": 2, "prompt_leak": 0}


def test_build_output_drops_and_renumbers():
    raw = [RawSegment(0.0, 10.0, "Call to order.", -0.1, 0.0),
           RawSegment(100.0, 101.0, "Thank you for joining us.", -1.1, 0.002),
           RawSegment(200.0, 210.0, "Meeting adjourned.", -0.1, 0.0)]
    turns = [DiarTurn(0.0, 210.0, "SPEAKER_00")]
    out = build_output(1, 1, _FakeEngine(), raw, turns, {"SPEAKER_00": [0.1]}, 210.0, "ab" * 32, None,
                       initial_prompt="")
    assert [s.seq for s in out.segments] == [0, 1, 2]
    assert [s.is_silence for s in out.segments] == [False, True, False]
    assert out.segments[1].start_s == 10.0 and out.segments[1].end_s == 200.0
    assert [s.text for s in out.segments if not s.is_silence] == ["Call to order.", "Meeting adjourned."]
    assert out.speech_seconds == pytest.approx(20.0)
    out.validate()


# --- per-word speaker split (plan transcriber-clean-speaker-segments, M2) ---

import dataclasses  # noqa: E402

from transcriber.engine import Word, assign_word_clusters, normalize_text, split_by_speaker  # noqa: E402

FIXTURE_NAMES = ("Brian Gunn", "Clinton P. Woods", "Crystal N. Smitherman", "Darrell O'Quinn", "Hunter Williams",
                 "Josh Vasa", "LaTonya A. Tate", "Sonja Q. Smith", "Wardine T. Alexander")


def _name_pieces(name: str) -> list[str]:
    """faster-whisper keeps a word's leading space and emits an apostrophe piece with none."""
    last = name.split()[-1]
    if "'" in last:
        head, tail = last.split("'", 1)
        return [" Councilmember", f" {head}", f"'{tail}."]
    return [" Councilmember", f" {last}."]


def _roll_call_chunk(start: float, spacing: float = 2.0) -> tuple[RawSegment, list[DiarTurn]]:
    """One chunk whose words alternate 'Councilmember <surname>.' (CLERK) and 'Here.' (S1..S9)."""
    words: list[Word] = []
    turns: list[DiarTurn] = []
    t = start
    for i, name in enumerate(FIXTURE_NAMES, start=1):
        pieces = _name_pieces(name)
        step = (spacing * 0.8) / len(pieces)
        for j, p in enumerate(pieces):
            words.append(Word(t + j * step, t + j * step + step * 0.9, p))
        turns.append(DiarTurn(t, t + spacing * 0.8, "CLERK"))
        t += spacing
        words.append(Word(t, t + spacing * 0.2, " Here."))
        turns.append(DiarTurn(t, t + spacing * 0.2, f"S{i}"))
        t += spacing
    chunk = RawSegment(start, t, "".join(w.text for w in words), -0.2, 0.01, words=words)
    return chunk, turns


def _roster(speakers):
    return [speakers.RosterMember(i, n, speakers.surname(n)) for i, n in enumerate(FIXTURE_NAMES, start=1)]


def test_assign_word_clusters_by_overlap_and_snap():
    turns = [DiarTurn(0.0, 14.0, "A"), DiarTurn(14.5, 28.0, "B")]
    words = [Word(13.8, 14.2, " x"), Word(14.2, 14.4, " y"), Word(20.0, 21.0, " z")]
    assert assign_word_clusters(words, turns) == ["A", "B", "B"]
    only_a = [DiarTurn(0.0, 5.0, "A")]
    assert assign_word_clusters([Word(1.0, 2.0, " x"), Word(50.0, 51.0, " y")], only_a) == ["A", "A"]
    assert assign_word_clusters([Word(50.0, 51.0, " y")], only_a) == [None]
    # a leading unlabelled run takes the first labelled word's cluster
    assert assign_word_clusters([Word(50.0, 51.0, " y"), Word(1.0, 2.0, " x")], only_a) == ["A", "A"]


def test_split_by_speaker_cuts_chunk_at_speaker_change():
    turns = [DiarTurn(0.0, 15.0, "A"), DiarTurn(15.0, 28.0, "B")]
    pieces = [" Good", " morning,", " please", " call", " the", " roll.",
              " Councilmember", " O", "'Quinn.", " Here."]
    words = [Word(0.5 + 2.5 * i, 1.5 + 2.5 * i, p) for i, p in enumerate(pieces)]
    words[-1] = Word(words[-1].start_s, 28.05, words[-1].text)   # DTW lands a hair past the chunk
    chunk = RawSegment(0.0, 28.0, "".join(pieces), -0.25, 0.01, words=words)
    segs = split_by_speaker([chunk], turns)
    assert [s.seq for s in segs] == [0, 1]
    assert [s.cluster_label for s in segs] == ["A", "B"]
    assert segs[0].start_s == 0.0 and segs[0].end_s == words[5].end_s
    assert segs[1].start_s == words[6].start_s and segs[1].end_s == 28.0
    assert segs[0].text == "Good morning, please call the roll."
    assert segs[1].text == "Councilmember O'Quinn. Here."
    assert all(s.avg_logprob == -0.25 and s.no_speech_prob == 0.01 for s in segs)
    # a final one-word run starting past the chunk's end clamps to end_s == start_s, and validates
    late = RawSegment(0.0, 10.0, " a b", -0.1, 0.0, words=[Word(0.0, 9.0, " a"), Word(10.02, 10.05, " b")])
    segs = split_by_speaker([late], [DiarTurn(0.0, 10.0, "A"), DiarTurn(10.0, 11.0, "B")])
    assert [s.cluster_label for s in segs] == ["A", "B"]
    assert segs[1].start_s == 10.02 and segs[1].end_s == 10.02
    out = build_output(1, 1, _FakeEngine(), [late], [DiarTurn(0.0, 10.0, "A"), DiarTurn(10.0, 11.0, "B")],
                       {}, 10.0, "ab" * 32, None)
    out.validate()


def test_split_by_speaker_without_words_keeps_whole_chunk():
    turns = [DiarTurn(0.0, 15.0, "A"), DiarTurn(15.0, 28.0, "B")]
    chunk = RawSegment(0.0, 28.0, " whole chunk ", -0.1, 0.0)
    segs = split_by_speaker([chunk], turns)
    assert len(segs) == 1
    assert (segs[0].seq, segs[0].start_s, segs[0].end_s, segs[0].text) == (0, 0.0, 28.0, "whole chunk")
    assert segs[0].cluster_label == assign_clusters([chunk], turns)[0] == "A"


def test_roll_call_inside_one_chunk_pairs_after_split():
    speakers = pytest.importorskip("docket.ai.transcripts.speakers")
    roster = _roster(speakers)
    chunk, turns = _roll_call_chunk(0.0)
    assert chunk.end_s <= 60.0
    out = build_output(2543, 1, _FakeEngine(), [chunk], turns, {}, 60.0, "ab" * 32, None)
    pairs = speakers.find_roll_call_pairs([dataclasses.asdict(s) for s in out.segments], roster)
    assert [p.response_cluster for p in pairs] == [f"S{i}" for i in range(1, 10)]
    assert [p.member.surname for p in pairs] == [speakers.surname(n) for n in FIXTURE_NAMES]
    # the old whole-chunk path gives the roll call one label and pairs nothing
    label = assign_clusters([chunk], turns)[0]
    assert label is not None
    old = [dataclasses.asdict(Segment(0, chunk.start_s, chunk.end_s, chunk.text.strip(), label, -0.2, 0.01))]
    assert speakers.find_roll_call_pairs(old, roster) == []


def test_fixture_shaped_transcript_through_build_output():
    speakers = pytest.importorskip("docket.ai.transcripts.speakers")
    roster = _roster(speakers)
    prompt = build_initial_prompt([])
    raw: list[RawSegment] = []
    turns: list[DiarTurn] = []
    for i in range(19):
        start = 30.0 * i
        words = [Word(start + 1.3 * j, start + 1.3 * j + 1.0, f" word{j}") for j in range(20)]
        raw.append(RawSegment(start, start + 27.0, "".join(w.text for w in words), -0.15, 0.01, words=words))
        turns += [DiarTurn(start, start + 13.5, "P"), DiarTurn(start + 13.5, start + 27.0, "Q")]
        if i in (1, 3, 5, 7):
            raw.append(RawSegment(start + 27.5, start + 28.5, "Thank you for joining us.", -1.1, 0.002))
    chunk, roll_turns = _roll_call_chunk(570.0, spacing=1.5)
    assert chunk.end_s - chunk.start_s == pytest.approx(27.0)
    raw.append(chunk)
    turns += roll_turns
    leak = " ".join(prompt.split()[-12:])
    raw.append(RawSegment(600.0, 610.0, leak, -0.3, 0.01,
                          words=[Word(600.0 + 0.8 * j, 600.5 + 0.8 * j, f" {w}") for j, w in enumerate(leak.split())]))
    turns.append(DiarTurn(600.0, 610.0, "P"))
    out = build_output(2543, 1, _FakeEngine(), raw, turns, {}, 620.0, "ab" * 32, None, initial_prompt=prompt)
    speech = [s for s in out.segments if not s.is_silence]
    assert len(speech) > 20
    assert not any("Thank you for joining us" in s.text for s in speech)
    norm_prompt = normalize_text(prompt)
    assert not any(len(normalize_text(s.text).split()) >= 8 and normalize_text(s.text) in norm_prompt
                   for s in speech)
    pairs = speakers.find_roll_call_pairs([dataclasses.asdict(s) for s in out.segments], roster)
    assert len(pairs) == 9
    out.validate()
