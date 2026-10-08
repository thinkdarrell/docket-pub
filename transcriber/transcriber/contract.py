"""The upload contract between the desktop producer and the Railway side.

One JSON file per meeting. This is the only thing the two sides share.
Word-level timestamps are NOT in this file's segments; they are written to
a sibling file named in ``words_path`` and never uploaded.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

CONTRACT_VERSION = 1
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """The output does not satisfy the contract."""


@dataclass
class Segment:
    seq: int
    start_s: float
    end_s: float
    text: str
    cluster_label: str | None
    avg_logprob: float | None
    no_speech_prob: float | None
    is_silence: bool = False


@dataclass
class Speaker:
    cluster_label: str
    embedding: list[float] | None


@dataclass
class TranscriptOutput:
    meeting_id: int
    version: int
    engine: str
    asr_model: str
    diarization_model: str | None
    audio_duration_s: float
    speech_seconds: float
    audio_sha256: str
    segments: list[Segment] = field(default_factory=list)
    speakers: list[Speaker] = field(default_factory=list)
    words_path: str | None = None

    @property
    def word_count(self) -> int:
        return sum(len(s.text.split()) for s in self.segments if not s.is_silence)

    @property
    def speech_ratio(self) -> float:
        if self.audio_duration_s <= 0:
            return 0.0
        return self.speech_seconds / self.audio_duration_s

    def validate(self) -> None:
        if not _SHA_RE.match(self.audio_sha256):
            raise ContractError("audio_sha256 must be 64 lowercase hex chars")
        labels = {sp.cluster_label for sp in self.speakers}
        for i, s in enumerate(self.segments):
            if s.seq != i:
                raise ContractError(f"segment seq must be contiguous from 0; got {s.seq} at {i}")
            if s.end_s < s.start_s or s.start_s < 0:
                raise ContractError(f"segment {i}: end_s {s.end_s} before start_s {s.start_s}")
            if s.cluster_label is not None and s.cluster_label not in labels:
                raise ContractError(f"segment {i}: unknown cluster {s.cluster_label}")

    def to_json(self) -> str:
        d = asdict(self)
        d["contract_version"] = CONTRACT_VERSION
        return json.dumps(d, ensure_ascii=False, indent=1)

    @classmethod
    def from_json(cls, s: str) -> "TranscriptOutput":
        d = json.loads(s)
        if d.pop("contract_version", CONTRACT_VERSION) != CONTRACT_VERSION:
            raise ContractError("unsupported contract_version")
        d["segments"] = [Segment(**x) for x in d["segments"]]
        d["speakers"] = [Speaker(**x) for x in d["speakers"]]
        return cls(**d)
