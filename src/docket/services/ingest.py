"""Ingestion service — scrape meetings and agenda items via adapters.

Every entry point that needs to ingest meeting data calls into this module.
Functions here own their DB transactions.

Pipeline stages per meeting:
    1. Scrape meetings from platform adapter
    2. Scrape agenda items for each meeting
    (Stages 3-4 — video vote scan + matching — will be ported later)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date

from docket.adapters import get_adapter
from docket.adapters._helpers import normalize_title
from docket.db import db, db_cursor
from docket.models.protocol import RawMeeting
from docket.services.enrichment import enrich_agenda_item

logger = logging.getLogger(__name__)

# MediaPlayer index-point titles for BHM agendas are shaped like
# "ITEM 1 - Resolution setting public hearing on...". When backfilling
# video timestamps onto items that were originally inserted from the
# pre-recording PDF, we extract the agenda item_number from this title
# so we can match by item_number rather than position-in-list.
_AGENDA_ITEM_NUMBER_RE = re.compile(r"\bITEM\s+(\d+)\b", re.IGNORECASE)


@dataclass
class IngestResult:
    municipality_slug: str
    meetings_found: int
    meetings_inserted: int
    meetings_updated: int
    agenda_items_inserted: int
    votes_inserted: int
    errors: list[str]

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


def ingest_municipality(slug: str, since: date | None = None) -> IngestResult:
    """Run the full ingestion pipeline for a municipality.

    1. Load municipality config from DB
    2. Instantiate the appropriate adapter
    3. Scrape meetings
    4. Upsert meetings into DB
    5. Scrape agenda items for new/updated meetings
    """
    errors: list[str] = []

    # Load municipality config
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, slug, adapter_class, adapter_config FROM municipalities WHERE slug = %s",
            (slug,),
        )
        muni = cur.fetchone()

    if muni is None:
        return IngestResult(slug, 0, 0, 0, 0, [f"Municipality '{slug}' not found"])

    adapter_config = muni["adapter_config"]
    if isinstance(adapter_config, str):
        adapter_config = json.loads(adapter_config)

    adapter = get_adapter(muni["adapter_class"], slug, adapter_config)
    municipality_id = muni["id"]

    # Stage 1: Scrape meetings
    logger.info("Scraping meetings for %s...", slug)
    try:
        raw_meetings = adapter.list_meetings(since=since)
    except Exception as e:
        return IngestResult(slug, 0, 0, 0, 0, [f"Failed to scrape meetings: {e}"])

    # Stage 2: Upsert meetings
    inserted, updated = _upsert_meetings(municipality_id, raw_meetings)
    logger.info("Meetings: %d found, %d inserted, %d updated", len(raw_meetings), inserted, updated)

    # Stage 3: Scrape agenda items for meetings that don't have them yet
    total_items = 0
    for raw_meeting in raw_meetings:
        try:
            count = _ingest_agenda_items(municipality_id, adapter, raw_meeting)
            total_items += count
        except Exception as e:
            errors.append(f"Agenda items for {raw_meeting.external_id}: {e}")
            logger.error("  Failed to scrape agenda for %s: %s", raw_meeting.external_id, e)

    logger.info("Agenda items: %d inserted", total_items)

    # Stage 4: Extract votes from minutes (if adapter supports it)
    total_votes = 0
    for raw_meeting in raw_meetings:
        if raw_meeting.minutes_url is None:
            continue
        try:
            count = _ingest_votes(municipality_id, adapter, raw_meeting)
            total_votes += count
        except Exception as e:
            errors.append(f"Votes for {raw_meeting.external_id}: {e}")
            logger.error("  Failed to parse votes for %s: %s", raw_meeting.external_id, e)

    logger.info("Votes: %d inserted", total_votes)

    # Stage 5: Sweep for adoption-pattern agenda items and resolve minutes_adopted_at
    try:
        from docket.services.minutes_adoption import sweep_adoptions
        flipped = sweep_adoptions(municipality_id)
        logger.info("adoption_sweep municipality_id=%s flipped=%d", municipality_id, len(flipped))
    except Exception as e:
        logger.warning("adoption_sweep failed for municipality %s: %s", municipality_id, e)

    return IngestResult(
        municipality_slug=slug,
        meetings_found=len(raw_meetings),
        meetings_inserted=inserted,
        meetings_updated=updated,
        agenda_items_inserted=total_items,
        votes_inserted=total_votes,
        errors=errors,
    )


def _upsert_meetings(municipality_id: int, raw_meetings: list[RawMeeting]) -> tuple[int, int]:
    """Insert or update meetings. Returns (inserted, updated) counts.

    For archive-shape meetings (external_id is a plain clip_id, not
    `event-N`), attempts reconciliation against any prior upcoming-row
    counterpart before falling back to INSERT — see
    `_try_upgrade_event_row` for the match logic.
    """
    inserted = 0
    updated = 0

    with db() as conn:
        with conn.cursor() as cur:
            for m in raw_meetings:
                cur.execute(
                    "SELECT id FROM meetings WHERE municipality_id = %s AND external_id = %s",
                    (municipality_id, m.external_id),
                )
                existing = cur.fetchone()

                if existing:
                    cur.execute(
                        """
                        UPDATE meetings SET
                            title = %s, meeting_date = %s, meeting_type = %s,
                            agenda_url = %s, minutes_url = %s, video_url = %s,
                            source_url = %s,
                            start_time = COALESCE(%s, start_time)
                        WHERE municipality_id = %s AND external_id = %s
                        """,
                        (
                            m.title, m.meeting_date, m.meeting_type,
                            m.agenda_url, m.minutes_url, m.video_url,
                            m.source_url, m.start_time,
                            municipality_id, m.external_id,
                        ),
                    )
                    updated += 1
                    continue

                # Archive-shape rows may correspond to a prior upcoming
                # (event-*) row that we've already ingested. Try to upgrade
                # that row in place before inserting a duplicate.
                if not m.external_id.startswith("event-"):
                    if _try_upgrade_event_row(cur, municipality_id, m):
                        updated += 1
                        continue

                cur.execute(
                    """
                    INSERT INTO meetings (
                        municipality_id, external_id, title, meeting_date,
                        meeting_type, agenda_url, minutes_url, video_url,
                        source_url, start_time
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        municipality_id, m.external_id, m.title, m.meeting_date,
                        m.meeting_type, m.agenda_url, m.minutes_url, m.video_url,
                        m.source_url, m.start_time,
                    ),
                )
                inserted += 1

    return inserted, updated


