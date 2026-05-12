"""Admin review queue for badges Haiku suggested without deterministic backing.

Refactor #2: rather than auto-applying LLM-only badge suggestions to
citizen-facing surfaces (which produced a 71% over-tag rate on
``public_safety_tech_privacy`` in Wave 1), suggestions land in
``status='flagged'`` and require admin approval to be promoted to
``'applied'``. This blueprint exposes the queue + approve/reject
actions.

Plan: docs/superpowers/plans/2026-05-11-conservative-policy-badges.md
"""

from __future__ import annotations

from flask import Blueprint, abort, render_template, request, session

from docket.db import db, db_cursor
from docket.web.auth import login_required

bp = Blueprint("admin_badge_review", __name__, url_prefix="/admin")

PER_PAGE = 50


@bp.route("/badge-review")
@login_required
def review_queue():
    """List ``agenda_item_badges`` rows with ``status='flagged'`` for
    human review. Filters ``?slug=`` and ``?city_id=`` narrow the queue.

    Newest flags lead; LIMIT keeps the page lightweight even when the
    backfill (Section E) has just dropped ~400 rows into the queue. The
    partial-index ``idx_agenda_item_badges_status_slug`` on
    ``(status, city_id, badge_slug) WHERE status='flagged'`` makes this
    listing cheap regardless of total badge count.
    """
    badge_slug_filter = request.args.get("slug")
    city_id_filter = request.args.get("city_id", type=int)

    sql = """
        SELECT b.id           AS badge_id,
               b.agenda_item_id,
               b.city_id,
               b.badge_slug,
               b.confidence::float AS confidence,
               b.matching_metadata,
               b.detected_at,
               ai.title        AS item_title,
               m.meeting_date  AS meeting_date,
               muni.name       AS city_name,
               muni.slug       AS city_slug
          FROM agenda_item_badges b
          JOIN agenda_items ai     ON ai.id = b.agenda_item_id
          JOIN meetings m          ON m.id = ai.meeting_id
          JOIN municipalities muni ON muni.id = b.city_id
         WHERE b.status = 'flagged'
    """
    params: list = []
    if badge_slug_filter:
        sql += " AND b.badge_slug = %s"
        params.append(badge_slug_filter)
    if city_id_filter:
        sql += " AND b.city_id = %s"
        params.append(city_id_filter)
    sql += " ORDER BY b.detected_at DESC LIMIT %s"
    params.append(PER_PAGE)

    with db_cursor() as cur:
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]

    return render_template(
        "admin/badge_review.html",
        flagged_badges=rows,
        badge_slug_filter=badge_slug_filter,
        city_id_filter=city_id_filter,
    )


@bp.route("/badge-review/<int:badge_id>/approve", methods=["POST"])
@login_required
def approve_badge(badge_id: int):
    """Promote ``status='flagged'`` → ``'applied'``, audit, return empty
    body (HTMX swaps the row out of the table)."""
    return _set_status_and_audit(badge_id, "applied", "approved")


@bp.route("/badge-review/<int:badge_id>/reject", methods=["POST"])
@login_required
def reject_badge(badge_id: int):
    """Set ``status='rejected'``, audit, return empty body for HTMX swap."""
    return _set_status_and_audit(badge_id, "rejected", "rejected")


def _set_status_and_audit(badge_id: int, new_status: str, audit_action: str):
    """Atomic status flip + audit row write in one connection."""
    actor = session.get("admin_user", "unknown")
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agenda_item_badges
                   SET status = %s
                 WHERE id = %s
             RETURNING agenda_item_id, badge_slug
                """,
                (new_status, badge_id),
            )
            row = cur.fetchone()
            if row is None:
                abort(404)
            agenda_item_id, badge_slug = row
            cur.execute(
                """
                INSERT INTO agenda_item_badges_audit
                  (agenda_item_id, badge_slug, action, actor, actor_role, reason)
                VALUES (%s, %s, %s, %s, 'admin', %s)
                """,
                (
                    agenda_item_id,
                    badge_slug,
                    audit_action,
                    actor,
                    f"admin review queue: {audit_action}",
                ),
            )
    return ("", 200)
