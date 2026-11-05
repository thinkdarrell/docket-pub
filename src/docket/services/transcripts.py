"""Read-side helpers for public transcript surfaces.

Rows come from the tables in migration 035 and, for an item's snapped
bounds, the search cards of migration 041. Nothing here writes. Speaker
names are joined in from transcript_speakers; the search vector never
includes them (spec Section 1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re as _re

from markupsafe import Markup, escape

from docket.ai.transcripts.shared import SPEAKER_CONFIDENCE_FLOOR, speaker_ordinals
from docket.config import TRANSCRIPT_BACKFILL_SINCE, TRANSCRIPT_MIN_WORDS
from docket.db import db_cursor
from docket.services.search_query import SearchQuery, coverage_sql, or_tsquery_sql

# SPEAKER_CONFIDENCE_FLOOR and speaker_ordinals are owned by
# docket.ai.transcripts.shared, which the transcript stages import directly.
# They stay importable from this module: docket.services.speaker_correction
# and the routes read them from here.

# A transcript is public once uploaded, whatever the producer or a worker
# stage does to its status afterwards (a re-claim for re-transcription, a
# worker-stage failure, a hold), except low_speech, which both writers use
# to mean there is no usable transcript. uploaded_at is set only by the
# producer's upload() in the transaction that publishes the segments, and a
# producer failure on a never-uploaded row leaves it NULL. The one row this
# predicate hides by status alone, a worker low_speech row with uploaded_at
# set, would become public when the producer re-claims it to 'claimed', so
# claim_meeting() in transcriber/transcriber/db.py clears its uploaded_at
# for the run and restore_row() or upload() sets it again (decision 0050).
_PUBLIC_PREDICATE = "({a}.uploaded_at IS NOT NULL AND {a}.status <> 'low_speech')"


def public_predicate(alias: str) -> str:
    return _PUBLIC_PREDICATE.format(a=alias)


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
            f"""SELECT t.id, t.meeting_id, t.status, t.version, t.asr_model, t.diarization_model,
                      t.audio_duration_s, t.word_count, t.uploaded_at
                 FROM transcripts t
                WHERE t.meeting_id = %s AND {public_predicate('t')}""",
            [meeting_id],
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


# One row per agenda item whose meeting has a public transcript: the
# transcript, the meeting, the city, and the snapped bounds of the item's
# current card when it has one with bounds, otherwise two nulls. A card is
# current when it was written from the upload that is on the site now
# (`source_uploaded_at` equals the transcript row's `uploaded_at`); the
# bounds of any other card point into segments that no longer exist.
# `source_uploaded_at` is selected so that the statement, used as a CTE named
# `c`, is the `c` SNAPPED_OWNER_SQL reads.
_ITEM_RANGES_SQL = f"""
    SELECT ai.id AS item_id, t.id AS transcript_id, t.meeting_id, mu.slug AS municipality_slug,
           t.uploaded_at AS source_uploaded_at, card.start_seq, card.end_seq
      FROM agenda_items ai
      JOIN meetings m ON m.id = ai.meeting_id
      JOIN municipalities mu ON mu.id = m.municipality_id
      JOIN transcripts t ON t.meeting_id = ai.meeting_id AND {public_predicate('t')}
      LEFT JOIN agenda_item_search_cards card
             ON card.agenda_item_id = ai.id AND card.transcript_id = t.id
            AND card.source_uploaded_at = t.uploaded_at AND card.start_seq IS NOT NULL
     WHERE ai.id = ANY(%(item_ids)s)"""

# Which segments of a snapped range belong to the item. `c` is the item's
# current card (or a row of _ITEM_RANGES_SQL with bounds) and `s` a segment of
# its transcript. Items voted as a block are each given the block's ending, so
# ranges overlap; a segment inside the range of an item opened later belongs
# to that item. Of a block each item owns its own reading and the last owns
# the shared ending, and an item always owns its own start segment. This is
# the one statement of the rule: every reader of a snapped range uses it.
SNAPPED_OWNER_SQL = """s.seq BETWEEN c.start_seq AND c.end_seq
               AND NOT EXISTS (SELECT 1 FROM agenda_item_search_cards c2
                                WHERE c2.transcript_id = c.transcript_id
                                  AND c2.source_uploaded_at = c.source_uploaded_at
                                  AND c2.start_seq > c.start_seq
                                  AND s.seq BETWEEN c2.start_seq AND c2.end_seq)"""

_RANGE_KEYS = ("transcript_id", "meeting_id", "municipality_slug", "start_seq", "end_seq")


def item_ranges(item_ids: list[int]) -> dict[int, dict]:
    """Where each item's discussion is, for the items whose meeting has a public transcript.

    Each value has `transcript_id`, `meeting_id`, `municipality_slug`, and
    `start_seq` and `end_seq`: the snapped bounds of the item's current card,
    or two Nones when it has no current card with bounds, in which case the
    item's range is the segments filed under it (the placement).
    """
    if not item_ids:
        return {}
    with db_cursor() as cur:
        cur.execute(_ITEM_RANGES_SQL, {"item_ids": list(item_ids)})
        return {r["item_id"]: {k: r[k] for k in _RANGE_KEYS} for r in cur.fetchall()}


_EXCERPT_SELECT = """SELECT s.seq, s.start_s, s.end_s, s.text, s.cluster_label, s.is_silence,
                      s.agenda_item_id,
                      COALESCE(cm.name, sp.display_name) AS speaker_name,
                      sp.confidence AS speaker_confidence,
                      sp.council_member_id AS speaker_member_id"""


def excerpt_for_item(item_id: int, max_turns: int = 4) -> dict | None:
    """First few transcript turns of this agenda item's discussion, or None.

    The discussion is the segments the item owns inside its snapped bounds
    when a current search card has them (`snapped` is True), and otherwise
    the segments filed under the item (`snapped` is False).
    """
    rng = item_ranges([item_id]).get(item_id)
    if rng is None:
        return None
    segs: list[dict] = []
    with db_cursor() as cur:
        if rng["start_seq"] is not None:
            cur.execute(
                f"""WITH c AS ({_ITEM_RANGES_SQL})
                {_EXCERPT_SELECT}
                 FROM c
                 JOIN transcript_segments s ON s.transcript_id = c.transcript_id
                 LEFT JOIN transcript_speakers sp ON sp.id = s.speaker_id
                 LEFT JOIN council_members cm ON cm.id = sp.council_member_id
                WHERE s.is_silence = FALSE AND c.start_seq IS NOT NULL
                  AND {SNAPPED_OWNER_SQL}
                ORDER BY s.seq""",
                {"item_ids": [item_id]},
            )
            segs = [dict(r) for r in cur.fetchall()]
            # group_turns starts a new turn where agenda_item_id changes, and
            # inside snapped bounds a neighbouring segment may be filed under
            # another item. Every segment here is this item's.
            for seg in segs:
                seg["agenda_item_id"] = item_id
        snapped = bool(segs)
        if not snapped:
            cur.execute(
                f"""{_EXCERPT_SELECT}
                 FROM transcript_segments s
                 LEFT JOIN transcript_speakers sp ON sp.id = s.speaker_id
                 LEFT JOIN council_members cm ON cm.id = sp.council_member_id
                WHERE s.transcript_id = %s AND s.agenda_item_id = %s AND s.is_silence = FALSE
                ORDER BY s.seq""",
                [rng["transcript_id"], item_id],
            )
            segs = [dict(r) for r in cur.fetchall()]
    if not segs:
        return None
    turns = group_turns(segs, ordinals=speaker_ordinals(rng["transcript_id"]))
    return {
        "meeting_id": rng["meeting_id"],
        "transcript_id": rng["transcript_id"],
        "turns": turns[:max_turns],
        "anchor": turns[0].anchor,
        "truncated": len(turns) > max_turns,
        "snapped": snapped,
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
_HEADLINE_OPTIONS = "'MaxWords=40, MinWords=20, StartSel=[[HL]], StopSel=[[/HL]]'"


def _speaker_predicate(placeholder: str) -> str:
    """The `speaker:` filter. `placeholder` is the typed name's psycopg2 placeholder, which occurs twice.

    Fuzzy trigram match (typos) OR punctuation-insensitive substring
    ("oquinn" must find "Darrell O'Quinn"). %% is psycopg2's literal %.
    """
    return (f"({_SPEAKER_NAME} %% {placeholder}"
            f" OR regexp_replace(lower({_SPEAKER_NAME}), '[^a-z0-9]', '', 'g')"
            f" LIKE '%%' || regexp_replace(lower({placeholder}), '[^a-z0-9]', '', 'g') || '%%')")


def search_transcripts(q: str, *, municipality_slug: str | None, speaker: str | None,
                       limit: int = 10, offset: int = 0) -> list[dict]:
    where = ["mu.active = TRUE", "m.is_hidden = FALSE", public_predicate("t"), "s.is_silence = FALSE"]
    params: list = []
    if municipality_slug:
        where.append("mu.slug = %s"); params.append(municipality_slug)
    if speaker:
        where.append(_speaker_predicate("%s"))
        params.extend([speaker, speaker])
    if q:
        where.append("s.search_vector @@ websearch_to_tsquery('english', %s)"); params.append(q)
        select_rank = "ts_rank(s.search_vector, websearch_to_tsquery('english', %s)) AS rank,"
        # Postgres' headline parser silently drops <tags> and keeps entities,
        # so feed it entity-escaped text; _safe_headline then must not re-escape.
        pre_escaped = True
        headline = (f"ts_headline('english', {_PRE_ESCAPED_TEXT}, websearch_to_tsquery('english', %s), "
                    f"{_HEADLINE_OPTIONS}) AS headline")
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


def moments_for_items(item_ids: list[int], sq: SearchQuery, *, speaker: str | None = None,
                      per_item: int = 3) -> dict[int, list[dict]]:
    """The spoken moments to show under each search result: item id -> its best-matching segments.

    A moment is one non-silence transcript segment inside the item's range
    (the segments the item owns inside its snapped bounds when a current card
    has them, otherwise the segments filed under it) that matches at least
    one unit of `sq`. Per item the best `per_item` are kept: a segment
    matching more of the query's word and phrase units leads, then ts_rank,
    then the earlier segment. Each item's list is returned in `seq` order,
    and an item with no matching segment is absent. `speaker`, when given, is
    the `speaker:` filter of `search_transcripts`.

    The headline is the transcript's own words with the matches marked. A
    speaker is named only when the site is confident of the name; a cluster
    label never reaches a page.
    """
    if not item_ids or not sq.units:
        return {}
    or_sql, params = or_tsquery_sql(sq.units, "u")
    cov_sql, cov_params = coverage_sql(sq.units, "s.search_vector", "u")
    params.update(cov_params)
    params.update(item_ids=list(item_ids), per_item=per_item)
    speaker_sql = ""
    if speaker:
        speaker_sql = "AND " + _speaker_predicate("%(speaker)s")
        params["speaker"] = speaker
    with db_cursor() as cur:
        # ts_headline is the costly call, so it runs in the outer select, on
        # the kept rows only. The outer alias is `s` because _PRE_ESCAPED_TEXT
        # reads `s.text`.
        cur.execute(
            f"""WITH c AS ({_ITEM_RANGES_SQL}),
            matched AS (
                SELECT c.item_id, c.meeting_id, c.municipality_slug, s.seq, s.start_s, s.text,
                       {_SPEAKER_NAME} AS speaker_name, sp.confidence AS speaker_confidence,
                       row_number() OVER (
                           PARTITION BY c.item_id
                           ORDER BY {cov_sql} DESC, ts_rank(s.search_vector, {or_sql}) DESC, s.seq) AS place
                  FROM c
                  JOIN transcript_segments s ON s.transcript_id = c.transcript_id
                  LEFT JOIN transcript_speakers sp ON sp.id = s.speaker_id
                  LEFT JOIN council_members cm ON cm.id = sp.council_member_id
                 WHERE s.is_silence = FALSE
                   AND s.search_vector @@ {or_sql}
                   AND ((c.start_seq IS NOT NULL
                         AND {SNAPPED_OWNER_SQL})
                        OR (c.start_seq IS NULL AND s.agenda_item_id = c.item_id))
                   {speaker_sql}
            )
            SELECT s.item_id, s.meeting_id, s.municipality_slug, s.seq, s.start_s,
                   s.speaker_name, s.speaker_confidence,
                   ts_headline('english', {_PRE_ESCAPED_TEXT}, {or_sql}, {_HEADLINE_OPTIONS}) AS headline
              FROM matched s
             WHERE s.place <= %(per_item)s
             ORDER BY s.item_id, s.seq""",
            params,
        )
        rows = [dict(r) for r in cur.fetchall()]
    out: dict[int, list[dict]] = {}
    for r in rows:
        name, confidence = r["speaker_name"], r["speaker_confidence"]
        confident = bool(name) and (confidence is None or confidence >= SPEAKER_CONFIDENCE_FLOOR)
        out.setdefault(r["item_id"], []).append({
            "item_id": r["item_id"],
            "meeting_id": r["meeting_id"],
            "seq": r["seq"],
            "start_s": r["start_s"],
            "speaker_label": name if confident else None,
            "headline": _safe_headline(r["headline"] or "", pre_escaped=True),
            "anchor_url": f"/al/{r['municipality_slug']}/meetings/{r['meeting_id']}/transcript/#t-{r['seq']}",
        })
    return out


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
                      t.status, t.last_error, t.stage_attempts, t.word_count
                 FROM meetings m
                 LEFT JOIN transcripts t ON t.meeting_id = m.id
                WHERE m.municipality_id = %s
                  AND m.is_hidden = FALSE
                  AND m.video_url IS NOT NULL
                  AND (m.external_id ~ '^[0-9]+$' OR m.external_id LIKE 'yt-%%')
                  AND (
                        t.status IN ('failed', 'needs_review')
                     OR (t.status = 'low_speech'
                         AND (COALESCE(t.audio_duration_s, 0) >= %s
                              OR (t.word_count IS NOT NULL AND t.word_count < %s)))
                     OR (t.id IS NULL AND m.meeting_date < CURRENT_DATE - 14
                         AND m.meeting_date >= %s)
                  )
                ORDER BY m.meeting_date DESC
                LIMIT %s""",
            [municipality_id, SHORT_MEETING_S, TRANSCRIPT_MIN_WORDS, TRANSCRIPT_BACKFILL_SINCE, limit],
        )
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        if r["status"] == "low_speech" and r["word_count"] is not None and r["word_count"] < TRANSCRIPT_MIN_WORDS:
            r["friendly_label"] = f"Too short to analyze ({r['word_count']} words)"
        else:
            r["friendly_label"] = TRANSCRIPT_DEBT_LABELS.get(r["status"], "Transcript problem")
    return rows


def speaker_index(transcript_id: int) -> list[dict]:
    """Resolved speakers for the 'Who spoke' list, merged by person across clusters."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT COALESCE(cm.name, sp.display_name) AS name, sp.council_member_id AS member_id,
                      array_agg(DISTINCT sp.cluster_label) AS cluster_labels,
                      count(*) AS turns, COALESCE(sum(s.end_s - s.start_s), 0) AS seconds
                 FROM transcript_segments s
                 JOIN transcript_speakers sp ON sp.id = s.speaker_id
                 LEFT JOIN council_members cm ON cm.id = sp.council_member_id
                WHERE s.transcript_id = %s AND s.is_silence = FALSE
                  AND COALESCE(cm.name, sp.display_name) IS NOT NULL
                  AND (sp.is_manual OR sp.confidence >= %s)
                GROUP BY 1, 2
                ORDER BY seconds DESC, name""",
            [transcript_id, SPEAKER_CONFIDENCE_FLOOR],
        )
        return [dict(r) for r in cur.fetchall()]
