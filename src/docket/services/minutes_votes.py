"""Votes read from a city's minutes files: read, pair to a meeting, store, attach by code.

A city whose ``adapter_config`` names a ``minutes_reader`` has its listed
Minutes files read by that reader (``docket.analysis.mobile_minutes`` for
``mobile``). This module owns everything that reading writes. Plan
`mobile-votes-from-minutes`, M3 and M4.

Two callers: stage 4b of ``docket.services.ingest.ingest_municipality``, every
day, with the adapter that listed the city's events; and ``read_city``, the
entry of ``scripts/read_minutes_votes.py``, which lists them itself.

One file is one row of ``minutes_files``, whatever became of it:

- ``paired``: its heading dates it to the one meeting the city has on that
  date. That meeting's votes from a reader are replaced by the file's votes
  (``source`` ``minutes_text``, ``minutes_reader`` the reader's name, with the
  page, caption, motion and declaration), its member votes are resolved
  against the roster on the meeting date, and its ``minutes_url`` becomes the
  file's address.
- ``superseded``: another file already holds that meeting, and this one is
  not attached to the meeting's own event. A file on the meeting's own event
  takes the meeting from a file on another event.
- ``not_minutes``: its heading lines print no one date.
- ``no_meeting``: its date is before the city's ``backlog_floor``, or the
  city has no meeting, or more than one, on that date.
- ``error``: the fetch or the read raised. It is tried again by a later run
  until it has failed ``MAX_ATTEMPTS`` times.

A file that is not paired stores no vote, and a meeting whose ``minutes_url``
was that file's address loses the link (``docs/PRINCIPLES.md``, Source or
silence). A file is read once: a later run reads only files with no row, rows
written under a lower ``READER_VERSION``, and ``error`` rows with attempts
left.

No transaction is open while a file is fetched or parsed. ``read_listed``
first fetches and reads every file it took, holding the readings in memory,
then stores them, one transaction per file; a dry run stores them all on one
connection and rolls it back.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date

import psycopg2.extras

from docket.adapters import get_adapter
from docket.analysis import mobile_minutes
from docket.db import db, db_cursor
from docket.models.protocol import RawMeeting, RawMinutesFile
from docket.services.member_votes import RosterIndex, load_roster_index

logger = logging.getLogger(__name__)

# A reader is a module of `docket.analysis` with `READER_VERSION`,
# `read_minutes(pages)` and `pages_from_pdf(pdf_bytes)`.
_READERS = {"mobile": mobile_minutes}

DEFAULT_READ_CAP = 10
MAX_ATTEMPTS = 3

_POSITIONS = (("ayes", "yea"), ("nays", "nay"), ("abstain", "abstain"), ("absent", "absent"))

_LINK_BY_CODE_SQL = r"""
    INSERT INTO vote_agenda_items
        (vote_id, agenda_item_id, association_type, match_method, match_confidence, provisional, is_manual, is_active)
    SELECT v.id, min(ai.id), 'explicit', 'minutes_code', 1.0, FALSE, FALSE, TRUE
      FROM votes v
      JOIN meetings m ON m.id = v.meeting_id
      JOIN agenda_items ai ON ai.meeting_id = v.meeting_id
       AND substring(ai.title from '^(\d{2}-\d{3,4})\y') = substring(v.resolution_number from '^(\d{2}-\d{3,4})-\d{4}$')
     WHERE m.municipality_id = %s
       AND v.minutes_reader IS NOT NULL
       AND v.resolution_number IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM vote_agenda_items x WHERE x.vote_id = v.id)
     GROUP BY v.id
    HAVING count(*) = 1
    ON CONFLICT (vote_id, agenda_item_id) DO NOTHING
"""

_INSERT_VOTES_SQL = """
    INSERT INTO votes
        (meeting_id, external_id, result, yeas, nays, abstentions, source, confidence,
         needs_review, review_reason, raw_text, resolution_number,
         minutes_reader, source_page, caption, motion_text, declared_text)
    VALUES %s
    RETURNING id, external_id
"""

_INSERT_MEMBER_VOTES_SQL = """
    INSERT INTO member_votes (vote_id, council_member_id, member_name, position) VALUES %s
