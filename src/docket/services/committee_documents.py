"""The council committees' own documents, listed, fetched, read and stored.

A city whose ``municipalities.metadata`` carries ``committee_document_pages``
(Birmingham, since migration 045) publishes one page per standing committee
listing that committee's agenda and minutes PDFs.
``docket.adapters.committee_documents`` fetches a page or a PDF and reads
what either says; this module decides what is stored and owns every write.

- ``sync_listings`` records each PDF a page lists as a ``committee_documents``
  row, unique by ``(municipality_id, url)``.
- ``read_pending`` fetches the rows not yet read and hands each to ``_read``,
  which stores the document's text, what the document is (which committee,
  which date, agenda or minutes: its own first lines first, its listing as
  the fallback) and, for minutes, what the committee took up as
  ``committee_items`` rows.
- ``reparse`` reads stored text again, with no fetch, after a rule has been
  mended and ``PARSER_VERSION`` raised.
- ``attach`` gives each read document the committee meeting it records: the
  meeting row that already exists for that committee and date, or, for
  minutes that have none, a new row, because minutes prove a meeting was
  held. ``primary_documents`` says which of a meeting's documents of each
  kind is the one to show.
- ``for_meeting`` is the meeting page's one read: a meeting's documents and
  the items of its primary minutes.
- ``refresh_city`` runs the four steps in order for one city, and
  ``refresh_all`` for every city that names its pages: the worker's daily
  task. ``backfill`` is the same run with a summary of what the tables then
  hold, for the operator's script; with ``dry_run`` it happens inside one
  transaction that is rolled back.

Nothing here writes ``agenda_items``, ``votes``, ``meetings.agenda_url`` or
``meetings.minutes_url``: every reader of those treats a row as council
business. A committee's action is its minutes' own words and one of a closed
list of categories, never a vote.

Plan `committee-documents`, M3 (listing, reading, storing), M4 (attaching) and
M5 (the meeting page's read) and M6 (the daily refresh and the backfill).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date

import psycopg2.extras

from docket.adapters import committee_documents as source
from docket.adapters._helpers import classify_title
from docket.analysis.minutes_parser import extract_text_from_pdf
from docket.db import db
from docket.db import db_cursor as _committing_cursor

log = logging.getLogger(__name__)

# The connection of a dry run in progress, or None. While it is set, every
# function of this module works on it and commits nothing (``_rolled_back``).
_dry_run_conn = None


@contextmanager
def db_cursor() -> Iterator[psycopg2.extras.RealDictCursor]:
    """This module's cursor. Ordinarily ``docket.db.db_cursor``: its own
    connection, committed on success and rolled back on an error. During a
    dry run, a cursor on the dry run's one connection, between a savepoint
    and its release, so that a block that raises is undone alone, as its own
    transaction would have been, and what the blocks before it wrote stays
    visible to the blocks after it."""
    if _dry_run_conn is None:
        with _committing_cursor() as cur:
            yield cur
        return
    with _dry_run_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SAVEPOINT committee_documents_block")
        try:
            yield cur
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT committee_documents_block")
            raise
        cur.execute("RELEASE SAVEPOINT committee_documents_block")


@contextmanager
def _rolled_back() -> Iterator[None]:
    """Everything this module does inside the block happens in one
    transaction, which is rolled back when the block ends, however it ends."""
    global _dry_run_conn
    with db() as conn:
        _dry_run_conn = conn
        try:
            yield
        finally:
            _dry_run_conn = None
            conn.rollback()

# Raised when a reading rule changes; ``reparse`` then reads every stored
# text below it again.
PARSER_VERSION = 1

# A document that failed this many times is not tried again.
MAX_FETCH_ATTEMPTS = 3
# Fewer characters than this that are not spaces: a scanned image, with no
# text layer to read.
MIN_TEXT_CHARS = 200


def sync_listings(municipality_id: int, pages: list[dict]) -> int:
    """Record what each committee page lists; returns how many addresses are new.

    ``pages`` is the city's ``committee_document_pages``: a list of
    ``{"committee": <canonical name>, "url": <page address>}``. A new address
    is inserted as ``listed``; a known one takes the page's current name and
    heading and a new ``last_seen_at``, and nothing else of it changes. A page
    that cannot be fetched, or that yields no listing, is logged and skipped;
    only when every page did so does the call raise, because then the city
    has changed its site and nothing was learned.
    """
    new = 0
    failed = 0
    for page in pages:
        committee, page_url = page["committee"], page["url"]
        try:
            listings = source.parse_committee_page(source.fetch_page(page_url), page_url)
        except Exception:
            log.exception("committee documents: page %s failed", page_url)
            failed += 1
            continue
        if not listings:
            log.warning("committee documents: page %s lists no document", page_url)
            failed += 1
            continue
        with db_cursor() as cur:
            for listing in listings:
                cur.execute(
                    """INSERT INTO committee_documents
                              (municipality_id, url, page_url, page_committee, listed_name, listed_heading)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (municipality_id, url) DO UPDATE
                          SET last_seen_at = now(),
                              listed_name = EXCLUDED.listed_name,
                              listed_heading = EXCLUDED.listed_heading
                       RETURNING (xmax = 0) AS inserted""",
                    (municipality_id, listing.url, listing.page_url, committee, listing.listed_name,
                     listing.listed_heading),
                )
                new += 1 if cur.fetchone()["inserted"] else 0
    if pages and failed == len(pages):
        raise RuntimeError(f"committee documents: {failed} of {len(pages)} pages gave no listing")
    return new


def read_pending(municipality_id: int, limit: int | None) -> int:
    """Fetch and read up to ``limit`` documents not yet read, oldest first;
    returns how many were read. ``limit`` None is no limit.

    A document is pending while it is ``listed``, or ``fetch_failed`` with
    fewer than three attempts. One that cannot be fetched, or whose bytes
    cannot be read, is marked ``fetch_failed`` with one more attempt, and the
    documents after it are still read. The limit is on documents tried, so it
    bounds the requests a run makes.
    """
    with db_cursor() as cur:
        cur.execute(
            """SELECT id, url, page_url, page_committee, listed_name, listed_heading
                 FROM committee_documents
                WHERE municipality_id = %s
                  AND (status = 'listed' OR (status = 'fetch_failed' AND fetch_attempts < %s))
                ORDER BY first_seen_at, id
                LIMIT %s""",
            (municipality_id, MAX_FETCH_ATTEMPTS, limit),
        )
        rows = cur.fetchall()

    read = 0
    for row in rows:
        done = False
        try:
            pdf_bytes = source.fetch_pdf(row["url"])
            if pdf_bytes is not None:
                _read(row, pdf_bytes)
                done = True
        except Exception:
            log.exception("committee documents: %s could not be read", row["url"])
        if done:
            read += 1
            continue
        with db_cursor() as cur:
            cur.execute(
                "UPDATE committee_documents SET status = 'fetch_failed', fetch_attempts = fetch_attempts + 1 "
                "WHERE id = %s",
                (row["id"],),
            )
    return read


def _read(row: dict, pdf_bytes: bytes) -> None:
    """Read one document from its bytes and store the reading, in one
    transaction. ``row`` is its ``committee_documents`` row (the id and what
    the page listed)."""
    text = extract_text_from_pdf(pdf_bytes)
    with db_cursor() as cur:
        cur.execute(
            "UPDATE committee_documents SET pdf_sha256 = %s, fetched_at = now() WHERE id = %s",
            (hashlib.sha256(pdf_bytes).hexdigest(), row["id"]),
        )
        _store_reading(cur, row, text)


def _store_reading(cur, row: dict, text: str) -> None:
    """Store what ``text`` says the document is, and replace its items.

    Too little text is a scanned image: nothing of it is kept, and what it is
    comes from its listing alone. A document whose header says it is a meeting
    of the full council is kept as text and given no facts. Otherwise the
    document's own header decides, with the listing as the fallback, and
    minutes are read into items numbered from 1 in the minutes' order.
    """
    listing = source.Listing(
        url=row["url"], listed_name=row["listed_name"], listed_heading=row["listed_heading"],
        page_url=row["page_url"],
    )
    facts = None
    minutes = None
    if len("".join(text.split())) < MIN_TEXT_CHARS:
        status, stored = "no_text", None
        facts = source.resolve(listing, row["page_committee"], None)
    else:
        stored = text
        header = source.read_header(text)
        if header is None:
            status = "not_committee"
        else:
            status = "read"
            facts = source.resolve(listing, row["page_committee"], header)
            if facts.kind == "minutes":
                minutes = source.parse_minutes_items(text)

    cur.execute(
        """UPDATE committee_documents
              SET status = %s, text = %s, kind = %s, committees = %s, meeting_date = %s, date_source = %s,
                  listing_disagrees = %s, special = %s, work_session = %s, present = %s, trailing_lines = %s,
                  parser_version = %s
            WHERE id = %s""",
        (
            status,
            stored,
            facts.kind if facts else None,
            list(facts.committees) if facts else [],
            facts.meeting_date if facts else None,
            facts.date_source if facts else None,
            facts.listing_disagrees if facts else False,
            facts.special if facts else False,
            facts.work_session if facts else False,
            minutes.present if minutes else None,
            minutes.trailing_lines if minutes else None,
            PARSER_VERSION,
            row["id"],
        ),
    )
    cur.execute("DELETE FROM committee_items WHERE document_id = %s", (row["id"],))
    for position, item in enumerate(minutes.items if minutes else (), start=1):
        cur.execute(
            """INSERT INTO committee_items
                      (document_id, position, heading_label, heading_text, owns_heading, group_text, name, body,
                       action_text, action_category, moved_by, seconded_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (row["id"], position, item.heading_label, item.heading_text, item.owns_heading, item.group, item.name,
             item.body, item.action_text, item.action_category, item.moved_by, item.seconded_by),
        )


