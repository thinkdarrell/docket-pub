"""Query service — read APIs for meetings, agenda items, votes, search.

Every read operation goes through this module. Returns dataclasses or dicts.
"""

from __future__ import annotations

from dataclasses import dataclass
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
            ) b_agg ON true
            WHERE ai.meeting_id = %s
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
              )
            """
        )
        params.append(cross_slug)

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

    Single round-trip JOIN of ``priority_badge_templates`` against
    ``priority_badges_config`` on ``(template_slug, city_id)``. Returns
    a dict shaped for template rendering:

    - ``slug``        — template slug (primary key)
    - ``name``        — ``COALESCE(c.name_override, t.name)``
    - ``description`` — ``COALESCE(c.description_override, t.description)``
    - ``icon``        — emoji from the template
    - ``kind``        — ``'process'`` | ``'policy'``
    - ``enabled``     — config row's enabled flag (always ``True`` here
      because the WHERE clause filters disabled rows out)

    Returns ``None`` when:

    1. The template doesn't exist (unknown slug), OR
    2. The city has no ``priority_badges_config`` row for the template
       (city hasn't opted in), OR
    3. The city's config row has ``enabled = FALSE``.

    All three cases mean the badge is not active for this city, so the
    caller (route handler) should respond with 404. We deliberately do
    NOT fall back to the template alone when a city hasn't opted in —
    the enablement gate lives in ``priority_badges_config`` and a city
    seeing a category page for a badge they haven't enabled would be a
    bug, not a feature.
    """
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
            WHERE t.slug = %s
              AND c.enabled = TRUE
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


def badge_volume_series(
    city_id: int,
    badge_slug: str,
    start_date,
    end_date,
    bucket: str = "month",
) -> list[dict]:
    """Volume timeline data for a category landing page — F2 STUB.

    F3 lands the real implementation reading from
    ``mv_badge_volume_monthly`` (migration 013) and returning
    ``[{period, x, y, width, height_substantive, height_consent,
       n_items, n_consent, total_dollars}, ...]`` per spec §6.6.

    F2 stubs this to ``[]`` so the route can call it and template
    rendering can branch on emptiness — F3 lands without changing the
    route signature or template control flow. The signature is
    deliberately the F3-final shape (``city_id``, ``badge_slug``,
    ``start_date``, ``end_date``, ``bucket``) so F3 fills in the body.
    """
    return []


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
