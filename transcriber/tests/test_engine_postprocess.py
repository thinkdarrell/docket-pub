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
