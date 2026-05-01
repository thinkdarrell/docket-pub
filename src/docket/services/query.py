"""Query service — read APIs for meetings, agenda items, votes, search.

Every read operation goes through this module. Returns dataclasses or dicts.
"""

from __future__ import annotations

from dataclasses import dataclass

from docket.db import db_cursor
from docket.models.agenda import AgendaItem
from docket.models.meeting import Meeting
from docket.models.vote import MemberVote, Vote


@dataclass(frozen=True)
class PaginatedMeetings:
    """Meetings with pagination metadata."""

    meetings: list[Meeting]
    total: int
    limit: int
    offset: int


def list_municipalities() -> list[dict]:
    """Return all active municipalities with meeting counts."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT m.id, m.slug, m.name, m.state, m.county, m.council_type,
                   COUNT(mt.id) AS meeting_count,
                   MAX(mt.meeting_date) AS last_meeting_date
            FROM municipalities m
            LEFT JOIN meetings mt ON m.id = mt.municipality_id
            WHERE m.active = TRUE
            GROUP BY m.id
            ORDER BY m.name
        """)
        return [dict(row) for row in cur.fetchall()]


def get_municipality(slug: str) -> dict | None:
    """Return a single municipality by slug."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM municipalities WHERE slug = %s AND active = TRUE",
            (slug,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def list_meetings(
    municipality_slug: str,
    meeting_type: str | None = None,
    since: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> PaginatedMeetings:
    """Return meetings for a municipality, newest first, with total count."""
    with db_cursor() as cur:
        where = "m.slug = %s"
        params: list = [municipality_slug]

        if meeting_type:
            where += " AND mt.meeting_type = %s"
            params.append(meeting_type)
        if since:
            where += " AND mt.meeting_date >= %s"
            params.append(since)

        # Total count
        cur.execute(
            f"SELECT COUNT(*) AS count FROM meetings mt "
            f"JOIN municipalities m ON mt.municipality_id = m.id WHERE {where}",
            params,
        )
        total = cur.fetchone()["count"]

        # Paginated results
        cur.execute(
            f"SELECT mt.* FROM meetings mt "
            f"JOIN municipalities m ON mt.municipality_id = m.id "
            f"WHERE {where} ORDER BY mt.meeting_date DESC LIMIT %s OFFSET %s",
            [*params, limit, offset],
        )
        meetings = [Meeting.from_row(dict(row)) for row in cur.fetchall()]

        return PaginatedMeetings(meetings=meetings, total=total, limit=limit, offset=offset)


def get_meeting(meeting_id: int) -> Meeting | None:
    """Return a single meeting by ID."""
    with db_cursor() as cur:
        cur.execute("SELECT * FROM meetings WHERE id = %s", (meeting_id,))
        row = cur.fetchone()
        return Meeting.from_row(dict(row)) if row else None


def list_agenda_items(meeting_id: int) -> list[AgendaItem]:
    """Return agenda items for a meeting."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM agenda_items WHERE meeting_id = %s ORDER BY item_number",
            (meeting_id,),
        )
        return [AgendaItem.from_row(dict(row)) for row in cur.fetchall()]


def list_votes(meeting_id: int) -> list[Vote]:
    """Return votes for a meeting, with member votes attached."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM votes WHERE meeting_id = %s ORDER BY id",
            (meeting_id,),
        )
        votes = [Vote.from_row(dict(row)) for row in cur.fetchall()]

        for vote in votes:
            cur.execute(
                "SELECT * FROM member_votes WHERE vote_id = %s ORDER BY id",
                (vote.id,),
            )
            member_votes = [
                MemberVote(
                    member_name=row["member_name"],
                    position=row["position"],
                    council_member_id=row.get("council_member_id"),
                )
                for row in cur.fetchall()
            ]
            # Replace the empty list with loaded member votes
            object.__setattr__(vote, "member_votes", member_votes)

        return votes


def dashboard_stats() -> dict:
    """Return summary stats for the admin dashboard."""
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS count FROM municipalities WHERE active = TRUE")
        muni_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) AS count FROM meetings")
        meeting_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) AS count FROM agenda_items")
        item_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) AS count FROM votes")
        vote_count = cur.fetchone()["count"]

        return {
            "municipalities": muni_count,
            "meetings": meeting_count,
            "agenda_items": item_count,
            "votes": vote_count,
        }


# --- Council members --------------------------------------------------------


def list_council_members(municipality_slug: str, active_only: bool = True) -> list[dict]:
    """Return council members for a municipality, with district info."""
    with db_cursor() as cur:
        where = "m.slug = %s"
        params: list = [municipality_slug]
        if active_only:
            where += " AND cm.active = TRUE"

        cur.execute(
            f"""
            SELECT cm.*, d.name AS district_name, d.number AS district_number,
                   m.name AS municipality_name
            FROM council_members cm
            JOIN municipalities m ON cm.municipality_id = m.id
            LEFT JOIN districts d ON cm.district_id = d.id
            WHERE {where}
            ORDER BY d.number NULLS FIRST, cm.name
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