"""

_UPSERT_FILE_SQL = """
    INSERT INTO minutes_files
        (municipality_id, file_id, url, event_external_id, status, header_date, meeting_id,
         page_count, votes_stored, reader_version, attempts, error, read_at)
    VALUES (%(municipality_id)s, %(file_id)s, %(url)s, %(event_external_id)s, %(status)s,
            %(header_date)s, %(meeting_id)s, %(page_count)s, %(votes_stored)s,
            %(reader_version)s, %(attempts)s, %(error)s, NOW())
    ON CONFLICT (municipality_id, file_id) DO UPDATE SET
        url = EXCLUDED.url,
        event_external_id = EXCLUDED.event_external_id,
        status = EXCLUDED.status,
        header_date = EXCLUDED.header_date,
        meeting_id = EXCLUDED.meeting_id,
        page_count = EXCLUDED.page_count,
        votes_stored = EXCLUDED.votes_stored,
        reader_version = EXCLUDED.reader_version,
        attempts = EXCLUDED.attempts,
        error = EXCLUDED.error,
        read_at = EXCLUDED.read_at
"""


@dataclass
class FileOutcome:
    """What became of one file in one run."""

    file_id: str
    event_external_id: str
    header_date: date | None
    status: str  # 'paired' | 'superseded' | 'not_minutes' | 'no_meeting' | 'error'
    meeting_id: int | None
    votes: int
    error: str | None


@dataclass
class ReadReport:
    files: list[FileOutcome]
    waiting: int  # candidates left unread by the cap


@dataclass
class _Read:
    """One file after the first pass: its reading, or the text of what was raised."""

    file: RawMinutesFile
    reading: mobile_minutes.MinutesReading | None
    page_count: int | None
    error: str | None


def reader_settings(adapter_config: dict) -> tuple[str | None, int]:
    """(reader, cap). 'minutes_reader' absent or null: (None, 0). Its only value is 'mobile'.

    'minutes_read_cap' absent or null: 10; a whole number of 0 or more otherwise.
    Raises ValueError naming the key; true and false are not whole numbers here.
    """
    config = adapter_config or {}

    reader = config.get("minutes_reader")
    if reader is None:
        return None, 0
    if not isinstance(reader, str) or reader not in _READERS:
        known = ", ".join(repr(name) for name in sorted(_READERS))
        raise ValueError(f"minutes_reader must be one of {known}, not {reader!r}")

    cap = config.get("minutes_read_cap")
    if cap is None:
        return reader, DEFAULT_READ_CAP
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 0:
        raise ValueError(f"minutes_read_cap must be a whole number of 0 or more, not {cap!r}")
    return reader, cap


def with_paired_links(municipality_id: int, raw_meetings: list[RawMeeting]) -> list[RawMeeting]:
    """The listed meetings with ``minutes_url`` decided by ``minutes_files``.

    A meeting a ``paired`` row names gets that file's address. A meeting an
    ``error`` row names keeps its stored link while that link is the row's
    address: the file held the meeting and failed a later read, which says
    nothing about the file. Any other meeting keeps the link its listing gave
    only while the file that link names has not been read (no row) or failed
    to read (``error``); once the file has been read and is not this
    meeting's, the meeting has no link.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT mf.url, mf.status, m.external_id, m.minutes_url AS stored_url
              FROM minutes_files mf
              LEFT JOIN meetings m ON m.id = mf.meeting_id
             WHERE mf.municipality_id = %s
            """,
            (municipality_id,),
        )
        rows = cur.fetchall()

    paired = {r["external_id"]: r["url"] for r in rows if r["status"] == "paired" and r["external_id"] is not None}
    still_held = {
        r["external_id"]: r["url"]
        for r in rows
        if r["status"] == "error" and r["external_id"] is not None and r["stored_url"] == r["url"]
    }
    status_of = {r["url"]: r["status"] for r in rows}

    decided: list[RawMeeting] = []
    for meeting in raw_meetings:
        if meeting.external_id in paired:
            url = paired[meeting.external_id]
        elif meeting.external_id in still_held:
            url = still_held[meeting.external_id]
        elif meeting.minutes_url is not None and status_of.get(meeting.minutes_url, "error") == "error":
            url = meeting.minutes_url
        else:
            url = None
        decided.append(meeting if url == meeting.minutes_url else replace(meeting, minutes_url=url))
    return decided


def read_listed(
    municipality_id: int,
    adapter,
    *,
    cap: int,
    dry_run: bool = False,
    fetch_pages: Callable[[RawMinutesFile], list[str]] | None = None,
) -> ReadReport:
    """Read up to ``cap`` of the city's listed Minutes files that are waiting, and store them.

    ``adapter`` gives ``listed_minutes_files()`` and, unless ``fetch_pages``
    is given, ``fetch_file(url)``. The files are taken newest event first. A
    fetch or read that raises is that file's ``error`` and the run goes on.
    In a dry run every statement is run and then rolled back. Raises
    ValueError for a city whose ``adapter_config`` names no reader.
    """
    # Inside the function: `docket.services.ingest` calls this module.
    from docket.services.ingest import _backlog_settings

    with db_cursor() as cur:
        cur.execute("SELECT slug, adapter_config FROM municipalities WHERE id = %s", (municipality_id,))
        city = cur.fetchone()
        if city is None:
            raise ValueError(f"Municipality {municipality_id} not found")
        cur.execute(
            "SELECT file_id, status, attempts, reader_version FROM minutes_files WHERE municipality_id = %s",
            (municipality_id,),
        )
        stored = {r["file_id"]: r for r in cur.fetchall()}

    reader_name, _ = reader_settings(city["adapter_config"])
    if reader_name is None:
        raise ValueError(f"adapter_config of {city['slug']} names no minutes_reader")
    reader = _READERS[reader_name]
    version = reader.READER_VERSION
    floor, _ = _backlog_settings(city["adapter_config"])

    if fetch_pages is None:
        def fetch_pages(file: RawMinutesFile) -> list[str]:
            return reader.pages_from_pdf(adapter.fetch_file(file.url))

    listed = sorted(adapter.listed_minutes_files(), key=lambda f: f.event_date, reverse=True)
    candidates = [f for f in listed if _is_waiting(stored.get(f.file_id), version)]
    taken = candidates[: max(cap, 0)]
    report = ReadReport(files=[], waiting=len(candidates) - len(taken))
    if not taken:
        return report

    # First pass: the network and the PDF, with no connection open.
    reads: list[_Read] = []
    for file in taken:
        try:
            pages = fetch_pages(file)
            reads.append(_Read(file, reader.read_minutes(pages), len(pages), None))
        except Exception as exc:
            logger.warning("Minutes file %s: %s", file.file_id, exc)
            reads.append(_Read(file, None, None, str(exc) or type(exc).__name__))

    roster = load_roster_index(municipality_id)

    # Second pass: one transaction per file; in a dry run, one for all, rolled back.
    def store(conn, read: _Read) -> FileOutcome:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            return _store(cur, municipality_id, reader_name, version, floor, roster, read)

    if dry_run:
        with db() as conn:
            report.files = [store(conn, read) for read in reads]
            conn.rollback()
    else:
        for read in reads:
            with db() as conn:
                report.files.append(store(conn, read))
    return report


def link_votes_by_code(municipality_id: int) -> int:
    """Attach each coded reader vote to the one agenda item of its meeting that opens with its code.

    A vote's code is ``NN-NNN-YYYY`` and an item's title opens ``NN-NNN``. A
    vote with no such item, or two, gets nothing; a vote that has any link,
    active or not, is never touched, so a link an admin removed stays
    removed; ``_replace_votes`` carries such a link to the vote that replaces
    its own. Returns how many links were made.
    """
    with db_cursor() as cur:
        cur.execute(_LINK_BY_CODE_SQL, (municipality_id,))
        return cur.rowcount


def read_city(slug: str, *, limit: int, apply: bool) -> ReadReport:
    """The script's entry. ValueError for an unknown slug and for a city whose adapter_config names no reader.

    Lists the city's events from its ``backlog_floor`` with the city's own
    adapter, then reads up to ``limit`` waiting Minutes files as
    ``read_listed`` does: stored when ``apply`` is true, run and rolled back
    otherwise. Coded votes are attached to their agenda items only when
    applying. A setting that cannot be read is a ValueError too, raised
    before the adapter is built, so nothing is asked of the city.
    """
    from docket.services.ingest import _backlog_settings

    with db_cursor() as cur:
        cur.execute("SELECT id, adapter_class, adapter_config FROM municipalities WHERE slug = %s", (slug,))
        city = cur.fetchone()
    if city is None:
        raise ValueError(f"Municipality '{slug}' not found")
    reader_name, _ = reader_settings(city["adapter_config"])
    if reader_name is None:
        raise ValueError(f"adapter_config of {slug} names no minutes_reader")
    floor, _ = _backlog_settings(city["adapter_config"])

    adapter = get_adapter(city["adapter_class"], slug, city["adapter_config"])
    adapter.list_meetings(since=floor)
    report = read_listed(city["id"], adapter, cap=limit, dry_run=not apply)
    if apply:
        linked = link_votes_by_code(city["id"])
        logger.info("Minutes votes linked by code: %d", linked)
    return report


def _is_waiting(row: dict | None, version: int) -> bool:
    """Whether a listed file is to be read: never read, read under an older version, or failed with attempts left."""
    if row is None or row["reader_version"] < version:
        return True
    return row["status"] == "error" and row["attempts"] < MAX_ATTEMPTS


def _store(
    cur,
    municipality_id: int,
    reader_name: str,
    version: int,
    floor: date | None,
    roster: RosterIndex,
    read: _Read,
) -> FileOutcome:
    """Write one file's outcome on the caller's transaction."""
    file = read.file
    cur.execute(
        "SELECT url, status, attempts, reader_version, header_date, meeting_id, page_count, votes_stored "
        "FROM minutes_files WHERE municipality_id = %s AND file_id = %s FOR UPDATE",
        (municipality_id, file.file_id),
    )
    prior = cur.fetchone()
    # Only another try of a row that failed under this version counts on; a
    # file read again for a newer version starts again.
    retry = prior is not None and prior["status"] == "error" and prior["reader_version"] >= version
    row = {
        "municipality_id": municipality_id,
        "file_id": file.file_id,
        "url": file.url,
        "event_external_id": file.event_external_id,
        "reader_version": version,
        "attempts": prior["attempts"] + 1 if retry else 1,
        "header_date": None,
        "meeting_id": None,
        "page_count": read.page_count,
        "votes_stored": 0,
        "error": read.error,
    }

    if read.reading is None:
        # Nothing was read, so nothing stored for this file before is undone.
        if prior is not None:
            row.update({k: prior[k] for k in ("header_date", "meeting_id", "page_count", "votes_stored")})
        row["status"] = "error"
        cur.execute(_UPSERT_FILE_SQL, row)
        return FileOutcome(file.file_id, file.event_external_id, row["header_date"], "error", row["meeting_id"], 0, read.error)

    reading = read.reading
    row["header_date"] = reading.header_date
    status, meeting = _pair(cur, municipality_id, floor, file, reading.header_date)
    row["status"] = status
    row["meeting_id"] = meeting["id"] if meeting is not None else None

    # A meeting this file held before and does not hold now loses the votes and the link it gave.
    held = _held_meeting(cur, prior)
    if held is not None and held != row["meeting_id"]:
        _delete_reader_votes(cur, held)
        cur.execute("UPDATE meetings SET minutes_url = NULL WHERE id = %s AND minutes_url = %s", (held, prior["url"]))

    if status == "paired":
        cur.execute(
            "UPDATE minutes_files SET status = 'superseded' WHERE meeting_id = %s AND status = 'paired' AND file_id <> %s",
            (meeting["id"], file.file_id),
        )
        row["votes_stored"] = _replace_votes(cur, meeting, reader_name, roster, reading.votes)
        cur.execute("UPDATE meetings SET minutes_url = %s WHERE id = %s", (file.url, meeting["id"]))
        # The listing may have given this address to the meeting of the file's event; it is not that meeting's.
        cur.execute(
            "UPDATE meetings SET minutes_url = NULL WHERE municipality_id = %s AND minutes_url = %s AND id <> %s",
            (municipality_id, file.url, meeting["id"]),
        )
    else:
        cur.execute(
            "UPDATE meetings SET minutes_url = NULL WHERE municipality_id = %s AND minutes_url = %s",
            (municipality_id, file.url),
        )

    cur.execute(_UPSERT_FILE_SQL, row)
    return FileOutcome(
        file.file_id, file.event_external_id, reading.header_date, status, row["meeting_id"], row["votes_stored"], None
    )


def _held_meeting(cur, prior: dict | None) -> int | None:
    """The meeting a file's stored row holds, if any.

    A ``paired`` row holds its meeting. An ``error`` row does while its
    meeting's ``minutes_url`` is still its address: it was paired and failed a
    later read, and no other file has taken the meeting since. A row that is
    ``error`` after being ``superseded`` names a meeting whose link is
    another file's, and holds nothing.
    """
    if prior is None or prior["meeting_id"] is None:
        return None
    if prior["status"] == "paired":
        return prior["meeting_id"]
    if prior["status"] == "error":
        cur.execute("SELECT 1 FROM meetings WHERE id = %s AND minutes_url = %s", (prior["meeting_id"], prior["url"]))
        if cur.fetchone() is not None:
            return prior["meeting_id"]
    return None


def _pair(cur, municipality_id: int, floor: date | None, file: RawMinutesFile, header_date: date | None):
    """(status, meeting row or None) for a file that was read."""
    if header_date is None:
        return "not_minutes", None
    if floor is not None and header_date < floor:
        return "no_meeting", None
    cur.execute(
        "SELECT id, external_id, meeting_date FROM meetings WHERE municipality_id = %s AND meeting_date = %s",
        (municipality_id, header_date),
    )
    meetings = cur.fetchall()
    if len(meetings) != 1:
        return "no_meeting", None
    meeting = meetings[0]
    cur.execute(
        "SELECT file_id FROM minutes_files WHERE meeting_id = %s AND status = 'paired' AND file_id <> %s",
        (meeting["id"], file.file_id),
    )
    if cur.fetchone() is None or file.event_external_id == meeting["external_id"]:
        return "paired", meeting
    return "superseded", meeting


def _delete_reader_votes(cur, meeting_id: int) -> None:
    """A meeting's votes from a reader; their member votes and links go by cascade. No other vote is touched."""
    cur.execute("DELETE FROM votes WHERE meeting_id = %s AND minutes_reader IS NOT NULL", (meeting_id,))


