"""ASR + diarization engine and the pure post-processing around it.

Everything that touches torch is inside FasterWhisperEngine and imported
lazily, so unit tests run on a laptop with no GPU libraries installed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .contract import Segment, Speaker, TranscriptOutput

log = logging.getLogger(__name__)

LOW_SPEECH_FLOOR_S = 180.0


@dataclass
class RawSegment:
    start_s: float
    end_s: float
    text: str
    avg_logprob: float | None
    no_speech_prob: float | None


@dataclass
class DiarTurn:
    start_s: float
    end_s: float
    label: str


class Engine(Protocol):
    name: str
    asr_model: str
    diarization_model: str | None

    def transcribe(self, wav: Path, initial_prompt: str) -> list[RawSegment]: ...
    def diarize(self, wav: Path) -> tuple[list[DiarTurn], dict[str, list[float]]]: ...


def speech_seconds(raw: list[RawSegment]) -> float:
    return float(sum(max(0.0, r.end_s - r.start_s) for r in raw))


def is_low_speech(speech_s: float) -> bool:
    return speech_s < LOW_SPEECH_FLOOR_S


def assign_clusters(raw: list[RawSegment], turns: list[DiarTurn]) -> list[str | None]:
    out: list[str | None] = []
    for r in raw:
        overlap: dict[str, float] = {}
        for t in turns:
            o = min(r.end_s, t.end_s) - max(r.start_s, t.start_s)
            if o > 0:
                overlap[t.label] = overlap.get(t.label, 0.0) + o
        out.append(max(overlap, key=overlap.get) if overlap else None)
    return out


def insert_silence_markers(segments: list[Segment], audio_duration_s: float,
                           min_gap_s: float = 60.0) -> list[Segment]:
    result: list[Segment] = []
    cursor = 0.0
    for s in sorted(segments, key=lambda x: x.start_s):
        if s.start_s - cursor >= min_gap_s:
            result.append(Segment(0, cursor, s.start_s, "", None, None, None, is_silence=True))
        result.append(s)
        cursor = max(cursor, s.end_s)
    if audio_duration_s - cursor >= min_gap_s:
        result.append(Segment(0, cursor, audio_duration_s, "", None, None, None, is_silence=True))
    for i, s in enumerate(result):
        s.seq = i
    return result


def build_output(meeting_id: int, version: int, engine: Engine, raw: list[RawSegment],
                 turns: list[DiarTurn], embeddings: dict[str, list[float]],
                 audio_duration_s: float, audio_sha256: str,
                 words_path: str | None) -> TranscriptOutput:
    labels = assign_clusters(raw, turns)
    segs = [Segment(i, r.start_s, r.end_s, r.text.strip(), lab, r.avg_logprob, r.no_speech_prob)
            for i, (r, lab) in enumerate(zip(raw, labels))]
    segs = insert_silence_markers(segs, audio_duration_s)
    used = {s.cluster_label for s in segs if s.cluster_label}
    speakers = [Speaker(lab, embeddings.get(lab)) for lab in sorted(used)]
    out = TranscriptOutput(
        meeting_id=meeting_id, version=version, engine=engine.name, asr_model=engine.asr_model,
        diarization_model=engine.diarization_model, audio_duration_s=audio_duration_s,
        speech_seconds=speech_seconds(raw), audio_sha256=audio_sha256,
        segments=segs, speakers=speakers, words_path=words_path,
    )
    out.validate()
    return out


class FasterWhisperEngine:
    """faster-whisper for ASR, pyannote 3.1 for diarization. Both stay resident."""

    name = "faster-whisper"

    def __init__(self, model_size: str = "large-v3", device: str = "cuda",
                 compute_type: str = "float16", hf_token: str | None = None,
                 batch_size: int = 16):
        import torch  # noqa: F401  (lazy; proves CUDA stack is importable)
        from faster_whisper import BatchedInferencePipeline, WhisperModel

        self.asr_model = model_size
        self.device = device
        self.compute_type = compute_type
        self.batch_size = batch_size
        self._hf_token = hf_token
        self._whisper = WhisperModel(model_size, device=device, compute_type=compute_type)
        self._batched = BatchedInferencePipeline(model=self._whisper)
        self.diarization_model: str | None = None
        self._pipeline = None
        if hf_token:
            from pyannote.audio import Pipeline
            self.diarization_model = "pyannote/speaker-diarization-3.1"
            self._pipeline = Pipeline.from_pretrained(self.diarization_model, use_auth_token=hf_token)
            import torch
            self._pipeline.to(torch.device(device))
        self.oom_fallbacks = 0
        self.last_words: list[dict] = []

    def _is_oom(self, exc: BaseException) -> bool:
        return "out of memory" in str(exc).lower()

    def transcribe(self, wav: Path, initial_prompt: str) -> list[RawSegment]:
        try:
            return self._transcribe(wav, initial_prompt)
        except RuntimeError as e:
            if not self._is_oom(e):
                raise
            self.oom_fallbacks += 1
            log.warning("CUDA OOM in ASR; unloading diarizer and retrying once")
            self._unload_diarizer()
            return self._transcribe(wav, initial_prompt)

    def _transcribe(self, wav: Path, initial_prompt: str) -> list[RawSegment]:
        segments, _info = self._batched.transcribe(
            str(wav), batch_size=self.batch_size, word_timestamps=True,
            vad_filter=True, initial_prompt=initial_prompt, language="en",
        )
        raw: list[RawSegment] = []
        words: list[dict] = []
        for s in segments:
            raw.append(RawSegment(float(s.start), float(s.end), s.text,
                                  getattr(s, "avg_logprob", None), getattr(s, "no_speech_prob", None)))
            for w in (s.words or []):
                words.append({"s": float(w.start), "e": float(w.end), "w": w.word, "p": float(w.probability)})
        self.last_words = words
        return raw

    def diarize(self, wav: Path) -> tuple[list[DiarTurn], dict[str, list[float]]]:
        if self._pipeline is None:
            self._reload_diarizer()
        if self._pipeline is None:
            return [], {}
        try:
            return self._diarize(wav)
        except RuntimeError as e:
            if not self._is_oom(e):
                raise
            self.oom_fallbacks += 1
            log.warning("CUDA OOM in diarization; unloading ASR and retrying once")
            import gc, torch
            self._batched = None
            self._whisper = None
            gc.collect(); torch.cuda.empty_cache()
            result = self._diarize(wav)
            self._reload_asr()
            return result

    def _diarize(self, wav: Path):
        # pyannote.audio 3.1.x: SpeakerDiarization.apply(file, ..., return_embeddings=False)
        # returns (Annotation, ndarray[n_speakers, dim]) when True, and Pipeline.__call__
        # forwards **kwargs to apply(). Verified against tags 3.1.0 and 3.1.1. The
        # embeddings row order matches diar.labels().
        diar, embeddings = self._pipeline(str(wav), return_embeddings=True)
        turns = [DiarTurn(float(seg.start), float(seg.end), label)
                 for seg, _, label in diar.itertracks(yield_label=True)]
        labels = diar.labels()
        emb = {lab: [float(x) for x in embeddings[i]] for i, lab in enumerate(labels)}
        return turns, emb

    def _unload_diarizer(self):
        import gc, torch
        self._pipeline = None
        gc.collect(); torch.cuda.empty_cache()

    def _reload_diarizer(self):
        if not self._hf_token:
            return
        from pyannote.audio import Pipeline
        import torch
        self._pipeline = Pipeline.from_pretrained(self.diarization_model, use_auth_token=self._hf_token)
        self._pipeline.to(torch.device(self.device))

    def _reload_asr(self):
        from faster_whisper import BatchedInferencePipeline, WhisperModel
        self._whisper = WhisperModel(self.asr_model, device=self.device, compute_type=self.compute_type)
        self._batched = BatchedInferencePipeline(model=self._whisper)
