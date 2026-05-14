"""Admin routes — roster management and data operations."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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

    Migration 017 candidate (016 is reserved for the audit-FK
    relaxation shipped in this fix-up; the next available slot for the
    ``requires_manual_review BOOLEAN`` column is 017). The JSONB
    stopgap avoids a schema change for v1 but isn't indexable cheaply;
    once the volume of escalated items grows past a handful we should
    promote this to a real column. **Flagged as a follow-up.**
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


# --- Badge audit log viewer + manual badge management (G3) ------------------


_AUDIT_PAGE_SIZE = 50

# Decision #10: badge audit date filters are interpreted in
# America/Chicago — the project is single-state Alabama. A literal
# ::timestamptz cast against a UTC session would silently shift
# user-meaningful day boundaries by 5–6 hours.
_APP_TZ = ZoneInfo("America/Chicago")


def _parse_filter_str(raw: str | None) -> str | None:
    """Trim + treat empty as None — query-param hygiene."""
    if raw is None:
        return None
    s = raw.strip()
    return s or None


def _parse_audit_since(raw: str | None) -> datetime | None:
    """YYYY-MM-DD → start-of-day in America/Chicago (timezone-aware).

    Returns None if the raw string is empty / unparseable. Parse errors
    fall through to None rather than 400 — the viewer is forgiving for
    bookmark-mangled URLs; a user typing garbage just gets the unfiltered
    view back, not an error page.
    """
    s = _parse_filter_str(raw)
    if s is None:
        return None
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=_APP_TZ)


def _parse_audit_until_exclusive(raw: str | None) -> datetime | None:
    """YYYY-MM-DD → start-of-(day+1) in America/Chicago.

    The viewer's UI promises 'include the whole day' for ``until``; the
    helper takes an exclusive upper bound, so this function adds one day
    to make the math line up. (Decision #10's exclusive-of-next-day
    convention.) An event at 23:59 local on the requested day still
    matches.
    """
    start = _parse_audit_since(raw)
    if start is None:
        return None
    return start + timedelta(days=1)


@bp.route("/badges/audit")
def badges_audit():
    """Filterable view of ``agenda_item_badges_audit`` (spec §6.10).

    Filters (all combinable, all bookmarkable):

    - ``badge_slug`` — exact match.
    - ``actor`` — exact match (admin usernames).
    - ``since`` / ``until`` — ``YYYY-MM-DD`` strings interpreted in
      America/Chicago. ``since`` is inclusive at start-of-day local;
      ``until`` is inclusive of the local day-end (translated to an
      exclusive upper bound at start-of-next-day, see decision #10 +
      ``_parse_audit_until_exclusive``).

    Pagination: ``offset`` query param + sentinel-pagination
    (limit+1 / slice / next_offset). Page size 50.

    Auth: blueprint-level ``before_request`` hook redirects
    unauthenticated callers to ``/admin/login``.

    Renders all actor_roles ('admin', 'cron', 'on_write') — admins
    debugging odd badge state need to see automated activity too. Only
    the manage UI restricts to admin-authored writes.
    """
    badge_slug = _parse_filter_str(request.args.get("badge_slug"))
    actor = _parse_filter_str(request.args.get("actor"))
    since_dt = _parse_audit_since(request.args.get("since"))
    until_excl_dt = _parse_audit_until_exclusive(request.args.get("until"))
    offset = _parse_offset(request.args.get("offset"))

    rows_plus_one = query.list_badge_audit_log(
        badge_slug=badge_slug,
        actor=actor,
        since=since_dt,
        until_exclusive=until_excl_dt,
        limit=_AUDIT_PAGE_SIZE + 1,
        offset=offset,
    )
    rows = rows_plus_one[:_AUDIT_PAGE_SIZE]
    next_offset = (
        offset + _AUDIT_PAGE_SIZE
        if len(rows_plus_one) > _AUDIT_PAGE_SIZE
        else None
    )

    return render_template(
        "admin/badges_audit.html",
        rows=rows,
        offset=offset,
        next_offset=next_offset,
        filter_badge_slug=badge_slug or "",
        filter_actor=actor or "",
        # Echo the raw user-supplied YYYY-MM-DD strings back into the
        # form fields so the date inputs stay populated on round-trip.
        filter_since=_parse_filter_str(request.args.get("since")) or "",
        filter_until=_parse_filter_str(request.args.get("until")) or "",
    )


@bp.route("/badges/items/<int:item_id>")
def badges_manage_item(item_id: int):
    """Manage the badge set for a single item.

    Shows the item's current badges (with remove buttons) and a
    dropdown of badges available to add (process + city-policy). Each
    button is an HTMX form posting to the add/remove endpoints; the
    response swaps the panel back in.

    404 if the item doesn't exist. Auth via blueprint hook.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT ai.id, ai.title,
                   m.id   AS municipality_id,
                   m.slug AS municipality_slug,
                   m.name AS municipality_name,
                   mt.id  AS meeting_id,
                   mt.meeting_date
              FROM agenda_items ai
              JOIN meetings mt ON mt.id = ai.meeting_id
              JOIN municipalities m ON m.id = mt.municipality_id
             WHERE ai.id = %s
            """,
            (item_id,),
        )
        item = cur.fetchone()
        if item is None:
            abort(404)
        item = dict(item)

    current = query.list_badges_on_item(item_id)
    attached_slugs = {b["slug"] for b in current}
    addable = [
        b for b in query.list_enabled_badges(item["municipality_id"])
        if b["slug"] not in attached_slugs
    ]

    return render_template(
        "admin/badges_manage.html",
        item=item,
        current=current,
        addable=addable,
    )


@bp.route("/badges/<int:item_id>/add/<slug>", methods=["POST"])
def badge_add(item_id: int, slug: str):
    """Manual add: write badge + audit row in one transaction.

    Decision #92: ``city_id`` is INSERT'd from the item's meeting's
    municipality.

    Idempotent: re-adding a slug that already exists is a no-op (the
    badges table's ``UNIQUE(agenda_item_id, badge_slug)`` constraint
    drives an ``ON CONFLICT DO NOTHING``; the audit row is only
    written if the row was actually inserted).

    Confidence is fixed at 0.95 — high but below the 1.0 threshold
    that triggers the AI-verified Verification Spark (decision #67).
    Source is ``'manual'`` (CHECK constraint accepts it). The actor
    name is recorded in ``matching_metadata`` AND in the audit row's
    ``actor`` column for redundancy.

    Slug must exist in ``priority_badge_templates`` (joined for
    ``kind`` and to validate the slug) — unknown slugs 404.

    Returns the re-rendered manage panel (HTMX swap target).
    """
    actor = session.get("admin_user", "unknown")

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
                abort(404)
            city_id, kind = row
            if kind is None:
                # Slug not in templates → reject.
                abort(404)

            cur.execute(
                """
                INSERT INTO agenda_item_badges
                  (agenda_item_id, city_id, badge_slug, kind, confidence,
                   source, matching_metadata)
                VALUES (%s, %s, %s, %s, 0.95, 'manual', %s::jsonb)
                ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING
                RETURNING id
                """,
                (
                    item_id, city_id, slug, kind,
                    json.dumps({"manual": True, "added_by": actor}),
                ),
            )
            inserted = cur.fetchone()

            if inserted is not None:
                cur.execute(
                    """
                    INSERT INTO agenda_item_badges_audit
                      (agenda_item_id, badge_slug, action, actor, actor_role)
                    VALUES (%s, %s, 'added', %s, 'admin')
                    """,
                    (item_id, slug, actor),
                )

    current_app.logger.info(
        "admin badge add: item_id=%s slug=%s actor=%s inserted=%s",
        item_id, slug, actor, inserted is not None,
    )
    return _render_manage_panel(item_id)


def _render_manage_panel(item_id: int):
    """Re-fetch the manage state and render the swap-target partial.
    Shared by add/remove handlers."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT ai.id, ai.title,
                   m.id   AS municipality_id,
                   m.slug AS municipality_slug
              FROM agenda_items ai
              JOIN meetings mt ON mt.id = ai.meeting_id
              JOIN municipalities m ON m.id = mt.municipality_id
             WHERE ai.id = %s
            """,
            (item_id,),
        )
        item = cur.fetchone()
        if item is None:
            abort(404)
        item = dict(item)

    current = query.list_badges_on_item(item_id)
    attached_slugs = {b["slug"] for b in current}
    addable = [
        b for b in query.list_enabled_badges(item["municipality_id"])
        if b["slug"] not in attached_slugs
    ]

    return render_template(
        "admin/_badges_manage_panel.html",
        item=item,
        current=current,
        addable=addable,
    )


@bp.route("/badges/<int:item_id>/add", methods=["POST"])
def badge_add_via_form(item_id: int):
    """307 redirector: the manage UI form posts ``slug`` as a body
    field; redirect (preserving method + body via 307) to the canonical
    slug-in-path endpoint. Spec mandates ``POST /admin/badges/<id>/add/<slug>``
    as the write site; this route only exists to bridge HTML form
    semantics without JavaScript in the template.

    HTMX honors 307 redirects natively.
    """
    slug = (request.form.get("slug") or "").strip()
    if not slug:
        abort(400)
    return redirect(
        url_for("admin.badge_add", item_id=item_id, slug=slug),
        code=307,
    )


@bp.route("/badges/<int:item_id>/remove/<slug>", methods=["POST"])
def badge_remove(item_id: int, slug: str):
    """Manual remove: hard-DELETE badge + write audit row in one tx.

    The badges table has no ``is_active`` column; remove is a real
    DELETE. The audit row is the historical record.

    404 if the badge isn't attached to the item — no audit row gets
    written for a no-op DELETE. The DELETE's ``RETURNING id`` arm is
    the source of truth for "was anything actually removed."

    Returns the re-rendered manage panel (HTMX swap target).
    """
    actor = session.get("admin_user", "unknown")

    with db() as conn:
        with conn.cursor() as cur:
            # First confirm the item exists at all (separate from the
            # badge presence — we want 404 in either of the two
            # not-found cases).
            cur.execute(
                "SELECT 1 FROM agenda_items WHERE id = %s",
                (item_id,),
            )
            if cur.fetchone() is None:
                abort(404)

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
                abort(404)

            cur.execute(
                """
                INSERT INTO agenda_item_badges_audit
                  (agenda_item_id, badge_slug, action, actor, actor_role)
                VALUES (%s, %s, 'removed', %s, 'admin')
                """,
                (item_id, slug, actor),
            )

    current_app.logger.info(
        "admin badge remove: item_id=%s slug=%s actor=%s",
        item_id, slug, actor,
    )
    return _render_manage_panel(item_id)


# --- Cross-Stage Conflict Resolution UI (G4 — decision #93) -----------------


_CONFLICTS_PAGE_SIZE = 25  # heavier rows than G3; smaller page


@bp.route("/review/conflicts")
def review_conflicts():
    """List items in ``processing_status='cross_stage_conflict'`` for
    admin resolution. Spec decision #93.

    Side-by-side display per row: original title + description + Stage 1
    structured facts (extracted_facts JSONB) + Stage 2 verdict (procedural)
    + conflict reasons array (score_overrides->'conflicts'). Four
    HTMX-powered resolution actions per row, each routing to a service
    function in :mod:`docket.services.conflict_resolution`.

    Sort matches G2/G3 admin queues: priority DESC, ai_generated_at DESC
    (the local schema has no ``updated_at`` on agenda_items; the helper
    uses ``ai_generated_at`` as the closest freshness proxy, mirroring
    the calibration.py spec/code drift workaround).
    Page size 25 (smaller than F5/G2/G3 50 because rows render
    side-by-side, much heavier per-row).

    Auth: blueprint-level ``before_request`` hook redirects unauthed.
    """
    offset = _parse_offset(request.args.get("offset"))

    rows_plus_one = query.list_cross_stage_conflicts(
        limit=_CONFLICTS_PAGE_SIZE + 1,
        offset=offset,
    )
    rows = rows_plus_one[:_CONFLICTS_PAGE_SIZE]
    next_offset = (
        offset + _CONFLICTS_PAGE_SIZE
        if len(rows_plus_one) > _CONFLICTS_PAGE_SIZE
        else None
    )

    return render_template(
        "admin/review_conflicts.html",
        rows=rows,
        offset=offset,
        next_offset=next_offset,
    )


from docket.services import conflict_resolution as conflict_svc


@bp.route("/review/conflicts/<int:item_id>/_form/accept-stage-1")
def conflict_form_accept_s1(item_id: int):
    """GET-only HTMX form expander — renders the inline accept-Stage-1 form
    for a single item (manual_headline + manual_why_it_matters inputs).

    Pre-conditional: the item must exist and be in cross_stage_conflict;
    otherwise 404 to avoid leaking the form for a completed item."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, title, processing_status::text "
            "FROM agenda_items WHERE id = %s",
            (item_id,),
        )
        row = cur.fetchone()
    if row is None or row["processing_status"] != "cross_stage_conflict":
        abort(404)

    return render_template(
        "admin/_conflict_form_accept_s1.html",
        item_id=item_id,
    )


