"""Read-side helpers for public transcript surfaces.

Rows come from the tables in migration 035. Nothing here writes. Speaker
names are joined in from transcript_speakers; the search vector never
includes them (spec Section 1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from docket.db import db_cursor

PUBLIC_STATUSES = ("uploaded", "speakers_resolved", "events_extracted", "compared")
SPEAKER_CONFIDENCE_FLOOR = 0.6


@dataclass(frozen=True)
class Transcript:
    id: int
    meeting_id: int
    status: str
    version: int
    asr_model: str | None
    diarization_model: str | None
    audio_duration_s: float | None
    word_count: int | None
    uploaded_at: datetime | None


@dataclass
class Turn:
    anchor: str
    start_s: float
    end_s: float
    speaker_label: str
    speaker_member_id: int | None
    cluster_label: str | None
    texts: list[str] = field(default_factory=list)
    agenda_item_id: int | None = None
    is_silence: bool = False

    @property
    def text(self) -> str:
        return " ".join(self.texts)


def get_public_transcript(meeting_id: int) -> Transcript | None:
    with db_cursor() as cur:
        cur.execute(
            """SELECT id, meeting_id, status, version, asr_model, diarization_model,
                      audio_duration_s, word_count, uploaded_at
                 FROM transcripts
                WHERE meeting_id = %s AND status = ANY(%s)""",
            [meeting_id, list(PUBLIC_STATUSES)],
        )
        row = cur.fetchone()
        return Transcript(**row) if row else None


def list_segments(transcript_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            """SELECT s.seq, s.start_s, s.end_s, s.text, s.cluster_label, s.is_silence,
                      s.agenda_item_id,
                      COALESCE(cm.name, sp.display_name) AS speaker_name,
                      sp.confidence AS speaker_confidence,
                      sp.council_member_id AS speaker_member_id
                 FROM transcript_segments s
                 LEFT JOIN transcript_speakers sp ON sp.id = s.speaker_id
                 LEFT JOIN council_members cm ON cm.id = sp.council_member_id
                WHERE s.transcript_id = %s
                ORDER BY s.seq""",
            [transcript_id],
        )
        return [dict(r) for r in cur.fetchall()]


def speaker_ordinals(transcript_id: int) -> dict[str, int]:
    """cluster_label -> 1-based ordinal by first appearance over the whole meeting.

    The transcript page and the item excerpt both number unresolved speakers
    from this map, so "Speaker 3" means the same voice on every surface.
    """
    with db_cursor() as cur:
        cur.execute(
            """SELECT cluster_label, MIN(seq) AS first_seq
                 FROM transcript_segments
                WHERE transcript_id = %s AND is_silence = FALSE AND cluster_label IS NOT NULL
                GROUP BY cluster_label
                ORDER BY first_seq""",
            [transcript_id],
        )
        return {r["cluster_label"]: i + 1 for i, r in enumerate(cur.fetchall())}


def _label(seg: dict, ordinals: dict[str, int], floor: float) -> tuple[str, int | None]:
    """Resolved name when confident (or manual), else "Speaker N".

    N is the cluster's ordinal by first appearance among ALL clusters, resolved
    or not, so the number is stable when a correction later resolves a cluster.
    A cluster not yet in `ordinals` is appended with the next number.
    """
    cl = seg.get("cluster_label")
    if cl is not None and cl not in ordinals:
        ordinals[cl] = len(ordinals) + 1
    name, conf = seg.get("speaker_name"), seg.get("speaker_confidence")
    if name and (conf is None or conf >= floor):
        return name, seg.get("speaker_member_id")
    if cl is None:
        return "Unknown speaker", None
    return f"Speaker {ordinals[cl]}", None


def group_turns(segments: list[dict], confidence_floor: float = SPEAKER_CONFIDENCE_FLOOR,
                ordinals: dict[str, int] | None = None) -> list[Turn]:
    turns: list[Turn] = []
    ordinals = dict(ordinals) if ordinals else {}
    for seg in segments:
        if seg.get("is_silence"):
            turns.append(Turn(f"t-{seg['seq']}", seg["start_s"], seg["end_s"], "", None, None,
                              [], seg.get("agenda_item_id"), True))
            continue
        label, member_id = _label(seg, ordinals, confidence_floor)
        last = turns[-1] if turns else None
        if (last is not None and not last.is_silence and last.cluster_label is not None
                and last.cluster_label == seg.get("cluster_label")
                and last.agenda_item_id == seg.get("agenda_item_id")):
            # A change of agenda item starts a new turn so item_anchor_map can
            # point at the exact turn where the item begins.
            last.texts.append(seg["text"])
            last.end_s = seg["end_s"]
            continue
        turns.append(Turn(f"t-{seg['seq']}", seg["start_s"], seg["end_s"], label, member_id,
                          seg.get("cluster_label"), [seg["text"]], seg.get("agenda_item_id")))
    return turns


def item_anchor_map(turns: list[Turn]) -> dict[int, str]:
    out: dict[int, str] = {}
    for t in turns:
        if t.is_silence:
            continue  # silence turns render no item marker
        if t.agenda_item_id is not None and t.agenda_item_id not in out:
            out[t.agenda_item_id] = t.anchor
    return out