def _try_upgrade_event_row(cur, municipality_id: int, m: RawMeeting) -> bool:
    """Look for an existing event-* row matching this archive-shape RawMeeting
    and upgrade its external_id in place. Returns True if an upgrade happened.

    Match strategy (dual-tier):
        1. Exact match on `(muni, date, normalize_title(title))` — preferred.
        2. Date-only fallback — only when exactly one event-* row exists for
           that municipality on that date. If multiple, refuse to guess and
           let the caller insert a new row (cosmetic duplicate is recoverable;
           mis-mapping is not).
    """
    cur.execute(
        """
        SELECT id, external_id, title
        FROM meetings
        WHERE municipality_id = %s
          AND meeting_date = %s
          AND external_id LIKE 'event-%%'
        """,
        (municipality_id, m.meeting_date),
    )
    candidates = cur.fetchall()

    if not candidates:
        return False

    target = normalize_title(m.title)
    exact = [c for c in candidates if normalize_title(c[2]) == target]

    if len(exact) == 1:
        chosen = exact[0]
    elif len(exact) == 0 and len(candidates) == 1:
        chosen = candidates[0]
        logger.info(
            "reconciliation: date-only fallback upgrade — muni=%s date=%s "
            "archive_title=%r event_title=%r",
            municipality_id, m.meeting_date, m.title, chosen[2],
        )
    else:
        logger.warning(
            "reconciliation: ambiguous event-* upgrade — muni=%s date=%s "
            "%d candidates, %d exact-title matches — inserting new row",
            municipality_id, m.meeting_date, len(candidates), len(exact),
        )
        return False

    cur.execute(
        """
        UPDATE meetings SET
            external_id = %s, title = %s, meeting_type = %s,
            agenda_url = %s, minutes_url = %s, video_url = %s,
            source_url = %s,
            start_time = COALESCE(%s, start_time)
        WHERE id = %s
        """,
        (
            m.external_id, m.title, m.meeting_type,
            m.agenda_url, m.minutes_url, m.video_url,
            m.source_url, m.start_time, chosen[0],
        ),
    )
    logger.info(
        "reconciliation: upgraded meeting id=%s external_id=%s → %s "
        "(muni=%s, date=%s)",
        chosen[0], chosen[1], m.external_id, municipality_id, m.meeting_date,
    )
    return True


