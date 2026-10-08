"""Read-side helpers for public transcript surfaces.

Rows come from the tables in migration 035. Nothing here writes. Speaker
names are joined in from transcript_speakers; the search vector never
includes them (spec Section 1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re as _re

from markupsafe import Markup, escape

from docket.config import TRANSCRIPT_BACKFILL_SINCE
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
    seqs: list[int] = field(default_factory=list)
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
                              [], [], seg.get("agenda_item_id"), True))
            continue
        label, member_id = _label(seg, ordinals, confidence_floor)
        last = turns[-1] if turns else None
        if (last is not None and not last.is_silence and last.cluster_label is not None
                and last.cluster_label == seg.get("cluster_label")
                and last.agenda_item_id == seg.get("agenda_item_id")):
            # A change of agenda item starts a new turn so item_anchor_map can
            # point at the exact turn where the item begins.
            last.texts.append(seg["text"])
            last.seqs.append(seg["seq"])
            last.end_s = seg["end_s"]
            continue
        turns.append(Turn(f"t-{seg['seq']}", seg["start_s"], seg["end_s"], label, member_id,
                          seg.get("cluster_label"), [seg["text"]], [seg["seq"]], seg.get("agenda_item_id")))
    return turns


def item_anchor_map(turns: list[Turn]) -> dict[int, str]:
    out: dict[int, str] = {}
    for t in turns:
        if t.is_silence:
            continue  # silence turns render no item marker
        if t.agenda_item_id is not None and t.agenda_item_id not in out:
            out[t.agenda_item_id] = t.anchor
    return out


def excerpt_for_item(item_id: int, max_turns: int = 4) -> dict | None:
    """First few transcript turns tagged with this agenda item, or None."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT t.id AS transcript_id, t.meeting_id
                 FROM agenda_items ai
                 JOIN transcripts t ON t.meeting_id = ai.meeting_id
                WHERE ai.id = %s AND t.status = ANY(%s)""",
            [item_id, list(PUBLIC_STATUSES)],
        )
        head = cur.fetchone()
        if head is None:
            return None
        cur.execute(
            """SELECT s.seq, s.start_s, s.end_s, s.text, s.cluster_label, s.is_silence,
                      s.agenda_item_id,
                      COALESCE(cm.name, sp.display_name) AS speaker_name,
                      sp.confidence AS speaker_confidence,
                      sp.council_member_id AS speaker_member_id
                 FROM transcript_segments s
                 LEFT JOIN transcript_speakers sp ON sp.id = s.speaker_id
                 LEFT JOIN council_members cm ON cm.id = sp.council_member_id
                WHERE s.transcript_id = %s AND s.agenda_item_id = %s AND s.is_silence = FALSE
                ORDER BY s.seq""",
            [head["transcript_id"], item_id],
        )
        segs = [dict(r) for r in cur.fetchall()]
    if not segs:
        return None
    turns = group_turns(segs, ordinals=speaker_ordinals(head["transcript_id"]))
    return {
        "meeting_id": head["meeting_id"],
        "transcript_id": head["transcript_id"],
        "turns": turns[:max_turns],
        "anchor": turns[0].anchor,
        "truncated": len(turns) > max_turns,
    }


_SPEAKER_RE = _re.compile(r'\bspeaker:(?:"([^"]+)"|(\S+))', _re.IGNORECASE)


def parse_speaker_token(q: str) -> tuple[str, str | None]:
    m = _SPEAKER_RE.search(q)
    if not m:
        return q.strip(), None
    speaker = m.group(1) or m.group(2)
    rest = (q[:m.start()] + q[m.end():]).strip()
    return _re.sub(r"\s{2,}", " ", rest), speaker


_SPEAKER_NAME = "COALESCE(cm.name, sp.display_name)"
_PRE_ESCAPED_TEXT = "replace(replace(replace(s.text, '&', '&amp;'), '<', '&lt;'), '>', '&gt;')"


def search_transcripts(q: str, *, municipality_slug: str | None, speaker: str | None,
                       limit: int = 10, offset: int = 0) -> list[dict]:
    where = ["mu.active = TRUE", "m.is_hidden = FALSE", "t.status = ANY(%s)", "s.is_silence = FALSE"]
    params: list = [list(PUBLIC_STATUSES)]
    if municipality_slug:
        where.append("mu.slug = %s"); params.append(municipality_slug)
    if speaker:
        # Fuzzy trigram match (typos) OR punctuation-insensitive substring
        # ("oquinn" must find "Darrell O'Quinn"). %% is psycopg2's literal %.
        where.append(
            f"({_SPEAKER_NAME} %% %s"
            f" OR regexp_replace(lower({_SPEAKER_NAME}), '[^a-z0-9]', '', 'g')"
            f" LIKE '%%' || regexp_replace(lower(%s), '[^a-z0-9]', '', 'g') || '%%')"
        )
        params.extend([speaker, speaker])
    if q:
        where.append("s.search_vector @@ websearch_to_tsquery('english', %s)"); params.append(q)
        select_rank = "ts_rank(s.search_vector, websearch_to_tsquery('english', %s)) AS rank,"
        # Postgres' headline parser silently drops <tags> and keeps entities,
        # so feed it entity-escaped text; _safe_headline then must not re-escape.
        pre_escaped = True
        headline = (f"ts_headline('english', {_PRE_ESCAPED_TEXT}, websearch_to_tsquery('english', %s), "
                    "'MaxWords=40, MinWords=20, StartSel=[[HL]], StopSel=[[/HL]]') AS headline")
        head_params = [q, q]
        order = "ORDER BY rank DESC, m.meeting_date DESC, s.seq"
    else:
        select_rank = "0::float AS rank,"
        pre_escaped = False
        headline = "left(s.text, 240) AS headline"
        head_params = []
        order = "ORDER BY m.meeting_date DESC, s.seq"
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT m.id AS meeting_id, mu.slug AS municipality_slug, m.title AS meeting_title,
                       m.meeting_date, s.seq, s.start_s,
                       {_SPEAKER_NAME} AS speaker_name,
                       {select_rank}
                       {headline}
                  FROM transcript_segments s
                  JOIN transcripts t ON t.id = s.transcript_id
                  JOIN meetings m ON m.id = t.meeting_id
                  JOIN municipalities mu ON mu.id = m.municipality_id
                  LEFT JOIN transcript_speakers sp ON sp.id = s.speaker_id
                  LEFT JOIN council_members cm ON cm.id = sp.council_member_id
                 WHERE {' AND '.join(where)}
                 {order}
                 LIMIT %s OFFSET %s""",
            [*head_params, *params, limit, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["headline"] = _safe_headline(r["headline"] or "", pre_escaped=pre_escaped)
        r["anchor_url"] = f"/al/{r['municipality_slug']}/meetings/{r['meeting_id']}/transcript/#t-{r['seq']}"
    return rows


_HL_OPEN, _HL_CLOSE = "[[HL]]", "[[/HL]]"


def _safe_headline(raw: str, *, pre_escaped: bool = False) -> Markup:
    """Escape transcript text, then turn the ts_headline markers into <mark>.

    ts_headline does not HTML-escape the document, and the no-text-query path
    is a plain left(text, 240). Both go through here, so a transcript with
    '<' or '&' can never inject markup. Returns Markup: the template needs
    no `| safe`.
    """
    escaped = raw if pre_escaped else str(escape(raw))
    return Markup(escaped.replace(_HL_OPEN, "<mark>").replace(_HL_CLOSE, "</mark>"))


TRANSCRIPT_DEBT_LABELS = {
    "failed": "Transcription failed",
    "low_speech": "No usable audio",
    "needs_review": "Transcript held for review",
    None: "Not yet transcribed",
}

# A low_speech result on a recording shorter than this is a short session
# (roll call and adjourn), not a problem to fix. Longer recordings with under
# three minutes of speech are a dead or near-empty stream and stay on the list.
SHORT_MEETING_S = 600.0


def list_transcript_debt(municipality_id: int, limit: int = 50) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            """SELECT m.id AS meeting_id, m.title AS meeting_title, m.meeting_date,
                      t.status, t.last_error, t.stage_attempts
                 FROM meetings m
                 LEFT JOIN transcripts t ON t.meeting_id = m.id
                WHERE m.municipality_id = %s
                  AND m.is_hidden = FALSE
                  AND m.video_url IS NOT NULL
                  AND m.external_id ~ '^[0-9]+$'
                  AND (
                        t.status IN ('failed', 'needs_review')
                     OR (t.status = 'low_speech' AND COALESCE(t.audio_duration_s, 0) >= %s)
                     OR (t.id IS NULL AND m.meeting_date < CURRENT_DATE - 14
                         AND m.meeting_date >= %s)
                  )
                ORDER BY m.meeting_date DESC
                LIMIT %s""",
            [municipality_id, SHORT_MEETING_S, TRANSCRIPT_BACKFILL_SINCE, limit],
        )
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["friendly_label"] = TRANSCRIPT_DEBT_LABELS.get(r["status"], "Transcript problem")
    return rows