@bp.route("/review/conflicts/<int:item_id>/accept-stage-1", methods=["POST"])
def conflict_accept_stage_1(item_id: int):
    """POST-only: persist manual_headline + manual_why_it_matters,
    flip status to completed, write audit row.

    Returns the rendered ``_conflict_resolved.html`` partial as the
    HTMX swap target. Validation errors return 400 + plain-text body
    (HTMX will render in-place; no full re-render of the row).
    """
    actor = session.get("admin_user", "unknown")
    headline = request.form.get("manual_headline", "")
    why = request.form.get("manual_why_it_matters", "")

    try:
        result = conflict_svc.accept_stage_1(
            item_id,
            manual_headline=headline,
            manual_why_it_matters=why,
            actor=actor,
        )
    except conflict_svc.ConflictValidationError as e:
        return (str(e), 400)
    except LookupError:
        abort(404)

    return render_template(
        "admin/_conflict_resolved.html",
        result=result,
    )


@bp.route("/review/conflicts/<int:item_id>/_form/re-prompt")
def conflict_form_re_prompt(item_id: int):
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, processing_status::text "
            "FROM agenda_items WHERE id = %s",
            (item_id,),
        )
        row = cur.fetchone()
    if row is None or row["processing_status"] != "cross_stage_conflict":
        abort(404)
    return render_template(
        "admin/_conflict_form_re_prompt.html",
        item_id=item_id,
    )


