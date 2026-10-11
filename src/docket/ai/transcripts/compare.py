# src/docket/ai/transcripts/compare.py
"""Comparison: aligner candidates -> Opus 5.5 judge; full texts -> Opus 5.5 hunter; rows into minutes_discrepancies.

Vote outcomes are deterministic (spec decision J) and never go to the judge.
Every quoted excerpt is verified by the guard against the same text the
model saw; a quote the guard cannot find keeps the row with
citation_match = 'missing' and half the confidence, so the queue shows it
and a reviewer must attach a citation before it can be approved.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from difflib import SequenceMatcher

from pydantic import ValidationError

from docket.ai.exceptions import TranscriptHeld
from docket.ai.transcripts.aligner import Candidate, Event, align, event_from_row
from docket.ai.transcripts.events import (extract_minutes_side, load_agenda, load_segments_with_speakers, render_minutes,
                                           render_transcript)
from docket.ai.transcripts.guard import find_citation, window
from docket.ai.transcripts.guard import normalize as _norm
from docket.ai.transcripts.minutes import MinutesCapture, load_minutes, page_for_offset
from docket.ai.transcripts.prompts import COMPARE_PROMPT_VERSION, HUNTER_SYSTEM, JUDGE_SYSTEM
from docket.ai.transcripts.schemas import HUNTER_SCHEMA, JUDGE_SCHEMA, HunterResult, JudgeResult
from docket.ai.transcripts.speakers import hms
from docket.config import AI_TRANSCRIPT_COMPARE_MODEL, TRANSCRIPT_CANDIDATE_CAP, TRANSCRIPT_TOKEN_CEILING
from docket.db import db_cursor
from docket.services.transcripts import SPEAKER_CONFIDENCE_FLOOR, speaker_ordinals

log = logging.getLogger(__name__)

# --- loaders ----------------------------------------------------------------

def load_events(meeting_id: int, source: str) -> list[Event]:
    with db_cursor() as cur:
        cur.execute("""SELECT id, source, seq, event_type, scope, agenda_item_refs, actor_member_id, actor_text, summary, detail,
                              start_s, page, char_offset FROM meeting_events
                        WHERE meeting_id = %s AND source = %s ORDER BY seq""", [meeting_id, source])
        return [event_from_row(dict(r)) for r in cur.fetchall()]


def load_votes(meeting_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute("""SELECT v.id, v.result, v.yeas, v.nays, v.abstentions, v.raw_text,
                              COALESCE(array_agg(vai.agenda_item_id) FILTER (WHERE vai.id IS NOT NULL), '{}') AS item_ids
                         FROM votes v LEFT JOIN vote_agenda_items vai ON vai.vote_id = v.id AND vai.is_active
                        WHERE v.meeting_id = %s AND v.source = 'minutes_text'
                        GROUP BY v.id ORDER BY v.id""", [meeting_id])
        return [dict(r) for r in cur.fetchall()]


def load_consent_items(meeting_id: int) -> set[int]:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM agenda_items WHERE meeting_id = %s AND is_consent", [meeting_id])
        return {r["id"] for r in cur.fetchall()}


# --- text helpers -----------------------------------------------------------

@dataclass
class TranscriptText:
    joined: str
    bounds: list[tuple[int, int, dict]]


def transcript_text(segments: list[dict]) -> TranscriptText:
    parts, bounds, pos = [], [], 0
    for s in segments:
        if s.get("is_silence") or not (s.get("text") or "").strip():
            continue
        t = s["text"].strip()
        bounds.append((pos, pos + len(t), s))
        parts.append(t)
        pos += len(t) + 1
    return TranscriptText(" ".join(parts), bounds)


def segment_at(tt: TranscriptText, offset: int) -> dict | None:
    for lo, hi, seg in tt.bounds:
        if lo <= offset <= hi:
            return seg
    return None


def _label(seg: dict, ordinals: dict[str, int]) -> str:
    name, conf = seg.get("speaker_name"), seg.get("speaker_confidence")
    if name and (conf is None or conf >= SPEAKER_CONFIDENCE_FLOOR):
        return name
    return f"Speaker {ordinals.get(seg.get('cluster_label'), 0)}" if seg.get("cluster_label") else "Unknown speaker"


def transcript_window(segments: list[dict], start_s: float, radius_s: float = 45.0, ordinals: dict | None = None) -> str:
    ords = ordinals if ordinals is not None else {}
    if not ords:
        seen: dict[str, int] = {}
        for s in segments:
            cl = s.get("cluster_label")
            if cl and cl not in seen and not s.get("is_silence"):
                seen[cl] = len(seen) + 1
        ords = seen
    lines = [f"[seq={s['seq']} t={hms(s['start_s'])} {_label(s, ords)}] {s['text'].strip()}" for s in segments
             if not s.get("is_silence") and (s.get("text") or "").strip() and abs(s["start_s"] - start_s) <= radius_s]
    return "\n".join(lines)


def minutes_window(minutes: MinutesCapture, char_offset: int, radius: int = 600) -> str:
    return window(minutes.text, char_offset, char_offset, radius)


def render_timeline(events: list[Event]) -> str:
    return "\n".join(f"#{e.id} seq={e.seq} {e.event_type} items={sorted(e.item_refs)} "
                     f"{'t=' + hms(e.start_s) if e.start_s is not None else ('page ' + str(e.page) if e.page else '')}: {e.summary}"
                     for e in events)


def _event_line(e: Event | None, side: str) -> str:
    if e is None:
        return f"{side} event: none"
    where = f"seq {e.seq}, t={hms(e.start_s)}" if e.start_s is not None else f"page {e.page}"
    return f"{side} event #{e.id} ({where}): {e.event_type} — {e.summary}; detail {e.detail}"


def render_judge_user(candidates: list[Candidate], t_events, m_events, segments, minutes) -> str:
    out = ["Candidates:"]
    for c in candidates:
        out.append(f"\n### Candidate {c.candidate_id} — {c.kind} ({c.category}) items {sorted(c.item_refs)}")
        out.append(c.note)
        out.append(_event_line(c.transcript_event, "Transcript"))
        out.append(_event_line(c.minutes_event, "Minutes"))
        if c.transcript_event and c.transcript_event.start_s is not None:
            out.append("Transcript window:\n" + transcript_window(segments, c.transcript_event.start_s))
        if c.minutes_event and minutes is not None and c.minutes_event.char_offset is not None:
            page = page_for_offset(minutes.page_offsets, c.minutes_event.char_offset)
            out.append(f"Minutes window (page {page}):\n" + minutes_window(minutes, c.minutes_event.char_offset))
    out += ["\nTranscript timeline:", render_timeline(t_events), "\nMinutes timeline:", render_timeline(m_events)]
    return "\n".join(out)


def render_hunter_user(candidates, t_events, m_events, transcript_rendered: str, minutes_rendered: str) -> str:
    known = "\n".join(f"- {c.kind} ({c.category}) items {sorted(c.item_refs)}: {c.note}" for c in candidates) or "- none"
    return (f"Candidates the aligner already found (do not repeat):\n{known}\n\nTranscript timeline:\n{render_timeline(t_events)}\n\n"
            f"Minutes timeline:\n{render_timeline(m_events)}\n\nFull transcript:\n{transcript_rendered}\n\nFull minutes:\n{minutes_rendered}")


# --- citations ---------------------------------------------------------------

def cite(quote: str | None, *, side: str, tt: TranscriptText | None, minutes: MinutesCapture | None):
    """-> (kind, excerpt, start_s, page). kind is 'missing' when there is no quote or no match."""
    if not quote or not quote.strip():
        return "missing", None, None, None
    if side == "transcript":
        if tt is None:
            return "missing", quote, None, None
        cm = find_citation(quote, tt.joined)
        if cm.kind == "missing":
            return "missing", quote, None, None
        seg = segment_at(tt, cm.start)
        return cm.kind, tt.joined[cm.start:cm.end], (seg["start_s"] if seg else None), None
    if minutes is None:
        return "missing", quote, None, None
    cm = find_citation(quote, minutes.text)
    if cm.kind == "missing":
        return "missing", quote, None, None
    return cm.kind, minutes.text[cm.start:cm.end], None, page_for_offset(minutes.page_offsets, cm.start)


def citation_match_for(kinds: list[str]) -> str:
    if not kinds or "missing" in kinds:
        return "missing"
    return "fuzzy" if "fuzzy" in kinds else "exact"


def nearest_event(events: list[Event], *, start_s: float | None = None, char_offset: int | None = None,
                  item_refs: frozenset = frozenset()) -> Event | None:
    def dist(e: Event) -> float:
        if start_s is not None and e.start_s is not None:
            return abs(e.start_s - start_s)
        if char_offset is not None and e.char_offset is not None:
            return abs(e.char_offset - char_offset)
        return float("inf")
    pool = [e for e in events if item_refs and e.item_refs & item_refs] or events
    pool = [e for e in pool if dist(e) != float("inf")]
    return min(pool, key=dist) if pool else None


# --- row assembly -----------------------------------------------------------

def build_rows(meeting_id: int, candidates: list[Candidate], verdicts, hunted, *, tt: TranscriptText,
               minutes: MinutesCapture | None, t_events: list[Event], m_events: list[Event],
               valid_item_ids: set[int] | None = None, item_numbers: dict[int, str] | None = None) -> list[dict]:
    by_id = {c.candidate_id: c for c in candidates}
    numbers = item_numbers or {}
    rows: list[dict] = []

    def base(cat, sev, title, desc, t_ev, m_ev, refs, origin):
        return {"meeting_id": meeting_id, "agenda_item_id": min(refs) if refs else None, "category": cat, "severity": sev,
                "title": title, "description": desc, "transcript_event_id": t_ev.id if t_ev else None,
                "minutes_event_id": m_ev.id if m_ev else None, "origin": origin, "prompt_version": COMPARE_PROMPT_VERSION,
                "transcript_excerpt": None, "transcript_start_s": t_ev.start_s if t_ev else None, "minutes_excerpt": None,
                "minutes_page": m_ev.page if m_ev else None, "citation_match": "missing", "confidence": None,
                "review_state": "proposed", "reject_reason": None}

    # Deterministic vote outcomes (spec J): no model involved. Both kinds of candidate (unpaired tally check and
    # paired-event mismatch) carry category == "vote_outcome".
    for c in candidates:
        if c.category != "vote_outcome":
            continue
        v = c.vote_row or {}
        label = ", ".join(str(numbers.get(i) or i) for i in sorted(c.item_refs))
        row = base("vote_outcome", "material", f"Vote outcome differs from the minutes for item {label}",
                   c.note, c.transcript_event, c.minutes_event, c.item_refs, "aligner")
        t_quote = c.transcript_event.detail.get("quote") if c.transcript_event else None
        kind, exc, start_s, _ = cite(t_quote, side="transcript", tt=tt, minutes=None)
        kinds = [kind]
        row.update(transcript_excerpt=exc, transcript_start_s=start_s if start_s is not None else row["transcript_start_s"])
        if c.minutes_event is not None:
            mk, mexc, _, page = cite(c.minutes_event.detail.get("quote"), side="minutes", tt=None, minutes=minutes)
            kinds.append(mk)
            row.update(minutes_excerpt=mexc, minutes_page=page if page is not None else row["minutes_page"])
        else:
            raw = v.get("raw_text")
            kinds.append("exact" if raw else "missing")
            row.update(minutes_excerpt=(raw or "")[-300:] or None, minutes_page=None)
        row.update(citation_match=citation_match_for(kinds), confidence=0.9)
        rows.append(row)

    for v in verdicts:
        c = by_id.get(v.candidate_id)
        if c is None:
            continue
        if not v.is_real:
            row = base(c.category, "minor", c.note[:200], v.dismiss_reason or "dismissed by model", c.transcript_event,
                       c.minutes_event, c.item_refs, "aligner")
            row.update(review_state="dismissed_by_model", reject_reason=v.dismiss_reason, confidence=v.confidence)
            rows.append(row)
            continue
        row = base(v.category or c.category, v.severity or "minor", v.title or c.note[:200], v.description or c.note,
                   c.transcript_event, c.minutes_event, c.item_refs, "aligner")
        kinds = []
        if c.transcript_event is not None:
            k, exc, start_s, _ = cite(v.transcript_quote, side="transcript", tt=tt, minutes=None)
            kinds.append(k); row.update(transcript_excerpt=exc, transcript_start_s=start_s if start_s is not None else row["transcript_start_s"])
        if c.minutes_event is not None:
            k, exc, _, page = cite(v.minutes_quote, side="minutes", tt=None, minutes=minutes)
            kinds.append(k); row.update(minutes_excerpt=exc, minutes_page=page if page is not None else row["minutes_page"])
        match = citation_match_for(kinds)
        row.update(citation_match=match, confidence=round(v.confidence * (0.5 if match == "missing" else 1.0), 3))
        rows.append(row)

    # The hunter is told which candidates the aligner already raised, but it still restates a finding now and then
    # (first production run: both the statute-ground and the vote-order discrepancies arrived twice). A hunted row
    # that lands on the same category and the same anchor event as an aligner row is the same finding; keep the
    # aligner's, which carries the judge's verdict.
    taken = {(r["category"], "t", r["transcript_event_id"]) for r in rows if r["review_state"] == "proposed" and r["transcript_event_id"]} | \
            {(r["category"], "m", r["minutes_event_id"]) for r in rows if r["review_state"] == "proposed" and r["minutes_event_id"]}
    for h in hunted:
        refs = frozenset(h.agenda_item_refs)
        if valid_item_ids is not None:
            refs = frozenset(r for r in refs if r in valid_item_ids)
        kt, t_exc, start_s, _ = cite(h.transcript_quote, side="transcript", tt=tt, minutes=None)
        km, m_exc, _, page = cite(h.minutes_quote, side="minutes", tt=None, minutes=minutes)
        t_ev = nearest_event(t_events, start_s=start_s, item_refs=refs) if h.transcript_quote and start_s is not None else None
        m_ev = None
        if h.minutes_quote and minutes is not None:
            cm = find_citation(h.minutes_quote, minutes.text)
            if cm.kind != "missing":
                m_ev = nearest_event(m_events, char_offset=cm.start, item_refs=refs)
        if t_ev is None and m_ev is None:
            # No positional match (quote not found): anchor to the first event on the item, else on the quoted side.
            shared = lambda evs: next((e for e in evs if refs and e.item_refs & refs), None)
            if h.transcript_quote:
                t_ev = shared(t_events) or (t_events[0] if t_events else None)
            if t_ev is None and h.minutes_quote:
                m_ev = shared(m_events) or (m_events[0] if m_events else None)
            if t_ev is None and m_ev is None:
                t_ev = shared(t_events) or shared(m_events) or (t_events[0] if t_events else None)
                if t_ev is None and m_events:
                    m_ev = shared(m_events) or m_events[0]
        if t_ev is None and m_ev is None:
            # App-level anchor guard: migration 036 dropped the DB CHECK (re-extraction legitimately NULLs one side's
            # FK on stale rows), so no new row may be inserted without at least one event anchor.
            log.warning("hunter row dropped: no events at all to anchor it (%s)", h.title)
            continue
        if (t_ev is not None and (h.category, "t", t_ev.id) in taken) or (m_ev is not None and (h.category, "m", m_ev.id) in taken):
            log.info("compare: meeting %s hunter row folded into an aligner row (%s on %s)", meeting_id, h.category, h.title[:60])
            continue
        row = base(h.category, h.severity, h.title, h.description, t_ev, m_ev, refs, "model_initiated")
        kinds = [k for k, q in ((kt, h.transcript_quote), (km, h.minutes_quote)) if q]
        match = citation_match_for(kinds)
        row.update(transcript_excerpt=t_exc, transcript_start_s=start_s if start_s is not None else row["transcript_start_s"],
                   minutes_excerpt=m_exc, minutes_page=page if page is not None else row["minutes_page"], citation_match=match,
                   confidence=round(h.confidence * (0.5 if match == "missing" else 1.0), 3))
        rows.append(row)
    # Every new row must carry an anchor (see the guard above). Aligner candidates should always have one; a row
    # that somehow has neither is dropped here rather than written, since the DB no longer enforces it (036).
    anchored = [r for r in rows if r["transcript_event_id"] is not None or r["minutes_event_id"] is not None]
    if len(anchored) != len(rows):
        log.warning("compare: meeting %s dropped %d row(s) with no event anchor", meeting_id, len(rows) - len(anchored))
    return anchored


_COLS = ("meeting_id", "agenda_item_id", "category", "severity", "title", "description", "transcript_event_id", "minutes_event_id",
         "transcript_excerpt", "transcript_start_s", "minutes_excerpt", "minutes_page", "citation_match", "confidence", "origin",
         "review_state", "reject_reason", "prompt_version")


def insert_rows(meeting_id: int, rows: list[dict]) -> int:
    with db_cursor() as cur:
        for r in rows:
            cur.execute(f"INSERT INTO minutes_discrepancies ({', '.join(_COLS)}) VALUES ({', '.join(['%s'] * len(_COLS))})",
                        [r[c] for c in _COLS])
    return len(rows)


ADDITION_MATCH_RATIO = 0.8


def match_stale(new_row: dict, stale_rows: list[dict]) -> dict | None:
    if new_row.get("transcript_event_id") is not None:
        for s in stale_rows:
            if s["category"] == new_row["category"] and s.get("transcript_event_id") == new_row["transcript_event_id"]:
                return s
        return None
    best, best_ratio = None, 0.0
    for s in stale_rows:
        if s["category"] != new_row["category"] or s.get("agenda_item_id") != new_row.get("agenda_item_id"):
            continue
        r = SequenceMatcher(None, _norm(s.get("minutes_excerpt") or ""), _norm(new_row.get("minutes_excerpt") or "")).ratio()
        if r > best_ratio:
            best, best_ratio = s, r
    return best if best_ratio >= ADDITION_MATCH_RATIO else None


def reconcile(meeting_id: int, rows: list[dict]) -> dict:
    """Spec Section 4, 'Re-comparison'. Transcript event ids are stable across a minutes-side re-run.

    approved/proposed -> stale first; matched stale rows are updated in place and
    re-proposed with previous_review_state; rejected rows that match stay rejected
    (the reviewer already said no); old model dismissals are replaced wholesale.
    """
    with db_cursor() as cur:
        cur.execute("DELETE FROM minutes_discrepancies WHERE meeting_id = %s AND review_state = 'dismissed_by_model'", [meeting_id])
        cur.execute("""UPDATE minutes_discrepancies SET previous_review_state = review_state, review_state = 'stale'
                        WHERE meeting_id = %s AND review_state IN ('approved', 'proposed')""", [meeting_id])
        cur.execute("""SELECT id, category, transcript_event_id, agenda_item_id, minutes_excerpt, review_state, previous_review_state
                         FROM minutes_discrepancies WHERE meeting_id = %s AND review_state IN ('stale', 'rejected')""", [meeting_id])
        pool = [dict(r) for r in cur.fetchall()]
        inserted = updated = 0
        used: set[int] = set()
        for r in rows:
            match = match_stale(r, [p for p in pool if p["id"] not in used]) if r["review_state"] == "proposed" else None
            if match is None:
                cur.execute(f"INSERT INTO minutes_discrepancies ({', '.join(_COLS)}) VALUES ({', '.join(['%s'] * len(_COLS))})",
                            [r[c] for c in _COLS])
                inserted += 1
                continue
            used.add(match["id"])
            new_state = "rejected" if match["review_state"] == "rejected" else "proposed"
            # A re-proposed row is unreviewed again: clear who signed off on the old version (the old state
            # survives in previous_review_state). A still-rejected row keeps its reviewer and reason.
            cur.execute("""UPDATE minutes_discrepancies
                              SET title = %s, description = %s, severity = %s, minutes_event_id = %s, minutes_excerpt = %s,
                                  minutes_page = %s, transcript_excerpt = %s, transcript_start_s = %s, citation_match = %s,
                                  confidence = %s, prompt_version = %s, review_state = %s,
                                  reviewed_at  = CASE WHEN %s = 'proposed' THEN NULL ELSE reviewed_at  END,
                                  reviewed_by  = CASE WHEN %s = 'proposed' THEN NULL ELSE reviewed_by  END,
                                  review_note  = CASE WHEN %s = 'proposed' THEN NULL ELSE review_note  END
                            WHERE id = %s""",
                        [r["title"], r["description"], r["severity"], r["minutes_event_id"], r["minutes_excerpt"], r["minutes_page"],
                         r["transcript_excerpt"], r["transcript_start_s"], r["citation_match"], r["confidence"], r["prompt_version"],
                         new_state, new_state, new_state, new_state, match["id"]])
            updated += 1
        cur.execute("SELECT count(*) AS n FROM minutes_discrepancies WHERE meeting_id = %s AND review_state = 'stale'", [meeting_id])
        stale = cur.fetchone()["n"]
    return {"inserted": inserted, "updated": updated, "stale": stale}


def write_rows(meeting_id: int, rows: list[dict]) -> int:
    r = reconcile(meeting_id, rows)
    log.info("compare: meeting %s reconcile inserted=%d updated=%d stale=%d", meeting_id, r["inserted"], r["updated"], r["stale"])
    return r["inserted"] + r["updated"]


# --- stage ------------------------------------------------------------------

def _call(client, *, system: str, user: str, schema: dict, model_cls, max_tokens: int):
    tokens = client.count_tokens(model=AI_TRANSCRIPT_COMPARE_MODEL, system=system, user=user)
    if tokens > TRANSCRIPT_TOKEN_CEILING:
        raise TranscriptHeld("token_ceiling", f"{tokens} tokens > ceiling {TRANSCRIPT_TOKEN_CEILING}")
    res = client.call(model=AI_TRANSCRIPT_COMPARE_MODEL, system=system, user=user, schema=schema, max_tokens=max_tokens, effort="high")
    try:
        return model_cls.model_validate(res.data)
    except ValidationError as e:
        raise TranscriptHeld("schema_invalid", f"{model_cls.__name__} failed validation: {e}") from e


def run_compare_stage(claim: dict, *, client) -> "StageOutcome":
    from docket.ai.transcripts.pipeline import StageOutcome

    tid, mid = claim["id"], claim["meeting_id"]
    m_events = load_events(mid, "minutes")
    if not m_events or claim.get("compare_skipped_reason") == "minutes_changed":
        status = extract_minutes_side(mid, client=client)
        if status != "ok":
            return StageOutcome("events_extracted", skipped_reason=status, detail="minutes side unavailable at compare time")
        m_events = load_events(mid, "minutes")
    t_events = load_events(mid, "transcript")
    minutes = load_minutes(mid)
    segments = load_segments_with_speakers(tid)
    tt = transcript_text(segments)
    candidates = align(t_events, m_events, consent_items=load_consent_items(mid), votes=load_votes(mid))
    judged = [c for c in candidates if c.category != "vote_outcome"]
    if len(judged) > TRANSCRIPT_CANDIDATE_CAP:
        raise TranscriptHeld("candidate_cap", f"{len(judged)} candidates > cap {TRANSCRIPT_CANDIDATE_CAP}")
    verdicts = []
    if judged:
        judge = _call(client, system=JUDGE_SYSTEM, user=render_judge_user(judged, t_events, m_events, segments, minutes),
                      schema=JUDGE_SCHEMA, model_cls=JudgeResult, max_tokens=32000)
        verdicts = judge.verdicts
    agenda = load_agenda(mid)
    hunter = _call(client, system=HUNTER_SYSTEM,
                   user=render_hunter_user(candidates, t_events, m_events, render_transcript(segments, agenda, speaker_ordinals(tid)),
                                           render_minutes(minutes.text, minutes.page_offsets) if minutes else ""),
                   schema=HUNTER_SCHEMA, model_cls=HunterResult, max_tokens=16000)
    rows = build_rows(mid, candidates, verdicts, hunter.discrepancies, tt=tt, minutes=minutes, t_events=t_events, m_events=m_events,
                      valid_item_ids={a["id"] for a in agenda}, item_numbers={a["id"]: a.get("item_number") for a in agenda})
    n = write_rows(mid, rows)
    proposed = sum(1 for r in rows if r["review_state"] == "proposed")
    log.info("compare: meeting %s candidates=%d judged=%d rows=%d proposed=%d hunted=%d", mid, len(candidates), len(judged), n,
             proposed, len(hunter.discrepancies))
    return StageOutcome("compared", detail=f"{proposed} proposed of {n} rows")