def reparse(municipality_id: int) -> int:
    """Read again, from its stored text and with no fetch, every document
    read under an older ``PARSER_VERSION``; returns how many. One transaction
    per document."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT id, url, page_url, page_committee, listed_name, listed_heading, text
                 FROM committee_documents
                WHERE municipality_id = %s AND text IS NOT NULL AND parser_version < %s
                ORDER BY id""",
            (municipality_id, PARSER_VERSION),
        )
        rows = cur.fetchall()
    for row in rows:
        with db_cursor() as cur:
            _store_reading(cur, row, row["text"])
    return len(rows)


@dataclass
class AttachReport:
    """What one ``attach`` call did. ``matched`` and ``created`` count the
    documents it attached, to a meeting that existed and to one it made;
    ``ambiguous`` counts those of the matched that had several meetings to
    choose from. The two ``unattached`` counts are the documents it
    considered and left with no meeting. ``crowded_days`` are the dates of
    the meetings it made on which the city also has a second visible Granicus
    meeting typed ``council``: the sign of a committee clip mislabelled."""

    matched: int = 0
    created: int = 0
    ambiguous: int = 0
    unattached_agendas: int = 0
    unattached_minutes: int = 0
    crowded_days: list[date] = field(default_factory=list)


def committee_of(body_name: str | None) -> str | None:
    """The one canonical committee a meeting's ``body_name`` names, or None
    when it names none or several."""
    named = source.committees_named(body_name)
    return named[0] if len(named) == 1 else None


