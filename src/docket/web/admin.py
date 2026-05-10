"""Admin routes — roster management and data operations."""

from __future__ import annotations

import json

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from docket.db import db, db_cursor
from docket.services import query

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.before_request
def require_login():
    """All admin routes require authentication."""
    # Auth blueprint handles /admin/login and /admin/logout itself
    from flask import session

    if request.endpoint and request.endpoint.startswith("admin."):
        if "admin_user" not in session:
            return redirect(url_for("auth.login", next=request.path))


# --- Council member management ----------------------------------------------


@bp.route("/members/")
def list_members():
    """List all council members across all cities."""
    municipalities = query.list_municipalities()
    members_by_city = {}
    for muni in municipalities:
        members_by_city[muni["slug"]] = {
            "municipality": muni,
            "members": query.list_council_members(muni["slug"], active_only=False),
        }

    return render_template(
        "admin/members.html",
        members_by_city=members_by_city,
    )


@bp.route("/members/add", methods=["GET", "POST"])
def add_member():
    """Add a new council member."""
    municipalities = query.list_municipalities()

    if request.method == "POST":
        slug = request.form["municipality"]
        name = request.form["name"].strip()
        district_name = request.form.get("district", "").strip()
        email = request.form.get("email", "").strip() or None
        photo_url = request.form.get("photo_url", "").strip() or None

        if not name or not slug:
            abort(400)

        muni = query.get_municipality(slug)
        if not muni:
            abort(404)

        with db_cursor() as cur:
            # Resolve district if provided
            district_id = None
            if district_name:
                cur.execute(
                    "SELECT id FROM districts WHERE municipality_id = %s AND name = %s",
                    (muni["id"], district_name),
                )
                row = cur.fetchone()
                if row:
                    district_id = row["id"]

            cur.execute(
                """
                INSERT INTO council_members
                    (municipality_id, district_id, name, email, photo_url, active)
                VALUES (%s, %s, %s, %s, %s, TRUE)
                """,
                (muni["id"], district_id, name, email, photo_url),
            )

        return redirect(url_for("admin.list_members"))

    # GET — show form
    # Fetch districts for each municipality
    districts_by_city = {}
    for muni in municipalities:
        with db_cursor() as cur:
            cur.execute(
                "SELECT name FROM districts WHERE municipality_id = %s ORDER BY number",
                (muni["id"],),
            )
            districts_by_city[muni["slug"]] = [row["name"] for row in cur.fetchall()]

    return render_template(
        "admin/member_form.html",
        municipalities=municipalities,
        districts_by_city=districts_by_city,
        member=None,
    )


@bp.route("/members/<int:member_id>/edit", methods=["GET", "POST"])
def edit_member(member_id):
    """Edit an existing council member."""
    member = query.get_council_member(member_id)
    if not member:
        abort(404)

    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form.get("email", "").strip() or None
        photo_url = request.form.get("photo_url", "").strip() or None
        active = request.form.get("active") == "on"

        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE council_members
                    SET name = %s, email = %s, photo_url = %s, active = %s
                    WHERE id = %s
                    """,
                    (name, email, photo_url, active, member_id),
                )

        return redirect(url_for("admin.list_members"))

    return render_template(
        "admin/member_form.html",
        member=member,
        municipalities=None,
        districts_by_city=None,
    )


@bp.route("/members/<int:member_id>/deactivate", methods=["POST"])
def deactivate_member(member_id):
    """Deactivate a council member (term ended)."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE council_members SET active = FALSE WHERE id = %s",
                (member_id,),
            )

    return redirect(url_for("admin.list_members"))


# --- Admin OCR queue + errors queue (G2) ------------------------------------


_QUEUE_PAGE_SIZE = 50


def _parse_offset(raw: str | None) -> int:
    """Defensive offset parsing (mirrors F5's category_landing pattern)."""
    try:
        offset = int(raw or 0)
    except (TypeError, ValueError):
        offset = 0
    return max(0, offset)


