# src/docket/services/discrepancies.py
"""Reads and state changes for minutes_discrepancies (admin queue, public block, ship gate)."""
from __future__ import annotations

from docket.db import db_cursor

QUEUE_STATES = ("proposed", "approved", "rejected", "dismissed_by_model", "stale")
SHIP_GATE_MEETINGS = 10
SHIP_GATE_CANDIDATES = 30
SHIP_GATE_RATIO = 0.70


class DiscrepancyStateError(Exception):
    """The row is not in a state that allows this action (409)."""


class CitationNotFound(Exception):
    """A reviewer-supplied excerpt could not be found in the source text (400)."""


_SELECT = """
    SELECT d.*, m.title AS meeting_title, m.meeting_date, m.video_url, m.minutes_url, mu.slug AS municipality_slug,
           ai.item_number, ai.external_id AS item_external_id, ai.title AS item_title,
           COALESCE(d.admin_title, d.title) AS display_title,
           COALESCE(d.admin_description, d.description) AS display_description
      FROM minutes_discrepancies d
      JOIN meetings m ON m.id = d.meeting_id
      JOIN municipalities mu ON mu.id = m.municipality_id
      LEFT JOIN agenda_items ai ON ai.id = d.agenda_item_id
"""


def list_queue(*, state: str = "proposed", category: str | None = None, meeting_id: int | None = None,
               limit: int = 50, offset: int = 0) -> list[dict]:
    where, params = ["d.review_state = %s"], [state]
    if category:
        where.append("d.category = %s"); params.append(category)
    if meeting_id:
        where.append("d.meeting_id = %s"); params.append(meeting_id)
    with db_cursor() as cur:
        cur.execute(f"""{_SELECT} WHERE {' AND '.join(where)}
                        ORDER BY (d.severity = 'material') DESC, m.meeting_date DESC, d.confidence DESC NULLS LAST, d.id
                        LIMIT %s OFFSET %s""", [*params, limit, offset])
        return [dict(r) for r in cur.fetchall()]


def get(discrepancy_id: int) -> dict | None:
    with db_cursor() as cur:
        cur.execute(f"{_SELECT} WHERE d.id = %s", [discrepancy_id])
        row = cur.fetchone()
        return dict(row) if row else None


def approve(discrepancy_id: int, actor: str, note: str | None = None) -> None:
    with db_cursor() as cur:
        cur.execute("""UPDATE minutes_discrepancies
                          SET review_state = 'approved', reviewed_at = now(), reviewed_by = %s, review_note = COALESCE(%s, review_note)
                        WHERE id = %s AND review_state = 'proposed' AND citation_match <> 'missing'""",
                    [actor, note, discrepancy_id])
        if cur.rowcount == 0:
            cur.execute("SELECT review_state, citation_match FROM minutes_discrepancies WHERE id = %s", [discrepancy_id])
            row = cur.fetchone()
            if row is None:
                raise LookupError(discrepancy_id)
            if row["citation_match"] == "missing":
                raise DiscrepancyStateError("attach a citation before approving")
            raise DiscrepancyStateError(f"row is {row['review_state']}, not proposed")