def attach(municipality_id: int, today: date) -> AttachReport:
    """Give each read document with no meeting the meeting it records.

    A document is considered when it is ``read`` or ``no_text`` and has a
    kind, a date and a committee. Its candidates are the city's visible
    committee meetings on that date whose ``body_name`` names one of its
    committees. With none, minutes whose date is their own header's and not
    after ``today`` create the meeting; anything else stays unattached and is
    considered again on the next call. Minutes are taken before agendas, so
    an agenda finds the meeting its minutes made in the same call. One
    transaction per document; a document that has a meeting is never moved.
    """
    with db_cursor() as cur:
        cur.execute(
            """SELECT id, kind, committees, meeting_date, date_source, special, work_session, page_url
                 FROM committee_documents
                WHERE municipality_id = %s
                  AND status IN ('read', 'no_text')
                  AND kind IS NOT NULL
                  AND meeting_date IS NOT NULL
                  AND cardinality(committees) > 0
                  AND meeting_id IS NULL
                ORDER BY (kind <> 'minutes'), id""",
            (municipality_id,),
        )
        documents = cur.fetchall()

    report = AttachReport()
    created_days: set[date] = set()
    for doc in documents:
        with db_cursor() as cur:
            cur.execute(
                """SELECT id, body_name, video_url
                     FROM meetings
                    WHERE municipality_id = %s AND meeting_date = %s
                      AND is_hidden = FALSE AND meeting_type = 'committee'
                    ORDER BY id""",
                (municipality_id, doc["meeting_date"]),
            )
            candidates = [m for m in cur.fetchall() if committee_of(m["body_name"]) in doc["committees"]]
            if candidates:
                if len(candidates) > 1:
                    report.ambiguous += 1
                    first_named = [m for m in candidates if committee_of(m["body_name"]) == doc["committees"][0]]
                    candidates = sorted(first_named or candidates, key=lambda m: (m["video_url"] is None, m["id"]))
                meeting_id, attached_by = candidates[0]["id"], "matched"
            elif doc["kind"] == "minutes" and doc["date_source"] == "header" and doc["meeting_date"] <= today:
                meeting_id, attached_by = _create_meeting(cur, municipality_id, doc)
            else:
                if doc["kind"] == "minutes":
                    report.unattached_minutes += 1
                else:
                    report.unattached_agendas += 1
                continue
            cur.execute(
                "UPDATE committee_documents SET meeting_id = %s, attached_by = %s WHERE id = %s AND meeting_id IS NULL",
                (meeting_id, attached_by, doc["id"]),
            )
        if attached_by == "created":
            report.created += 1
            created_days.add(doc["meeting_date"])
        else:
            report.matched += 1

    if created_days:
        with db_cursor() as cur:
            cur.execute(
                """SELECT meeting_date
                     FROM meetings
                    WHERE municipality_id = %s AND meeting_date = ANY(%s)
                      AND is_hidden = FALSE AND meeting_type = 'council' AND external_id ~ '^[0-9]+$'
                    GROUP BY meeting_date
                   HAVING count(*) > 1
                    ORDER BY meeting_date""",
                (municipality_id, sorted(created_days)),
            )
            report.crowded_days = [r["meeting_date"] for r in cur.fetchall()]

    log.info(
        "committee documents: attach matched=%d created=%d ambiguous=%d unattached_agendas=%d "
        "unattached_minutes=%d crowded_days=%s",
        report.matched, report.created, report.ambiguous, report.unattached_agendas, report.unattached_minutes,
        [d.isoformat() for d in report.crowded_days],
    )
    return report