@bp.route("/data-debt/")
def data_debt():
    """Admin OCR queue (G2.1, spec §6.10, decision #84).

    Cross-city: aggregates all items where source documents failed to
    yield machine-readable text (``data_quality != 'ok'``) or where the
    v3 pipeline gave up (``processing_status = 'failed_permanent'``).

    Sort: ``data_debt_priority DESC, meeting_date DESC`` — same as the
    F5 public page and the errors queue. HIGH-priority items lead.

    Differs from the F5 public page (``/al/<city>/data-debt``):

    - No ``<city>`` slug — admin sees all cities aggregated.
    - Per-row ``data_debt_priority``, ``data_quality``, and
      ``processing_status`` values shown verbatim (no jargon scrub).
    - Each row carries ``id="item-N"`` so the source-anchor button can
      deep-link to a specific item via ``#item-N`` fragment. The
      browser handles scroll natively — no server-side query-param
      plumbing. (Spec deviation: §6.10 shows ``?highlight=N``; the
      fragment-based approach was adopted to fix the silent no-op for
      items past the first paginated page.)

    Reuses :func:`query.list_data_debt_items` with ``city_id=None`` —
    one helper, two call sites (public + admin). Pagination is the same
    sentinel-pagination shape as the F5 public page.

    Auth: blueprint-level ``before_request`` hook covers login.
    """
    offset = _parse_offset(request.args.get("offset"))

    items_plus_one = query.list_data_debt_items(
        None,  # city_id=None → cross-city
        limit=_QUEUE_PAGE_SIZE + 1,
        offset=offset,
    )
    items = items_plus_one[: _QUEUE_PAGE_SIZE]
    next_offset = (offset + _QUEUE_PAGE_SIZE) if len(items_plus_one) > _QUEUE_PAGE_SIZE else None

    return render_template(
        "admin/data_debt.html",
        items=items,
        offset=offset,
        next_offset=next_offset,
    )


@bp.route("/errors")
def errors():
    """Admin errors queue (G2.2, decision #79).

    Lists items at ``processing_status='failed_permanent'`` across all
    cities. Sort matches :func:`data_debt`: priority then recency.
    Per-row retry / escalate POST buttons let an operator unstick or
    flag items for manual review.
    """
    offset = _parse_offset(request.args.get("offset"))

    items_plus_one = query.list_failed_permanent_items_all_cities(
        limit=_QUEUE_PAGE_SIZE + 1,
        offset=offset,
    )
    items = items_plus_one[: _QUEUE_PAGE_SIZE]
    next_offset = (offset + _QUEUE_PAGE_SIZE) if len(items_plus_one) > _QUEUE_PAGE_SIZE else None

    return render_template(
        "admin/errors.html",
        items=items,
        offset=offset,
        next_offset=next_offset,
    )


@bp.route("/errors/<int:item_id>/retry", methods=["POST"])
def errors_retry(item_id: int):
    """POST-only: reset an item back to ``pending`` so the worker re-runs it.

    Semantics:

    - Sets ``processing_status='pending'``.
    - Resets ``processing_attempts=0`` so retry budget is fresh.
    - Clears ``backfill_session_id``, ``last_error_at``,
      ``last_error_message`` so the row is in clean post-retry state
      (B5 backfill driver requires ``backfill_session_id IS NULL`` to
      pick up an item; defensive hygiene avoids stale-error display).
    - Writes a ``processing_status_audit`` row capturing the
      from/to/actor for traceability (decision #93's audit table).
    - Logs the action via ``current_app.logger`` for cron-correlated
      diagnostics.

    Does NOT touch ``score_overrides`` or any badge state — this is a
    pipeline unsticker, not a content rollback. If badges were attached
    after the worker last completed, they remain; the next worker pass
    is responsible for any badge re-evaluation.
    """
    actor = session.get("admin_user", "unknown")

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT processing_status::text FROM agenda_items WHERE id = %s",
                (item_id,),
            )
            row = cur.fetchone()
            if row is None:
                abort(404)
            from_status = row[0]

            cur.execute(
                """
                UPDATE agenda_items
                   SET processing_status = 'pending'::processing_status_enum,
                       processing_attempts = 0,
                       backfill_session_id = NULL,
                       last_error_at = NULL,
                       last_error_message = NULL
                 WHERE id = %s
                """,
                (item_id,),
            )

            cur.execute(
                """
                INSERT INTO processing_status_audit
                  (agenda_item_id, from_status, to_status, action,
                   actor, actor_role, reason)
                VALUES
                  (%s, %s::processing_status_enum,
                   'pending'::processing_status_enum,
                   'retry', %s, 'admin', %s)
                """,
                (item_id, from_status, actor, "Admin retry from errors queue"),
            )

    current_app.logger.info(
        "admin retry: item_id=%s actor=%s from_status=%s",
        item_id, actor, from_status,
    )
    flash(f"Item #{item_id} retry queued.")
    return redirect(url_for("admin.errors"))