def _backfill_video_timestamps(
    adapter, meeting_id: int, raw_meeting: RawMeeting
) -> int:
    """Add video_timestamp_seconds to existing agenda items that lack it.

    Runs when a meeting's items were inserted from the pre-recording
    agenda PDF (no timestamps) and the meeting has since been recorded
    and reconciled to a clip_id. Fetches MediaPlayer index points and
    UPDATEs matching items by `item_number` parsed from the index-point
    titles (since MediaPlayer's RawAgendaItem.item_number is
    position-in-list, not the real agenda item number).

    Preserves any AI summaries and existing item content — only the
    `video_timestamp_seconds` column is touched. Idempotent: a second
    call after all timestamps are filled is a cheap NULL-count check
    that early-exits without HTTP.

    Returns the number of items updated.
    """
    # Cheap precheck: are there any items needing a timestamp?
    with db_cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM agenda_items "
            "WHERE meeting_id = %s AND video_timestamp_seconds IS NULL",
            (meeting_id,),
        )
        null_count = cur.fetchone()["n"]

    if null_count == 0:
        return 0

    # Fetch MediaPlayer index points (have timestamps)
    media_items = adapter.fetch_agenda_items(raw_meeting)
    if not media_items:
        return 0

    # Build item_number → timestamp map by extracting "ITEM N" from titles
    timestamps_by_num: dict[str, float] = {}
    for item in media_items:
        if item.video_timestamp_seconds is None:
            continue
        match = _AGENDA_ITEM_NUMBER_RE.search(item.title or "")
        if not match:
            continue
        item_num = match.group(1)
        timestamps_by_num.setdefault(item_num, item.video_timestamp_seconds)

    if not timestamps_by_num:
        return 0

    updated = 0
    with db() as conn:
        with conn.cursor() as cur:
            for item_num, ts in timestamps_by_num.items():
                cur.execute(
                    "UPDATE agenda_items SET video_timestamp_seconds = %s "
                    "WHERE meeting_id = %s AND item_number = %s "
                    "AND video_timestamp_seconds IS NULL",
                    (ts, meeting_id, item_num),
                )
                updated += cur.rowcount

    if updated > 0:
        logger.info(
            "backfilled video timestamps for %d/%d items on meeting %s",
            updated, null_count, raw_meeting.external_id,
        )
    return updated