def get_council_member(member_id: int) -> dict | None:
    """Return a single council member by ID."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT cm.*, d.name AS district_name, d.number AS district_number,
                   m.name AS municipality_name, m.slug AS municipality_slug
            FROM council_members cm
            JOIN municipalities m ON cm.municipality_id = m.id
            LEFT JOIN districts d ON cm.district_id = d.id
            WHERE cm.id = %s
            """,
            (member_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_member_vote_summary(member_id: int) -> dict:
    """Return vote summary stats and recent votes for a council member."""
    with db_cursor() as cur:
        # Get the member's name to match against member_votes
        cur.execute("SELECT name FROM council_members WHERE id = %s", (member_id,))
        row = cur.fetchone()
        if not row:
            return {"total": 0, "yea": 0, "nay": 0, "abstain": 0, "absent": 0, "recent": []}

        member_name = row["name"]
        # Match on full name or last name (OCR uses "I. Lastname" format)
        last_name = member_name.split()[-1] if member_name else ""

        cur.execute(
            """
            SELECT CASE WHEN mv.position IN ('yea','yes') THEN 'yea'
                        WHEN mv.position IN ('nay','no') THEN 'nay'
                        ELSE mv.position END AS pos,
                   COUNT(*) as cnt
            FROM member_votes mv
            WHERE mv.member_name ILIKE %s OR mv.member_name ILIKE %s
            GROUP BY pos
            """,
            (f"%{last_name}", f"%{member_name}%"),
        )
        counts = {r["pos"]: r["cnt"] for r in cur.fetchall()}

        cur.execute(
            """
            SELECT v.result, v.source, v.yeas, v.nays,
                   CASE WHEN mv.position IN ('yea','yes') THEN 'yea'
                        WHEN mv.position IN ('nay','no') THEN 'nay'
                        ELSE mv.position END AS position,
                   m.meeting_date, m.title
            FROM member_votes mv
            JOIN votes v ON mv.vote_id = v.id
            JOIN meetings m ON v.meeting_id = m.id
            WHERE mv.member_name ILIKE %s OR mv.member_name ILIKE %s
            ORDER BY m.meeting_date DESC, v.id DESC
            LIMIT 20
            """,
            (f"%{last_name}", f"%{member_name}%"),
        )
        recent = [dict(r) for r in cur.fetchall()]

        total = sum(counts.values())
        return {
            "total": total,
            "yea": counts.get("yea", 0),
            "nay": counts.get("nay", 0),
            "abstain": counts.get("abstain", 0),
            "absent": counts.get("absent", 0),
            "recent": recent,
        }


# --- Cross-city queries ----------------------------------------------------


def list_recent_meetings(days: int = 7, limit: int = 20) -> list[dict]:
    """Return recent meetings across all cities, newest first.

    Includes municipality name for display context.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT mt.*, m.name AS municipality_name, m.slug AS municipality_slug
            FROM meetings mt
            JOIN municipalities m ON mt.municipality_id = m.id
            WHERE m.active = TRUE
              AND mt.meeting_date >= CURRENT_DATE - %s
              AND mt.meeting_date <= CURRENT_DATE
            ORDER BY mt.meeting_date DESC
            LIMIT %s
            """,
            (days, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def list_upcoming_meetings(days: int = 14, limit: int = 20) -> list[dict]:
    """Return upcoming meetings across all cities, soonest first."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT mt.*, m.name AS municipality_name, m.slug AS municipality_slug
            FROM meetings mt
            JOIN municipalities m ON mt.municipality_id = m.id
            WHERE m.active = TRUE
              AND mt.meeting_date > CURRENT_DATE
              AND mt.meeting_date <= CURRENT_DATE + %s
            ORDER BY mt.meeting_date ASC
            LIMIT %s
            """,
            (days, limit),
        )
        return [dict(row) for row in cur.fetchall()]


# --- Search -----------------------------------------------------------------


def search_meetings(
    query: str,
    municipality_slug: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Full-text search across meeting titles.

    Scoped to a single city by default. Pass municipality_slug=None for cross-city.
    """
    with db_cursor() as cur:
        where = "m.active = TRUE AND mt.search_vector @@ websearch_to_tsquery('english', %s)"
        params: list = [query]

        if municipality_slug:
            where += " AND m.slug = %s"
            params.append(municipality_slug)

        cur.execute(
            f"""
            SELECT mt.*, m.name AS municipality_name, m.slug AS municipality_slug,
                   ts_rank(mt.search_vector, websearch_to_tsquery('english', %s)) AS rank
            FROM meetings mt
            JOIN municipalities m ON mt.municipality_id = m.id
            WHERE {where}
            ORDER BY rank DESC, mt.meeting_date DESC
            LIMIT %s OFFSET %s
            """,
            (query, *params, limit, offset),
        )
        return [dict(row) for row in cur.fetchall()]


def search_agenda_items(
    query: str,
    municipality_slug: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Full-text search across agenda item titles and descriptions.

    Scoped to a single city by default. Pass municipality_slug=None for cross-city.
    """
    with db_cursor() as cur:
        where = "m.active = TRUE AND ai.search_vector @@ websearch_to_tsquery('english', %s)"
        params: list = [query]

        if municipality_slug:
            where += " AND m.slug = %s"
            params.append(municipality_slug)

        cur.execute(
            f"""
            SELECT ai.*, mt.title AS meeting_title, mt.meeting_date,
                   m.name AS municipality_name, m.slug AS municipality_slug,
                   ts_rank(ai.search_vector, websearch_to_tsquery('english', %s)) AS rank
            FROM agenda_items ai
            JOIN meetings mt ON ai.meeting_id = mt.id
            JOIN municipalities m ON mt.municipality_id = m.id
            WHERE {where}
            ORDER BY rank DESC, mt.meeting_date DESC
            LIMIT %s OFFSET %s
            """,
            (query, *params, limit, offset),
        )
        return [dict(row) for row in cur.fetchall()]


# --- Topic browsing ---------------------------------------------------------


def list_agenda_items_by_topic(
    topic: str,
    municipality_slug: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Return agenda items filtered by topic, optionally scoped to a city."""
    with db_cursor() as cur:
        where = "ai.topic = %s"
        params: list = [topic]

        if municipality_slug:
            where += " AND m.slug = %s"
            params.append(municipality_slug)

        cur.execute(
            f"""
            SELECT ai.*, mt.title AS meeting_title, mt.meeting_date,
                   m.name AS municipality_name, m.slug AS municipality_slug
            FROM agenda_items ai
            JOIN meetings mt ON ai.meeting_id = mt.id
            JOIN municipalities m ON mt.municipality_id = m.id
            WHERE m.active = TRUE AND {where}
            ORDER BY mt.meeting_date DESC
            LIMIT %s OFFSET %s
            """,
            [*params, limit, offset],
        )
        return [dict(row) for row in cur.fetchall()]


def topic_counts(municipality_slug: str | None = None) -> list[dict]:
    """Return count of agenda items per topic, for browse-by-topic UI."""
    with db_cursor() as cur:
        where = "ai.topic IS NOT NULL"
        params: list = []

        if municipality_slug:
            where += " AND m.slug = %s"
            params.append(municipality_slug)

        cur.execute(
            f"""
            SELECT ai.topic, COUNT(*) AS count
            FROM agenda_items ai
            JOIN meetings mt ON ai.meeting_id = mt.id
            JOIN municipalities m ON mt.municipality_id = m.id
            WHERE m.active = TRUE AND {where}
            GROUP BY ai.topic
            ORDER BY count DESC
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


# --- High-value item queries ------------------------------------------------


def list_high_dollar_items(
    min_dollars: float = 50000,
    municipality_slug: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Return notable high-dollar agenda items, balancing amount and recency.

    Uses a composite score: items from the last 90 days are ranked purely by
    dollar amount; older items are progressively discounted so that a $1M item
    from last month outranks a $5M item from 2016.
    """
    with db_cursor() as cur:
        where = "ai.dollars_amount >= %s"
        params: list = [min_dollars]

        if municipality_slug:
            where += " AND m.slug = %s"
            params.append(municipality_slug)

        cur.execute(
            f"""
            SELECT ai.*, mt.title AS meeting_title, mt.meeting_date,
                   m.name AS municipality_name, m.slug AS municipality_slug
            FROM agenda_items ai
            JOIN meetings mt ON ai.meeting_id = mt.id
            JOIN municipalities m ON mt.municipality_id = m.id
            WHERE m.active = TRUE AND {where}
            ORDER BY
                ai.dollars_amount
                / GREATEST(1, EXTRACT(EPOCH FROM (NOW() - mt.meeting_date)) / 86400 / 90)
                DESC
            LIMIT %s
            """,
            [*params, limit],
        )
        return [dict(row) for row in cur.fetchall()]