def _create_meeting(cur, municipality_id: int, doc: dict) -> tuple[int, str]:
    """Make the meeting a set of minutes proves was held, named for the
    document's first-named committee; returns its id and ``created``. When a
    row already holds the address the new one would take (it was no
    candidate: hidden, or typed otherwise since), nothing is made and that
    row's id is returned with ``matched``."""
    committee = doc["committees"][0]
    external_id = f"cdoc-{source.COMMITTEE_SLUGS[committee].removesuffix('-committee')}-{doc['meeting_date'].isoformat()}"
    title = committee + (" Committee Work Session" if doc["work_session"] else " Committee Meeting")
    if doc["special"]:
        title = "Special Called " + title
    classified = classify_title(title)
    cur.execute(
        """INSERT INTO meetings (municipality_id, external_id, title, meeting_date,
                                 meeting_type, session_kind, body_name, type_source, source_url)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 'title', %s)
           ON CONFLICT (municipality_id, external_id) DO NOTHING
           RETURNING id""",
        (municipality_id, external_id, title, doc["meeting_date"], classified.meeting_type, classified.session_kind,
         classified.body_name, doc["page_url"]),
    )
    row = cur.fetchone()
    if row:
        return row["id"], "created"
    cur.execute(
        "SELECT id FROM meetings WHERE municipality_id = %s AND external_id = %s", (municipality_id, external_id)
    )
    return cur.fetchone()["id"], "matched"


