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
