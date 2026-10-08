import json
import pytest
from transcriber.contract import (
    CONTRACT_VERSION, ContractError, Segment, Speaker, TranscriptOutput,
)


def _out(**kw) -> TranscriptOutput:
    base = dict(
        meeting_id=15, version=1, engine="faster-whisper", asr_model="large-v3",
        diarization_model="pyannote/speaker-diarization-3.1",
        audio_duration_s=530.6, speech_seconds=400.0, audio_sha256="ab" * 32,
        segments=[
            Segment(seq=0, start_s=0.0, end_s=4.2, text="Council is my recommendation",
                    cluster_label="SPEAKER_00", avg_logprob=-0.2, no_speech_prob=0.01),
            Segment(seq=1, start_s=4.2, end_s=70.0, text="", cluster_label=None,
                    avg_logprob=None, no_speech_prob=None, is_silence=True),
        ],
        speakers=[Speaker(cluster_label="SPEAKER_00", embedding=[0.1, 0.2])],
        words_path=None,
    )
    base.update(kw)
    return TranscriptOutput(**base)


def test_round_trip_json():
    out = _out()
    again = TranscriptOutput.from_json(out.to_json())
    assert again == out
    assert json.loads(out.to_json())["contract_version"] == CONTRACT_VERSION


def test_word_count_ignores_silence():
    assert _out().word_count == 4


def test_speech_ratio():
    assert _out().speech_ratio == pytest.approx(400.0 / 530.6)


def test_validate_rejects_non_contiguous_seq():
    out = _out()
    out.segments[1].seq = 5
    with pytest.raises(ContractError, match="seq"):
        out.validate()


def test_validate_rejects_end_before_start():
    out = _out()
    out.segments[0].end_s = -1.0
    with pytest.raises(ContractError, match="end_s"):
        out.validate()


def test_validate_rejects_unknown_cluster():
    out = _out()
    out.segments[0].cluster_label = "SPEAKER_99"
    with pytest.raises(ContractError, match="cluster"):
        out.validate()


def test_validate_rejects_bad_sha():
    with pytest.raises(ContractError, match="sha256"):
        _out(audio_sha256="nope").validate()
