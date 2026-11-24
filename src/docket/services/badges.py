"""Policy badge resolution service.

Reads from priority_badge_templates + priority_badges_config (Migration 013).
Caches per city via lru_cache; invalidate via cache_clear_for_city() if a
config row is mutated by the admin UI (added in a later phase).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from docket.db import db, db_cursor


@dataclass(frozen=True)
class EnabledBadge:
    """A policy badge enabled for a specific city, with merged matcher hints."""
    slug: str
    name: str           # post-override
    description: str    # post-override
    icon: str
    kind: str           # 'policy' for Section D, 'process' badges live elsewhere
    matcher_hints: dict[str, Any]  # post-override merge


@lru_cache(maxsize=32)
def get_enabled_policy_slugs(city_id: int) -> tuple[str, ...]:
    """Return enabled policy badge slugs for a city. Uses tuple so lru_cache works.

    Used by Stage 2 prompt construction — passes the comma-separated list
    of available slugs to the LLM (decision #9).
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT t.slug
              FROM priority_badge_templates t
              JOIN priority_badges_config c ON c.template_slug = t.slug
             WHERE c.city_id = %s
               AND c.enabled = TRUE
               AND t.kind = 'policy'
             ORDER BY t.slug
            """,
            [city_id],
        )
        return tuple(row['slug'] for row in cur.fetchall())


@lru_cache(maxsize=32)
def list_enabled_policy_badges(city_id: int) -> tuple[EnabledBadge, ...]:
    """Return EnabledBadge objects for a city, with hints merged."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT t.slug, t.name AS template_name, t.description AS template_description,
                   t.icon, t.kind, t.default_matcher_hints,
                   c.name_override, c.description_override, c.matcher_hints_override
              FROM priority_badge_templates t
              JOIN priority_badges_config c ON c.template_slug = t.slug
             WHERE c.city_id = %s
               AND c.enabled = TRUE
               AND t.kind = 'policy'
             ORDER BY t.slug
            """,
            [city_id],
        )
        rows = cur.fetchall()

    out: list[EnabledBadge] = []
    for r in rows:
        # Shallow merge: per-key override > default. List-typed values
        # (keywords, action_types, topics, excluded_phrases) get fully replaced;
        # they don't merge element-wise.
        hints = dict(r['default_matcher_hints'] or {})
        if r['matcher_hints_override']:
            hints.update(r['matcher_hints_override'])
        out.append(EnabledBadge(
            slug=r['slug'],
            name=r['name_override'] or r['template_name'],
            description=r['description_override'] or r['template_description'],
            icon=r['icon'],
            kind=r['kind'],
            matcher_hints=hints,
        ))
    return tuple(out)


def get_resolved_badge(city_id: int, slug: str) -> EnabledBadge | None:
    """Return a single (city_id, slug) badge with merged hints, or None if not enabled."""
    for b in list_enabled_policy_badges(city_id):
        if b.slug == slug:
            return b
    return None


def cache_clear_for_city(city_id: int) -> None:
    """Invalidate all caches for a city. Call from admin endpoints that mutate config.

    For v1 we just clear all caches — per-city granularity isn't worth the
    complexity yet.
    """
    get_enabled_policy_slugs.cache_clear()
    list_enabled_policy_badges.cache_clear()


def record_badge_action(
    cur,
    agenda_item_id: int,
    badge_slug: str,
    action: str,
    actor_role: str,
    *,
    actor: str | None = None,
    reason: str | None = None,
) -> None:
    """Insert one row into agenda_item_badges_audit.

    Caller controls the transaction. `cur` is a psycopg cursor.

    Args:
      agenda_item_id: FK to agenda_items.id
      badge_slug: badge slug (e.g. 'sole_source', 'blight')
      action: 'added' | 'removed' | 'modified'
      actor_role: 'admin' | 'cron' | 'on_write'
      actor: optional human/automation identifier (e.g. admin email, 'process_badges_task')
      reason: optional free-text rationale (e.g. 'manual override: misclassified')

    Raises ValueError on unknown action / actor_role to fail loud at the
    Python layer instead of at the DB CHECK constraint.
    """
    if action not in ('added', 'removed', 'modified'):
        raise ValueError(
            f"action must be one of added|removed|modified, got {action!r}"
        )
    if actor_role not in ('admin', 'cron', 'on_write'):
        raise ValueError(
            f"actor_role must be one of admin|cron|on_write, got {actor_role!r}"
        )

    cur.execute(
        """
        INSERT INTO agenda_item_badges_audit
          (agenda_item_id, badge_slug, action, actor, actor_role, reason)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        [agenda_item_id, badge_slug, action, actor, actor_role, reason],
    )


