"""ASR + diarization engine and the pure post-processing around it.

Everything that touches torch is inside FasterWhisperEngine and imported
lazily, so unit tests run on a laptop with no GPU libraries installed.
"""
from __future__ import annotations

import logging
import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .contract import Segment, Speaker, TranscriptOutput

log = logging.getLogger(__name__)

LOW_SPEECH_FLOOR_S = 180.0

# transcripts.version. 3 = signature-phrase filter, same-speaker merge; 2 = per-word speaker split,
# hallucination and prompt-leak filters, prose prompt; 1 = whole-chunk clusters, no cleaning. Bump it when the output changes shape or content again.
TRANSCRIPT_VERSION = 3


@dataclass
class Word:
    """One word-level timestamp from faster-whisper. ``text`` keeps the leading space
    faster-whisper puts on most words; an apostrophe or hyphen piece carries none."""
    start_s: float
    end_s: float
    text: str
    probability: float | None = None


@dataclass
class RawSegment:
    start_s: float
    end_s: float
    text: str
    avg_logprob: float | None
    no_speech_prob: float | None
    words: list[Word] = field(default_factory=list)


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


# Cleaning runs on the raw chunks before any splitting. The batched pipeline
# merges genuine short utterances into the surrounding ~28 s chunk, so a short
# standalone low-confidence chunk is almost always Whisper filling applause or
# silence ("Thank you for joining us."); after a per-word split a genuine
# one-word "Here." would look the same, which is why the order matters.
HALLUCINATION_LOGPROB = -0.9
HALLUCINATION_MAX_WORDS = 8
HALLUCINATION_PHRASES: tuple[str, ...] = (
    "thank you", "thanks", "thank you very much", "thank you so much",
    "thank you for joining us", "thank you for joining us today",
    "bye", "you", "all right", "okay", "thank you all",
)
# Phrases from Whisper's caption training data that nobody says at a council
# meeting. A chunk made only of stock phrases that includes one of these is
# dropped at the looser SIGNATURE_LOGPROB whatever its length (2543 at 91:47:
# "Thank you for watching.", 12 s, -0.78), while "Thank you very much." at -0.74
# is plausibly real and keeps the stricter HALLUCINATION_LOGPROB.
SIGNATURE_LOGPROB = -0.5
SIGNATURE_PHRASES: tuple[str, ...] = (
    "thank you for watching", "thanks for watching", "thank you so much for watching",
    "please subscribe", "like and subscribe", "subscribe to my channel",
    "subtitles by the amaraorg community",
)
PROMPT_LEAK_MIN_WORDS = 8

_NOT_ALNUM_OR_SPACE = re.compile(r"[^a-z0-9\s]+")


def normalize_text(text: str) -> str:
    """Lowercase, letters and digits only, single spaces."""
    return " ".join(_NOT_ALNUM_OR_SPACE.sub("", text.lower()).split())


def is_phrase_only(text: str) -> bool:
    """True when the normalized text is a sequence of stock phrases (HALLUCINATION_PHRASES
    and SIGNATURE_PHRASES) and nothing else.

    Tokens are consumed from the left, always taking the longest phrase that
    matches at the current position; an empty text counts as phrase-only.
    """
    tokens = normalize_text(text).split()
    phrases = sorted((p.split() for p in HALLUCINATION_PHRASES + SIGNATURE_PHRASES), key=len, reverse=True)
    i = 0
    while i < len(tokens):
        for ph in phrases:
            if tokens[i:i + len(ph)] == ph:
                i += len(ph)
                break
        else:
            return False
    return True


def has_signature_phrase(norm: str) -> bool:
    """True when normalized text contains one of SIGNATURE_PHRASES on word boundaries."""
    padded = f" {norm} "
    return any(f" {p} " in padded for p in SIGNATURE_PHRASES)


def is_hallucination(r: RawSegment) -> bool:
    norm = normalize_text(r.text)
    if norm == "":
        return True
    if r.avg_logprob is None:
        return False
    if r.avg_logprob <= SIGNATURE_LOGPROB and has_signature_phrase(norm) and is_phrase_only(r.text):
        return True
    if r.avg_logprob > HALLUCINATION_LOGPROB:
        return False
    return len(norm.split()) <= HALLUCINATION_MAX_WORDS or is_phrase_only(r.text)


