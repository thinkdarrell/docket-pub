"""Query service — read APIs for meetings, agenda items, votes, search.

Every read operation goes through this module. Returns dataclasses or dicts.
"""

from __future__ import annotations

from dataclasses import dataclass

from docket.db import db_cursor
from docket.models.agenda import AgendaItem
from docket.models.meeting import Meeting
from docket.models.vote import AgendaItemLink, MemberVote, Vote


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


def list_votes(meeting_id: int, *, include_excerpts: bool = False) -> list[Vote]:
    """Return votes for a meeting, with N:M agenda links and member votes.

    Three queries: votes, vote_agenda_items joined to agenda_items, member_votes.
    Grouped in Python — three round-trips per page regardless of vote count.

    include_excerpts: when False (default), excerpt_context is NULL'd out in the
    SELECT to keep payloads small. Templates and audit views that need the
    snippet should pass include_excerpts=True.
    """
    excerpt_select = "vai.excerpt_context" if include_excerpts else "NULL AS excerpt_context"

    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM votes WHERE meeting_id = %s ORDER BY id",
            (meeting_id,),
        )
        vote_rows = cur.fetchall()
        if not vote_rows:
            return []

        vote_ids = [r["id"] for r in vote_rows]

        cur.execute(
            f"""SELECT vai.id, vai.vote_id, vai.agenda_item_id,
                       vai.association_type, vai.match_method, vai.match_confidence,
                       vai.provisional, vai.is_manual, vai.is_active,
                       {excerpt_select},
                       ai.item_number, ai.title, ai.is_consent
                FROM vote_agenda_items vai
                JOIN agenda_items ai ON ai.id = vai.agenda_item_id
                WHERE vai.vote_id = ANY(%s)
                ORDER BY vai.vote_id, vai.match_confidence DESC, vai.id ASC""",
            (vote_ids,),
        )
        link_rows = cur.fetchall()

        cur.execute(
            "SELECT * FROM member_votes WHERE vote_id = ANY(%s) ORDER BY vote_id, id",
            (vote_ids,),
        )
        member_rows = cur.fetchall()

    links_by_vote: dict[int, list[AgendaItemLink]] = {}
    for r in link_rows:
        links_by_vote.setdefault(r["vote_id"], []).append(AgendaItemLink(
            id=r["id"],
            agenda_item_id=r["agenda_item_id"],
            item_number=r["item_number"],
            title=r["title"],
            is_consent=r["is_consent"],
            association_type=r["association_type"],
            match_method=r["match_method"],
            match_confidence=r["match_confidence"],
            excerpt_context=r["excerpt_context"],
            provisional=r["provisional"],
            is_manual=r["is_manual"],
            is_active=r["is_active"],
        ))

    members_by_vote: dict[int, list[MemberVote]] = {}
    for r in member_rows:
        members_by_vote.setdefault(r["vote_id"], []).append(MemberVote(
            member_name=r["member_name"],
            position=r["position"],
            council_member_id=r.get("council_member_id"),
        ))

    return [
        Vote(
            id=r["id"],
            meeting_id=r["meeting_id"],
            external_id=r.get("external_id"),
            result=r.get("result", ""),
            yeas=r.get("yeas"),
            nays=r.get("nays"),
            abstentions=r.get("abstentions"),
            source=r.get("source", ""),
            confidence=r.get("confidence", ""),
            header_result=r.get("header_result"),
            needs_review=bool(r.get("needs_review", False)),
            review_reason=r.get("review_reason"),
            resolution_number=r.get("resolution_number"),
            video_timestamp=r.get("video_timestamp"),
            agenda_links=links_by_vote.get(r["id"], []),
            member_votes=members_by_vote.get(r["id"], []),
        )
        for r in vote_rows
    ]


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


def list_recent_votes(municipality_slug: str, limit: int = 10) -> list[dict]:
    """Return recent votes with member breakdown, newest first."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT v.id, v.result, v.yeas, v.nays, v.abstentions,
                   v.source, v.confidence, v.needs_review,
                   m.meeting_date, m.title, m.id as meeting_id
            FROM votes v
            JOIN meetings m ON v.meeting_id = m.id
            JOIN municipalities mu ON m.municipality_id = mu.id
            WHERE mu.slug = %s
            ORDER BY m.meeting_date DESC, v.id DESC
            LIMIT %s
            """,
            (municipality_slug, limit),
        )
        votes = [dict(r) for r in cur.fetchall()]
        _attach_member_votes(cur, votes)
        return votes