def _replace_votes(cur, meeting: dict, reader_name: str, roster: RosterIndex, votes) -> int:
    """Replace the meeting's reader votes with these: two insert statements, whatever the count.

    A link someone removed or set by hand on a vote being replaced is put on
    the vote that replaces it (``_carry_hand_links``), a third statement only
    where there is such a link.
    """
    hand_links = _hand_links(cur, meeting["id"])
    _delete_reader_votes(cur, meeting["id"])
    if not votes:
        if hand_links:
            logger.warning(
                "Meeting %s: %d hand-made vote link(s) dropped, the file has no vote", meeting["id"], len(hand_links)
            )
        return 0

    by_external_id = {f"{meeting['external_id']}-mv-{n}": vote for n, vote in enumerate(votes, start=1)}
    vote_rows = [
        (
            meeting["id"], external_id, vote.result, len(vote.ayes), len(vote.nays), len(vote.abstain),
            "minutes_text", "medium" if vote.needs_review else "high",
            vote.needs_review, vote.review_reason, vote.raw_text, vote.code,
            reader_name, vote.page, vote.caption, vote.motion_text, vote.declared_text,
        )
        for external_id, vote in by_external_id.items()
    ]
    stored = psycopg2.extras.execute_values(
        cur, _INSERT_VOTES_SQL, vote_rows, page_size=len(vote_rows), fetch=True
    )

    member_rows = []
    for stored_vote in stored:
        vote = by_external_id[stored_vote["external_id"]]
        for attribute, position in _POSITIONS:
            for name in getattr(vote, attribute):
                member_rows.append((stored_vote["id"], roster.resolve(name, meeting["meeting_date"]), name, position))
    if member_rows:
        psycopg2.extras.execute_values(cur, _INSERT_MEMBER_VOTES_SQL, member_rows, page_size=len(member_rows))
    if hand_links:
        new_votes = [(stored_vote["id"], by_external_id[stored_vote["external_id"]]) for stored_vote in stored]
        _carry_hand_links(cur, meeting["id"], hand_links, new_votes)
    return len(vote_rows)