def primary_documents(meeting_id: int) -> dict:
    """The meeting's one primary document of each kind it has, by kind
    (``agenda``, ``minutes``): among its attached documents of that kind, one
    that does not disagree with its listing before one that does, then the
    lowest id. Each is its ``committee_documents`` row without the text. A
    meeting with no document gives an empty dict."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT DISTINCT ON (kind)
                      id, kind, url, page_url, listed_name, status, meeting_date, committees, listing_disagrees,
                      present, trailing_lines, attached_by
                 FROM committee_documents
                WHERE meeting_id = %s AND kind IS NOT NULL
                ORDER BY kind, listing_disagrees, id""",
            (meeting_id,),
        )
        return {r["kind"]: dict(r) for r in cur.fetchall()}


# The categories of an action that is the meeting's own housekeeping and not
# something the committee took up; the page lists these last.
PROCEDURAL_CATEGORIES = frozenset({"minutes_approved", "adjourned"})


@dataclass(frozen=True)
class CommitteeDocumentLink:
    """One of a meeting's documents, as the page links it."""

    kind: str  # 'agenda' | 'minutes'
    url: str
    is_primary: bool
    has_text: bool  # False for a scanned image, which was linked and not read


@dataclass(frozen=True)
class MeetingCommitteeRecord:
    """What a committee's own documents say of one meeting: the documents,
    primaries first, and from the primary minutes who was present and the
    items in the minutes' order. ``minutes_url`` is the primary minutes'
    address, the source of ``present`` and of every item."""

    documents: tuple[CommitteeDocumentLink, ...]
    minutes_url: str | None
    present: str | None
    items: tuple[dict, ...]

    @property
    def has_minutes(self) -> bool:
        return any(d.kind == "minutes" for d in self.documents)

    @property
    def substantive(self) -> tuple[dict, ...]:
        return tuple(i for i in self.items if i["action_category"] not in PROCEDURAL_CATEGORIES)

    @property
    def procedural(self) -> tuple[dict, ...]:
        return tuple(i for i in self.items if i["action_category"] in PROCEDURAL_CATEGORIES)


def for_meeting(meeting_id: int) -> MeetingCommitteeRecord | None:
    """What the meeting page shows of a meeting's committee documents, or
    None when the meeting has none attached. Which document of a kind is
    primary is ``primary_documents``'s to say; the items are the primary
    minutes' alone, so two copies of the minutes never list an item twice."""
    primary = primary_documents(meeting_id)
    if not primary:
        return None
    primary_ids = {d["id"] for d in primary.values()}
    minutes = primary.get("minutes")
    with db_cursor() as cur:
        cur.execute(
            """SELECT id, kind, url, status
                 FROM committee_documents
                WHERE meeting_id = %s AND kind IS NOT NULL
                ORDER BY kind, id""",
            (meeting_id,),
        )
        rows = cur.fetchall()
        items: tuple[dict, ...] = ()
        if minutes:
            cur.execute(
                """SELECT position, group_text, name, body, action_text, action_category, moved_by, seconded_by
                     FROM committee_items
                    WHERE document_id = %s
                    ORDER BY position""",
                (minutes["id"],),
            )
            items = tuple(dict(r) for r in cur.fetchall())
    documents = tuple(
        CommitteeDocumentLink(
            kind=r["kind"], url=r["url"], is_primary=r["id"] in primary_ids, has_text=r["status"] != "no_text"
        )
        for r in sorted(rows, key=lambda r: r["id"] not in primary_ids)
    )
    return MeetingCommitteeRecord(
        documents=documents,
        minutes_url=minutes["url"] if minutes else None,
        present=minutes["present"] if minutes else None,
        items=items,
    )


# How many documents the daily task tries in one run: with the eight pages,
# at most 33 requests, one a second.
DAILY_READ_LIMIT = 25
# The per-committee table of a backfill counts meetings from this day on.
SUMMARY_FROM = date(2026, 1, 1)


@dataclass
class RefreshReport:
    """What one ``refresh_city`` call did: the addresses new to the listing,
    the documents read, the documents read again from stored text, and what
    ``attach`` did."""

    new_listings: int = 0
    read: int = 0
    reparsed: int = 0
    attach: AttachReport = field(default_factory=AttachReport)