@bp.route("/review/conflicts/<int:item_id>/re-prompt-stage-2", methods=["POST"])
def conflict_re_prompt_stage_2(item_id: int):
    actor = session.get("admin_user", "unknown")
    override = request.form.get("override_instruction", "")

    try:
        result = conflict_svc.re_prompt_stage_2(
            item_id, override_instruction=override, actor=actor,
        )
    except conflict_svc.ConflictValidationError as e:
        return (str(e), 400)
    except conflict_svc.ConflictAlreadyResolvedError as e:
        # Decision #12 — TOCTOU race lost. 409 + plain-text body so the
        # form's hx-on:htmx:response-error handler renders the message
        # in-place; the form stays open.
        return (str(e), 409)
    except LookupError:
        abort(404)

    return render_template("admin/_conflict_resolved.html", result=result)


@bp.route("/review/conflicts/<int:item_id>/_form/edit-facts")
def conflict_form_edit_facts(item_id: int):
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, extracted_facts, processing_status::text
              FROM agenda_items WHERE id = %s
            """,
            (item_id,),
        )
        row = cur.fetchone()
    if row is None or row["processing_status"] != "cross_stage_conflict":
        abort(404)

    return render_template(
        "admin/_conflict_form_edit_facts.html",
        item_id=item_id,
        existing_facts=row["extracted_facts"] or {},
    )


@bp.route("/review/conflicts/<int:item_id>/edit-stage-1-facts", methods=["POST"])
def conflict_edit_stage_1_facts(item_id: int):
    actor = session.get("admin_user", "unknown")
    raw = request.form.get("new_facts_json", "")
    try:
        new_facts = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ("new_facts_json must be valid JSON", 400)

    reason = request.form.get("reason")
    try:
        result = conflict_svc.edit_stage_1_facts(
            item_id,
            new_facts_json=new_facts,
            actor=actor,
            reason=reason,
        )
    except conflict_svc.ConflictValidationError as e:
        return (str(e), 400)
    except conflict_svc.ConflictAlreadyResolvedError as e:
        return (str(e), 409)
    except LookupError:
        abort(404)

    return render_template("admin/_conflict_resolved.html", result=result)


@bp.route("/review/conflicts/<int:item_id>/accept-stage-2", methods=["POST"])
def conflict_accept_stage_2(item_id: int):
    """POST-only: clear Stage 1 facts + flip status to completed.

    No form expander — the listing template's button posts directly.
    Optional ``reason`` field in the body is persisted to
    ``processing_status_audit.reason``.
    """
    actor = session.get("admin_user", "unknown")
    reason = request.form.get("reason")

    try:
        result = conflict_svc.accept_stage_2(
            item_id, actor=actor, reason=reason,
        )
    except conflict_svc.ConflictValidationError as e:
        return (str(e), 400)
    except LookupError:
        abort(404)

    return render_template("admin/_conflict_resolved.html", result=result)


# --- Editorial coverage -----------------------------------------------------

@bp.route("/coverage", methods=["GET"])
def coverage_list():
    """List coverage entries with filter tabs."""
    status_filter = request.args.get('status')  # 'draft' / 'proposed' / 'published' / 'rejected' / None=all
    kind_filter = request.args.get('kind')      # 'note' / 'citation' / None=both

    where = []
    params = []
    if status_filter:
        where.append("ce.status = %s")
        params.append(status_filter)
    if kind_filter:
        where.append("ce.kind = %s")
        params.append(kind_filter)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    with db_cursor() as cur:
        cur.execute(
            f"""SELECT ce.id, ce.kind, ce.status, ce.body, ce.headline,
                       ce.updated_at, ce.featured_until,
                       COALESCE(au.display_name, au.username) AS author_label,
                       o.name AS outlet_name
                  FROM coverage_entries ce
                  JOIN admin_users au ON au.id = ce.author_id
             LEFT JOIN outlets o ON o.id = ce.outlet_id
              {where_sql}
              ORDER BY ce.updated_at DESC
              LIMIT 200""",
            tuple(params),
        )
        rows = cur.fetchall()

        cur.execute(
            """SELECT status, COUNT(*) AS n FROM coverage_entries GROUP BY status"""
        )
        counts = {r['status']: r['n'] for r in cur.fetchall()}

    return render_template(
        "admin/coverage/list.html",
        rows=rows,
        counts=counts,
        status_filter=status_filter,
        kind_filter=kind_filter,
    )


@bp.route("/coverage/new", methods=["GET"])
def coverage_new():
    kind = request.args.get('kind', 'note')
    if kind not in ('note', 'citation'):
        abort(400)
    with db_cursor() as cur:
        cur.execute("SELECT id, slug, name FROM outlets WHERE is_active = TRUE ORDER BY name")
        outlets = cur.fetchall()
    template = 'admin/coverage/new_note.html' if kind == 'note' else 'admin/coverage/new_citation.html'
    return render_template(template, outlets=outlets)


@bp.route("/coverage", methods=["POST"])
def coverage_create():
    from docket.services.coverage_writer import create_note, create_citation
    kind = request.form.get('kind')
    subjects = _parse_subjects_from_form(request.form)
    if not subjects:
        flash("Attach to at least one subject.")
        return redirect(url_for('admin.coverage_new', kind=kind or 'note'))
    author_id = session['admin_user']
    status = 'published' if request.form.get('publish_now') == 'on' else 'draft'
    if kind == 'note':
        body = (request.form.get('body') or '').strip()
        if not body:
            flash("Note body is required.")
            return redirect(url_for('admin.coverage_new', kind='note'))
        create_note(
            author_id=author_id,
            body=body,
            partner_credit=(request.form.get('partner_credit') or '').strip() or None,
            subjects=subjects,
            status=status,
        )
    elif kind == 'citation':
        outlet_id = int(request.form['outlet_id'])
        external_url = (request.form.get('external_url') or '').strip()
        headline = (request.form.get('headline') or '').strip()
        if not (external_url and headline):
            flash("Citation URL and headline are required.")
            return redirect(url_for('admin.coverage_new', kind='citation'))
        article_pub = request.form.get('article_published_at') or None
        create_citation(
            author_id=author_id,
            outlet_id=outlet_id,
            external_url=external_url,
            headline=headline,
            reporter_byline=(request.form.get('reporter_byline') or '').strip() or None,
            excerpt=(request.form.get('excerpt') or '').strip() or None,
            article_published_at=article_pub,
            subjects=subjects,
            status=status,
        )
    else:
        abort(400)
    return redirect(url_for('admin.coverage_list'))


@bp.route("/coverage/<int:coverage_id>/edit", methods=["GET"])
def coverage_edit(coverage_id: int):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM coverage_entries WHERE id = %s", (coverage_id,))
        entry = cur.fetchone()
        if not entry:
            abort(404)
        cur.execute(
            """SELECT subject_type, subject_id, subject_slug
                 FROM coverage_subject_links WHERE coverage_id = %s""",
            (coverage_id,),
        )
        subjects = cur.fetchall()
        # CRITICAL: include the citation's current outlet even if it's been
        # deactivated since the entry was created.
        cur.execute(
            "SELECT id, slug, name FROM outlets "
            "WHERE is_active = TRUE OR id = %s "
            "ORDER BY name",
            (entry['outlet_id'],),
        )
        outlets = cur.fetchall()
    return render_template("admin/coverage/edit.html", entry=entry, subjects=subjects, outlets=outlets)


@bp.route("/coverage/<int:coverage_id>", methods=["POST"])
def coverage_update(coverage_id: int):
    from docket.services.coverage_writer import update_coverage
    fields = {}
    for k in ('body', 'partner_credit', 'external_url', 'headline',
              'reporter_byline', 'excerpt', 'byline'):
        if k in request.form:
            v = (request.form[k] or '').strip()
            fields[k] = v or None
    if 'outlet_id' in request.form and request.form['outlet_id']:
        fields['outlet_id'] = int(request.form['outlet_id'])
    if 'article_published_at' in request.form:
        fields['article_published_at'] = request.form['article_published_at'] or None
    subjects = _parse_subjects_from_form(request.form) if 'subject[]' in request.form else None
    update_coverage(coverage_id, subjects=subjects, **fields)
    return redirect(url_for('admin.coverage_list'))


@bp.route("/coverage/<int:coverage_id>/delete", methods=["POST"])
def coverage_delete(coverage_id: int):
    from docket.services.coverage_writer import delete_coverage
    delete_coverage(coverage_id)
    return redirect(url_for('admin.coverage_list'))


@bp.route("/coverage/<int:coverage_id>/publish", methods=["POST"])
def coverage_publish(coverage_id: int):
    from docket.services.coverage_writer import set_status
    set_status(coverage_id, 'published')
    return redirect(request.referrer or url_for('admin.coverage_list'))


@bp.route("/coverage/<int:coverage_id>/unpublish", methods=["POST"])
def coverage_unpublish(coverage_id: int):
    from docket.services.coverage_writer import set_status
    set_status(coverage_id, 'draft')
    return redirect(request.referrer or url_for('admin.coverage_list'))


@bp.route("/coverage/<int:coverage_id>/reject", methods=["POST"])
def coverage_reject(coverage_id: int):
    from docket.services.coverage_writer import set_status
    set_status(coverage_id, 'rejected')
    return redirect(request.referrer or url_for('admin.coverage_list'))


@bp.route("/coverage/<int:coverage_id>/restore", methods=["POST"])
def coverage_restore(coverage_id: int):
    from docket.services.coverage_writer import set_status
    set_status(coverage_id, 'draft')
    return redirect(request.referrer or url_for('admin.coverage_list'))


@bp.route("/coverage/<int:coverage_id>/feature", methods=["POST"])
def coverage_feature(coverage_id: int):
    from docket.services.coverage_writer import set_featured_until
    set_featured_until(coverage_id, datetime.now(ZoneInfo("America/Chicago")) + timedelta(days=14))
    return redirect(request.referrer or url_for('admin.coverage_list'))


@bp.route("/coverage/<int:coverage_id>/unfeature", methods=["POST"])
def coverage_unfeature(coverage_id: int):
    from docket.services.coverage_writer import set_featured_until
    set_featured_until(coverage_id, None)
    return redirect(request.referrer or url_for('admin.coverage_list'))


@bp.route("/coverage/search", methods=["GET"])
def coverage_search():
    subject_type = request.args.get('subject_type', 'agenda_item')
    q = (request.args.get('q') or '').strip()
    results = []
    if not q:
        return render_template("admin/coverage/_search_results.html",
                               results=[], subject_type=subject_type)
    needle = f"%{_escape_like(q)}%"
    with db_cursor() as cur:
        if subject_type == 'agenda_item':
            cur.execute(
                "SELECT id, title FROM agenda_items "
                "WHERE title ILIKE %s ESCAPE '\\' ORDER BY id DESC LIMIT 15",
                (needle,),
            )
            results = [{'id': r['id'], 'label': r['title']} for r in cur.fetchall()]
        elif subject_type == 'meeting':
            cur.execute(
                "SELECT id, title, meeting_date FROM meetings "
                "WHERE title ILIKE %s ESCAPE '\\' "
                "ORDER BY meeting_date DESC LIMIT 15",
                (needle,),
            )
            results = [{'id': r['id'], 'label': f"{r['title']} ({r['meeting_date']:%Y-%m-%d})"}
                       for r in cur.fetchall()]
        elif subject_type == 'council_member':
            cur.execute(
                "SELECT id, name FROM council_members "
                "WHERE name ILIKE %s ESCAPE '\\' LIMIT 15",
                (needle,),
            )
            results = [{'id': r['id'], 'label': r['name']} for r in cur.fetchall()]
        elif subject_type == 'badge':
            cur.execute(
                "SELECT slug, name FROM priority_badge_templates "
                "WHERE (name ILIKE %s OR slug ILIKE %s) ESCAPE '\\' LIMIT 15",
                (needle, needle),
            )
            results = [{'id': r['slug'], 'label': r['name']} for r in cur.fetchall()]
    return render_template("admin/coverage/_search_results.html",
                           results=results, subject_type=subject_type)


def _parse_subjects_from_form(form) -> list:
    """Parse `subject[]` form fields into the SubjectSpec list expected by the writer.

    Each form value is `<subject_type>:<id_or_slug>`.
    """
    out = []
    for raw in form.getlist('subject[]'):
        if not raw or ':' not in raw:
            continue
        st, val = raw.split(':', 1)
        if st == 'badge':
            out.append((st, None, val))
        elif st in ('agenda_item', 'meeting', 'council_member'):
            try:
                out.append((st, int(val), None))
            except ValueError:
                continue
    return out


def _escape_like(s: str) -> str:
    """Escape Postgres LIKE/ILIKE wildcards in user input.

    A bare ``%`` in admin input would otherwise match every row (the entire
    table dump), and ``_`` would match any single char. Escape both, and
    escape backslashes first so we don't double-escape our own escapes.
    """
    return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


# --- Outlets ---------------------------------------------------------------

@bp.route("/outlets", methods=["GET"])
def outlets_list():
    with db_cursor() as cur:
        cur.execute("SELECT id, slug, name, homepage, is_active FROM outlets ORDER BY name")
        outlets = cur.fetchall()
    return render_template("admin/outlets/list.html", outlets=outlets)


@bp.route("/outlets", methods=["POST"])
def outlets_create():
    from docket.services.outlets_writer import create_outlet
    create_outlet(
        slug=request.form['slug'].strip(),
        name=request.form['name'].strip(),
        homepage=(request.form.get('homepage') or '').strip() or None,
    )
    return redirect(url_for('admin.outlets_list'))


@bp.route("/outlets/<int:outlet_id>", methods=["POST"])
def outlets_update(outlet_id: int):
    from docket.services.outlets_writer import update_outlet
    update_outlet(
        outlet_id,
        name=(request.form.get('name') or '').strip() or None,
        homepage=(request.form.get('homepage') or '').strip() or None,
    )
    return redirect(url_for('admin.outlets_list'))


@bp.route("/outlets/<int:outlet_id>/deactivate", methods=["POST"])
def outlets_deactivate(outlet_id: int):
    from docket.services.outlets_writer import deactivate_outlet
    deactivate_outlet(outlet_id)
    return redirect(url_for('admin.outlets_list'))


@bp.route("/outlets/<int:outlet_id>/activate", methods=["POST"])
def outlets_activate(outlet_id: int):
    from docket.services.outlets_writer import activate_outlet
    activate_outlet(outlet_id)
    return redirect(url_for('admin.outlets_list'))


# --- Admin profile ----------------------------------------------------------

@bp.route("/profile", methods=["GET"])
def profile():
    uid = session['admin_user']
    with db_cursor() as cur:
        cur.execute("SELECT username, display_name FROM admin_users WHERE id = %s", (uid,))
        user = cur.fetchone()
    return render_template("admin/profile.html", user=user)


@bp.route("/profile/display-name", methods=["POST"])
def profile_update_display_name():
    uid = session['admin_user']
    new_name = (request.form.get('display_name') or '').strip() or None
    with db_cursor() as cur:
        cur.execute("UPDATE admin_users SET display_name = %s WHERE id = %s",
                    (new_name, uid))
    return redirect(url_for('admin.profile'))