def is_prompt_leak(text: str, initial_prompt: str) -> bool:
    """True when any PROMPT_LEAK_MIN_WORDS consecutive normalized words of the text occur,
    in order and on word boundaries, in the normalized prompt. An empty prompt never matches."""
    prompt = normalize_text(initial_prompt)
    if not prompt:
        return False
    words = normalize_text(text).split()
    if len(words) < PROMPT_LEAK_MIN_WORDS:
        return False
    haystack = f" {prompt} "
    for i in range(len(words) - PROMPT_LEAK_MIN_WORDS + 1):
        window = " ".join(words[i:i + PROMPT_LEAK_MIN_WORDS])
        if f" {window} " in haystack:
            return True
    return False


def clean_segments(raw: list[RawSegment], initial_prompt: str) -> tuple[list[RawSegment], dict[str, int]]:
    """Drop hallucinated and prompt-leaked chunks; each dropped chunk is counted once."""
    kept: list[RawSegment] = []
    counts = {"hallucination": 0, "prompt_leak": 0}
    for r in raw:
        if is_hallucination(r):
            counts["hallucination"] += 1
        elif is_prompt_leak(r.text, initial_prompt):
            counts["prompt_leak"] += 1
        else:
            kept.append(r)
    return kept, counts


# The batched pipeline emits ~28 s chunks and a speaker change inside one is lost
# when the whole chunk takes one cluster: the roll call (nine names, nine "here"s)
# sits in one segment on 40 of 48 uploads. So every word takes a cluster from the
# word timestamps and a chunk is cut wherever the cluster changes.
WORD_SNAP_S = 1.0


def assign_word_clusters(words: list[Word], turns: list[DiarTurn]) -> list[str | None]:
    """The cluster of the turn each word overlaps most; a word overlapping no turn
    takes the nearest turn's cluster when that edge is within WORD_SNAP_S, else the
    previous word's label; a leading unlabelled run takes the first label found.

    Candidate turns are bounded with two bisects (turns sorted by start, plus a
    running maximum of end), so the cost is proportional to words plus turns.
    No smoothing of short runs: a one-word run ("Here.") is a legitimate turn.
    """
    if not words:
        return []
    ts = sorted(turns, key=lambda t: t.start_s)
    starts = [t.start_s for t in ts]
    max_end: list[float] = []
    running = float("-inf")
    for t in ts:
        running = max(running, t.end_s)
        max_end.append(running)
    labels: list[str | None] = []
    for w in words:
        lo = bisect_left(max_end, w.start_s - WORD_SNAP_S)
        hi = bisect_right(starts, w.end_s + WORD_SNAP_S)
        overlap: dict[str, float] = {}
        nearest: tuple[float, str] | None = None
        for t in ts[lo:hi]:
            o = min(w.end_s, t.end_s) - max(w.start_s, t.start_s)
            if o > 0:
                overlap[t.label] = overlap.get(t.label, 0.0) + o
            else:
                gap = max(t.start_s - w.end_s, w.start_s - t.end_s)
                if gap <= WORD_SNAP_S and (nearest is None or gap < nearest[0]):
                    nearest = (gap, t.label)
        if overlap:
            labels.append(max(overlap, key=overlap.get))
        elif nearest is not None:
            labels.append(nearest[1])
        else:
            labels.append(None)
    for i in range(1, len(labels)):
        if labels[i] is None:
            labels[i] = labels[i - 1]
    first = next((lab for lab in labels if lab is not None), None)
    for i, lab in enumerate(labels):
        if lab is not None:
            break
        labels[i] = first
    return labels


# Back-to-back segments from one cluster are joined when the gap between them is
# short and the result stays readable; MERGE_MAX_S keeps a long speech from
# collapsing back into multi-minute rows (v2's median segment is 12.4 s).
MERGE_MAX_GAP_S = 1.0
MERGE_MAX_S = 30.0


