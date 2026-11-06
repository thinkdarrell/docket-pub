"""Ingestion service — scrape meetings and agenda items via adapters.

Every entry point that needs to ingest meeting data calls into this module.
Functions here own their DB transactions.

Pipeline stages per meeting:
    1. Scrape meetings from platform adapter
    2. Scrape agenda items for each meeting
    3. (video vote scan + matching live in the worker's video_ocr and
       vote_matching tasks)
    4. Votes from the minutes: each member vote is resolved to its
       council member at insert through docket.services.member_votes
       (the roster rule; a name not on the roster stays NULL)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date

import psycopg2.extras

from docket.adapters import get_adapter
from docket.adapters._helpers import classify_title, normalize_title
from docket.db import db, db_cursor
from docket.models.protocol import RawMeeting
from docket.services import meeting_types
from docket.services.enrichment import enrich_agenda_item
from docket.services.member_votes import load_roster_index

logger = logging.getLogger(__name__)

# MediaPlayer index-point titles for BHM agendas are shaped like
# "ITEM 1 - Resolution setting public hearing on...". When backfilling
# video timestamps onto items that were originally inserted from the
# pre-recording PDF, we extract the agenda item_number from this title
# so we can match by item_number rather than position-in-list.
_AGENDA_ITEM_NUMBER_RE = re.compile(r"\bITEM\s+(\d+)\b", re.IGNORECASE)

# A Granicus chapter id (an index point's `data-id`) is all digits; only such
# an id makes the player jump (`&meta_id=<id>`). One pattern, read by Python
# and handed to PostgreSQL, so the rewrite and the query that looks for rows
# still to rewrite cannot disagree about what counts.
_CHAPTER_ID_PATTERN = "^[0-9]+$"
_CHAPTER_ID_RE = re.compile(_CHAPTER_ID_PATTERN)


def _is_chapter_id(external_id: str | None) -> bool:
    return external_id is not None and _CHAPTER_ID_RE.fullmatch(external_id) is not None

# The classification columns an UPDATE path writes, gated so a row an admin
# locked (type_locked_at) or the resolver placed on the calendar or
# schedule rung (type_source <> 'title') keeps its classification while the
# title, dates, and links still update. Only services.meeting_types moves a
# row between rungs. Three positional parameters: meeting_type,
# session_kind, body_name, in that order.
_CLASSIFICATION_GATE = "type_locked_at IS NULL AND type_source = 'title'"
_CLASSIFICATION_UPDATE_SQL = (
    f"meeting_type = CASE WHEN {_CLASSIFICATION_GATE} THEN %s ELSE meeting_type END, "
    f"session_kind = CASE WHEN {_CLASSIFICATION_GATE} THEN %s ELSE session_kind END, "
    f"body_name = CASE WHEN {_CLASSIFICATION_GATE} THEN %s ELSE body_name END, "
    f"type_source = CASE WHEN {_CLASSIFICATION_GATE} THEN 'title' ELSE type_source END"
)


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

    # Stage 3b: resolve each listed row's body and sitting now that its
    # items are in (the calendar match reads them). Every listed row, every
    # run, so a row that gained minutes or a cancelled title moves back
    # down the ladder on its own (docket.services.meeting_types).
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT id FROM meetings WHERE municipality_id = %s AND external_id = ANY(%s)",
                (municipality_id, [m.external_id for m in raw_meetings]),
            )
            listed_ids = [r["id"] for r in cur.fetchall()]
        resolved = meeting_types.resolve_and_store(municipality_id, listed_ids)
        logger.info("Meeting types: %d of %d rows reclassified", resolved, len(listed_ids))
    except Exception as e:
        errors.append(f"Meeting types: {e}")
        logger.error("  Failed to resolve meeting types for %s: %s", slug, e)

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
                cls = classify_title(m.title)

                if existing:
                    cur.execute(
                        f"""
                        UPDATE meetings SET
                            title = %s, meeting_date = %s,
                            {_CLASSIFICATION_UPDATE_SQL},
                            agenda_url = %s, minutes_url = %s, video_url = %s,
                            source_url = %s,
                            start_time = COALESCE(%s, start_time),
                            duration_s = COALESCE(%s, duration_s)
                        WHERE municipality_id = %s AND external_id = %s
                        """,
                        (
                            m.title, m.meeting_date,
                            cls.meeting_type, cls.session_kind, cls.body_name,
                            m.agenda_url, m.minutes_url, m.video_url,
                            m.source_url, m.start_time, m.duration_s,
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

                # A new row has no lock and no resolution: the title decides.
                cur.execute(
                    """
                    INSERT INTO meetings (
                        municipality_id, external_id, title, meeting_date,
                        meeting_type, session_kind, body_name, type_source,
                        agenda_url, minutes_url, video_url,
                        source_url, start_time, duration_s
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'title', %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        municipality_id, m.external_id, m.title, m.meeting_date,
                        cls.meeting_type, cls.session_kind, cls.body_name,
                        m.agenda_url, m.minutes_url, m.video_url,
                        m.source_url, m.start_time, m.duration_s,
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

    cls = classify_title(m.title)
    cur.execute(
        f"""
        UPDATE meetings SET
            external_id = %s, title = %s,
            {_CLASSIFICATION_UPDATE_SQL},
            agenda_url = %s, minutes_url = %s, video_url = %s,
            source_url = %s,
            start_time = COALESCE(%s, start_time),
            duration_s = COALESCE(%s, duration_s)
        WHERE id = %s
        """,
        (
            m.external_id, m.title,
            cls.meeting_type, cls.session_kind, cls.body_name,
            m.agenda_url, m.minutes_url, m.video_url,
            m.source_url, m.start_time, m.duration_s, chosen[0],
        ),
    )
    logger.info(
        "reconciliation: upgraded meeting id=%s external_id=%s → %s "
        "(muni=%s, date=%s)",
        chosen[0], chosen[1], m.external_id, municipality_id, m.meeting_date,
    )
    return True


def _backfill_video_timestamps(
    adapter,
    meeting_id: int,
    raw_meeting: RawMeeting,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    """Fill video timestamps and Granicus chapter ids on existing agenda items.

    Runs when a meeting's items were inserted from the pre-recording
    agenda PDF (no timestamps, ids such as `event-2715-1`) and the meeting
    has since been recorded and reconciled to a clip_id. Fetches the
    MediaPlayer index points and matches them to items by the `ITEM N`
    in each point's title (MediaPlayer's own RawAgendaItem.item_number is
    position-in-list, not the real agenda item number). The first point
    that names a number speaks for it.

    Two columns are written, and no other (AI summaries and item content
    are untouched):

    - `video_timestamp_seconds` is filled where it is NULL. A stored
      timestamp is never replaced.
    - `external_id` becomes the point's chapter id when the stored id is
      not one, the point has one, exactly one item of the meeting carries
      that item number, and no other row of the meeting holds or is being
      given that id (`UNIQUE(meeting_id, external_id)`). An id left alone
      for either of the last two reasons is logged at WARNING.

    With `force=True` every other reason a numbered item's id is left
    alone is logged at WARNING too, one line per meeting and reason: the
    player page has no index points, none of them names an ITEM number, no
    point names the item's number, or the item's point carries no chapter
    id. The ingest run does not log these: it reaches this pass on every
    run while a numbered item lacks its timestamp (`D102`), and they are
    there to explain a meeting the supervised pass lists again.

    Every change of the meeting goes in one UPDATE. Idempotent: a second
    call after all timestamps are filled is a cheap NULL-count check that
    early-exits without HTTP. That precheck asks only about timestamps, so
    a meeting whose items all have one but still carry non-chapter ids is
    reached with `force=True` (`correct_chapter_ids`), which skips it.
    `dry_run=True` computes and logs the same changes and writes nothing.

    Returns the number of rows changed (under `dry_run`, that would change).
    """
    if not force:
        # Cheap precheck: are there any items needing a timestamp? Un-numbered
        # items (the minutes-approval line) can never be matched below, so they
        # don't count.
        with db_cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM agenda_items "
                "WHERE meeting_id = %s AND video_timestamp_seconds IS NULL "
                "AND item_number IS NOT NULL",
                (meeting_id,),
            )
            null_count = cur.fetchone()["n"]

        if null_count == 0:
            return 0

    # Fetch MediaPlayer index points (have timestamps)
    media_items = adapter.fetch_agenda_items(raw_meeting)
    if not media_items:
        if force:
            logger.warning(
                "meeting %s (clip %s): no chapter id written: the player page has no index points",
                meeting_id, raw_meeting.external_id,
            )
        return 0

    # item number → (timestamp, chapter id or None), from the first point
    # whose title names that "ITEM N"
    points: dict[str, tuple[float, str | None]] = {}
    for item in media_items:
        if item.video_timestamp_seconds is None:
            continue
        match = _AGENDA_ITEM_NUMBER_RE.search(item.title or "")
        if not match:
            continue
        chapter_id = item.external_id if _is_chapter_id(item.external_id) else None
        points.setdefault(match.group(1), (item.video_timestamp_seconds, chapter_id))

    if not points:
        if force:
            logger.warning(
                "meeting %s (clip %s): no chapter id written: no index point of the "
                "player page names an ITEM number",
                meeting_id, raw_meeting.external_id,
            )
        return 0

    with db() as conn:
        with conn.cursor() as cur:
            # Every row of the meeting, un-numbered ones too: any of them may
            # hold an id a numbered item is about to be given.
            cur.execute(
                "SELECT id, item_number, external_id, video_timestamp_seconds "
                "FROM agenda_items WHERE meeting_id = %s ORDER BY id",
                (meeting_id,),
            )
            rows = cur.fetchall()

            by_number: dict[str, list[tuple]] = {}
            for row in rows:
                if row[1] is not None:
                    by_number.setdefault(row[1], []).append(row)
            taken = {row[2] for row in rows if row[2] is not None}

            changes: list[tuple[int, float, str | None]] = []
            filled = rewritten = 0
            for number, (point_ts, chapter_id) in points.items():
                same_number = by_number.get(number, [])
                for item_id, _, stored_id, stored_ts in same_number:
                    new_ts, new_id = stored_ts, stored_id
                    if stored_ts is None:
                        new_ts = point_ts
                        filled += 1
                    if chapter_id is not None and not _is_chapter_id(stored_id):
                        if len(same_number) > 1:
                            logger.warning(
                                "chapter id %s not written to agenda item %s of meeting %s: "
                                "item number %s is on %d rows",
                                chapter_id, item_id, raw_meeting.external_id,
                                number, len(same_number),
                            )
                        elif chapter_id in taken:
                            logger.warning(
                                "chapter id %s not written to agenda item %s of meeting %s: "
                                "another row of the meeting holds it or was given it",
                                chapter_id, item_id, raw_meeting.external_id,
                            )
                        else:
                            new_id = chapter_id
                            taken.add(chapter_id)
                            rewritten += 1
                    if (new_ts, new_id) != (stored_ts, stored_id):
                        changes.append((item_id, new_ts, new_id))

            if force:
                # The item numbers still waiting for a chapter id that the
                # loop above had nothing to say about, in row order.
                waiting = [
                    number for number, same_number in by_number.items()
                    if any(not _is_chapter_id(row[2]) for row in same_number)
                ]
                unnamed = [n for n in waiting if n not in points]
                without_id = [n for n in waiting if n in points and points[n][1] is None]
                if unnamed:
                    logger.warning(
                        "meeting %s (clip %s): no chapter id written to items %s: "
                        "no index point of the player page names them",
                        meeting_id, raw_meeting.external_id, ", ".join(unnamed),
                    )
                if without_id:
                    logger.warning(
                        "meeting %s (clip %s): no chapter id written to items %s: "
                        "their index points carry no chapter id",
                        meeting_id, raw_meeting.external_id, ", ".join(without_id),
                    )

            changed = len(changes)
            if changes and not dry_run:
                # One statement for the meeting; each tuple carries the row's
                # final values, so a column that does not change is set to
                # itself. page_size keeps execute_values from splitting it.
                psycopg2.extras.execute_values(
                    cur,
                    "UPDATE agenda_items AS a "
                    "SET video_timestamp_seconds = v.ts, external_id = v.ext "
                    "FROM (VALUES %s) AS v(id, ts, ext) WHERE a.id = v.id",
                    changes,
                    template="(%s::integer, %s::real, %s::text)",
                    page_size=len(changes),
                )
                changed = cur.rowcount

    if changes:
        logger.info(
            "meeting %s: %d video timestamps filled, %d chapter ids rewritten%s",
            raw_meeting.external_id, filled, rewritten,
            " (dry run, nothing written)" if dry_run else "",
        )
    return changed


def correct_chapter_ids(slug: str, *, limit: int = 50, dry_run: bool = False) -> list[dict]:
    """Write Granicus chapter ids onto cued items that still carry another id.

    The ingest run fetches a meeting's player page only while a numbered
    item lacks its timestamp, so a meeting whose items were all cued before
    `_backfill_video_timestamps` wrote chapter ids is never fetched again.
    This is the supervised pass for those rows
    (`scripts/correct_agenda_chapter_ids.py`): the city's clip meetings
    that have a numbered item with a timestamp and an id that is not a
    chapter id, newest first, at most `limit` of them, each put through
    `_backfill_video_timestamps(..., force=True)`. One player-page request
    per meeting, after which the adapter sleeps its polite delay, a request
    that fails included; one UPDATE per meeting. `dry_run=True` makes the same requests and writes
    nothing.

    Returns one dictionary per meeting visited: `meeting_id`, `external_id`,
    `meeting_date`, `changed` (rows changed, or that would change), and
    `error` (None, or the text of what kept this meeting from being
    corrected; the pass goes on to the next). A meeting that is listed
    again on a later run holds ids the rewrite leaves alone, and each run
    names them at WARNING with the reason (`_backfill_video_timestamps`
    gives the reasons). Raises ValueError for an unknown slug.
    """
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, slug, adapter_class, adapter_config FROM municipalities WHERE slug = %s",
            (slug,),
        )
        muni = cur.fetchone()

    if muni is None:
        raise ValueError(f"Municipality '{slug}' not found")

    adapter_config = muni["adapter_config"]
    if isinstance(adapter_config, str):
        adapter_config = json.loads(adapter_config)

    adapter = get_adapter(muni["adapter_class"], slug, adapter_config)

    with db_cursor() as cur:
        cur.execute(
            """
            SELECT m.id, m.external_id, m.title, m.meeting_date, m.meeting_type,
                   m.agenda_url, m.minutes_url, m.video_url, m.source_url
            FROM meetings m
            WHERE m.municipality_id = %s
              AND m.external_id ~ %s
              AND EXISTS (
                  SELECT 1 FROM agenda_items a
                  WHERE a.meeting_id = m.id
                    AND a.item_number IS NOT NULL
                    AND a.video_timestamp_seconds IS NOT NULL
                    AND (a.external_id IS NULL OR a.external_id !~ %s)
              )
            ORDER BY m.meeting_date DESC NULLS LAST, m.id DESC
            LIMIT %s
            """,
            (muni["id"], _CHAPTER_ID_PATTERN, _CHAPTER_ID_PATTERN, limit),
        )
        meetings = cur.fetchall()

    results: list[dict] = []
    for m in meetings:
        raw_meeting = RawMeeting(
            external_id=m["external_id"],
            municipality_slug=slug,
            title=m["title"],
            meeting_date=m["meeting_date"],
            meeting_type=m["meeting_type"],
            agenda_url=m["agenda_url"],
            minutes_url=m["minutes_url"],
            video_url=m["video_url"],
            source_url=m["source_url"],
        )
        error = None
        try:
            changed = _backfill_video_timestamps(
                adapter, m["id"], raw_meeting, force=True, dry_run=dry_run
            )
        except Exception as e:
            changed = 0
            error = f"{type(e).__name__}: {e}"
            logger.error(
                "chapter ids for meeting %s (clip %s) not corrected: %s",
                m["id"], m["external_id"], error,
            )
        results.append({
            "meeting_id": m["id"],
            "external_id": m["external_id"],
            "meeting_date": m["meeting_date"],
            "changed": changed,
            "error": error,
        })
    return results


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
    MediaPlayer index points and fills timestamps and chapter ids in place.
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

    # One short roster read per meeting, before the insert transaction;
    # the resolver is pure once the index is built.
    index = load_roster_index(municipality_id)

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
                        INSERT INTO member_votes
                            (vote_id, council_member_id, member_name, position)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (
                            vote_id,
                            index.resolve(mv["member"], raw_meeting.meeting_date),
                            mv["member"],
                            mv["vote"],
                        ),
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
