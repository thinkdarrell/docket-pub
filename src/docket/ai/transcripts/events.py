# src/docket/ai/transcripts/events.py
"""Event extraction: one Sonnet 5.5 call per side, rows into meeting_events.

Transcript side always runs. Minutes side runs when the meeting has a
minutes URL and the PDF downloads; otherwise the transcript stops at
events_extracted with compare_skipped_reason set and is re-claimed when
minutes appear (pipeline.CLAIM_SQL). Confident item_opened events re-assign
segments with assignment_method = 'event' (spec: index point drift).
"""
from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from docket.ai.exceptions import TranscriptHeld
from docket.ai.transcripts.guard import find_citation
from docket.ai.transcripts.minutes import MinutesCapture, capture_minutes, load_minutes, page_for_offset
from docket.ai.transcripts.prompts import EVENTS_MINUTES_SYSTEM, EVENTS_PROMPT_VERSION, EVENTS_TRANSCRIPT_SYSTEM
from docket.ai.transcripts.schemas import EVENTS_SCHEMA, EventList, ExtractedEvent
from docket.ai.transcripts.speakers import RosterMember, hms, mentioned_members, roster_for_meeting
from docket.config import AI_TRANSCRIPT_EVENTS_MODEL, TRANSCRIPT_TOKEN_CEILING
from docket.db import db_cursor
from docket.services.transcripts import SPEAKER_CONFIDENCE_FLOOR, speaker_ordinals

log = logging.getLogger(__name__)

MINUTES_MIN_WORDS = 50   # below this the PDF almost certainly has no text layer (the shortest real minutes run to pages)