def merge_same_speaker(segs: list[Segment]) -> list[Segment]:
    """Join consecutive segments with the same non-None cluster when the gap is at most
    MERGE_MAX_GAP_S and the joined span at most MERGE_MAX_S. The joined avg_logprob is
    the duration-weighted mean and no_speech_prob the larger (None when either is None);
    seq is renumbered."""
    out: list[Segment] = []
    for s in segs:
        p = out[-1] if out else None
        if (p is not None and s.cluster_label is not None and p.cluster_label == s.cluster_label
                and s.start_s - p.end_s <= MERGE_MAX_GAP_S and s.end_s - p.start_s <= MERGE_MAX_S):
            dp, ds = p.end_s - p.start_s, s.end_s - s.start_s
            if p.avg_logprob is None or s.avg_logprob is None:
                lp = None
            elif dp + ds > 0:
                lp = (p.avg_logprob * dp + s.avg_logprob * ds) / (dp + ds)
            else:
                lp = p.avg_logprob
            if p.no_speech_prob is None or s.no_speech_prob is None:
                nsp = None
            else:
                nsp = max(p.no_speech_prob, s.no_speech_prob)
            out[-1] = Segment(p.seq, p.start_s, max(p.end_s, s.end_s), f"{p.text} {s.text}".strip(),
                              p.cluster_label, lp, nsp)
        else:
            out.append(s)
    for i, s in enumerate(out):
        s.seq = i
    return out


def split_by_speaker(raw: list[RawSegment], turns: list[DiarTurn]) -> list[Segment]:
    """One Segment per run of same-cluster words in each chunk.

    A chunk with no words keeps today's whole-chunk assignment. The first run starts
    at the chunk's start_s and the last ends at its end_s; interior boundaries come
    from the word timestamps. Children inherit the chunk's avg_logprob and
    no_speech_prob (Whisper statistics of the chunk; there is no honest per-child
    value). A run's text concatenates the raw word pieces and collapses whitespace,
    which keeps "O'Quinn" together; a run whose text is empty is skipped. A label may
    be None, exactly as assign_clusters leaves an unmatched chunk.
    """
    segs: list[Segment] = []
    for r in raw:
        if not r.words:
            lab = assign_clusters([r], turns)[0]
            segs.append(Segment(len(segs), r.start_s, r.end_s, r.text.strip(), lab,
                                r.avg_logprob, r.no_speech_prob))
            continue
        words = sorted(r.words, key=lambda w: w.start_s)
        labels = assign_word_clusters(words, turns)
        runs: list[tuple[str | None, list[Word]]] = []
        for w, lab in zip(words, labels):
            if runs and runs[-1][0] == lab:
                runs[-1][1].append(w)
            else:
                runs.append((lab, [w]))
        runs = [(lab, run, " ".join("".join(w.text for w in run).split())) for lab, run in runs]
        runs = [x for x in runs if x[2]]
        for i, (lab, run, text) in enumerate(runs):
            start = r.start_s if i == 0 else run[0].start_s
            end = r.end_s if i == len(runs) - 1 else run[-1].end_s
            end = max(start, end)
            segs.append(Segment(len(segs), start, end, text, lab, r.avg_logprob, r.no_speech_prob))
    return segs


def build_output(meeting_id: int, version: int, engine: Engine, raw: list[RawSegment],
                 turns: list[DiarTurn], embeddings: dict[str, list[float]],
                 audio_duration_s: float, audio_sha256: str,
                 words_path: str | None, initial_prompt: str = "") -> TranscriptOutput:
    raw, dropped = clean_segments(raw, initial_prompt)
    if any(dropped.values()):
        log.info("meeting %s: dropped %s", meeting_id, dropped)
    segs = merge_same_speaker(split_by_speaker(raw, turns))
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
            import torch
            from pyannote.audio import Pipeline
            from pyannote.audio.core.task import Problem, Resolution, Specifications
            # torch>=2.6 loads weights_only by default; allowlist exactly the globals
            # pyannote's segmentation-3.0 checkpoint pickles, rather than disabling the check.
            torch.serialization.add_safe_globals(
                [torch.torch_version.TorchVersion, Specifications, Problem, Resolution])
            self.diarization_model = "pyannote/speaker-diarization-3.1"
            self._pipeline = Pipeline.from_pretrained(self.diarization_model, use_auth_token=hf_token)
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
        # handler has exited; the failing traceback (and its CUDA tensors) is released
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
                                  getattr(s, "avg_logprob", None), getattr(s, "no_speech_prob", None),
                                  words=[Word(float(w.start), float(w.end), w.word, float(w.probability))
                                         for w in (s.words or [])]))
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
        # handler has exited; the failing traceback (and its CUDA tensors) is released
        self.oom_fallbacks += 1
        log.warning("CUDA OOM in diarization; unloading ASR and retrying once")
        import gc, torch
        self._batched = None
        self._whisper = None
        gc.collect(); torch.cuda.empty_cache()
        try:
            result = self._diarize(wav)
        finally:
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
