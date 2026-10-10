"""Backfill meetings that the city's Granicus archive never recorded.

Birmingham met at Boutwell Auditorium from May to December 2023 while the
chamber was renovated; the meetings were streamed to Facebook and most
never became Granicus clips. The council's YouTube channel kept the video
and the Wayback Machine kept the old council site's agenda PDFs. A manifest
(scripts/manifests/) lists them; this creates the meeting rows and their
agenda items through the same write path ingest uses. Minutes stay NULL
until the clerk's copies are obtained.

Meetings are keyed ``yt-<video id>`` (or ``archive-<date>`` when there is
no video) so Granicus ingest never collides with them, and the video-OCR
cron only claims numeric clip ids, so it leaves them alone.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import requests

from docket.adapters._helpers import classify_meeting
from docket.analysis.agenda_parser import parse_agenda, parse_minutes_approval
from docket.analysis.minutes_parser import extract_text_from_pdf
from docket.db import db
from docket.models.protocol import RawAgendaItem, RawMeeting
from docket.services.ingest import _ingest_agenda_items, _upsert_meetings

log = logging.getLogger(__name__)

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass(frozen=True)
class ArchivedMeeting:
    meeting_date: date
    youtube_id: str | None
    agenda_url: str | None
    title: str = "Regular City Council Meeting"

    @property
    def external_id(self) -> str:
        return f"yt-{self.youtube_id}" if self.youtube_id else f"archive-{self.meeting_date.isoformat()}"

    @property
    def video_url(self) -> str | None:
        return f"https://www.youtube.com/watch?v={self.youtube_id}" if self.youtube_id else None


@dataclass
class BackfillResult:
    inserted: list[int] = field(default_factory=list)   # meeting ids created
    skipped: list[str] = field(default_factory=list)    # external ids left alone, with reason
    errors: list[str] = field(default_factory=list)
    planned: list[str] = field(default_factory=list)    # dry run: external ids that would be created


_RETRY_STATUSES = {429, 500, 502, 503, 504}
_RETRY_BUDGET = 6
_RETRY_BASE_SECONDS = 30.0


def fetch_agenda_text(url: str, *, cache_dir: Path | None = None) -> str:
    """Download an agenda PDF (Wayback ``id_`` URLs serve the original bytes) and extract its text.

    With ``cache_dir`` the PDF bytes are kept on disk, keyed by a hash of the
    URL, and later calls never go back to the network: the Wayback Machine
    throttles sustained fetching hard, so each agenda should be pulled once.
    429 and 5xx answers are retried with growing waits (30s, 60s, … up to
    about 16 minutes in all). A 200 that isn't a PDF (a truncated crawl, an
    error page) fails at once and is not cached.
    """
    cache_path = None
    if cache_dir is not None:
        cache_path = Path(cache_dir) / f"{hashlib.sha1(url.encode()).hexdigest()}.pdf"
        if cache_path.exists():
            return extract_text_from_pdf(cache_path.read_bytes())

    for attempt in range(_RETRY_BUDGET):
        resp = requests.get(url, timeout=120, headers={"User-Agent": _BROWSER_UA}, allow_redirects=True)
        if resp.status_code in _RETRY_STATUSES and attempt < _RETRY_BUDGET - 1:
            wait = _RETRY_BASE_SECONDS * (2 ** attempt)
            log.info("archived_meetings: %s from %s, waiting %.0fs", resp.status_code, url, wait)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        if resp.content[:5] != b"%PDF-":
            raise ValueError(f"not a PDF: {url} ({resp.content[:20]!r})")
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(resp.content)
        return extract_text_from_pdf(resp.content)
    raise AssertionError("unreachable")


class _ManifestAgenda:
    """Adapter shim for ingest._ingest_agenda_items: the items are already parsed."""

    def __init__(self, items: list[RawAgendaItem]):
        self._items = items

    def fetch_agenda_items(self, meeting: RawMeeting) -> list[RawAgendaItem]:
        return self._items


def _items_from_text(meeting: RawMeeting, text: str) -> list[RawAgendaItem]:
    """Mirror GranicusAdapter's PDF path: numbered items plus the un-numbered
    minutes-approval line the adoption sweep keys off."""
    items = [
        RawAgendaItem(
            external_id=f"{meeting.external_id}-{p.item_number}",
            meeting_external_id=meeting.external_id,
            item_number=p.item_number,
            title=p.title,
            description=p.body,
            section=None,
            is_consent=p.is_consent,
            sponsor=p.sponsor,
            video_timestamp_seconds=None,
        )
        for p in parse_agenda(text)
    ]
    approval = parse_minutes_approval(text) if items else None
    if approval:
        items.append(
            RawAgendaItem(
                external_id=f"{meeting.external_id}-minutes-approval",
                meeting_external_id=meeting.external_id,
                item_number=None,
                title=approval,
                description=None,
                section=None,
                is_consent=False,
                sponsor=None,
                video_timestamp_seconds=None,
            )
        )
    return items


def backfill_archived_meetings(
    municipality_id: int,
    entries: list[ArchivedMeeting],
    *,
    fetch_agenda_text: Callable[[str], str] = fetch_agenda_text,
    dry_run: bool = False,
) -> BackfillResult:
    """Create the manifest's meetings and their agenda items. Idempotent.

    A date Granicus already covers with a visible numeric-clip meeting is
    skipped. A meeting that exists with its agenda scraped is skipped
    without a fetch. A failed agenda fetch leaves the meeting row in place
    and its agenda unscraped so the next run retries it.
    """
    result = BackfillResult()
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT slug FROM municipalities WHERE id = %s", (municipality_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"unknown municipality id {municipality_id}")
        slug = row[0]

    for entry in entries:
        ext = entry.external_id
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT external_id FROM meetings
                   WHERE municipality_id = %s AND meeting_date = %s AND is_hidden = FALSE
                     AND external_id ~ '^[0-9]+$'""",
                (municipality_id, entry.meeting_date),
            )
            granicus = [r[0] for r in cur.fetchall()]
            cur.execute(
                """SELECT m.id, COALESCE(ps.agenda_items_scraped, FALSE)
                   FROM meetings m LEFT JOIN processing_status ps ON ps.meeting_id = m.id
                   WHERE m.municipality_id = %s AND m.external_id = %s""",
                (municipality_id, ext),
            )
            existing = cur.fetchone()
        if granicus:
            result.skipped.append(f"{ext}: Granicus clip {granicus[0]} already covers {entry.meeting_date}")
            continue
        if existing and existing[1]:
            result.skipped.append(f"{ext}: already backfilled")
            continue
        if dry_run:
            result.planned.append(ext)
            continue

        raw = RawMeeting(
            external_id=ext,
            municipality_slug=slug,
            title=entry.title,
            meeting_date=entry.meeting_date,
            meeting_type=classify_meeting(entry.title),
            agenda_url=entry.agenda_url,
            minutes_url=None,
            video_url=entry.video_url,
            source_url=entry.video_url or entry.agenda_url or "",
        )
        if existing is None:
            _upsert_meetings(municipality_id, [raw])
            with db() as conn, conn.cursor() as cur:
                cur.execute("SELECT id FROM meetings WHERE municipality_id = %s AND external_id = %s",
                            (municipality_id, ext))
                result.inserted.append(cur.fetchone()[0])

        if not entry.agenda_url:
            continue
        try:
            text = fetch_agenda_text(entry.agenda_url)
        except Exception as e:  # network, Wayback 5xx, truncated PDF: retry next run
            log.warning("archived_meetings: agenda fetch failed for %s: %s", ext, e)
            result.errors.append(f"{ext}: {e}")
            continue
        items = _items_from_text(raw, text)
        if not items:
            log.warning("archived_meetings: no items parsed for %s", ext)
            result.errors.append(f"{ext}: no items parsed")
            continue
        _ingest_agenda_items(municipality_id, _ManifestAgenda(items), raw)

    log.info("archived_meetings: inserted=%d skipped=%d errors=%d planned=%d",
             len(result.inserted), len(result.skipped), len(result.errors), len(result.planned))
    return result