def load_segments_with_speakers(transcript_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute("""SELECT s.id, s.seq, s.start_s, s.end_s, s.text, s.cluster_label, s.agenda_item_id, s.is_silence,
                              COALESCE(cm.name, sp.display_name) AS speaker_name, sp.confidence AS speaker_confidence
                         FROM transcript_segments s
                         LEFT JOIN transcript_speakers sp ON sp.id = s.speaker_id
                         LEFT JOIN council_members cm ON cm.id = sp.council_member_id
                        WHERE s.transcript_id = %s ORDER BY s.seq""", [transcript_id])
        return [dict(r) for r in cur.fetchall()]


def load_agenda(meeting_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute("""SELECT id, item_number, title, is_consent, external_id, video_timestamp_seconds
                         FROM agenda_items WHERE meeting_id = %s
                        ORDER BY video_timestamp_seconds NULLS LAST, id""", [meeting_id])
        return [dict(r) for r in cur.fetchall()]


def render_agenda(agenda: list[dict]) -> str:
    lines = ["Agenda items (id, number, title):"]
    for a in agenda:
        flag = " [consent]" if a.get("is_consent") else ""
        lines.append(f"  id={a['id']} Item {a.get('item_number') or '?'}{flag}: {a['title']}")
    return "\n".join(lines)


def _label(seg: dict, ordinals: dict[str, int]) -> str:
    name, conf = seg.get("speaker_name"), seg.get("speaker_confidence")
    if name and (conf is None or conf >= SPEAKER_CONFIDENCE_FLOOR):
        return name
    cl = seg.get("cluster_label")
    return f"Speaker {ordinals.get(cl, 0)}" if cl else "Unknown speaker"


def render_transcript(segments: list[dict], agenda: list[dict], ordinals: dict[str, int]) -> str:
    by_id = {a["id"]: a for a in agenda}
    lines, current = [], object()
    for s in segments:
        if s.get("is_silence") or not (s.get("text") or "").strip():
            continue
        if s.get("agenda_item_id") != current and s.get("agenda_item_id") in by_id:
            a = by_id[s["agenda_item_id"]]
            lines.append(f"=== Item {a.get('item_number') or '?'} (agenda_item_id={a['id']}): {a['title']} ===")
        current = s.get("agenda_item_id")
        lines.append(f"[seq={s['seq']} t={hms(s['start_s'])} {_label(s, ordinals)}] {s['text'].strip()}")
    return "\n".join(lines)


def render_minutes(text: str, page_offsets: list[int]) -> str:
    out, offsets = [], list(page_offsets) + [len(text)]
    for i in range(len(page_offsets)):
        out.append(f"[[page {i + 1}]]\n{text[offsets[i]:offsets[i + 1]].rstrip(chr(10))}")
    return "\n".join(out)


def extract_side(*, client, model: str, system: str, user: str) -> EventList:
    tokens = client.count_tokens(model=model, system=system, user=user)
    if tokens > TRANSCRIPT_TOKEN_CEILING:
        raise TranscriptHeld("token_ceiling", f"{tokens} tokens > ceiling {TRANSCRIPT_TOKEN_CEILING}")
    res = client.call(model=model, system=system, user=user, schema=EVENTS_SCHEMA, max_tokens=64000, effort="medium")
    try:
        return EventList.model_validate(res.data)
    except ValidationError as e:
        raise TranscriptHeld("schema_invalid", f"events response failed validation: {e}") from e


def match_actor(text: str | None, roster: list[RosterMember]) -> int | None:
    if not text:
        return None
    hits = mentioned_members(text, roster)
    return hits[0].id if len(hits) == 1 else None


def write_events(meeting_id: int, source: str, events: list[ExtractedEvent], *, segments: list[dict] | None = None,
                 minutes: MinutesCapture | None = None, roster: list[RosterMember], valid_item_ids: set[int]) -> list[dict]:
    by_seq = {s["seq"]: s for s in (segments or [])}
    roster_ids = {m.id for m in roster}
    rows: list[dict] = []
    with db_cursor() as cur:
        cur.execute("DELETE FROM meeting_events WHERE meeting_id = %s AND source = %s", [meeting_id, source])
        for i, ev in enumerate(events):
            refs = [r for r in ev.agenda_item_refs if r in valid_item_ids]
            actor = ev.actor_member_id if ev.actor_member_id in roster_ids else match_actor(ev.actor_text, roster)
            start_s = segment_id = page = char_offset = None
            if source == "transcript":
                seg = by_seq.get(ev.segment_seq) if ev.segment_seq is not None else None
                if seg:
                    start_s, segment_id = seg["start_s"], seg["id"]
            else:
                page = ev.page
                if minutes and ev.quote:
                    cm = find_citation(ev.quote, minutes.text)
                    if cm.kind != "missing":
                        char_offset = cm.start
                        page = page_for_offset(minutes.page_offsets, cm.start)
            cur.execute(
                """INSERT INTO meeting_events (meeting_id, source, seq, event_type, scope, agenda_item_refs, actor_member_id,
                                               actor_text, summary, detail, start_s, page, char_offset, segment_id, prompt_version)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
                   RETURNING id""",
                [meeting_id, source, i, ev.event_type, ev.scope, refs, actor, ev.actor_text, ev.summary,
                 json.dumps({**ev.detail.compact(), **({"quote": ev.quote} if ev.quote else {})}),
                 start_s, page, char_offset, segment_id, EVENTS_PROMPT_VERSION],
            )
            rows.append({"id": cur.fetchone()["id"], "seq": i, "event_type": ev.event_type, "agenda_item_refs": refs,
                         "start_s": start_s, "segment_id": segment_id, "segment_seq": ev.segment_seq, "page": page,
                         "char_offset": char_offset})
    return rows


def reassign_segments_from_events(transcript_id: int, transcript_rows: list[dict]) -> int:
    """Stamp segments between item_opened boundaries. Every item_opened (any ref
    count) and the first adjourn end the previous range; only ranges opened by
    a single-ref item_opened are written."""
    bounds = sorted([r for r in transcript_rows if r["event_type"] == "item_opened" and r.get("segment_seq") is not None],
                    key=lambda r: r["segment_seq"])
    adjourns = [r["segment_seq"] for r in transcript_rows if r["event_type"] == "adjourn" and r.get("segment_seq") is not None]
    adjourn_seq = min(adjourns) if adjourns else None
    n = 0
    with db_cursor() as cur:
        for i, r in enumerate(bounds):
            if len(r["agenda_item_refs"]) != 1:
                continue
            lo = r["segment_seq"]
            hi = bounds[i + 1]["segment_seq"] if i + 1 < len(bounds) else None
            if adjourn_seq is not None and adjourn_seq > lo and (hi is None or adjourn_seq < hi):
                hi = adjourn_seq
            cur.execute(
                """UPDATE transcript_segments SET agenda_item_id = %s, assignment_method = 'event'
                    WHERE transcript_id = %s AND is_silence = FALSE AND seq >= %s AND (%s::int IS NULL OR seq < %s)
                      AND assignment_method IS DISTINCT FROM 'manual'""",
                [r["agenda_item_refs"][0], transcript_id, lo, hi, hi],
            )
            n += cur.rowcount
    return n


def _meeting(meeting_id: int) -> dict:
    with db_cursor() as cur:
        cur.execute("SELECT id, title, meeting_date::text, minutes_url FROM meetings WHERE id = %s", [meeting_id])
        return dict(cur.fetchone())


def extract_minutes_side(meeting_id: int, *, client) -> str:
    meeting = _meeting(meeting_id)
    if not meeting.get("minutes_url"):
        return "no_minutes"
    minutes = capture_minutes(meeting_id, meeting["minutes_url"]) or load_minutes(meeting_id)
    if minutes is None:
        return "minutes_unavailable"
    words = len(minutes.text.split())
    if words < MINUTES_MIN_WORDS:
        # A scanned PDF has no text layer: pdfplumber returns nothing and a comparison against an empty
        # minutes side would call every transcript event an omission. A person has to decide (OCR, or
        # a different URL), so this is a hold, not a skip.
        raise TranscriptHeld("minutes_no_text", f"minutes PDF yielded {words} words of text (floor {MINUTES_MIN_WORDS}); "
                                                "scanned image without a text layer?")
    agenda = load_agenda(meeting_id)
    roster = roster_for_meeting(meeting_id)
    user = (f"Meeting: {meeting['title']} on {meeting['meeting_date']}\n\n{render_agenda(agenda)}\n\n"
            f"Minutes text:\n{render_minutes(minutes.text, minutes.page_offsets)}")
    parsed = extract_side(client=client, model=AI_TRANSCRIPT_EVENTS_MODEL, system=EVENTS_MINUTES_SYSTEM, user=user)
    rows = write_events(meeting_id, "minutes", parsed.events, minutes=minutes, roster=roster,
                        valid_item_ids={a["id"] for a in agenda})
    log.info("events: meeting %s minutes side %d events", meeting_id, len(rows))
    return "ok"


def run_events_stage(claim: dict, *, client) -> "StageOutcome":
    from docket.ai.transcripts.pipeline import StageOutcome

    tid, mid = claim["id"], claim["meeting_id"]
    meeting = _meeting(mid)
    segments = load_segments_with_speakers(tid)
    agenda = load_agenda(mid)
    roster = roster_for_meeting(mid)
    user = (f"Meeting: {meeting['title']} on {meeting['meeting_date']}\n\n{render_agenda(agenda)}\n\n"
            f"Transcript:\n{render_transcript(segments, agenda, speaker_ordinals(tid))}")
    parsed = extract_side(client=client, model=AI_TRANSCRIPT_EVENTS_MODEL, system=EVENTS_TRANSCRIPT_SYSTEM, user=user)
    rows = write_events(mid, "transcript", parsed.events, segments=segments, roster=roster,
                        valid_item_ids={a["id"] for a in agenda})
    reassigned = reassign_segments_from_events(tid, rows)
    log.info("events: meeting %s transcript side %d events, %d segments re-assigned", mid, len(rows), reassigned)
    minutes_status = extract_minutes_side(mid, client=client)
    skipped = None if minutes_status == "ok" else minutes_status
    return StageOutcome("events_extracted", skipped_reason=skipped, detail=f"{len(rows)} transcript events; minutes {minutes_status}")