def _ingest_agenda_items(
    municipality_id: int,
    adapter,
    raw_meeting: RawMeeting,
) -> int:
    """Scrape and insert agenda items for a meeting if not already done.

    For pre-recording (event-*) meetings, the adapter parses the agenda
    PDF — items get inserted normally but with no video timestamps.

    For archive-shape (clip_id) meetings whose items already exist but
    lack video timestamps (e.g., the items were inserted from a prior
    PDF scrape and the meeting has since been recorded and reconciled),
    fall through to `_backfill_video_timestamps` which fetches the
    MediaPlayer index points and UPDATE timestamps in place.
    """
    # Check if we already have agenda items for this meeting
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT m.id, ps.agenda_items_scraped
            FROM meetings m
            LEFT JOIN processing_status ps ON m.id = ps.meeting_id
            WHERE m.municipality_id = %s AND m.external_id = %s
            """,
            (municipality_id, raw_meeting.external_id),
        )
        row = cur.fetchone()

    if row is None:
        return 0

    meeting_id = row["id"]
    already_scraped = row.get("agenda_items_scraped") or False

    if already_scraped:
        # Items exist; if any lack video timestamps AND this is an archived
        # (clip_id) meeting, try to backfill timestamps from MediaPlayer.
        # No-op once timestamps are filled or for upcoming meetings.
        if not raw_meeting.external_id.startswith("event-"):
            return _backfill_video_timestamps(adapter, meeting_id, raw_meeting)
        return 0

    # Scrape agenda items via adapter
    raw_items = adapter.fetch_agenda_items(raw_meeting)
    if not raw_items:
        # Mark as scraped even if empty so we don't re-try
        _update_processing_status(meeting_id, agenda_items_scraped=True)
        return 0

    # Insert agenda items with enrichment
    with db() as conn:
        with conn.cursor() as cur:
            for item in raw_items:
                enriched = enrich_agenda_item(item.title, item.description, item.is_consent)
                # Use enriched sponsor if found, fall back to adapter-provided sponsor
                sponsor = enriched["sponsor"] or item.sponsor
                # Use cleaned title (attribution parentheticals removed)
                title = enriched["clean_title"] or item.title
                cur.execute(
                    """
                    INSERT INTO agenda_items (
                        meeting_id, external_id, item_number, title,
                        description, section, is_consent, sponsor,
                        dollars_amount, topic,
                        significance_score, consent_placement_score,
                        video_timestamp_seconds
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (meeting_id, external_id) DO NOTHING
                    """,
                    (
                        meeting_id, item.external_id, item.item_number,
                        title, item.description, item.section,
                        item.is_consent, sponsor,
                        enriched["dollars_amount"],
                        enriched["topic"],
                        enriched["significance_score"],
                        enriched["consent_placement_score"],
                        item.video_timestamp_seconds,
                    ),
                )

    _update_processing_status(meeting_id, agenda_items_scraped=True)
    logger.info("  [%s] %s → %d items", raw_meeting.meeting_date, raw_meeting.title, len(raw_items))
    return len(raw_items)


def _ingest_votes(
    municipality_id: int,
    adapter,
    raw_meeting: RawMeeting,
) -> int:
    """Extract and insert votes from minutes for a meeting if not already done."""
    # Defense-in-depth: upcoming meetings have minutes_url=None and the caller
    # already skips them, but a direct call should also be safe.
    if raw_meeting.external_id.startswith("event-"):
        return 0

    with db_cursor() as cur:
        cur.execute(
            """
            SELECT m.id, ps.votes_scanned
            FROM meetings m
            LEFT JOIN processing_status ps ON m.id = ps.meeting_id
            WHERE m.municipality_id = %s AND m.external_id = %s
            """,
            (municipality_id, raw_meeting.external_id),
        )
        row = cur.fetchone()

    if row is None:
        return 0

    meeting_id = row["id"]
    already_scanned = row.get("votes_scanned") or False

    if already_scanned:
        return 0

    raw_votes = adapter.fetch_votes(raw_meeting)
    if not raw_votes:
        _update_processing_status(meeting_id, votes_scanned=True)
        return 0

    with db() as conn:
        with conn.cursor() as cur:
            for rv in raw_votes:
                cur.execute(
                    """
                    INSERT INTO votes (
                        meeting_id, external_id, result,
                        yeas, nays, abstentions,
                        source, confidence,
                        resolution_number, match_context, raw_text
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        meeting_id, rv.external_id, rv.result,
                        rv.yeas, rv.nays, rv.abstentions,
                        rv.source, rv.confidence,
                        rv.resolution_number, rv.match_context, rv.raw_text,
                    ),
                )
                vote_id = cur.fetchone()[0]

                for mv in rv.member_votes:
                    cur.execute(
                        """
                        INSERT INTO member_votes (vote_id, member_name, position)
                        VALUES (%s, %s, %s)
                        """,
                        (vote_id, mv["member"], mv["vote"]),
                    )

    _update_processing_status(meeting_id, votes_scanned=True)
    logger.info(
        "  [%s] %s → %d votes",
        raw_meeting.meeting_date, raw_meeting.title, len(raw_votes),
    )
    return len(raw_votes)


def _update_processing_status(meeting_id: int, **fields) -> None:
    """Update or create processing status for a meeting."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM processing_status WHERE meeting_id = %s",
                (meeting_id,),
            )
            exists = cur.fetchone()

            if exists:
                sets = ", ".join(f"{k} = %s" for k in fields)
                cur.execute(
                    f"UPDATE processing_status SET {sets}, last_processed = NOW() WHERE meeting_id = %s",
                    (*fields.values(), meeting_id),
                )
            else:
                cols = ["meeting_id", "last_processed"] + list(fields.keys())
                val_parts = ["%s", "NOW()"] + ["%s"] * len(fields)
                col_str = ", ".join(cols)
                val_str = ", ".join(val_parts)
                cur.execute(
                    f"INSERT INTO processing_status ({col_str}) VALUES ({val_str})",
                    (meeting_id, *fields.values()),
                )