def refresh_city(municipality_id: int, metadata: dict, today: date, read_limit: int | None) -> RefreshReport:
    """List, read, read again and attach, in that order, for one city.

    ``metadata`` is the city's ``municipalities.metadata``; its
    ``committee_document_pages`` are the pages listed. The order is what lets
    one call settle a document: it is listed, then read, then attached. When
    every page fails, ``sync_listings`` raises and the call ends there: the
    city's site is down or has changed, and the caller is to hear of it."""
    report = RefreshReport()
    report.new_listings = sync_listings(municipality_id, metadata.get("committee_document_pages") or [])
    report.read = read_pending(municipality_id, limit=read_limit)
    report.reparsed = reparse(municipality_id)
    report.attach = attach(municipality_id, today)
    return report


def refresh_all(today: date) -> int:
    """Refresh every active city whose metadata names its committee pages,
    reading at most ``DAILY_READ_LIMIT`` documents each; returns how many
    cities were refreshed.

    A city that fails is logged and the next is still run; when any failed
    the call raises after the last, so the worker's task reports a failure
    and does not pass for a morning on which nothing was learned."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT id, slug, metadata
                 FROM municipalities
                WHERE active = TRUE AND metadata ? 'committee_document_pages'
                ORDER BY slug"""
        )
        cities = cur.fetchall()

    refreshed = 0
    failed = []
    for city in cities:
        try:
            report = refresh_city(city["id"], city["metadata"], today, DAILY_READ_LIMIT)
        except Exception:
            log.exception("committee documents: %s failed", city["slug"])
            failed.append(city["slug"])
            continue
        log.info(
            "committee documents: %s new_listings=%d read=%d reparsed=%d",
            city["slug"], report.new_listings, report.read, report.reparsed,
        )
        refreshed += 1
    if failed:
        raise RuntimeError(f"committee documents: failed for {', '.join(failed)}")
    return refreshed


@dataclass
class BackfillReport:
    """What one ``backfill`` call did and what the city's tables then held
    (in a dry run, held before the rollback).

    ``created_meetings`` are the ``cdoc-`` meetings that were not there
    before the call, by date. ``documents`` is ``(status, kind, count)``,
    ``items_by_category`` ``(category, count)`` with the commonest first.
    ``committees`` has one dict per canonical committee, counting the city's
    visible committee meetings dated ``SUMMARY_FROM`` or later whose
    ``body_name`` names that committee alone."""

    dry_run: bool
    tables_created: bool
    refresh: RefreshReport
    created_meetings: list[dict]
    documents: list[tuple[str, str | None, int]]
    date_sources: dict[str, int]
    listing_disagrees: int
    items_by_category: list[tuple[str, int]]
    committees: list[dict]