@bp.route("/errors/<int:item_id>/escalate", methods=["POST"])
def errors_escalate(item_id: int):
    """POST-only: flag an item for manual review.

    v1 stopgap: writes ``score_overrides->>'admin_escalated' = 'true'``
    (decision-#93 audit row also written). The worker should treat
    this flag as "do not auto-retry — human attention needed."

    Migration 016 candidate (next available migration slot): add a
    dedicated ``requires_manual_review BOOLEAN`` column on
    ``agenda_items``. The JSONB stopgap avoids a schema change for v1
    but isn't indexable cheaply; once the volume of escalated items
    grows past a handful we should promote this to a real column.
    **Flagged as a follow-up.**
    """
    actor = session.get("admin_user", "unknown")

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT processing_status::text, score_overrides
                  FROM agenda_items
                 WHERE id = %s
                """,
                (item_id,),
            )
            row = cur.fetchone()
            if row is None:
                abort(404)
            from_status, existing_overrides = row[0], row[1]

            # Merge admin_escalated into existing score_overrides
            # without clobbering Stage 2.5 floor data. psycopg2 returns
            # JSONB as a Python dict (or None when NULL).
            merged = dict(existing_overrides) if existing_overrides else {}
            merged["admin_escalated"] = True
            merged["admin_escalated_by"] = actor

            cur.execute(
                """
                UPDATE agenda_items
                   SET score_overrides = %s::jsonb
                 WHERE id = %s
                """,
                (json.dumps(merged), item_id),
            )

            cur.execute(
                """
                INSERT INTO processing_status_audit
                  (agenda_item_id, from_status, to_status, action,
                   actor, actor_role, reason, payload)
                VALUES
                  (%s, %s::processing_status_enum,
                   %s::processing_status_enum,
                   'escalate', %s, 'admin', %s, %s::jsonb)
                """,
                (
                    item_id, from_status, from_status, actor,
                    "Admin escalated from errors queue (manual review needed)",
                    json.dumps({"admin_escalated": True}),
                ),
            )

    current_app.logger.info(
        "admin escalate: item_id=%s actor=%s status=%s",
        item_id, actor, from_status,
    )
    flash(f"Item #{item_id} escalated to manual review.")
    return redirect(url_for("admin.errors"))


# --- Source-anchor domain allowlist refresh ---------------------------------


@bp.route("/source-security/refresh", methods=["POST"])
def refresh_source_security():
    """Invalidate the cached source-anchor domain allowlist.

    The allowlist (static platform domains + dynamic municipality hosts
    from ``municipalities.adapter_config->>'base_url'``) is cached at
    module level with a 10-minute TTL inside
    :mod:`docket.web.source_security`. Onboarding a new municipality
    will be picked up automatically within the TTL window; this endpoint
    forces an immediate refresh by clearing the cache. The next render
    that calls ``is_source_url_safe`` (or any direct call to
    :func:`source_security.get_allowlist`) re-reads from the DB.

    POST-only so accidental browser navigation (`GET /admin/source-
    security/refresh`) can't trigger a refresh — defense against the
    one-click-prefetch shape that crawlers/extensions sometimes hit.
    Auth is enforced by the blueprint-level ``before_request`` hook
    above, so unauth'd POSTs redirect to login like any other admin
    route.
    """
    from docket.web import source_security

    source_security.invalidate_cache()
    return (
        "Allowlist cache invalidated. Next request will refresh from DB.",
        200,
    )


# --- Calibration dashboard --------------------------------------------------


@bp.route("/calibration")
def calibration():
    """Calibration dashboard — score-divergence + drift + false-positives.

    Six panels, one per query in :mod:`docket.services.calibration`:

    1. Per-item divergence (24h, ABS sig delta > 3) — Spec §3.5 Query A.
    2. Under-scoring Impact (7d, sample >= 30, > 20% boosted) — §3.5 B1.
    3. Over-scoring Consent (symmetric to B1) — §3.5 B2.
    4. Baseline drift (12-week per-action_type trend) — §3.5 Query C.
    5. Badge volume calibration (12-week per-policy-badge with
       deterministic/llm split) — §5.7.
    6. Top False Positives (admin removals >= 5 / 7d) — §5.7 / decision #65.

    No caching for v1 — admin traffic is low and ``login_required``
    keeps random hits out. If the page feels slow on real production
    data later, add a ``threading.Lock`` + double-checked-locking
    cache helper following the F5 ``_rss_cached`` pattern in
    ``docket.web.public``. Five-minute staleness on an admin-only
    monitoring surface is the wrong tradeoff today.
    """
    from docket.services import calibration as calibration_service

    return render_template(
        "admin/calibration.html",
        per_item_divergence=calibration_service.query_a_per_item_divergence(),
        under_scoring_impact=calibration_service.query_b1_under_scoring_impact(),
        over_scoring_consent=calibration_service.query_b2_over_scoring_consent(),
        baseline_drift=calibration_service.query_c_baseline_drift(),
        badge_volume=calibration_service.query_badge_volume_calibration(),
        top_false_positives=calibration_service.query_top_false_positives(),
    )


# --- AI pipeline dashboard --------------------------------------------------


@bp.route("/ai")
def ai_panel():
    """AI pipeline dashboard — pending counts, cost telemetry, recent runs."""
    from docket.ai.prompts import ITEM_PROMPT_VERSION, MEETING_PROMPT_VERSION
    from docket.config import AI_DAILY_BUDGET_USD, AI_ITEM_DEBOUNCE_MINUTES

    with db_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS pending FROM agenda_items
             WHERE (ai_prompt_version IS NULL OR ai_prompt_version < %s)
               AND created_at < NOW() - (%s || ' minutes')::interval
            """,
            (ITEM_PROMPT_VERSION, AI_ITEM_DEBOUNCE_MINUTES),
        )
        items_pending = cur.fetchone()["pending"]

        cur.execute(
            """
            SELECT COUNT(*) AS pending FROM meetings m
             WHERE (
               ((m.ai_prompt_version IS NULL OR m.ai_prompt_version < %s)
                AND m.minutes_adopted_at IS NULL
                AND NOT EXISTS (
                  SELECT 1 FROM agenda_items ai
                   WHERE ai.meeting_id = m.id
                     AND (ai.ai_prompt_version IS NULL OR ai.ai_prompt_version < %s)
                ))
               OR (m.minutes_adopted_at IS NOT NULL
                   AND COALESCE(m.ai_metadata->>'phase', '') != 'adopted')
             )
            """,
            (MEETING_PROMPT_VERSION, ITEM_PROMPT_VERSION),
        )
        meetings_pending = cur.fetchone()["pending"]

        cur.execute(
            """
            SELECT COALESCE(SUM(cost_usd), 0)::float AS total,
                   COALESCE(SUM((usage->>'cache_read_input_tokens')::int), 0) AS cache_reads,
                   COALESCE(SUM((usage->>'input_tokens')::int), 0) AS regular_reads
              FROM ai_runs
             WHERE started_at > NOW() - INTERVAL '7 days'
            """
        )
        seven_day = dict(cur.fetchone())

        cur.execute(
            """
            SELECT id, started_at, stage, model, rows_processed, rows_failed, cost_usd
              FROM ai_runs
             ORDER BY id DESC
             LIMIT 20
            """
        )
        runs = [dict(row) for row in cur.fetchall()]

    return render_template(
        "admin/ai_panel.html",
        items_pending=items_pending,
        meetings_pending=meetings_pending,
        seven_day=seven_day,
        runs=runs,
        budget=AI_DAILY_BUDGET_USD,
        item_version=ITEM_PROMPT_VERSION,
        meeting_version=MEETING_PROMPT_VERSION,
    )