def list_contested_votes(municipality_slug: str, limit: int = 6) -> list[dict]:
    """Return recent votes where nays > 0, newest first."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT v.id, v.result, v.yeas, v.nays, v.abstentions,
                   v.source, v.confidence,
                   m.meeting_date, m.title, m.id as meeting_id
            FROM votes v
            JOIN meetings m ON v.meeting_id = m.id
            JOIN municipalities mu ON m.municipality_id = mu.id
            WHERE mu.slug = %s AND v.nays > 0
            ORDER BY m.meeting_date DESC, v.id DESC
            LIMIT %s
            """,
            (municipality_slug, limit),
        )
        votes = [dict(r) for r in cur.fetchall()]
        _attach_member_votes(cur, votes)
        return votes


def _attach_member_votes(cur, votes: list[dict]) -> None:
    """Batch-load member_votes for a list of vote dicts (single query instead of N+1)."""
    if not votes:
        return
    vote_ids = [v["id"] for v in votes]
    cur.execute(
        """SELECT vote_id, member_name, position FROM member_votes
           WHERE vote_id = ANY(%s) ORDER BY vote_id, id""",
        (vote_ids,),
    )
    by_vote: dict[int, list] = {}
    for r in cur.fetchall():
        by_vote.setdefault(r["vote_id"], []).append(dict(r))
    for v in votes:
        v["member_votes"] = by_vote.get(v["id"], [])


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
    """Return vote summary stats and recent votes for a council member.

    Each recent-vote dict carries an `agenda_links` list of dicts (one per
    linked agenda_item, filtered to is_active=TRUE) with item_number, title,
    and association_type — so the UI can show what was voted on, with
    consent-block votes rendered as a count rather than a single title.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT CASE WHEN mv.position IN ('yea','yes') THEN 'yea'
                        WHEN mv.position IN ('nay','no') THEN 'nay'
                        ELSE mv.position END AS pos,
                   COUNT(*) as cnt
            FROM member_votes mv
            WHERE mv.council_member_id = %s
            GROUP BY pos
            """,
            (member_id,),
        )
        counts = {r["pos"]: r["cnt"] for r in cur.fetchall()}

        cur.execute(
            """
            SELECT v.id AS vote_id, v.result, v.source, v.yeas, v.nays,
                   CASE WHEN mv.position IN ('yea','yes') THEN 'yea'
                        WHEN mv.position IN ('nay','no') THEN 'nay'
                        ELSE mv.position END AS position,
                   m.id AS meeting_id, m.meeting_date, m.title,
                   m.minutes_url, m.video_url, m.agenda_url, m.source_url
            FROM member_votes mv
            JOIN votes v ON mv.vote_id = v.id
            JOIN meetings m ON v.meeting_id = m.id
            WHERE mv.council_member_id = %s
            ORDER BY m.meeting_date DESC, v.id DESC
            LIMIT 20
            """,
            (member_id,),
        )
        recent = [dict(r) for r in cur.fetchall()]

        if recent:
            vote_ids = [r["vote_id"] for r in recent]
            cur.execute(
                """SELECT vai.vote_id, vai.association_type, vai.match_method,
                          vai.provisional, ai.item_number, ai.title AS item_title
                   FROM vote_agenda_items vai
                   JOIN agenda_items ai ON ai.id = vai.agenda_item_id
                   WHERE vai.vote_id = ANY(%s) AND vai.is_active
                   ORDER BY vai.vote_id, vai.match_confidence DESC, vai.id ASC""",
                (vote_ids,),
            )
            links_by_vote: dict = {}
            for r in cur.fetchall():
                links_by_vote.setdefault(r["vote_id"], []).append(dict(r))
            for v in recent:
                v["agenda_links"] = links_by_vote.get(v["vote_id"], [])

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
    days: int | None = None,
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

        if days:
            where += " AND mt.meeting_date >= CURRENT_DATE - %s * INTERVAL '1 day'"
            params.append(days)

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