def add_manual_badge(item_id: int, slug: str, actor: str) -> bool | None:
    """Attach a badge to an item by the admin's hand, with its audit row.

    One transaction. ``city_id`` comes from the item's meeting's
    municipality and ``kind`` from the slug's row in
    ``priority_badge_templates``. Confidence is fixed at 0.95, below the 1.0
    that marks an AI-verified badge; source is ``'manual'``; the actor is
    recorded in ``matching_metadata`` and in the audit row.

    Returns ``None``, having written nothing, when the item does not exist
    or the slug is not a template; ``True`` when the badge was inserted (and
    the audit row written); ``False`` when the item already carried the
    badge (no audit row).
    """
    with db() as conn:
        with conn.cursor() as cur:
            # Look up item + city + slug template in one round-trip.
            cur.execute(
                """
                SELECT m.id          AS city_id,
                       t.kind        AS kind
                  FROM agenda_items ai
                  JOIN meetings mt ON mt.id = ai.meeting_id
                  JOIN municipalities m ON m.id = mt.municipality_id
                  LEFT JOIN priority_badge_templates t ON t.slug = %s
                 WHERE ai.id = %s
                """,
                (slug, item_id),
            )
            row = cur.fetchone()
            if row is None:
                return None
            city_id, kind = row
            if kind is None:
                # Slug not in templates.
                return None

            # status='applied' is set explicitly: admin manual adds are
            # always citizen-visible by intent. The decision lane for the
            # LLM-suggested policy-badge path lives in
            # docket.ai.badges_policy.decide_status_and_confidence.
            cur.execute(
                """
                INSERT INTO agenda_item_badges
                  (agenda_item_id, city_id, badge_slug, kind, confidence,
                   source, matching_metadata, status)
                VALUES (%s, %s, %s, %s, 0.95, 'manual', %s::jsonb, 'applied')
                ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING
                RETURNING id
                """,
                (
                    item_id,
                    city_id,
                    slug,
                    kind,
                    json.dumps({"manual": True, "added_by": actor}),
                ),
            )
            inserted = cur.fetchone() is not None

            if inserted:
                record_badge_action(cur, item_id, slug, 'added', 'admin', actor=actor)
    return inserted


def remove_manual_badge(item_id: int, slug: str, actor: str) -> bool:
    """Delete a badge from an item by the admin's hand, with its audit row.

    One transaction. The badges table has no ``is_active`` column, so this
    is a real DELETE and the audit row is the historical record. Returns
    ``False``, having written nothing, when the item does not exist or does
    not carry the badge; ``True`` when the badge was deleted.
    """
    with db() as conn:
        with conn.cursor() as cur:
            # First confirm the item exists at all (separate from the
            # badge presence).
            cur.execute(
                "SELECT 1 FROM agenda_items WHERE id = %s",
                (item_id,),
            )
            if cur.fetchone() is None:
                return False

            cur.execute(
                """
                DELETE FROM agenda_item_badges
                 WHERE agenda_item_id = %s AND badge_slug = %s
                RETURNING id
                """,
                (item_id, slug),
            )
            removed = cur.fetchone()
            if removed is None:
                return False

            record_badge_action(cur, item_id, slug, 'removed', 'admin', actor=actor)
    return True
