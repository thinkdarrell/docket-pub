"""Query service — read APIs for meetings, agenda items, votes, search.

Every read operation goes through this module. Returns dataclasses or dicts.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Iterable, Sequence

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
    """Return agenda items for a meeting (list-page shape, A8).

    SELECT carries the v2 columns plus the v3 columns the Smart Brevity
    Card dispatcher and its sub-partials read (spec §6.1 — A8). Heavy
    JSONB blobs are kept lean:

    - ``extracted_facts``: pulled via jsonb_extract_path for the specific
      keys the v3 cards render (counterparty, funding_source,
      procurement_method, action_type, location, next_steps). The full
      blob is detail-page-only (separate query, not built here).
    - ``source_anchor``: small enough to inline as full JSONB.
    - ``ai_metadata``: kept as-is for v2 fallback (`confidence`/`phase`
      are read directly by ``card_v2_fallback.html``).

    Badges come from a correlated ``jsonb_agg`` subquery joining
    ``agenda_item_badges`` to ``priority_badge_templates`` so the row
    arrives shaped like the BadgeChip dict the ``_badge_row.html``
    partial expects (kind / slug / name / icon / description /
    confidence). Empty array when an item has no badges.

    EXPLAIN ANALYZE on a 100-item meeting must keep the plan on the
    indexed ``meeting_id`` path (no seq scan on ``agenda_items``) and
    the badges subquery on ``idx_agenda_item_badges_item``. See PR body
    for the captured plan.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
                ai.id,
                ai.meeting_id,
                ai.external_id,
                ai.item_number,
                ai.title,
                ai.description,
                ai.section,
                ai.is_consent,
                ai.sponsor,
                ai.dollars_amount,
                ai.topic,
                ai.significance_score,
                ai.consent_placement_score,
                ai.summary,
                ai.ai_metadata,
                ai.ai_prompt_version,
                ai.ai_generated_at,
                -- v3 flat columns
                ai.data_quality::text       AS data_quality,
                ai.data_debt_priority::text AS data_debt_priority,
                ai.processing_status::text  AS processing_status,
                ai.ai_extraction_version,
                ai.ai_rewrite_version,
                ai.ai_confidence,
                ai.headline,
                ai.why_it_matters,
                -- Small JSONB inline
                ai.source_anchor,
                -- LEAN extracted_facts: build a dict containing only the keys
                -- the v3 cards render. NULL out empty objects so Jinja's
                -- `or {}` guards collapse cleanly. Each individual key is
                -- pulled with jsonb_extract_path so a missing source key
                -- yields NULL (not the literal JSONB null).
                CASE
                    WHEN ai.extracted_facts IS NULL THEN NULL
                    ELSE jsonb_strip_nulls(jsonb_build_object(
                        'counterparty',       ai.extracted_facts->>'counterparty',
                        'funding_source',     ai.extracted_facts->>'funding_source',
                        'procurement_method', ai.extracted_facts->>'procurement_method',
                        'action_type',        ai.extracted_facts->>'action_type',
                        'location',           ai.extracted_facts->'location',
                        'next_steps',         ai.extracted_facts->'next_steps'
                    ))
                END AS extracted_facts,
                -- Badge JOIN: aggregate matching templates into a
                -- BadgeChip-shaped jsonb array. COALESCE to '[]' so
                -- AgendaItem.from_row() always sees a list. The
                -- subquery uses the (agenda_item_id) index from
                -- migration 013 (idx_agenda_item_badges_item).
                --
                -- NOTE: badge confidence values arrive as Decimal through
                -- the JSONB-agg round-trip (NUMERIC(3,2) column →
                -- jsonb_build_object → jsonb_agg → psycopg → Python).
                -- Consumers comparing to a float should explicitly cast
                -- (e.g., ``float(chip["confidence"]) >= 1.0``) — direct
                -- comparison works in Python but is non-obvious. See
                -- partials/badge_chip.html for the rendering side.
                COALESCE(b_agg.badges, '[]'::jsonb) AS badges
            FROM agenda_items ai
            LEFT JOIN LATERAL (
                SELECT jsonb_agg(jsonb_build_object(
                           'kind',        b.kind,
                           'slug',        b.badge_slug,
                           'confidence',  b.confidence,
                           'name',        t.name,
                           'icon',        t.icon,
                           'description', t.description
                       ) ORDER BY b.detected_at DESC) AS badges
                FROM agenda_item_badges b
                JOIN priority_badge_templates t ON t.slug = b.badge_slug
                WHERE b.agenda_item_id = ai.id
                  -- Refactor #2 retro fix (HIGH): hide flagged badges
                  -- from citizen meeting-detail rendering. Admins still
                  -- see flagged badges via /admin/badge-review queries
                  -- (which do not use this helper).
                  AND b.status = 'applied'
            ) b_agg ON true
            WHERE ai.meeting_id = %s
              -- Refactor #2 retro fix (HIGH): hide withdrawn items
              -- from citizen meeting-detail rendering. Council-removed
              -- items shouldn't render as "awaiting summary" — they
              -- have their own dedicated bucket. A future spec may
              -- add a "Show N withdrawn items" toggle for journalists;
              -- not in v1.
              AND ai.processing_status != 'withdrawn'
            -- Natural sort on item_number. Pre-A8 this was a plain
            -- TEXT sort, which lexicographically placed item "10"
            -- before "2" — wrong for the Birmingham agenda shape
            -- (1, 2, 10, 10A, 10B, 11, A.1, A.2). Strategy:
            --   1. Strip everything from the first non-digit onward to
            --      isolate the leading numeric prefix ("10A" -> "10",
            --      "A.1" -> "", "1" -> "1").
            --   2. NULLIF '' -> NULL, then ::int casts numeric prefixes
            --      to integers so they sort numerically.
            --   3. COALESCE(..., 999999) sends items with no leading
            --      digit (and rows where item_number itself is NULL)
            --      to the end.
            --   4. Tie-breaker on the full string puts "10A" before
            --      "10B"; NULLS LAST keeps NULL item_numbers truly
            --      last within the sentinel bucket.
            ORDER BY
                COALESCE(
                    NULLIF(
                        regexp_replace(COALESCE(ai.item_number, ''), '\D.*$', ''),
                        ''
                    )::int,
                    999999
                ),
                ai.item_number NULLS LAST
            """,
            (meeting_id,),
        )
        return [AgendaItem.from_row(dict(row)) for row in cur.fetchall()]


def get_agenda_item(item_id: int) -> AgendaItem | None:
    """Return a single agenda item by ID (same column shape as list_agenda_items)."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
                ai.id,
                ai.meeting_id,
                ai.external_id,
                ai.item_number,
                ai.title,
                ai.description,
                ai.section,
                ai.is_consent,
                ai.sponsor,
                ai.dollars_amount,
                ai.topic,
                ai.significance_score,
                ai.consent_placement_score,
                ai.summary,
                ai.ai_metadata,
                ai.ai_prompt_version,
                ai.ai_generated_at,
                ai.data_quality::text       AS data_quality,
                ai.data_debt_priority::text AS data_debt_priority,
                ai.processing_status::text  AS processing_status,
                ai.ai_extraction_version,
                ai.ai_rewrite_version,
                ai.ai_confidence,
                ai.headline,
                ai.why_it_matters,
                ai.source_anchor,
                CASE
                    WHEN ai.extracted_facts IS NULL THEN NULL
                    ELSE jsonb_strip_nulls(jsonb_build_object(
                        'counterparty',       ai.extracted_facts->>'counterparty',
                        'funding_source',     ai.extracted_facts->>'funding_source',
                        'procurement_method', ai.extracted_facts->>'procurement_method',
                        'action_type',        ai.extracted_facts->>'action_type',
                        'location',           ai.extracted_facts->'location',
                        'next_steps',         ai.extracted_facts->'next_steps'
                    ))
                END AS extracted_facts,
                COALESCE(b_agg.badges, '[]'::jsonb) AS badges
            FROM agenda_items ai
            LEFT JOIN LATERAL (
                SELECT jsonb_agg(jsonb_build_object(
                           'kind',        b.kind,
                           'slug',        b.badge_slug,
                           'confidence',  b.confidence,
                           'name',        t.name,
                           'icon',        t.icon,
                           'description', t.description
                       ) ORDER BY b.detected_at DESC) AS badges
                FROM agenda_item_badges b
                JOIN priority_badge_templates t ON t.slug = b.badge_slug
                WHERE b.agenda_item_id = ai.id
                  AND b.status = 'applied'
            ) b_agg ON true
            WHERE ai.id = %s
            """,
            (item_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return AgendaItem.from_row(dict(row))


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


# --- Badge-filtered item queries (Phase 2 / F1) -----------------------------


def _lookup_template_kind_and_hints(
    city_id: int, badge_slug: str
) -> tuple[str, dict] | None:
    """Single round-trip helper: returns ``(kind, effective_hints)`` for a
    (city, badge) pair, or ``None`` if the badge slug is unknown.

    Effective hints = per-key JSONB merge of ``default_matcher_hints``
    (template) overlaid with ``matcher_hints_override`` (city). Override
    keys win on duplicates; default keys survive when not overridden.

    PostgreSQL ``||`` on JSONB performs shallow merge — keys present in
    the right operand replace keys in the left, but unrelated keys from
    the left are preserved. This is intentional: a city setting only
    ``{"min_significance": 7}`` should not silently lose template-default
    ``keywords`` / ``action_types`` / etc., which the previous
    whole-object COALESCE did.

    This is the single source of truth for matcher-hint resolution; the
    public helpers (``resolve_significance_threshold``,
    ``resolve_matcher_hints``) build on it so they stay consistent.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT t.kind,
                   COALESCE(t.default_matcher_hints, '{}'::jsonb)
                     || COALESCE(c.matcher_hints_override, '{}'::jsonb)
                       AS effective_hints
            FROM priority_badge_templates t
            LEFT JOIN priority_badges_config c
                   ON c.template_slug = t.slug
                  AND c.city_id = %s
            WHERE t.slug = %s
            """,
            (city_id, badge_slug),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return row["kind"], (row["effective_hints"] or {})


def resolve_matcher_hints(city_id: int, badge_slug: str) -> dict | None:
    """Return the effective ``matcher_hints`` dict for a (city, badge) pair.

    Per-key JSONB merge of template defaults with the city's override:
    ``defaults || override`` — override wins on duplicate keys, default
    keys survive when not overridden. Returns ``None`` for unknown slugs.

    This is the helper Track 1 / D2 deterministic matchers should call
    when reading non-significance keys (``keywords``, ``action_types``,
    ``topics``, ``excluded_action_types``). ``resolve_significance_threshold``
    is a thin wrapper specialized for the ``min_significance`` read.

    Process badges and policy badges resolve their hints the same way;
    consumers that need to branch on kind should call
    ``_lookup_template_kind_and_hints`` directly (or call
    ``resolve_significance_threshold`` which already encodes the
    process-badge branch).
    """
    result = _lookup_template_kind_and_hints(city_id, badge_slug)
    if result is None:
        return None
    _kind, hints = result
    return hints


def resolve_significance_threshold(city_id: int, badge_slug: str) -> int | None:
    """Return the policy-significance threshold for a (city, badge) pair.

    Decision #61 — render-time significance gate. Three call sites need it:

    1. ``list_items_by_badge`` (this module) for category landing pages.
    2. Search-results narrowed by badge slug.
    3. Smart Brevity Card chip rendering (per-item badge filter) — uses
       the in-Python sibling ``apply_policy_significance_gate`` below
       since SQL pushdown isn't available in a Jinja loop.

    Resolution:

    - Look up the template ``kind`` in ``priority_badge_templates``.
    - **Process** badges have no significance gate ever — return ``None``.
    - **Policy** badges read ``min_significance`` from the effective
      matcher_hints dict (template defaults merged with the city's
      override per ``resolve_matcher_hints``). If the city has no
      ``priority_badges_config`` row for this template (e.g., the template
      is seeded but the city hasn't opted in), we still fall back to
      ``default_matcher_hints`` — the *enablement* gate lives elsewhere;
      this helper just tells callers what threshold to apply if they
      decide to render the badge at all.
    - Default threshold is ``3`` if the hints dict is missing
      ``min_significance`` (matches migration 013 seeds).

    Unknown badge slugs return ``None`` (no gate). The spec at §6.5 does not
    explicitly say how to treat unknown slugs — returning None is the
    least-surprising behavior because it lets callers degrade gracefully:
    a category page for a non-existent badge will show no items anyway
    (the slug join in ``list_items_by_badge`` filters them out), so an
    extra "no gate" answer here is harmless. F2 (route handler) is
    responsible for 404'ing on unknown slugs at the route level.
    """
    result = _lookup_template_kind_and_hints(city_id, badge_slug)
    if result is None:
        # Unknown slug — no gate. Caller's slug filter will return [].
        return None
    kind, hints = result
    if kind != "policy":
        # Process badges are always-on; never gated by significance.
        return None
    # min_significance default is 3 per migration 013 seeds.
    return int(hints.get("min_significance", 3))


def apply_policy_significance_gate(
    items: Iterable[AgendaItem],
    badge_slug: str,
    city_id: int,
) -> list[AgendaItem]:
    """Filter items by per-badge significance threshold (in-Python).

    Sibling to ``resolve_significance_threshold`` (SQL-pushdown helper).
    For callers that have items already in memory (Smart Brevity Card
    chip rendering, post-fetch filtering) where SQL pushdown isn't
    possible — e.g., a Jinja loop iterating an item's badge chips and
    deciding which to render. The SQL-pushdown sibling is preferred for
    query construction; this wrapper exists for the chip-rendering
    call site (G-track).

    Behavior:

    - Process badges → no filtering (all items returned).
    - Unknown slug   → no filtering (defensive — caller should 404
      separately at the route level).
    - Policy badge   → items with ``significance_score < threshold``
      dropped. Items with NULL ``significance_score`` are treated as 0
      and excluded by the gate (consistent with the SQL ``>=`` predicate
      in ``list_items_by_badge`` which would also exclude NULL).

    Threshold logic stays in ``resolve_significance_threshold`` so all
    three call sites (listing SQL, search-narrowing SQL, in-Python chip
    rendering) plus future matchers (Track 1 / D2) read consistent values.
    """
    threshold = resolve_significance_threshold(city_id, badge_slug)
    if threshold is None:
        return list(items)
    return [it for it in items if (it.significance_score or 0) >= threshold]


def list_items_by_badge(
    city_id: int,
    badge_slug: str,
    *,
    min_confidence: float = 0.6,
    cross_filter_slugs: Sequence[str] = (),
    limit: int = 25,
    offset: int = 0,
    include_low_significance: bool = False,
    month_filter: str | None = None,
) -> list[AgendaItem]:
    """Return items in ``city_id`` carrying ``badge_slug``, ordered for the
    category landing page (spec §6.5, decision #61).

    Filters in order of selectivity:

    1. ``aib.city_id = %s AND aib.badge_slug = %s`` — uses
       ``idx_agenda_item_badges_city_slug_conf (city_id, badge_slug,
       confidence DESC)`` from migration 013 (decision #92), the index
       designed for this exact predicate.
    2. ``aib.confidence >= min_confidence`` — same index covers the
       confidence DESC tail. Default 0.6 hides single-source matches
       (decision #61); admins toggle to 0.0 for review.
    3. ``ai.processing_status = 'completed'`` — only show items that
       finished v3 processing. v2 / pre-v3 items don't render via the
       Smart Brevity Card path so they shouldn't surface on category pages.
    4. **Render-time significance gate** (policy only,
       ``include_low_significance=False``): ``ai.significance_score >=
       resolved_threshold``. Process badges always render; admin toggle
       bypasses the gate for review.
    5. **Cross-filter slugs**: each adds an ``EXISTS`` subquery so the
       item must carry every cross-filter badge in addition to the
       primary slug. AND semantics, no confidence filter on cross
       (intentional — cross-filters are a "show items also tagged X"
       refinement, not a quality gate).

    Ordering: ``meeting_date DESC, dollars_amount DESC NULLS LAST`` so
    recent items lead and big-ticket items break ties within a date.

    Returns the same ``AgendaItem`` shape as ``list_agenda_items`` minus
    the badges JSONB aggregate (this listing is already badge-scoped, so
    rendering doesn't need a chip array). The Smart Brevity Card partial
    handles a missing/empty ``badges`` field gracefully.
    """
    threshold = (
        None
        if include_low_significance
        else resolve_significance_threshold(city_id, badge_slug)
    )

    sql_parts = [
        """
        SELECT
            ai.id,
            ai.meeting_id,
            m.meeting_date,
            ai.external_id,
            ai.item_number,
            ai.title,
            ai.description,
            ai.section,
            ai.is_consent,
            ai.sponsor,
            ai.dollars_amount,
            ai.topic,
            ai.significance_score,
            ai.consent_placement_score,
            ai.summary,
            ai.ai_metadata,
            ai.ai_prompt_version,
            ai.ai_generated_at,
            ai.data_quality::text       AS data_quality,
            ai.data_debt_priority::text AS data_debt_priority,
            ai.processing_status::text  AS processing_status,
            ai.ai_extraction_version,
            ai.ai_rewrite_version,
            ai.ai_confidence,
            ai.headline,
            ai.why_it_matters,
            ai.source_anchor,
            -- LEAN extracted_facts: same projection as list_agenda_items
            -- (A8). Builds a dict containing only the keys v3 cards
            -- render. NULL out empty objects so Jinja's `or {}` guards
            -- collapse cleanly. Each individual key is pulled with a
            -- direct ``->>`` / ``->`` so a missing source key yields
            -- NULL (not the literal JSONB null). Payload parity between
            -- this listing and meeting-detail keeps Smart Brevity Card
            -- partials behaving identically across both surfaces.
            CASE
                WHEN ai.extracted_facts IS NULL THEN NULL
                ELSE jsonb_strip_nulls(jsonb_build_object(
                    'counterparty',       ai.extracted_facts->>'counterparty',
                    'funding_source',     ai.extracted_facts->>'funding_source',
                    'procurement_method', ai.extracted_facts->>'procurement_method',
                    'action_type',        ai.extracted_facts->>'action_type',
                    'location',           ai.extracted_facts->'location',
                    'next_steps',         ai.extracted_facts->'next_steps'
                ))
            END AS extracted_facts
        FROM agenda_items ai
        JOIN agenda_item_badges aib ON aib.agenda_item_id = ai.id
        JOIN meetings m ON m.id = ai.meeting_id
        WHERE aib.city_id = %s
          AND aib.badge_slug = %s
          AND aib.confidence >= %s
          AND aib.status = 'applied'
          AND ai.processing_status = 'completed'
        """
    ]
    params: list = [city_id, badge_slug, min_confidence]

    if threshold is not None:
        sql_parts.append(" AND ai.significance_score >= %s")
        params.append(threshold)

    for cross_slug in cross_filter_slugs:
        sql_parts.append(
            """
              AND EXISTS (
                  SELECT 1 FROM agenda_item_badges x
                  WHERE x.agenda_item_id = ai.id
                    AND x.badge_slug = %s
                    AND x.status = 'applied'
              )
            """
        )
        params.append(cross_slug)

    # ?month=YYYY-MM drill-down. Defensive regex check — the route also
    # validates, but a misuse from another caller shouldn't smuggle a
    # free-form string into SQL. date_trunc on meeting_date is safe
    # because meeting_date is DATE (no TZ semantics).
    if month_filter:
        import re as _re
        if _re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month_filter):
            sql_parts.append(
                " AND date_trunc('month', m.meeting_date)::date = %s::date "
            )
            params.append(f"{month_filter}-01")

    sql_parts.append(
        """
        ORDER BY m.meeting_date DESC, ai.dollars_amount DESC NULLS LAST
        LIMIT %s OFFSET %s
        """
    )
    params.extend([limit, offset])

    with db_cursor() as cur:
        cur.execute("".join(sql_parts), params)
        return [AgendaItem.from_row(dict(row)) for row in cur.fetchall()]


# --- Category landing helpers (Phase 2 / F2) --------------------------------


def get_resolved_badge(city_id: int, badge_slug: str) -> dict | None:
    """Resolve a badge for a city — applies name/description overrides.

    Single round-trip LEFT JOIN of ``priority_badge_templates`` against
    ``priority_badges_config`` on ``(template_slug, city_id)``. Returns
    a dict shaped for template rendering:

    - ``slug``        — template slug (primary key)
    - ``name``        — ``COALESCE(c.name_override, t.name)``
    - ``description`` — ``COALESCE(c.description_override, t.description)``
    - ``icon``        — emoji from the template
    - ``kind``        — ``'process'`` | ``'policy'``
    - ``enabled``     — ``COALESCE(c.enabled, TRUE)`` — process badges
      have no config row, so the COALESCE surfaces ``TRUE`` for them.

    Returns ``None`` when:

    1. The template doesn't exist (unknown slug), OR
    2. The badge is **policy** and the city has no ``enabled=TRUE``
       row in ``priority_badges_config`` (policy badges are city-opt-in
       per spec §4.2 / decision #11). Process badges are always-on
       across cities and resolve template-only.

    F4 review fix-up (R1): the prior implementation required a
    ``priority_badges_config`` row for *every* badge (process or policy)
    with ``enabled=TRUE``. That broke process-badge category landing
    pages on every city — the homepage Browse-by-Priority grid linked
    to ``/al/<city>/<process_slug>/`` for all 7 process badges, every
    one of which 404'd because process badges are intentionally NOT
    seeded into ``priority_badges_config``. The LEFT JOIN + ``kind =
    'process' OR enabled = TRUE`` clause matches the always-on contract
    set in the spec.

    Single call site (``category_landing`` in ``web/public.py``) — the
    LEFT-JOIN relaxation is downstream-safe; no admin/search/RSS path
    consumes this helper.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT t.slug,
                   COALESCE(c.name_override, t.name)               AS name,
                   COALESCE(c.description_override, t.description) AS description,
                   t.icon,
                   t.kind,
                   COALESCE(c.enabled, TRUE)                       AS enabled
            FROM priority_badge_templates t
            LEFT JOIN priority_badges_config c
                   ON c.template_slug = t.slug
                  AND c.city_id = %s
            WHERE t.slug = %s
              AND (t.kind = 'process' OR c.enabled = TRUE)
            """,
            (city_id, badge_slug),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def category_kpis(
    city_id: int,
    badge_slug: str,
    year: int,
    *,
    cross_filter_slugs: Sequence[str] = (),
) -> dict:
    """KPI strip data for a category landing page (spec §6.5).

    Returns a dict with three keys:

    - ``item_count``           — total items with this badge in the
      year for the city. Only ``processing_status = 'completed'`` items
      with ``aib.confidence >= 0.6`` are counted, matching the listing's
      default render contract (``list_items_by_badge``). Policy badges
      additionally apply the per-badge ``min_significance`` gate via
      ``resolve_significance_threshold`` so KPI counts always match the
      listed cards. Cross-filter slugs apply the same AND-semantic
      EXISTS filter the listing helper applies, so KPIs narrow with
      filters in lock-step.
    - ``total_dollars``        — sum of ``ai.dollars_amount`` across the
      same set. NULL dollars treated as 0 via ``COALESCE``. Returned as
      a Python ``Decimal`` (PostgreSQL ``NUMERIC`` round-trip).
    - ``mayor_priority_quote`` — None for v1. Phase 4 / spec line 3052
      will wire mayoral-priority annotations from ``mayoral_terms`` and
      a yet-to-be-built priorities table; this stub keeps the template
      contract stable so F4/F5 don't churn.

    Year filter uses ``meeting_date BETWEEN '<year>-01-01' AND
    '<year>-12-31'`` (inclusive boundary on both ends — the upper bound
    catches December 31 meetings cleanly).

    F2 review fix-up (R1): the original implementation skipped both
    the significance gate and cross-filter respect, so for a policy
    badge like ``blight_accountability`` (``min_significance=3``) and
    a cross-filtered view, citizens saw KPI counts that did not match
    the rendered card count below. Both gates are now applied here so
    the KPI strip and the listing share an identical predicate set.
    """
    threshold = resolve_significance_threshold(city_id, badge_slug)

    sql_parts = [
        """
        SELECT COUNT(*)                              AS item_count,
               COALESCE(SUM(ai.dollars_amount), 0)   AS total_dollars
        FROM agenda_item_badges aib
        JOIN agenda_items ai ON ai.id = aib.agenda_item_id
        JOIN meetings m      ON m.id = ai.meeting_id
        WHERE aib.city_id = %s
          AND aib.badge_slug = %s
          AND aib.confidence >= 0.6
          AND aib.status = 'applied'
          AND ai.processing_status = 'completed'
          AND m.meeting_date BETWEEN %s AND %s
        """
    ]
    params: list = [city_id, badge_slug, f"{year}-01-01", f"{year}-12-31"]

    if threshold is not None:
        sql_parts.append(" AND ai.significance_score >= %s")
        params.append(threshold)

    for cross_slug in cross_filter_slugs:
        sql_parts.append(
            """
              AND EXISTS (
                  SELECT 1 FROM agenda_item_badges x
                  WHERE x.agenda_item_id = ai.id
                    AND x.badge_slug = %s
                    AND x.status = 'applied'
              )
            """
        )
        params.append(cross_slug)

    with db_cursor() as cur:
        cur.execute("".join(sql_parts), params)
        row = cur.fetchone() or {}
        return {
            "item_count": int(row.get("item_count") or 0),
            "total_dollars": row.get("total_dollars") or 0,
            "mayor_priority_quote": None,
        }


def category_tally(
    city_id: int,
    badge_slug: str,
    *,
    cross_filter_slugs: Sequence[str] = (),
) -> dict:
    """All-time-indexed tally for the category-landing chart tally band.

    Replaces the year-scoped ``category_kpis()`` — partial-backfill
    year scopes give misleading "X items this year" numbers when the
    worker hasn't processed history yet. The all-time-indexed framing
    is more honest: it answers "what does our index hold for this
    badge so far?" Pairs with the chart's backfill banner which
    discloses the % of all indexable items processed.

    Returns::

        {
            "indexed_count":   int,
            "indexed_months":  int,        # distinct months in result set
            "total_dollars":   Decimal,
            "peak_month": {                # or None when result set is empty
                "year_month": "YYYY-MM",
                "items":      int,
                "dollars":    Decimal,
            },
        }

    Predicate matches ``list_items_by_badge`` (same significance
    threshold + cross-filter rules) so the tally and the listed cards
    can never disagree.

    Spec: 2026-05-12-category-landing-redesign-design.md §2 tally band.
    """
    from decimal import Decimal

    threshold = resolve_significance_threshold(city_id, badge_slug)

    where_clauses = [
        "aib.city_id = %s",
        "aib.badge_slug = %s",
        "aib.confidence >= 0.6",
        "aib.status = 'applied'",
        "ai.processing_status = 'completed'",
    ]
    params: list = [city_id, badge_slug]

    if threshold is not None:
        where_clauses.append("ai.significance_score >= %s")
        params.append(threshold)

    cross_join = ""
    for cross_slug in cross_filter_slugs:
        cross_join += """
              AND EXISTS (
                  SELECT 1 FROM agenda_item_badges x
                  WHERE x.agenda_item_id = ai.id
                    AND x.badge_slug = %s
                    AND x.status = 'applied'
              )
        """
        params.append(cross_slug)

    where_sql = " AND ".join(where_clauses) + cross_join

    sql = f"""
        WITH src AS (
            SELECT ai.id,
                   ai.dollars_amount,
                   m.meeting_date,
                   to_char(m.meeting_date, 'YYYY-MM') AS year_month
            FROM agenda_item_badges aib
            JOIN agenda_items ai ON ai.id = aib.agenda_item_id
            JOIN meetings m      ON m.id = ai.meeting_id
            WHERE {where_sql}
        ),
        aggregates AS (
            SELECT
                COUNT(*)                                  AS indexed_count,
                COUNT(DISTINCT year_month)                AS indexed_months,
                COALESCE(SUM(dollars_amount), 0)::numeric AS total_dollars
            FROM src
        ),
        monthly AS (
            SELECT year_month,
                   COUNT(*)                                  AS items,
                   COALESCE(SUM(dollars_amount), 0)::numeric AS dollars
            FROM src GROUP BY year_month
        ),
        peak AS (
            SELECT * FROM monthly ORDER BY items DESC, year_month DESC LIMIT 1
        )
        SELECT
            a.indexed_count,
            a.indexed_months,
            a.total_dollars,
            p.year_month AS peak_year_month,
            p.items      AS peak_items,
            p.dollars    AS peak_dollars
        FROM aggregates a
        LEFT JOIN peak p ON true
    """

    with db_cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()

    peak = None
    if row and row["peak_year_month"]:
        peak = {
            "year_month": row["peak_year_month"],
            "items": int(row["peak_items"] or 0),
            "dollars": row["peak_dollars"] or Decimal("0"),
        }

    return {
        "indexed_count": int(row["indexed_count"] or 0) if row else 0,
        "indexed_months": int(row["indexed_months"] or 0) if row else 0,
        "total_dollars": (row["total_dollars"] if row else None) or Decimal("0"),
        "peak_month": peak,
    }


def city_backfill_ratio(city_id: int) -> float | None:
    """Read the cached per-city v3-completion ratio from
    ``mv_city_backfill_ratio`` (migration 025).

    Returns a float in [0.0, 1.0] for cities with indexable items,
    or ``None`` for cities with zero indexable items (NULLIF guard).
    Callers treat ``None`` as the conservative "< 5%" banner state.

    The MV is refreshed daily by the cron worker
    (``worker/tasks.py:refresh_backfill_ratio_mv``).

    Defensive: if the MV doesn't exist yet (deploys can land the new
    code before the migration applies in some edge cases), return
    ``None`` rather than 500ing the whole category-landing page.
    """
    import psycopg2

    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT ratio FROM mv_city_backfill_ratio WHERE city_id = %s",
                (city_id,),
            )
            row = cur.fetchone()
    except psycopg2.errors.UndefinedTable:
        return None
    if not row or row["ratio"] is None:
        return None
    return float(row["ratio"])


def resolve_badges(
    city_id: int, badge_slugs: Sequence[str]
) -> dict[str, dict]:
    """Batch-resolve multiple badges for a city — single round-trip.

    Returns a dict mapping ``slug → {slug, name, description, icon, kind,
    enabled}`` with per-badge ``name_override`` / ``description_override``
    applied (same shape ``get_resolved_badge`` returns). Slugs that don't
    resolve — unknown templates, no city config row, or rows with
    ``enabled = FALSE`` — are omitted from the dict; callers check
    membership and degrade gracefully (e.g., fall back to the raw slug
    label).

    Used by the category-landing route to label cross-filter chips
    without N+1 queries — reviewers flagged the chip-label resolution as
    a sibling helper need (S5). Empty input list short-circuits without
    hitting the DB.

    SQL uses ``WHERE t.slug = ANY(%s)`` — psycopg2 binds a Python list
    to a PostgreSQL ``TEXT[]`` cleanly, so the join filter scales to any
    number of slugs without per-slug round-trips.
    """
    if not badge_slugs:
        return {}
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT t.slug,
                   COALESCE(c.name_override, t.name)               AS name,
                   COALESCE(c.description_override, t.description) AS description,
                   t.icon,
                   t.kind,
                   c.enabled
            FROM priority_badge_templates t
            JOIN priority_badges_config c
              ON c.template_slug = t.slug
             AND c.city_id = %s
            WHERE t.slug = ANY(%s)
              AND c.enabled = TRUE
            """,
            (city_id, list(badge_slugs)),
        )
        return {row["slug"]: dict(row) for row in cur.fetchall()}


# --- Volume timeline (F3) ---------------------------------------------------
#
# SVG layout constants for the category-landing volume timeline (spec
# §6.6). The viewBox is 800x200; we reserve 14px at the top for the
# mayoral-term label band (`<text y="14">`) and 10px at the bottom for
# the year-tick labels (`<text y="195">`). That leaves the bar plotting
# area at y=20..185 (height 165). Constants live up here so a reviewer
# can see the layout intent at a glance and so the test asserting
# coordinate math has a single source of truth to import.

VOLUME_TIMELINE_WIDTH = 800.0
VOLUME_TIMELINE_HEIGHT = 200.0
VOLUME_TIMELINE_TOP_PAD = 20.0       # term-overlay label band
VOLUME_TIMELINE_BOTTOM_PAD = 15.0    # year-tick labels (text at y=195)
VOLUME_TIMELINE_PLOT_TOP = VOLUME_TIMELINE_TOP_PAD                    # 20
VOLUME_TIMELINE_PLOT_BOTTOM = VOLUME_TIMELINE_HEIGHT - VOLUME_TIMELINE_BOTTOM_PAD  # 185
VOLUME_TIMELINE_PLOT_HEIGHT = VOLUME_TIMELINE_PLOT_BOTTOM - VOLUME_TIMELINE_PLOT_TOP  # 165


def _months_in_range(start_date, end_date) -> list:
    """Yield first-of-month dates between start_date and end_date inclusive.

    Always starts at ``DATE_TRUNC('month', start_date)``; preserves the
    "every month gets a slot" property so adjacent bars never visually
    touch when one month happens to have zero items. Dates with day != 1
    are normalized to month-start.
    """
    from datetime import date as _date

    start_month = _date(start_date.year, start_date.month, 1)
    end_month = _date(end_date.year, end_date.month, 1)
    months: list = []
    cursor = start_month
    while cursor <= end_month:
        months.append(cursor)
        # advance one month
        if cursor.month == 12:
            cursor = _date(cursor.year + 1, 1, 1)
        else:
            cursor = _date(cursor.year, cursor.month + 1, 1)
    return months


def badge_volume_series(
    city_id: int,
    badge_slug: str,
    start_date,
    end_date,
    bucket: str = "month",
) -> list[dict]:
    """Volume timeline data for a category landing page (F3, spec §6.6).

    Reads ``mv_badge_volume_monthly`` (migration 013) — a materialized
    view that stores ``(city_id, badge_slug, month, n_items, n_consent,
    n_substantive, total_dollars)`` for every month with at least one
    matching item. Confidence gating (>= 0.6) is baked into the MV's
    definition so we don't re-apply it here.

    Returns one dict per month in ``[start_date, end_date]`` — including
    months that have zero items. Filling in the gaps in Python (rather
    than excluding them) preserves the "every month is a column"
    property so the per-bucket hit-area rect always has a slot, even for
    empty months — citizens hovering an empty column still get the
    "0 items" tooltip rather than a silent gap.

    Each returned dict carries:

    - ``period`` (date, first of month) — used by the template's
      ``data-period`` attribute and the ``<title>`` tooltip
    - ``n_items``, ``n_consent``, ``n_substantive`` — counts from the MV
    - ``total_dollars`` — Decimal, used by the tooltip and KPI parity
    - ``x``, ``width`` — bar geometry (px in viewBox space)
    - ``y_substantive``, ``height_substantive`` — lower bar segment
      (items NOT on consent — the saturated color); height is 0 when
      the month has no substantive items
    - ``y_consent``, ``height_consent`` — upper bar segment (items on
      consent — the lighter shade per spec §6.6 line 3144); height is 0
      when the month has no consent items
    - ``hit_x``, ``hit_width`` — full-column hit-area geometry; spans
      the entire bucket including the inter-bar gap so adjacent
      hit-areas tile without seams
    - ``hit_y``, ``hit_height`` — covers the full plot area
      (PLOT_TOP..PLOT_BOTTOM) so empty months still capture hover

    The bar plotting area is y=``VOLUME_TIMELINE_PLOT_TOP`` to
    y=``VOLUME_TIMELINE_PLOT_BOTTOM``. Bar heights scale to the max
    n_items across the visible window so a single tall month doesn't
    push the rest into an unreadable smear.

    ``bucket`` accepts ``"month"`` only for now; the materialized view
    is monthly-grained and a weekly view would require a different MV.
    Passing ``bucket="week"`` raises ``NotImplementedError``.
    """
    if bucket == "week":
        raise NotImplementedError(
            "Weekly bucketing not supported — mv_badge_volume_monthly is "
            "monthly-grained. Add a weekly MV before enabling."
        )
    if bucket != "month":
        raise ValueError(f"Unknown bucket {bucket!r}")

    months = _months_in_range(start_date, end_date)
    if not months:
        return []

    # Pull every row from the MV that falls in our window; we'll merge
    # against the dense month list below. Index by month for O(1) lookup.
    #
    # PostgreSQL raises ``ObjectNotInPrerequisiteState`` when querying a
    # materialized view that exists but has never been refreshed
    # (CREATE MATERIALIZED VIEW ... WITH NO DATA — the case in
    # migration 013). Production refreshes this MV nightly via the cron
    # worker; local dev clones may not. Treating the unrefreshed state
    # as "no rows yet" keeps the page renderable in both environments
    # rather than 500-ing on a brand-new install.
    import psycopg2

    rows_by_month: dict = {}
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT month, n_items, n_consent, n_substantive, total_dollars
                FROM mv_badge_volume_monthly
                WHERE city_id   = %s
                  AND badge_slug = %s
                  AND month     >= %s
                  AND month     <= %s
                ORDER BY month
                """,
                (city_id, badge_slug, months[0], months[-1]),
            )
            rows_by_month = {row["month"]: dict(row) for row in cur.fetchall()}
    except psycopg2.errors.ObjectNotInPrerequisiteState:
        rows_by_month = {}

    # Layout math — column width is a strict fraction of the plot width
    # so the rightmost bar's right edge sits flush at x=800.
    n = len(months)
    col_width = VOLUME_TIMELINE_WIDTH / n
    bar_gap = min(col_width * 0.15, 2.0)
    bar_width = max(col_width - bar_gap, 1.0)

    # Vertical scale: tallest bar uses the full plot height. The
    # column-wide hit-area `<rect>` (one per bucket, full plot height)
    # carries the `<title>` tooltip — visible bar segments stay
    # `aria-hidden` and decoration-only. Empty months still emit a
    # hit-area so hover/touch reads "0 items" rather than a silent gap.
    max_items = max(
        (rows_by_month.get(m, {}).get("n_items", 0) or 0) for m in months
    )

    out: list[dict] = []
    for i, month in enumerate(months):
        row = rows_by_month.get(month)
        n_items = (row or {}).get("n_items", 0) or 0
        n_consent = (row or {}).get("n_consent", 0) or 0
        n_substantive = (row or {}).get("n_substantive", 0) or 0
        total_dollars = (row or {}).get("total_dollars", 0) or 0

        x = i * col_width + (bar_gap / 2.0)

        if max_items > 0:
            full_h = (n_items / max_items) * VOLUME_TIMELINE_PLOT_HEIGHT
            sub_h = (
                (n_substantive / n_items) * full_h if n_items > 0 else 0.0
            )
            con_h = full_h - sub_h
        else:
            full_h = sub_h = con_h = 0.0

        # Bars sit on the plot baseline (PLOT_BOTTOM) and grow upward.
        # Substantive (saturated) is the LOWER segment; consent (lighter)
        # is stacked above per spec §6.6 line 3142–3146.
        y_substantive = VOLUME_TIMELINE_PLOT_BOTTOM - sub_h
        y_consent = y_substantive - con_h
        height_substantive = sub_h
        height_consent = con_h

        # Column-wide hit-area: spans the entire bucket (including
        # inter-bar gap) and the full plot vertical range, so empty
        # months and adjacent buckets tile seamlessly under hover/touch.
        hit_x = i * col_width
        hit_width = col_width

        out.append(
            {
                "period": month,
                "n_items": n_items,
                "n_consent": n_consent,
                "n_substantive": n_substantive,
                "total_dollars": total_dollars,
                "x": round(x, 3),
                "width": round(bar_width, 3),
                "y_substantive": round(y_substantive, 3),
                "height_substantive": round(height_substantive, 3),
                "y_consent": round(y_consent, 3),
                "height_consent": round(height_consent, 3),
                "hit_x": round(hit_x, 3),
                "hit_width": round(hit_width, 3),
                "hit_y": round(VOLUME_TIMELINE_PLOT_TOP, 3),
                "hit_height": round(VOLUME_TIMELINE_PLOT_HEIGHT, 3),
            }
        )
    return out


def _normalize_party(raw: str | None) -> str:
    """Map ``mayoral_terms.party`` to a single-letter CSS modifier.

    Migration 013 seeds full strings (``"Democrat"``, ``"Republican"``)
    to keep the table readable in admin tools, but the spec's CSS hooks
    ``.term-overlay--D / --R / --I`` use single letters to keep the
    class list short. ``I`` (Independent) is the catch-all for unknown
    or NULL — non-partisan municipal elections, third parties, etc.
    """
    if not raw:
        return "I"
    head = raw.strip()[:1].upper()
    return head if head in ("D", "R", "I") else "I"


def mayoral_term_overlay(
    city_id: int,
    start_date,
    end_date,
) -> list[dict]:
    """Render-ready data for the mayoral-term overlay bands (spec §6.6).

    Reads ``mayoral_terms`` (migration 013) and projects each term that
    intersects ``[start_date, end_date]`` onto the SVG x-axis. Term
    spans that extend past the visible window get clipped — a 2010
    term-start with a 2022 window-start renders starting at x=0.

    Returns ``list[dict]`` with keys:

    - ``mayor`` — mayor name (passed straight to the SVG ``<text>``)
    - ``party`` — single-letter normalized class modifier (D/R/I)
    - ``x_start`` — left edge in viewBox px
    - ``width`` — span width in viewBox px (always > 0; zero-width terms
      are filtered out)
    - ``x_label`` — x for the centered text label (just inside the band)

    Empty list when the city has no mayoral_terms rows or no terms
    intersect the visible window. Terms with NULL ``term_end`` are
    treated as "currently in office" and clipped to ``end_date``.

    The total visible-window length is ``end_date - start_date`` in
    days, mapped linearly to ``VOLUME_TIMELINE_WIDTH``. Day-level
    granularity is sufficient — these are background bands, not data.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT mayor_name, party, term_start, term_end
            FROM mayoral_terms
            WHERE city_id = %s
              AND term_start <= %s
              AND (term_end IS NULL OR term_end >= %s)
            ORDER BY term_start
            """,
            (city_id, end_date, start_date),
        )
        rows = cur.fetchall()

    total_days = (end_date - start_date).days
    if total_days <= 0 or not rows:
        return []

    px_per_day = VOLUME_TIMELINE_WIDTH / total_days

    out: list[dict] = []
    for row in rows:
        term_start = row["term_start"]
        term_end = row["term_end"] or end_date

        # Clip to visible window.
        clipped_start = max(term_start, start_date)
        clipped_end = min(term_end, end_date)
        span_days = (clipped_end - clipped_start).days
        if span_days <= 0:
            continue

        x_start = (clipped_start - start_date).days * px_per_day
        width = span_days * px_per_day
        x_label = x_start + (width / 2.0)

        out.append(
            {
                "mayor": row["mayor_name"],
                "party": _normalize_party(row["party"]),
                "x_start": round(x_start, 3),
                "width": round(width, 3),
                "x_label": round(x_label, 3),
            }
        )
    return out


def year_ticks(start_date, end_date) -> list[dict]:
    """X-axis year-tick labels for the volume timeline (spec §6.6 line 3126+).

    Returns ``[{year, x}, ...]`` for each calendar year fully or
    partially in ``[start_date, end_date]``. ``x`` is the midpoint of
    the year inside the visible window, so a label sits roughly under
    the middle of its 12-month bar group. Years that begin before or
    end after the window are clipped before midpoint computation —
    keeps the leftmost/rightmost labels from running off the SVG.

    Empty list when ``end_date <= start_date``.
    """
    from datetime import date as _date

    total_days = (end_date - start_date).days
    if total_days <= 0:
        return []
    px_per_day = VOLUME_TIMELINE_WIDTH / total_days

    out: list[dict] = []
    for year in range(start_date.year, end_date.year + 1):
        year_start = max(_date(year, 1, 1), start_date)
        # Use end-exclusive next-year-jan-1 then back off by 1 day to
        # get the actual year-end inside the window.
        year_end_full = _date(year, 12, 31)
        year_end = min(year_end_full, end_date)
        if year_end < year_start:
            continue
        midpoint = year_start + (year_end - year_start) / 2
        x = (midpoint - start_date).days * px_per_day
        out.append({"year": year, "x": round(x, 3)})
    return out


# --- Browse-by-Priority helpers (F4) ----------------------------------------
#
# Spec §6.7 (homepage Browse-by-Priority section) + §6.8 (cross-filter
# dropdown on category landing). Four small helpers feed two homepage
# grids (4 BHM policy + 7 always-on process tiles) and the dropdown.
#
# Pattern note: each helper returns either a count or a list of dicts.
# The route layer (``public.py``) composes them — counts are zipped onto
# the badge dicts before passing to the template, so the template stays
# a single loop per grid (no Jinja-side fan-out, no global functions).
# Same precedent F2 set with ``category_kpis`` + ``list_items_by_badge``.


def badge_volume_year(
    city_id: int,
    badge_slug: str,
    *,
    year: int | None = None,
) -> int:
    """Count items carrying ``badge_slug`` in ``city_id`` for a calendar year.

    Used by the homepage Browse-by-Priority **policy** tiles ("N this
    year"). Reuses the same significance + confidence + status gates as
    ``list_items_by_badge`` and ``category_kpis`` (decision #61) so the
    tile counts match what citizens see when they click into the
    category landing page.

    - ``confidence >= 0.6`` (single-source low-confidence matches hidden)
    - ``processing_status = 'completed'`` (v3 items only)
    - Per-badge ``min_significance`` gate via
      ``resolve_significance_threshold`` — no-op for process badges,
      kicks in for policy badges (default 3).

    Year defaults to ``date.today().year``. Inclusive boundary on both
    ends (``meeting_date BETWEEN '<year>-01-01' AND '<year>-12-31'``).

    We query base tables rather than ``mv_badge_volume_monthly`` because
    the MV doesn't carry the significance dimension — sum'ing n_items
    across months would over-count for policy badges with low-sig items.
    The (city_id, badge_slug, confidence DESC) index keeps this fast.
    """
    if year is None:
        from datetime import date as _date
        year = _date.today().year

    threshold = resolve_significance_threshold(city_id, badge_slug)

    sql_parts = [
        """
        SELECT COUNT(*) AS n
        FROM agenda_item_badges aib
        JOIN agenda_items ai ON ai.id = aib.agenda_item_id
        JOIN meetings m      ON m.id = ai.meeting_id
        WHERE aib.city_id = %s
          AND aib.badge_slug = %s
          AND aib.confidence >= 0.6
          AND aib.status = 'applied'
          AND ai.processing_status = 'completed'
          AND m.meeting_date BETWEEN %s AND %s
        """
    ]
    params: list = [city_id, badge_slug, f"{year}-01-01", f"{year}-12-31"]

    if threshold is not None:
        sql_parts.append(" AND ai.significance_score >= %s")
        params.append(threshold)

    with db_cursor() as cur:
        cur.execute("".join(sql_parts), params)
        row = cur.fetchone() or {}
        return int(row.get("n") or 0)


def badge_volume_recent(
    city_id: int,
    badge_slug: str,
    *,
    days: int = 30,
) -> int:
    """Count items carrying ``badge_slug`` in the last ``days`` days.

    Used by the homepage Browse-by-Priority **process** tiles ("N last
    30 days"). Same gating rules as ``badge_volume_year`` — confidence
    + status + significance — so tile counts and category-page counts
    line up.

    Process badges (``hidden_on_consent``, ``sole_source``, etc.) all
    have ``kind='process'`` and resolve to ``threshold=None``, so the
    significance branch is a no-op for them. Keeping the threshold
    branch in here anyway means a future "policy on a 30-day window"
    use case stays consistent.

    The MV is monthly-grained so a 30-day window can't read from it
    cleanly; this helper hits base tables. The
    ``(city_id, badge_slug, confidence DESC)`` index from migration 013
    is still the leading predicate, and the date bound is the second
    selectivity filter — fast enough for a homepage cold load.

    ``days`` is a positive integer; ``days=0`` returns 0 (treats today
    as the only day, but ``CURRENT_DATE - 0 * INTERVAL '1 day'`` is
    still today, so really ``days=0`` returns the count for today
    alone — semantics aren't load-bearing for the spec's 30-day default).
    """
    threshold = resolve_significance_threshold(city_id, badge_slug)

    sql_parts = [
        """
        SELECT COUNT(*) AS n
        FROM agenda_item_badges aib
        JOIN agenda_items ai ON ai.id = aib.agenda_item_id
        JOIN meetings m      ON m.id = ai.meeting_id
        WHERE aib.city_id = %s
          AND aib.badge_slug = %s
          AND aib.confidence >= 0.6
          AND aib.status = 'applied'
          AND ai.processing_status = 'completed'
          AND m.meeting_date >= CURRENT_DATE - %s * INTERVAL '1 day'
        """
    ]
    params: list = [city_id, badge_slug, days]

    if threshold is not None:
        sql_parts.append(" AND ai.significance_score >= %s")
        params.append(threshold)

    with db_cursor() as cur:
        cur.execute("".join(sql_parts), params)
        row = cur.fetchone() or {}
        return int(row.get("n") or 0)


def list_city_policy_badges(city_id: int) -> list[dict]:
    """Return enabled policy badges for ``city_id``, ordered for display.

    Reads the JOIN of ``priority_badge_templates`` (kind='policy') against
    ``priority_badges_config`` filtered to ``enabled=TRUE``. A city with
    no opt-ins (e.g., Mobile pre-config) returns ``[]`` — the homepage
    grid simply doesn't render. BHM is seeded into all 4 policy badges
    by migration 013 so the typical render is 4 tiles.

    Each dict carries: ``slug``, ``name``, ``description``, ``icon``,
    ``kind`` — same shape ``get_resolved_badge`` returns, with name/
    description override applied. Keeps the homepage tile and the
    category-landing header in lockstep on labels.

    Sort: alphabetical by resolved name. Policy badges don't have an
    inherent "alarm order" (decision #64 only ranks process badges), so
    a stable alpha sort keeps the grid layout predictable.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT t.slug,
                   COALESCE(c.name_override, t.name)               AS name,
                   COALESCE(c.description_override, t.description) AS description,
                   t.icon,
                   t.kind
            FROM priority_badge_templates t
            JOIN priority_badges_config c
              ON c.template_slug = t.slug
             AND c.city_id = %s
            WHERE t.kind = 'policy'
              AND c.enabled = TRUE
            ORDER BY name
            """,
            (city_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def list_enabled_badges(city_id: int) -> list[dict]:
    """Return every badge available for ``city_id`` — policy + process.

    Used by the category-landing cross-filter dropdown (spec §6.8) so
    citizens browsing one badge can refine to items also tagged with
    another. Combines:

    - **Policy badges**: must have an ``enabled=TRUE`` row in
      ``priority_badges_config`` for ``city_id``.
    - **Process badges**: always-on across cities (no config row
      requirement) — same model ``list_process_badges`` uses.

    Sort: process badges first (in alarm-priority order matching
    decision #64), then policy badges alphabetically. Mirrors the chip
    row's process-then-policy convention so dropdown order doesn't
    surprise a user who's learned chip semantics.

    Each dict carries: ``slug``, ``name``, ``description``, ``icon``,
    ``kind`` — name/description overrides applied for policy badges that
    have a config row. Process badges read from the template directly
    (no overrides — process badges are intentionally uniform across
    cities). Shape symmetry with ``get_resolved_badge`` /
    ``list_city_policy_badges`` / ``list_process_badges`` (Opus#1-S1).

    Callers (the route handler) typically subtract the current
    ``badge_slug`` from this list before rendering — no point in
    offering "filter by the badge you're already on" as an option.
    """
    process_alarm_order = [
        "hidden_on_consent",
        "legal_settlement",
        "contested",
        "sole_source",
        "emergency_action",
        "split_vote",
        "amends_prior_contract",
    ]
    order_index = {slug: i for i, slug in enumerate(process_alarm_order)}

    with db_cursor() as cur:
        # One query, two-arm UNION:
        # - process: every template with kind='process' (always-on),
        #   read straight from the templates table.
        # - policy: templates with kind='policy' that the city has
        #   opted into via priority_badges_config.enabled=TRUE.
        cur.execute(
            """
            SELECT t.slug,
                   t.name,
                   t.description,
                   t.icon,
                   t.kind
            FROM priority_badge_templates t
            WHERE t.kind = 'process'
            UNION ALL
            SELECT t.slug,
                   COALESCE(c.name_override, t.name)               AS name,
                   COALESCE(c.description_override, t.description) AS description,
                   t.icon,
                   t.kind
            FROM priority_badge_templates t
            JOIN priority_badges_config c
              ON c.template_slug = t.slug
             AND c.city_id = %s
            WHERE t.kind = 'policy'
              AND c.enabled = TRUE
            """,
            (city_id,),
        )
        rows = [dict(row) for row in cur.fetchall()]

    def _sort_key(r: dict) -> tuple:
        # Process before policy; within process, alarm order; within
        # policy, alphabetical by display name.
        if r["kind"] == "process":
            return (0, order_index.get(r["slug"], 999), r["name"])
        return (1, 0, r["name"])

    rows.sort(key=_sort_key)
    return rows


def list_process_badges() -> list[dict]:
    """Return all 7 process badge templates, in the alarm-priority order.

    Process badges are always-on across cities (Section 4.2 of the
    spec). They are NOT seeded into ``priority_badges_config`` per-city
    — their existence in ``priority_badge_templates`` is itself the
    enable signal. So this helper reads the templates table directly
    and ignores the config table.

    Sort follows decision #64's ``process_alarm_order`` — the same
    order applied to per-item badge chips (``order_badges`` in the
    badge_chip helpers). Keeping homepage-grid order aligned with
    chip-row order means a citizen who learns "🔥 = Contested" on the
    chip row reads it the same way on the homepage grid.

    Unknown templates (e.g., a future 8th process badge added to the
    seed before alarm_order is updated) sort to the end.
    """
    process_alarm_order = [
        "hidden_on_consent",
        "legal_settlement",
        "contested",
        "sole_source",
        "emergency_action",
        "split_vote",
        "amends_prior_contract",
    ]
    order_index = {slug: i for i, slug in enumerate(process_alarm_order)}

    with db_cursor() as cur:
        cur.execute(
            """
            SELECT slug, name, description, icon, kind
            FROM priority_badge_templates
            WHERE kind = 'process'
            """
        )
        rows = [dict(row) for row in cur.fetchall()]

    rows.sort(key=lambda r: order_index.get(r["slug"], 999))
    return rows


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


# --- Data-debt + RSS service helpers (F5) -----------------------------------


def list_data_debt_items(
    city_id: int | None,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return items that have data-debt — items where the text layer /
    agenda content is missing (``data_quality != 'ok'``) or where the
    v3 pipeline has given up (``processing_status = 'failed_permanent'``).
    Decision #84.

    G2 extension: pass ``city_id=None`` to skip the per-city filter and
    return rows across all cities (admin OCR queue at
    ``/admin/data-debt``). Public callers (F5) always pass an integer
    ``city_id``; the admin queue passes ``None``.

    Sort: ``data_debt_priority DESC, meeting_date DESC`` so HIGH-priority
    items lead and within a priority tier the most recent items rise.

    Pagination: caller asks for ``limit`` rows; this helper accepts a
    sentinel-pagination caller (``limit=51`` to detect a 51st row) — it
    does NOT add ``+1`` itself. Same shape as
    :func:`list_items_by_badge`.

    Index: ``idx_agenda_items_data_debt`` from migration 013 covers the
    primary predicate (data_quality not ok) but not the
    ``failed_permanent`` arm — that arm is rare enough (Wave 0 emits
    only on hard pipeline failures) that a partial-index miss isn't a
    hot-path cost. If ``failed_permanent`` becomes common we can extend
    the index.

    Returns dicts (not :class:`AgendaItem`) — this is a queue page, not
    a Smart Brevity Card surface, so the lighter shape is fine and the
    template doesn't need the v3 extracted_facts projection.
    """
    where_clauses = [
        "((ai.data_quality IS NOT NULL AND ai.data_quality != 'ok') "
        "OR ai.processing_status = 'failed_permanent')"
    ]
    params: list = []
    if city_id is not None:
        where_clauses.insert(0, "m.id = %s")
        params.append(city_id)
    params.extend([limit, offset])
    where_sql = " AND ".join(where_clauses)

    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT ai.id,
                   ai.meeting_id,
                   ai.item_number,
                   ai.title,
                   ai.is_consent,
                   ai.data_quality::text       AS data_quality,
                   ai.data_debt_priority::text AS data_debt_priority,
                   ai.processing_status::text  AS processing_status,
                   ai.processing_attempts,
                   ai.last_error_message,
                   mt.meeting_date             AS meeting_date,
                   mt.title                    AS meeting_title,
                   m.id                        AS municipality_id,
                   m.slug                      AS municipality_slug,
                   m.name                      AS municipality_name
            FROM agenda_items ai
            JOIN meetings mt ON ai.meeting_id = mt.id
            JOIN municipalities m ON mt.municipality_id = m.id
            WHERE {where_sql}
            ORDER BY
                CASE ai.data_debt_priority::text
                    WHEN 'high'   THEN 3
                    WHEN 'normal' THEN 2
                    WHEN 'low'    THEN 1
                    ELSE 0
                END DESC,
                mt.meeting_date DESC NULLS LAST,
                ai.id DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params),
        )
        return [dict(row) for row in cur.fetchall()]


def list_failed_permanent_items_all_cities(
    *,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    """Return items at ``processing_status='failed_permanent'`` across
    all cities — used by the admin errors queue at ``/admin/errors``.
    G2 (decision #79).

    Sort: same as :func:`list_data_debt_items` —
    ``data_debt_priority DESC, meeting_date DESC``. Although decision
    #79 originally framed errors-queue ordering as
    "significance-sorted," priority is built from significance-driven
    heuristics (decision #31), so reusing the priority sort keeps
    behavior consistent across both admin queues. The plan §G2.2
    "significance-sorted" comment defers to decision #79's text.

    Returns dicts. Includes ``last_error_message`` and
    ``processing_attempts`` so the template can show why the worker
    gave up.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT ai.id,
                   ai.meeting_id,
                   ai.item_number,
                   ai.title,
                   ai.is_consent,
                   ai.data_quality::text       AS data_quality,
                   ai.data_debt_priority::text AS data_debt_priority,
                   ai.processing_status::text  AS processing_status,
                   ai.processing_attempts,
                   ai.last_error_message,
                   ai.last_error_at,
                   ai.score_overrides,
                   mt.meeting_date             AS meeting_date,
                   mt.title                    AS meeting_title,
                   m.id                        AS municipality_id,
                   m.slug                      AS municipality_slug,
                   m.name                      AS municipality_name
            FROM agenda_items ai
            JOIN meetings mt ON ai.meeting_id = mt.id
            JOIN municipalities m ON mt.municipality_id = m.id
            WHERE ai.processing_status = 'failed_permanent'
            ORDER BY
                CASE ai.data_debt_priority::text
                    WHEN 'high'   THEN 3
                    WHEN 'normal' THEN 2
                    WHEN 'low'    THEN 1
                    ELSE 0
                END DESC,
                mt.meeting_date DESC NULLS LAST,
                ai.id DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        return [dict(row) for row in cur.fetchall()]


def list_cross_stage_conflicts(
    *,
    limit: int = 25,
    offset: int = 0,
) -> list[dict]:
    """Return items at ``processing_status='cross_stage_conflict'`` for
    the G4 admin viewer. Spec decision #93.

    Sort: ``data_debt_priority DESC, ai_generated_at DESC`` — high-priority
    conflicts surface first; within a priority tier the most recently
    flipped to conflict state rises. Same priority sort as F5 / G2 /
    G3 admin queues for consistency.

    (Plan referenced ``updated_at`` but ``agenda_items`` has no such
    column locally; ``ai_generated_at`` is the closest freshness analog —
    matches the calibration.py spec/code drift workaround.)

    Pagination: caller passes ``limit`` (sentinel-pagination compatible
    — caller passes ``limit+1`` and slices). Page size 25 in the route
    handler — these rows are heavy (full Stage 1 facts JSON + Stage 2
    rationale + raw description rendered side-by-side).

    Returns dicts, not :class:`AgendaItem` objects, because the admin
    queue template needs a flatter projection (joined city + meeting
    context) than the v3 Smart Brevity Card surface.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
              ai.id,
              ai.title,
              ai.description,
              ai.dollars_amount,
              ai.extracted_facts,
              ai.headline,
              ai.why_it_matters,
              ai.score_overrides,
              ai.data_debt_priority::text AS data_debt_priority,
              ai.processing_status::text  AS processing_status,
              ai.ai_generated_at,
              mt.id            AS meeting_id,
              mt.meeting_date,
              mt.title         AS meeting_title,
              m.id             AS municipality_id,
              m.slug           AS municipality_slug,
              m.name           AS municipality_name
            FROM agenda_items ai
            JOIN meetings mt ON mt.id = ai.meeting_id
            JOIN municipalities m ON m.id = mt.municipality_id
            WHERE ai.processing_status = 'cross_stage_conflict'
            ORDER BY
                CASE ai.data_debt_priority::text
                    WHEN 'high'   THEN 3
                    WHEN 'normal' THEN 2
                    WHEN 'low'    THEN 1
                    ELSE 0
                END DESC,
                ai.ai_generated_at DESC NULLS LAST,
                ai.id DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        return [dict(row) for row in cur.fetchall()]


def list_badge_audit_log(
    *,
    badge_slug: str | None = None,
    actor: str | None = None,
    since: datetime | None = None,
    until_exclusive: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return ``agenda_item_badges_audit`` rows joined to context for
    the G3 viewer at ``/admin/badges/audit``. Spec §6.10.

    Filters (all optional, all combinable):

    - ``badge_slug`` — exact match on ``aiba.badge_slug``.
    - ``actor`` — exact match on ``aiba.actor`` (case-sensitive; admin
      usernames are the existing convention).
    - ``since`` — **timezone-aware** ``datetime``; returns rows where
      ``occurred_at >= since``. Inclusive lower bound. Callers should
      build this from a YYYY-MM-DD form input by combining the date
      with start-of-day in ``America/Chicago`` (decision #10).
    - ``until_exclusive`` — **timezone-aware** ``datetime`` representing
      the **exclusive upper bound**. Returns rows where
      ``occurred_at < until_exclusive``. Callers translate
      ``until=YYYY-MM-DD`` (which the user understands as "include the
      whole day") into start-of-(day+1) in ``America/Chicago`` —
      that's why the parameter name explicitly says ``_exclusive``.
      Avoids end-of-day microsecond gymnastics.

    psycopg2 binds timezone-aware ``datetime`` values to ``timestamptz``
    natively; no ``::timestamptz`` cast in the SQL is needed when the
    Python value is already aware. Naive ``datetime`` would be an
    error here — the caller is responsible for tz-attachment.

    Sort: ``occurred_at DESC, id DESC`` — newest-first, with id as
    tiebreaker for same-second rows. Hits ``idx_badge_audit_recent``
    (migration 013:251-253) when ``actor_role='admin'`` is in the
    predicate; G3 doesn't restrict to admin actor_role at the helper
    level (the viewer surfaces all roles so cron and on-write actions
    are debuggable too), so this is a sequential scan over the audit
    table. That's acceptable for v1 — admin traffic is bounded by the
    admin blueprint's ``before_request`` auth hook and the table is
    small (one row per badge add/remove/modify, currently zero in
    production).

    Pagination: caller passes ``limit`` and ``offset``; sentinel
    pagination is the caller's responsibility (caller passes
    ``limit+1`` and slices). Same shape as
    :func:`list_data_debt_items`.

    Returns a list of dicts. Joined columns:

    - ``id``, ``agenda_item_id``, ``badge_slug``, ``action``,
      ``actor``, ``actor_role``, ``reason``, ``occurred_at`` — direct
      from ``agenda_item_badges_audit``.
    - ``item_title`` — from ``agenda_items.title``.
    - ``meeting_date`` — from ``meetings.meeting_date``.
    - ``municipality_slug``, ``municipality_name`` — from
      ``municipalities`` for cross-city display.

    NB: as of Migration 016 the audit table's ``agenda_item_id`` FK
    uses ``ON DELETE SET NULL``, so audit rows survive item deletion
    (the conventional audit-table pattern). The LEFT JOIN below is
    load-bearing — orphaned rows surface with NULL item_title /
    meeting_date / municipality_* so the viewer can still display the
    historical action even after the underlying item is gone.
    """
    where_clauses: list[str] = []
    params: list = []

    if badge_slug:
        where_clauses.append("aiba.badge_slug = %s")
        params.append(badge_slug)
    if actor:
        where_clauses.append("aiba.actor = %s")
        params.append(actor)
    if since is not None:
        if since.tzinfo is None:
            raise ValueError("list_badge_audit_log: 'since' must be timezone-aware")
        where_clauses.append("aiba.occurred_at >= %s")
        params.append(since)
    if until_exclusive is not None:
        if until_exclusive.tzinfo is None:
            raise ValueError(
                "list_badge_audit_log: 'until_exclusive' must be timezone-aware"
            )
        where_clauses.append("aiba.occurred_at < %s")
        params.append(until_exclusive)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    params.extend([limit, offset])

    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT
              aiba.id,
              aiba.agenda_item_id,
              aiba.badge_slug,
              aiba.action,
              aiba.actor,
              aiba.actor_role,
              aiba.reason,
              aiba.occurred_at,
              ai.title                 AS item_title,
              mt.meeting_date          AS meeting_date,
              m.slug                   AS municipality_slug,
              m.name                   AS municipality_name
            FROM agenda_item_badges_audit aiba
            LEFT JOIN agenda_items ai ON ai.id = aiba.agenda_item_id
            LEFT JOIN meetings mt ON mt.id = ai.meeting_id
            LEFT JOIN municipalities m ON m.id = mt.municipality_id
            {where_sql}
            ORDER BY aiba.occurred_at DESC, aiba.id DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params),
        )
        return [dict(row) for row in cur.fetchall()]


def list_badges_on_item(item_id: int) -> list[dict]:
    """Return active badges on a single agenda item, joined to template
    metadata for display. Used by the G3 manage UI.

    Returns dicts with: ``slug``, ``kind``, ``confidence``, ``source``,
    ``name``, ``description``, ``icon``. Empty list if no badges.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT aib.badge_slug AS slug,
                   aib.kind,
                   aib.confidence,
                   aib.source,
                   t.name,
                   t.description,
                   t.icon
              FROM agenda_item_badges aib
              JOIN priority_badge_templates t ON t.slug = aib.badge_slug
             WHERE aib.agenda_item_id = %s
             ORDER BY aib.kind, aib.badge_slug
            """,
            (item_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def list_upcoming_hearings(city_id: int, *, days_ahead: int = 60, limit: int = 50) -> list[dict]:
    """Return future-dated hearings in ``city_id`` likely to surface a
    public hearing — used by the upcoming-hearings RSS feed (F5.2).

    Heuristic (v1 — flagged as a follow-up to refine when a structured
    "hearing" signal exists):

    - ``meeting_date`` is in the future (>= today) and within
      ``days_ahead`` days, AND
    - meeting title or any of its agenda-item titles contains
      ``'hearing'`` (case-insensitive).

    Returns one row per hit. The result shape:

    - For meetings with one or more agenda items whose title matches
      ``'%hearing%'``: one row per matching agenda item, with
      ``agenda_item_id`` set and ``hearing_title`` carrying the item
      title.
    - For meetings whose own title matches but with no per-item
      hearing rows: one row with ``agenda_item_id = NULL`` and
      ``hearing_title`` carrying the meeting title.

    F5 fix-up (R6 + S2): the previous shape used a scalar ``LIMIT 1``
    subquery that silently dropped subsequent hearings from a meeting
    with multiple. The RSS feed needs each hearing to surface as its
    own ``<item>`` with a unique ``<guid>``, so we now JOIN
    ``agenda_items`` and emit N rows per meeting. ``agenda_item_id``
    is included so the RSS template can build a stable per-row GUID
    anchored at a primary key (titles can change; PKs cannot).

    The codebase has no structured ``action_type='hearing'`` column on
    agenda items today (the v3 ``extracted_facts->>'action_type'`` enum
    has ``contract_award``, ``ordinance``, ``appropriation`` — nothing
    hearing-specific). When that signal lands the helper should switch
    to it; until then the title-substring heuristic ships v1.

    Returns dicts. Empty when no upcoming hearings.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            -- Per-item hearings: one row per agenda item whose title
            -- contains 'hearing'. Carries agenda_item_id so the feed
            -- can build a stable per-row GUID.
            SELECT
                m_row.id            AS meeting_id,
                ai.id               AS agenda_item_id,
                m_row.meeting_date  AS meeting_date,
                m_row.meeting_type  AS meeting_type,
                m_row.title         AS meeting_title,
                muni.slug           AS municipality_slug,
                muni.name           AS municipality_name,
                ai.title            AS hearing_title
            FROM meetings m_row
            JOIN municipalities muni ON muni.id = m_row.municipality_id
            JOIN agenda_items ai     ON ai.meeting_id = m_row.id
            WHERE muni.id = %s
              AND m_row.meeting_date >= CURRENT_DATE
              AND m_row.meeting_date <= CURRENT_DATE + %s * INTERVAL '1 day'
              AND ai.title ILIKE '%%hearing%%'

            UNION ALL

            -- Meeting-level hearings: meeting title matches but the
            -- meeting has zero matching agenda items (so nothing in
            -- the per-item branch surfaces it). agenda_item_id is NULL.
            SELECT
                m_row.id            AS meeting_id,
                NULL::int           AS agenda_item_id,
                m_row.meeting_date  AS meeting_date,
                m_row.meeting_type  AS meeting_type,
                m_row.title         AS meeting_title,
                muni.slug           AS municipality_slug,
                muni.name           AS municipality_name,
                m_row.title         AS hearing_title
            FROM meetings m_row
            JOIN municipalities muni ON muni.id = m_row.municipality_id
            WHERE muni.id = %s
              AND m_row.meeting_date >= CURRENT_DATE
              AND m_row.meeting_date <= CURRENT_DATE + %s * INTERVAL '1 day'
              AND m_row.title ILIKE '%%hearing%%'
              AND NOT EXISTS (
                  SELECT 1 FROM agenda_items ai2
                  WHERE ai2.meeting_id = m_row.id
                    AND ai2.title ILIKE '%%hearing%%'
              )

            ORDER BY meeting_date ASC, meeting_id ASC, agenda_item_id ASC NULLS LAST
            LIMIT %s
            """,
            (city_id, days_ahead, city_id, days_ahead, limit),
        )
        return [dict(row) for row in cur.fetchall()]


# ============================================================================
# Editorial Coverage (Migration 027)
# ============================================================================
# Spec: docs/superpowers/specs/2026-05-13-editorial-coverage-design.md
# Modularity refactor will relocate this section to services/query/coverage.py
# during PR 0.2 (services/query.py decomposition). Keep imports local and
# clearly grouped to make that extraction mechanical.

from docket.models.coverage import (
    CoverageEntry,
    CoverageSubjectLink,
    CoverageSubjectType,
)


def _hydrate_coverage_rows(cur) -> list[CoverageEntry]:
    """Convert cursor rows into CoverageEntry instances. Caller must have
    selected the full row + author + outlet hydration columns in the right
    order — see queries below."""
    out: list[CoverageEntry] = []
    for r in cur.fetchall():
        out.append(CoverageEntry(
            id=r['id'], kind=r['kind'], status=r['status'], source=r['source'],
            body=r['body'], partner_credit=r['partner_credit'],
            outlet_id=r['outlet_id'], external_url=r['external_url'],
            headline=r['headline'], reporter_byline=r['reporter_byline'],
            excerpt=r['excerpt'], article_published_at=r['article_published_at'],
            author_id=r['author_id'], byline=r['byline'],
            created_at=r['created_at'], updated_at=r['updated_at'],
            published_at=r['published_at'], featured_until=r['featured_until'],
            author_display_name=r['author_display_name'],
            author_username=r['author_username'],
            outlet_slug=r['outlet_slug'],
            outlet_name=r['outlet_name'],
        ))
    return out


_COVERAGE_SELECT = """
    SELECT ce.id, ce.kind, ce.status, ce.source,
           ce.body, ce.partner_credit,
           ce.outlet_id, ce.external_url, ce.headline,
           ce.reporter_byline, ce.excerpt, ce.article_published_at,
           ce.author_id, ce.byline,
           ce.created_at, ce.updated_at, ce.published_at, ce.featured_until,
           au.display_name AS author_display_name,
           au.username     AS author_username,
           o.slug          AS outlet_slug,
           o.name          AS outlet_name
      FROM coverage_entries ce
      JOIN admin_users au ON au.id = ce.author_id
 LEFT JOIN outlets o ON o.id = ce.outlet_id
"""


def coverage_for_subject(
    subject_type: CoverageSubjectType,
    subject_id: int | None = None,
    subject_slug: str | None = None,
) -> list[CoverageEntry]:
    """Return published coverage entries attached to one subject.

    Exactly one of ``subject_id`` or ``subject_slug`` must be set; the choice
    is gated by ``subject_type`` (badge → slug; others → id).

    Notes are returned first (newest published_at first), then citations
    (newest article_published_at first). Matches the template's render order.
    """
    if subject_type == 'badge':
        if subject_slug is None:
            raise ValueError("subject_slug required when subject_type='badge'")
        where = "csl.subject_type = 'badge' AND csl.subject_slug = %s"
        params = (subject_slug,)
    else:
        if subject_id is None:
            raise ValueError(f"subject_id required when subject_type={subject_type!r}")
        where = "csl.subject_type = %s AND csl.subject_id = %s"
        params = (subject_type, subject_id)

    # ORDER BY: notes first (0), citations after (1); within each, newest date first.
    # We map kind to 0/1 explicitly because plain ASC on the enum's text values
    # would sort 'citation' before 'note' alphabetically.
    sql = _COVERAGE_SELECT + f"""
        JOIN coverage_subject_links csl ON csl.coverage_id = ce.id
       WHERE {where}
         AND ce.status = 'published'
       ORDER BY CASE WHEN ce.kind = 'note' THEN 0 ELSE 1 END ASC,
                CASE WHEN ce.kind = 'note'
                     THEN ce.published_at
                     ELSE ce.article_published_at::timestamptz
                END DESC NULLS LAST
    """

    with db_cursor() as cur:
        cur.execute(sql, params)
        return _hydrate_coverage_rows(cur)


def coverage_counts_for_items(item_ids: list[int]) -> dict[int, tuple[int, int]]:
    """Return {item_id: (note_count, citation_count)} for items with published coverage.

    Items with no coverage are omitted from the returned dict — callers should
    default to ``(0, 0)``.

    Short-circuits to ``{}`` when ``item_ids`` is empty, since
    ``WHERE subject_id IN ()`` raises a syntax error in psycopg.
    """
    if not item_ids:
        return {}
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT csl.subject_id,
                   COUNT(*) FILTER (WHERE ce.kind = 'note')     AS note_count,
                   COUNT(*) FILTER (WHERE ce.kind = 'citation') AS cit_count
              FROM coverage_subject_links csl
              JOIN coverage_entries ce ON ce.id = csl.coverage_id
             WHERE csl.subject_type = 'agenda_item'
               AND csl.subject_id = ANY(%s)
               AND ce.status = 'published'
             GROUP BY csl.subject_id
            """,
            (item_ids,),
        )
        return {r['subject_id']: (r['note_count'], r['cit_count']) for r in cur.fetchall()}


def _hydrate_subjects_for_entries(cur, entries: list[CoverageEntry]) -> list[CoverageEntry]:
    """Populate the ``subjects`` field on each entry with one bulk query.

    Resolves a human-readable label per subject from agenda_items / meetings /
    council_members / priority_badge_templates via COALESCE'd lookups, so the
    template can render '→ on Item 25-0042 (Westside Rezoning)' chips without
    a second per-row trip.

    Returns a NEW list (frozen dataclass — uses ``replace``).
    """
    if not entries:
        return entries
    ids = [e.id for e in entries]
    cur.execute(
        """
        SELECT csl.coverage_id, csl.subject_type, csl.subject_id, csl.subject_slug,
               CASE csl.subject_type
                 WHEN 'agenda_item'    THEN (SELECT title FROM agenda_items WHERE id = csl.subject_id)
                 WHEN 'meeting'        THEN (SELECT title FROM meetings WHERE id = csl.subject_id)
                 WHEN 'council_member' THEN (SELECT name  FROM council_members WHERE id = csl.subject_id)
                 WHEN 'badge'          THEN (SELECT name  FROM priority_badge_templates WHERE slug = csl.subject_slug)
                 ELSE ''
               END AS label,
               -- City slug for url_for() in the subjects footer. NULL for badges (global) and ELSE branch.
               CASE csl.subject_type
                 WHEN 'agenda_item' THEN
                   (SELECT mu.slug FROM agenda_items ai
                      JOIN meetings m ON m.id = ai.meeting_id
                      JOIN municipalities mu ON mu.id = m.municipality_id
                     WHERE ai.id = csl.subject_id)
                 WHEN 'meeting' THEN
                   (SELECT mu.slug FROM meetings m
                      JOIN municipalities mu ON mu.id = m.municipality_id
                     WHERE m.id = csl.subject_id)
                 WHEN 'council_member' THEN
                   (SELECT mu.slug FROM council_members cm
                      JOIN municipalities mu ON mu.id = cm.municipality_id
                     WHERE cm.id = csl.subject_id)
                 ELSE NULL
               END AS city_slug
          FROM coverage_subject_links csl
         WHERE csl.coverage_id = ANY(%s)
         ORDER BY csl.coverage_id, csl.id
        """,
        (ids,),
    )
    grouped: dict[int, list[CoverageSubjectLink]] = {}
    for r in cur.fetchall():
        grouped.setdefault(r['coverage_id'], []).append(
            CoverageSubjectLink(
                subject_type=r['subject_type'],
                subject_id=r['subject_id'],
                subject_slug=r['subject_slug'],
                label=r['label'] or None,
                city_slug=r['city_slug'],
            )
        )
    return [replace(e, subjects=tuple(grouped.get(e.id, []))) for e in entries]


def list_published_coverage(
    *,
    kind: str | None = None,
    outlet_id: int | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[CoverageEntry], int]:
    """Paginated listing of published coverage with subjects hydrated.

    Returns (rows, total_count). Each row's ``subjects`` tuple is populated so
    the listing template can render the 'on Item X, Meeting Y' context footer
    without a second per-row query.

    ``q`` runs full-text search against the generated ``search_vector`` column.
    Empty-string ``q`` is treated as None.
    """
    where = ["ce.status = 'published'"]
    params: list = []
    if kind:
        where.append("ce.kind = %s")
        params.append(kind)
    if outlet_id:
        where.append("ce.outlet_id = %s")
        params.append(outlet_id)
    if q and q.strip():
        where.append("ce.search_vector @@ websearch_to_tsquery('english', %s)")
        params.append(q.strip())
    where_sql = " AND ".join(where)

    # Count query
    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM coverage_entries ce WHERE {where_sql}",
                    tuple(params))
        total = cur.fetchone()['n']

    # Page query + subject hydration in the same cursor (one connection)
    offset = max(0, (page - 1) * page_size)
    sql = _COVERAGE_SELECT + f"""
        WHERE {where_sql}
       ORDER BY ce.published_at DESC NULLS LAST
       LIMIT %s OFFSET %s
    """
    with db_cursor() as cur:
        cur.execute(sql, tuple(params) + (page_size, offset))
        rows = _hydrate_coverage_rows(cur)
        rows = _hydrate_subjects_for_entries(cur, rows)
    return rows, total