_LINK_COLUMNS = (
    "agenda_item_id", "association_type", "match_method", "match_confidence", "excerpt_context",
    "provisional", "is_manual", "is_active", "created_at", "updated_at",
)


def _hand_links(cur, meeting_id: int) -> list[dict]:
    """The links of a meeting's reader votes that someone removed or set by hand, each with its vote's ``key``.

    One statement where there is no such link, two where there is.
    """
    cur.execute(
        f"""
        SELECT x.vote_id, {", ".join("x." + c for c in _LINK_COLUMNS)}
          FROM vote_agenda_items x
          JOIN votes v ON v.id = x.vote_id
         WHERE v.meeting_id = %s AND v.minutes_reader IS NOT NULL AND (x.is_manual OR NOT x.is_active)
         ORDER BY x.id
        """,
        (meeting_id,),
    )
    links = [dict(r) for r in cur.fetchall()]
    if not links:
        return []
    cur.execute(
        "SELECT id, resolution_number, raw_text FROM votes WHERE meeting_id = %s AND minutes_reader IS NOT NULL",
        (meeting_id,),
    )
    key_of = _vote_keys([(r["id"], r["resolution_number"], r["raw_text"]) for r in cur.fetchall()])
    return [dict(link, key=key_of.get(link["vote_id"])) for link in links]