def reject(discrepancy_id: int, actor: str, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("reason required")
    with db_cursor() as cur:
        cur.execute("""UPDATE minutes_discrepancies SET review_state = 'rejected', reject_reason = %s, reviewed_at = now(), reviewed_by = %s
                        WHERE id = %s AND review_state = 'proposed'""", [reason.strip(), actor, discrepancy_id])
        if cur.rowcount == 0:
            raise DiscrepancyStateError("row is not proposed")


def _attach_citation(row: dict, transcript_excerpt: str | None, minutes_excerpt: str | None) -> tuple[str, dict]:
    from docket.ai.transcripts.compare import transcript_text, segment_at, citation_match_for
    from docket.ai.transcripts.events import load_segments_with_speakers
    from docket.ai.transcripts.guard import find_citation
    from docket.ai.transcripts.minutes import load_minutes, page_for_offset
    updates, kinds = {}, []
    if transcript_excerpt and transcript_excerpt.strip():
        with db_cursor() as cur:
            cur.execute("SELECT id FROM transcripts WHERE meeting_id = %s", [row["meeting_id"]])
            tid = cur.fetchone()["id"]
        tt = transcript_text(load_segments_with_speakers(tid))
        cm = find_citation(transcript_excerpt, tt.joined)
        if cm.kind == "missing":
            raise CitationNotFound("transcript excerpt not found in the transcript")
        seg = segment_at(tt, cm.start)
        updates.update(transcript_excerpt=tt.joined[cm.start:cm.end], transcript_start_s=seg["start_s"] if seg else row["transcript_start_s"])
        kinds.append(cm.kind)
    if minutes_excerpt and minutes_excerpt.strip():
        minutes = load_minutes(row["meeting_id"])
        cm = find_citation(minutes_excerpt, minutes.text) if minutes else None
        if cm is None or cm.kind == "missing":
            raise CitationNotFound("minutes excerpt not found in the minutes text")
        updates.update(minutes_excerpt=minutes.text[cm.start:cm.end], minutes_page=page_for_offset(minutes.page_offsets, cm.start))
        kinds.append(cm.kind)
    if not kinds:
        raise CitationNotFound("no excerpt supplied")
    return citation_match_for(kinds), updates


def edit_and_approve(discrepancy_id: int, actor: str, admin_title: str, admin_description: str,
                     transcript_excerpt: str | None = None, minutes_excerpt: str | None = None) -> None:
    row = get(discrepancy_id)
    if row is None:
        raise LookupError(discrepancy_id)
    if row["review_state"] != "proposed":
        raise DiscrepancyStateError(f"row is {row['review_state']}, not proposed")
    updates = {"admin_title": admin_title.strip() or None, "admin_description": admin_description.strip() or None}
    if row["citation_match"] == "missing" or transcript_excerpt or minutes_excerpt:
        match, cit = _attach_citation(row, transcript_excerpt, minutes_excerpt)
        updates.update(cit, citation_match=match)
    sets = ", ".join(f"{k} = %s" for k in updates)
    with db_cursor() as cur:
        cur.execute(f"UPDATE minutes_discrepancies SET {sets} WHERE id = %s", [*updates.values(), discrepancy_id])
    approve(discrepancy_id, actor)


def held_transcripts() -> list[dict]:
    with db_cursor() as cur:
        cur.execute("""SELECT t.id AS transcript_id, t.meeting_id, t.status, t.needs_review_reason, t.last_error, t.stage_attempts,
                              t.updated_at, m.title AS meeting_title, m.meeting_date, mu.slug AS municipality_slug
                         FROM transcripts t JOIN meetings m ON m.id = t.meeting_id JOIN municipalities mu ON mu.id = m.municipality_id
                        WHERE t.status IN ('needs_review', 'failed') AND t.uploaded_at IS NOT NULL
                        ORDER BY m.meeting_date DESC""")
        return [dict(r) for r in cur.fetchall()]


def retry_transcript(meeting_id: int) -> str:
    """Put a held/failed transcript back at the earliest stage whose output is missing."""
    with db_cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM meeting_events WHERE meeting_id = %s AND source = 'transcript') AS ev", [meeting_id])
        has_events = cur.fetchone()["ev"]
        cur.execute("SELECT EXISTS (SELECT 1 FROM transcript_speakers WHERE meeting_id = %s AND method IS NOT NULL) AS sp", [meeting_id])
        has_speakers = cur.fetchone()["sp"]
        status = "events_extracted" if has_events else ("speakers_resolved" if has_speakers else "uploaded")
        cur.execute("""UPDATE transcripts SET status = %s, stage_attempts = 0, last_attempted_at = NULL, needs_review_reason = NULL,
                              last_error = NULL, compare_skipped_reason = NULL, updated_at = now()
                        WHERE meeting_id = %s AND status IN ('needs_review', 'failed')""", [status, meeting_id])
        if cur.rowcount == 0:
            raise DiscrepancyStateError("transcript is not held or failed")
    return status


# --- public reads (approved only) --------------------------------------------

_PUBLIC_ORDER = "ORDER BY (d.severity = 'material') DESC, d.reviewed_at DESC, d.id"


def list_public_for_meeting(meeting_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(f"{_SELECT} WHERE d.meeting_id = %s AND d.review_state = 'approved' AND m.is_hidden = FALSE {_PUBLIC_ORDER}", [meeting_id])
        return [dict(r) for r in cur.fetchall()]


def list_public_for_item(item_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(f"{_SELECT} WHERE d.agenda_item_id = %s AND d.review_state = 'approved' AND m.is_hidden = FALSE {_PUBLIC_ORDER}", [item_id])
        return [dict(r) for r in cur.fetchall()]


def list_public_recent(limit: int = 50, offset: int = 0) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(f"""{_SELECT} WHERE d.review_state = 'approved' AND m.is_hidden = FALSE
                        ORDER BY m.meeting_date DESC, (d.severity = 'material') DESC, d.id LIMIT %s OFFSET %s""", [limit, offset])
        return [dict(r) for r in cur.fetchall()]


# --- ship gate -----------------------------------------------------------------

def ship_gate(rows: list[dict]) -> dict:
    """Spec Section 6: >= 70% of material candidates approved over the first 10 reviewed meetings
    or the first 30 reviewed candidates, whichever comes first. `rows` are material rows in
    review_state approved/rejected ordered by reviewed_at with keys meeting_id, review_state."""
    approved = rejected = 0
    meetings: list[int] = []
    for r in rows:
        if r["meeting_id"] not in meetings:
            if len(meetings) == SHIP_GATE_MEETINGS:
                break
            meetings.append(r["meeting_id"])
        if r["review_state"] == "approved":
            approved += 1
        else:
            rejected += 1
        if approved + rejected >= SHIP_GATE_CANDIDATES:
            break
    total = approved + rejected
    ratio = approved / total if total else 0.0
    complete = total >= SHIP_GATE_CANDIDATES or len(meetings) >= SHIP_GATE_MEETINGS
    return {"approved": approved, "rejected": rejected, "total": total, "meetings": len(meetings),
            "ratio": round(ratio, 3), "window_complete": complete, "gate_met": complete and ratio >= SHIP_GATE_RATIO}


def approval_ratio() -> dict:
    with db_cursor() as cur:
        cur.execute("""SELECT meeting_id, review_state FROM minutes_discrepancies
                        WHERE severity = 'material' AND review_state IN ('approved', 'rejected') AND reviewed_at IS NOT NULL
                        ORDER BY reviewed_at, id""")
        return ship_gate([dict(r) for r in cur.fetchall()])
