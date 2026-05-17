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
from dataclasses import dataclass
from datetime import date

from docket.adapters import get_adapter
from docket.db import db, db_cursor
from docket.models.protocol import RawMeeting
from docket.services.enrichment import enrich_agenda_item

logger = logging.getLogger(__name__)


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
    """Insert or update meetings. Returns (inserted, updated) counts."""
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
                            source_url = %s
                        WHERE municipality_id = %s AND external_id = %s
                        """,
                        (
                            m.title, m.meeting_date, m.meeting_type,
                            m.agenda_url, m.minutes_url, m.video_url,
                            m.source_url, municipality_id, m.external_id,
                        ),
                    )
                    updated += 1
                else:
                    cur.execute(
                        """
                        INSERT INTO meetings (
                            municipality_id, external_id, title, meeting_date,
                            meeting_type, agenda_url, minutes_url, video_url, source_url
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            municipality_id, m.external_id, m.title, m.meeting_date,
                            m.meeting_type, m.agenda_url, m.minutes_url, m.video_url,
                            m.source_url,
                        ),
                    )
                    inserted += 1

    return inserted, updated


def _ingest_agenda_items(
    municipality_id: int,
    adapter,
    raw_meeting: RawMeeting,
) -> int:
    """Scrape and insert agenda items for a meeting if not already done."""
    # Short-circuit upcoming meetings: no clip_id is assigned yet, so the
    # adapter can't fetch items, and marking agenda_items_scraped=TRUE here
    # would persist through the eventual event-N → clip_id reconciliation
    # (the flag is keyed on the integer meeting_id PK) and permanently lock
    # the meeting out of agenda extraction.
    if raw_meeting.external_id.startswith("event-"):
        return 0

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