def _vote_keys(votes: list[tuple[int, str | None, str | None]]) -> dict[int, tuple[str, str]]:
    """vote id -> what tells it from the other votes given: its code, or failing that its own words.

    ``votes`` is (id, code, raw text). A vote whose code no other vote here
    has is ``('code', code)``; otherwise one whose text no other has is
    ``('text', text)``; a vote that has neither has no key.
    """
    codes = Counter(code for _, code, _ in votes if code)
    texts = Counter(text for _, _, text in votes if text)
    keys: dict[int, tuple[str, str]] = {}
    for vote_id, code, text in votes:
        if code and codes[code] == 1:
            keys[vote_id] = ("code", code)
        elif text and texts[text] == 1:
            keys[vote_id] = ("text", text)
    return keys


def _carry_hand_links(cur, meeting_id: int, hand_links: list[dict], new_votes: list[tuple[int, object]]) -> None:
    """Put each hand-made link on the one new vote that is the vote it was on; drop it where that cannot be told.

    The vote it was on is found by code, and by its own words where the code
    does not tell it, never by its place in the file: a newer reader may find
    a vote the older one missed, and every place after it moves. A link whose
    vote is not found is dropped and logged, so the vote reads as never
    linked and the code join may attach it (``docs/PRINCIPLES.md``, Source or
    silence: no link is better than one moved to another vote).
    """
    triples = [(vote_id, vote.code, vote.raw_text) for vote_id, vote in new_votes]
    # A new vote can be found by its code and, separately, by its words.
    codes = Counter(code for _, code, _ in triples if code)
    texts = Counter(text for _, _, text in triples if text)
    found: dict[tuple[str, str], int] = {}
    for vote_id, code, text in triples:
        if code and codes[code] == 1:
            found[("code", code)] = vote_id
        if text and texts[text] == 1:
            found[("text", text)] = vote_id

    rows = []
    dropped = 0
    for link in hand_links:
        new_id = found.get(link["key"]) if link["key"] is not None else None
        if new_id is None:
            dropped += 1
            continue
        rows.append((new_id, *(link[c] for c in _LINK_COLUMNS)))
    if dropped:
        logger.warning(
            "Meeting %s: %d hand-made vote link(s) dropped, the vote each was on is not told apart in the new reading",
            meeting_id, dropped,
        )
    if rows:
        psycopg2.extras.execute_values(
            cur,
            f"INSERT INTO vote_agenda_items (vote_id, {', '.join(_LINK_COLUMNS)}) VALUES %s "
            "ON CONFLICT (vote_id, agenda_item_id) DO NOTHING",
            rows,
            page_size=len(rows),
        )