def backfill(
    slug: str, today: date, *, limit: int | None = None, dry_run: bool = False, schema_sql: str | None = None
) -> BackfillReport:
    """Run ``refresh_city`` for one city, reading up to ``limit`` documents
    (None: every one), and report what the tables then hold.

    With ``dry_run`` the pages and the PDFs are fetched and read as usual,
    inside one transaction that is rolled back, so the report says what a
    real run would do and nothing is left. A dry run on a database that has
    not the tables yet runs ``schema_sql`` (migration 045's ``SQL_UP``, which
    the script hands in) inside that same transaction; while it lasts, the
    new tables' references make writes to ``meetings`` and ``municipalities``
    wait. Raises ``ValueError`` for a city that is unknown or names no pages,
    and for a real run without the tables."""
    with _rolled_back() if dry_run else _nothing():
        tables_created = False
        with db_cursor() as cur:
            cur.execute("SELECT to_regclass('committee_documents') IS NULL AS absent")
            if cur.fetchone()["absent"]:
                if not (dry_run and schema_sql):
                    raise ValueError("the committee_documents table does not exist: run the migrations first")
                cur.execute(schema_sql)
                tables_created = True
            cur.execute("SELECT id, metadata FROM municipalities WHERE slug = %s", (slug,))
            city = cur.fetchone()
            if city is None:
                raise ValueError(f"no city with the slug {slug!r}")
            if not city["metadata"].get("committee_document_pages"):
                raise ValueError(f"{slug} has no committee_document_pages in its metadata")
            before = _created_meetings(cur, city["id"])
        refresh = refresh_city(city["id"], city["metadata"], today, limit)
        with db_cursor() as cur:
            held = {m["id"] for m in before}
            created = [m for m in _created_meetings(cur, city["id"]) if m["id"] not in held]
            cur.execute(
                """SELECT status, kind, count(*) AS n
                     FROM committee_documents
                    WHERE municipality_id = %s
                    GROUP BY status, kind
                    ORDER BY status, kind NULLS LAST""",
                (city["id"],),
            )
            documents = [(r["status"], r["kind"], r["n"]) for r in cur.fetchall()]
            cur.execute(
                """SELECT count(*) FILTER (WHERE date_source = 'header') AS header,
                          count(*) FILTER (WHERE date_source = 'heading') AS heading,
                          count(*) FILTER (WHERE date_source IS NULL) AS none,
                          count(*) FILTER (WHERE listing_disagrees) AS disagrees
                     FROM committee_documents
                    WHERE municipality_id = %s AND status IN ('read', 'no_text')""",
                (city["id"],),
            )
            row = cur.fetchone()
            date_sources = {"header": row["header"], "heading": row["heading"], "none": row["none"]}
            cur.execute(
                """SELECT i.action_category, count(*) AS n
                     FROM committee_items i
                     JOIN committee_documents d ON d.id = i.document_id
                    WHERE d.municipality_id = %s
                    GROUP BY i.action_category
                    ORDER BY n DESC, i.action_category""",
                (city["id"],),
            )
            items_by_category = [(r["action_category"], r["n"]) for r in cur.fetchall()]
            committees = _committee_counts(cur, city["id"])
    return BackfillReport(
        dry_run=dry_run,
        tables_created=tables_created,
        refresh=refresh,
        created_meetings=created,
        documents=documents,
        date_sources=date_sources,
        listing_disagrees=row["disagrees"],
        items_by_category=items_by_category,
        committees=committees,
    )


@contextmanager
def _nothing() -> Iterator[None]:
    yield


def _created_meetings(cur, municipality_id: int) -> list[dict]:
    """The city's meetings made from minutes, by date."""
    cur.execute(
        """SELECT id, external_id, title, meeting_date
             FROM meetings
            WHERE municipality_id = %s AND external_id LIKE 'cdoc-%%'
            ORDER BY meeting_date, external_id""",
        (municipality_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def _committee_counts(cur, municipality_id: int) -> list[dict]:
    """Per canonical committee, of its visible meetings since ``SUMMARY_FROM``:
    how many there are, how many have an agenda, minutes, and items, how many
    have a document and no recording, and how many a recording and no
    document."""
    cur.execute(
        """SELECT m.body_name,
                  m.video_url IS NOT NULL AS has_video,
                  EXISTS (SELECT 1 FROM committee_documents d
                           WHERE d.meeting_id = m.id AND d.kind = 'agenda') AS has_agenda,
                  EXISTS (SELECT 1 FROM committee_documents d
                           WHERE d.meeting_id = m.id AND d.kind = 'minutes') AS has_minutes,
                  EXISTS (SELECT 1 FROM committee_items i JOIN committee_documents d ON d.id = i.document_id
                           WHERE d.meeting_id = m.id) AS has_items,
                  EXISTS (SELECT 1 FROM committee_documents d WHERE d.meeting_id = m.id) AS has_document
             FROM meetings m
            WHERE m.municipality_id = %s AND m.meeting_type = 'committee' AND m.is_hidden = FALSE
              AND m.meeting_date >= %s""",
        (municipality_id, SUMMARY_FROM),
    )
    counts = {
        name: {"committee": name, "meetings": 0, "with_agenda": 0, "with_minutes": 0, "with_items": 0,
               "document_no_video": 0, "video_no_document": 0}
        for name in source.COMMITTEES
    }
    for m in cur.fetchall():
        row = counts.get(committee_of(m["body_name"]))
        if row is None:
            continue
        row["meetings"] += 1
        row["with_agenda"] += m["has_agenda"]
        row["with_minutes"] += m["has_minutes"]
        row["with_items"] += m["has_items"]
        row["document_no_video"] += m["has_document"] and not m["has_video"]
        row["video_no_document"] += m["has_video"] and not m["has_document"]
    return list(counts.values())
