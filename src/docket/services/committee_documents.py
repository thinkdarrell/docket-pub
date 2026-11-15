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

Nothing here writes ``agenda_items``, ``votes``, ``meetings.agenda_url`` or
``meetings.minutes_url``: every reader of those treats a row as council
business. A committee's action is its minutes' own words and one of a closed
list of categories, never a vote.

Plan `committee-documents`, M3 (listing, reading, storing) and M4 (attaching).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date

from docket.adapters import committee_documents as source
from docket.adapters._helpers import classify_title
from docket.analysis.minutes_parser import extract_text_from_pdf
from docket.db import db_cursor

log = logging.getLogger(__name__)

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
