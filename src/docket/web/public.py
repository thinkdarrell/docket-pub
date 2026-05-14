"""Public-facing routes — citizen UI.

Thin routes that call into docket.services.query and render templates.
Business logic stays in services, not here.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    url_for,
)

from docket.enrichment.topics import all_topics, get_topic_display_name
from docket.models.data_quality import friendly_label
from docket.services import query

bp = Blueprint("public", __name__)


# --- Template context helpers -----------------------------------------------
#
# The ``dollar_tier`` filter used to live here as a thin wrapper around
# ``classify_dollar_tier`` returning the colour string. It moved to
# :mod:`docket.web.filters` in E5 (Phase 2 v3 partials) where it now
# returns a :class:`~docket.web.filters.DollarTier` NamedTuple. Backward
# compatibility for v2 templates is preserved via ``DollarTier.__str__``
# returning ``self.color`` — ``class="tier tier-{{ amt | dollar_tier }}"``
# still renders ``tier-green``. See ``filters.py`` for the rationale.


@bp.app_template_filter("topic_name")
def topic_name_filter(slug):
    """Jinja2 filter: {{ item.topic | topic_name }}"""
    if not slug:
        return ""
    return get_topic_display_name(slug) or slug


# --- Routes -----------------------------------------------------------------


@bp.route("/")
def index():
    """Homepage — city picker, this week, upcoming."""
    municipalities = query.list_municipalities()
    recent = query.list_recent_meetings(days=7, limit=10)
    upcoming = query.list_upcoming_meetings(days=14, limit=10)
    stats = query.dashboard_stats()

    return render_template(
        "index.html",
        municipalities=municipalities,
        recent_meetings=recent,
        upcoming_meetings=upcoming,
        stats=stats,
    )


_overview_cache: dict[str, tuple] = {}
_CACHE_TTL = 300  # 5 minutes
# F5 fix-up (R1 + D4 / Override 2): symmetric thread safety. Module-level
# Lock + double-checked locking shields the cache-miss + render + set
# sequence from the thundering-herd race when multiple workers/threads
# request the same cold key simultaneously. Latent today (single-worker
# sync gunicorn per Procfile + Dockerfile), but cheap to fix while the
# helper is small. Mirrors the lock we add to ``_rss_cached`` below.
_overview_lock = threading.Lock()


@bp.route("/al/<slug>/")
def city_overview(slug):
    """City landing page — full overview with all sections."""
    municipality = query.get_municipality(slug)
    if not municipality:
        abort(404)

    now_ts = time.time()
    cached = _overview_cache.get(slug)
    if cached and (now_ts - cached[0]) < _CACHE_TTL:
        return cached[1]

    with _overview_lock:
        # Double-check: another waiter may have populated the cache
        # while we were blocked acquiring the lock.
        cached = _overview_cache.get(slug)
        if cached and (time.time() - cached[0]) < _CACHE_TTL:
            return cached[1]
        return _city_overview_render(slug, municipality, now_ts)


def _city_overview_render(slug, municipality, now_ts):
    """Render and cache the city overview page. Caller holds ``_overview_lock``."""
    from datetime import datetime

    result = query.list_meetings(slug, limit=6)
    topics = query.topic_counts(municipality_slug=slug)
    members = query.list_council_members(slug)
    recent = query.list_recent_meetings(days=7, limit=4)
    upcoming = query.list_upcoming_meetings(days=14, limit=4)
    notable = query.list_high_dollar_items(municipality_slug=slug, limit=6, days=180)
    stats = query.dashboard_stats()
    # TODO: precompute these — too heavy for cold page loads on Railway
    contested = []
    recent_votes = []

    # Filter timeline to this city
    recent_city = [m for m in recent if m.get("municipality_slug") == slug]
    upcoming_city = [m for m in upcoming if m.get("municipality_slug") == slug]

    # F4 Browse-by-Priority (spec §6.7): two grids passed as
    # pre-decorated dicts — counts are zipped on here in the route, NOT
    # computed via Jinja globals (route-side pre-compute pattern set by
    # F2). Counts are gated identically to ``list_items_by_badge`` /
    # ``category_kpis`` so a tile reading "12 this year" matches what
    # the citizen will see when they click into the category page.
    #
    # Cost: each grid does one count query per badge, all light
    # (covered by ``idx_agenda_item_badges_city_slug_conf``). 4 + 7 = 11
    # SELECT COUNT queries per cold city homepage render, then cached
    # for 5 min by the existing ``_overview_cache``. If this turns out
    # to be a hot-path tax post-deploy, the natural follow-up is a
    # single GROUP BY query rolled into ``list_*_badges``.
    current_year = date.today().year
    city_policy_badges = [
        {**b,
         "count": query.badge_volume_year(
             municipality["id"], b["slug"], year=current_year
         )}
        for b in query.list_city_policy_badges(municipality["id"])
    ]
    process_badges = [
        {**b,
         "count": query.badge_volume_recent(
             municipality["id"], b["slug"], days=30
         )}
        for b in query.list_process_badges()
    ]

    from docket.services.query import coverage_counts_for_items
    notable_item_ids = [it['id'] for it in notable if 'id' in it]
    coverage_counts = coverage_counts_for_items(notable_item_ids)

    rendered = render_template(
        "city.html",
        municipality=municipality,
        meetings=result.meetings,
        meeting_count=result.total,
        topics=topics,
        members=members,
        recent_meetings=recent_city,
        upcoming_meetings=upcoming_city,
        notable_items=notable,
        contested_votes=contested,
        recent_votes=recent_votes,
        stats=stats,
        city_policy_badges=city_policy_badges,
        process_badges=process_badges,
        now=datetime.now(),
        coverage_counts=coverage_counts,
    )
    _overview_cache[slug] = (now_ts, rendered)
    return rendered


@bp.route("/al/<slug>/meetings/")
def city_meetings(slug):
    """Meeting list with filters and pagination."""
    municipality = query.get_municipality(slug)
    if not municipality:
        abort(404)

    meeting_type = request.args.get("type")
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 20
    offset = (page - 1) * per_page

    result = query.list_meetings(
        slug,
        meeting_type=meeting_type,
        limit=per_page,
        offset=offset,
    )
    total_pages = (result.total + per_page - 1) // per_page

    return render_template(
        "meetings.html",
        municipality=municipality,
        meetings=result.meetings,
        total=result.total,
        page=page,
        total_pages=total_pages,
        meeting_type=meeting_type,
    )


@bp.route("/al/<slug>/meetings/<int:meeting_id>/")
def meeting_detail(slug, meeting_id):
    """Meeting detail — agenda items, votes."""
    municipality = query.get_municipality(slug)
    if not municipality:
        abort(404)

    meeting = query.get_meeting(meeting_id)
    if not meeting or meeting.municipality_id != municipality["id"]:
        abort(404)

    agenda_items = query.list_agenda_items(meeting_id)
    votes = query.list_votes(meeting_id)
    consent_items = [i for i in agenda_items if i.is_consent]
    regular_items = [i for i in agenda_items if not i.is_consent]
    dollar_count = sum(1 for i in agenda_items if i.dollars_amount)
    topic_count = len({i.topic for i in agenda_items if i.topic})

    from docket.services.query import coverage_counts_for_items
    item_ids = [it.id for it in agenda_items]
    coverage_counts = coverage_counts_for_items(item_ids)

    return render_template(
        "meeting_detail.html",
        municipality=municipality,
        meeting=meeting,
        agenda_items=agenda_items,
        consent_items=consent_items,
        regular_items=regular_items,
        votes=votes,
        dollar_count=dollar_count,
        topic_count=topic_count,
        item_count=len(agenda_items),
        coverage_counts=coverage_counts,
    )


@bp.route("/al/<slug>/items/<int:item_id>/")
def item_detail(slug, item_id):
    """Per-item detail page."""
    municipality = query.get_municipality(slug)
    if not municipality:
        abort(404)

    item = query.get_agenda_item(item_id)
    if not item:
        abort(404)

    # Verify the item belongs to this city via its meeting
    meeting = query.get_meeting(item.meeting_id)
    if not meeting or meeting.municipality_id != municipality["id"]:
        abort(404)

    from docket.services.query import coverage_for_subject
    coverage = coverage_for_subject('agenda_item', subject_id=item_id)

    return render_template(
        "item_detail.html",
        municipality=municipality,
        item=item,
        meeting=meeting,
        coverage=coverage,
    )


@bp.route("/al/<slug>/<badge_slug>/")
def category_landing(slug: str, badge_slug: str):
    """Category landing page for a priority badge in a city.

    Renders spec §6.5: header (badge icon + name + city), KPI strip,
    volume timeline (server-rendered SVG via partials/volume_timeline.html),
    filter controls, item list (Smart Brevity Cards), load-more pagination.

    404s on:
      - Unknown city slug
      - Unknown badge slug
      - Badge slug that exists but is not enabled for this city
        (``get_resolved_badge`` returns ``None``)

    Query params:
      - ``and=slug,slug``  — cross-filter slugs, AND-semantic
        (item must carry every cross-filter badge in addition to the
        primary). Empty/missing → no cross filter.
      - ``offset=N``       — pagination offset. Bad input → 0;
        negative input → clamped to 0.

    Note: this route does NOT respect ``SMART_BREVITY_UI`` flag — the
    page is brand-new v3-only. The ``smart_brevity_card`` dispatcher
    routes per-item to a v3 partial when ``ai_rewrite_version == 3``
    and falls back to v2/pending variants for items still in earlier
    pipeline states (same dispatcher used by ``meeting_detail.html``
    in the flag-on branch).
    """
    municipality = query.get_municipality(slug)
    if not municipality:
        abort(404)

    badge = query.get_resolved_badge(municipality["id"], badge_slug)
    if not badge:
        abort(404)

    # Cross-filters via /?and=slug,slug — AND semantics enforced by the
    # service helper. Whitespace stripped + empty tokens dropped so the
    # URL-encoded form ``?and=blight,%20housing`` doesn't yield a stray
    # ``" housing"`` slug that silently fails to match. Stray commas and
    # all-whitespace segments are also discarded (S1).
    raw = request.args.get("and", "")
    raw_cross_filters = [s.strip() for s in raw.split(",") if s.strip()]

    # Trailing ``?and=`` cleanup (Opus#2-S4). HTMX serializes the empty
    # "(none)" option as ``and=`` which leaves a dangling query param
    # in the URL bar. Redirect to the canonical no-filter URL so a
    # bookmark / share doesn't carry the empty param. Skipped for HTMX
    # requests (the redirect would force a full-page load and undo the
    # partial swap; the URL-bar cleanup matters for full-page navigation).
    if (
        "and" in request.args
        and not raw_cross_filters
        and request.headers.get("HX-Request") != "true"
    ):
        return redirect(
            url_for(
                "public.category_landing",
                slug=municipality["slug"],
                badge_slug=badge_slug,
            )
        )

    # Slug validation against enabled badges for the city (S5 / spec
    # §6.8 "validates against enabled badges"). Drops slugs that aren't
    # process-or-policy-enabled for the city — typo'd query params or
    # disabled badges no longer leak into the EXISTS predicate (which
    # would silently match nothing). Computed once and reused below for
    # the dropdown's ``available_badges`` so we don't query twice.
    enabled_badges = query.list_enabled_badges(municipality["id"])
    enabled_slugs = {b["slug"] for b in enabled_badges}
    cross_filters = [s for s in raw_cross_filters if s in enabled_slugs]

    # Defensive offset parsing: bad input becomes 0 (never crashes the
    # route); negative input clamped to 0 (a -5 offset would otherwise
    # confuse the SQL planner / leak past data).
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)

    # ?month=YYYY-MM bar-click drill-down (PR D). Defensive regex check;
    # bad input silently becomes no filter so a misuse from another
    # caller can't smuggle a free-form string into the SQL params.
    month_filter_raw = request.args.get("month", "")
    if month_filter_raw and not re.fullmatch(
        r"\d{4}-(0[1-9]|1[0-2])", month_filter_raw
    ):
        month_filter_raw = ""
    month_filter = month_filter_raw or None
    active_month_label = None
    if month_filter:
        active_month_label = date.fromisoformat(month_filter + "-01").strftime(
            "%B %Y"
        )
    # Args minus ?month for the clear-month chip/link in templates.
    # Jinja can't do dict comprehensions, so precompute here.
    args_without_month = {
        k: v for k, v in request.args.items() if k != "month"
    }

    # LIMIT 26 sentinel pagination (S3): ask for one more than the page
    # size. If we get all 26 back, slice off the 26th and signal there's
    # a next page; if we get <= 25, there is no next page. This avoids
    # the off-by-one where exactly 25 items in the dataset would surface
    # a "load more" button that loaded an empty page.
    items_plus_one = query.list_items_by_badge(
        municipality["id"],
        badge_slug,
        cross_filter_slugs=cross_filters,
        limit=26,
        offset=offset,
        month_filter=month_filter,
    )
    items = items_plus_one[:25]
    next_offset = (offset + 25) if len(items_plus_one) > 25 else None

    current_year = date.today().year
    # All-time-indexed tally replaces year-scoped KPI strip (PR D).
    # category_kpis is retained for any out-of-scope caller but the
    # category-landing route no longer reads it.
    tally = query.category_tally(
        municipality["id"],
        badge_slug,
        cross_filter_slugs=cross_filters,
    )
    backfill_ratio = query.city_backfill_ratio(municipality["id"])

    # Volume timeline window: 5-year rolling, inclusive of current_year.
    # Mayoral-term overlay dropped in PR D (decision #9) — the band
    # competed with the bars for attention and rarely told a useful
    # citizen-facing story.
    timeline_start = date(current_year - 4, 1, 1)
    timeline_end = date(current_year, 12, 31)
    timeline = query.badge_volume_series(
        municipality["id"],
        badge_slug,
        start_date=timeline_start,
        end_date=timeline_end,
    )
    timeline_year_ticks = query.year_ticks(timeline_start, timeline_end)

    # Batch-resolve cross-filter chip labels (S5) — single round-trip
    # for the whole list rather than one query per chip. Empty input
    # short-circuits in resolve_badges() without hitting the DB.
    cross_filter_badges = (
        query.resolve_badges(municipality["id"], cross_filters)
        if cross_filters
        else {}
    )

    # F4 cross-filter dropdown options (spec §6.8). Every enabled badge
    # for the city minus the one we're currently on — no point in
    # offering "filter by the page you're already viewing." Process
    # badges (always-on) and policy badges (city-opted-in) both surface;
    # ``list_enabled_badges`` enforces the gates so we don't filter here.
    # Pre-computed in the route (route-side pre-compute pattern set by
    # F2) — the template is a single-loop dropdown render, not a Jinja
    # call into a global function. ``enabled_badges`` reused from the
    # validation step above to avoid a second round-trip.
    available_badges = [b for b in enabled_badges if b["slug"] != badge_slug]

    # F4 review fix-up (R2): HTMX cross-filter requests get just the
    # item-list partial back. The ``<select>`` swaps the response into
    # ``#item-list`` (outerHTML), leaving the dropdown DOM (and its
    # post-change ``selected`` option) intact. Saves ~5 DB queries per
    # filter swap (no KPI strip, timeline series, mayoral overlay,
    # year ticks, dropdown re-render) and resolves S9 (post-swap
    # dropdown unsync). Non-HTMX requests fall through to the full
    # page render so deep links / bookmarks render unchanged.
    from docket.services.query import coverage_counts_for_items
    coverage_counts = coverage_counts_for_items([it.id for it in items])

    if request.headers.get("HX-Request") == "true":
        return render_template(
            "partials/_item_list.html",
            municipality=municipality,
            badge=badge,
            items=items,
            next_offset=next_offset,
            cross_filters=cross_filters,
            month_filter=month_filter,
            active_month_label=active_month_label,
            args_without_month=args_without_month,
            # Category-landing cards span many meetings — surface date +
            # item ref per card via the shared meta strip (no-op on
            # meeting-detail surfaces where show_meeting_context is unset).
            show_meeting_context=True,
            coverage_counts=coverage_counts,
        )

    return render_template(
        "category_landing.html",
        municipality=municipality,
        badge=badge,
        items=items,
        tally=tally,
        backfill_ratio=backfill_ratio,
        timeline=timeline,
        year_ticks=timeline_year_ticks,
        cross_filters=cross_filters,
        cross_filter_badges=cross_filter_badges,
        available_badges=available_badges,
        offset=offset,
        next_offset=next_offset,
        current_year=current_year,
        month_filter=month_filter,
        active_month_label=active_month_label,
        args_without_month=args_without_month,
        show_meeting_context=True,
        coverage_counts=coverage_counts,
    )


# --- F5: Public data-debt page + RSS feeds ----------------------------------
#
# Path-drift resolution: spec §6.9 example uses
# ``/al/<city>/upcoming-hearings.rss`` (hyphen). The pre-F5 stub at
# ``/al/<city>/hearings.rss`` was renamed to match the spec — the
# longer form is more discoverable and the spec is the source of truth.
#
# Data-debt admin email: ``municipalities`` has no ``admin_email`` column
# yet (decision #77 retired the in-app data_issue_reports queue in favor
# of mailto). Until the column lands the data-debt page falls back to
# ``admin@docket.pub`` — flagged for follow-up. Adding the column is a
# Migration 016 candidate (next available migration slot).
#
# Cache: existing ``_overview_cache`` idiom (``dict[str, tuple[float,
# str]]``) extended for RSS with a 60-min TTL. ``flask-caching`` is NOT
# a dependency of this project, intentionally — the dict pattern is good
# enough at our scale (4 cities × 2 feeds = 8 keys max).

_rss_cache: dict[str, tuple[float, str]] = {}
_RSS_TTL_SECONDS = 3600  # 60 min, per spec §6.9
# F5 fix-up (R1 + Override 2): Lock + double-checked locking.
# See ``_overview_lock`` above for the rationale; this is the same
# shape applied to the RSS cache. Lock is module-level (one per
# cache); cost of acquisition on the cache-hit fast path is zero
# because we check the cache *before* touching the lock.
_rss_lock = threading.Lock()
# RSS HTTP Cache-Control max-age (seconds). Matches the in-memory TTL so
# intermediate caches and feed-reader-side caches absorb load on the same
# clock. F5 fix-up S4.
_RSS_HTTP_MAX_AGE = _RSS_TTL_SECONDS
_RSS_CACHE_CONTROL = f"public, max-age={_RSS_HTTP_MAX_AGE}"


def _rss_cached(cache_key: str, render_fn) -> str:
    """60-minute dict-based RSS cache. Returns rendered XML string.

    Mirrors the ``_overview_cache`` pattern (line 58/73/138). The cache
    is bounded by the number of cities × the number of feeds (8 keys
    max in production), so no eviction policy is required.

    F5 fix-up (R1 / Override 2): thread-safe via ``_rss_lock`` +
    double-checked locking. The fast path (cache hit) does NOT acquire
    the lock — readers only block on cold misses. Once one waiter
    finishes the render, all queued waiters short-circuit on the
    re-checked cache lookup.
    """
    now = time.time()
    cached = _rss_cache.get(cache_key)
    if cached and (now - cached[0]) < _RSS_TTL_SECONDS:
        return cached[1]
    with _rss_lock:
        # Double-check after acquiring the lock — another waiter may
        # have populated the cache while we were blocked.
        cached = _rss_cache.get(cache_key)
        if cached and (time.time() - cached[0]) < _RSS_TTL_SECONDS:
            return cached[1]
        rendered = render_fn()
        _rss_cache[cache_key] = (time.time(), rendered)
        return rendered


def _data_debt_admin_email(municipality: dict) -> str:
    """Pull the city's admin email or fall back to the project mailbox.

    ``municipalities.admin_email`` isn't seeded yet — when it lands
    (decision #77 follow-up), this helper picks it up automatically.
    Until then we honor the same precedence as
    ``engagement_strip.html:77`` — fall through to
    ``current_app.config["ADMIN_EMAIL"]`` (env-var-driven, defaults to
    ``admin@docket.pub`` per :mod:`docket.config`). F5 fix-up R5.
    """
    explicit = municipality.get("admin_email")
    if explicit:
        return explicit
    return current_app.config.get("ADMIN_EMAIL", "admin@docket.pub")


@bp.route("/al/<string:city>/data-debt")
def data_debt(city):
    """Public data-debt page (spec §6.9, decision #84).

    Lists items where the source document failed to yield machine-
    readable text (``data_quality != 'ok'``) or where the v3 pipeline
    gave up (``processing_status = 'failed_permanent'``). Sorted by
    ``data_debt_priority DESC, meeting_date DESC`` so the highest-
    priority items lead and recent items rise within a tier.

    Citizen-facing — the template translates the internal enum values
    into jargon-free copy ("needs OCR", "extraction failed", etc.) and
    surfaces a mailto "Report a problem" link to the city's admin
    email (or ``admin@docket.pub`` as fallback). Decision #77 retired
    the in-app data_issue_reports queue in favor of mailto.

    Pagination: load-more pattern. Default page size 50; LIMIT 51
    sentinel detection signals next page presence.
    """
    municipality = query.get_municipality(city)
    if not municipality:
        abort(404)

    # Defensive offset parsing (matches category_landing pattern).
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)

    page_size = 50
    items_plus_one = query.list_data_debt_items(
        municipality["id"],
        limit=page_size + 1,
        offset=offset,
    )
    items = items_plus_one[:page_size]
    next_offset = (offset + page_size) if len(items_plus_one) > page_size else None

    # F5 fix-up (R3 / Override 3): precompute the citizen-friendly label
    # in the route so the template doesn't need to know about the
    # ``data_quality`` / ``processing_status`` enums. ``filters.py`` is
    # for functional transformations (URL encoding, date formatting);
    # UI copy belongs with the enum (see ``docket.models.data_quality``).
    # Both the HTML template and the RSS macro read
    # ``item['friendly_label']`` directly — single source of truth.
    for it in items:
        it["friendly_label"] = friendly_label(it)

    # Group by priority tier for the rendered list. HIGH priority is
    # ``data_debt_priority = 'high'``; everything else (normal/low/NULL)
    # falls into NORMAL.
    high_items = [i for i in items if i.get("data_debt_priority") == "high"]
    normal_items = [i for i in items if i.get("data_debt_priority") != "high"]

    return render_template(
        "data_debt.html",
        municipality=municipality,
        items=items,
        high_items=high_items,
        normal_items=normal_items,
        offset=offset,
        next_offset=next_offset,
        admin_email=_data_debt_admin_email(municipality),
    )


@bp.route("/al/<string:city>/data-debt.rss")
def data_debt_rss(city):
    """RSS 2.0 feed of data-debt items for ``city`` (spec §6.9).

    60-minute cache via ``_rss_cached`` — cheaper than rebuilding the
    feed on every poll from feed readers. F5 fix-up S4 also emits a
    matching ``Cache-Control: public, max-age=3600`` header so
    intermediate caches and feed-reader-side caches share the same
    clock.
    """
    municipality = query.get_municipality(city)
    if not municipality:
        abort(404)

    feed_url = url_for(
        "public.data_debt_rss", city=city, _external=True
    )

    def _render():
        items = query.list_data_debt_items(municipality["id"], limit=50)
        # Precompute citizen-friendly labels — same source of truth as
        # the HTML page (see ``data_debt`` route above).
        for it in items:
            it["friendly_label"] = friendly_label(it)
        return render_template(
            "rss/data_debt.xml.j2",
            items=items,
            municipality=municipality,
            feed_url=feed_url,
        )

    rendered = _rss_cached(f"data-debt:{city}", _render)
    return Response(
        rendered,
        mimetype="application/rss+xml",
        headers={"Cache-Control": _RSS_CACHE_CONTROL},
    )


@bp.route("/al/<string:city>/upcoming-hearings.rss")
def upcoming_hearings_rss(city):
    """Upcoming public hearings RSS feed (spec §6.9).

    Renamed from the pre-F5 ``/al/<city>/hearings.rss`` stub to match
    the spec example (path discoverability).

    60-minute cache via ``_rss_cached``. F5 fix-up S4 adds a matching
    ``Cache-Control`` header.
    """
    municipality = query.get_municipality(city)
    if not municipality:
        abort(404)

    feed_url = url_for(
        "public.upcoming_hearings_rss", city=city, _external=True
    )

    def _render():
        items = query.list_upcoming_hearings(municipality["id"])
        return render_template(
            "rss/upcoming_hearings.xml.j2",
            items=items,
            municipality=municipality,
            feed_url=feed_url,
        )

    rendered = _rss_cached(f"upcoming-hearings:{city}", _render)
    return Response(
        rendered,
        mimetype="application/rss+xml",
        headers={"Cache-Control": _RSS_CACHE_CONTROL},
    )


@bp.route("/items/<int:item_id>/badges")
def item_badges_overflow(item_id: int):
    """HTMX overflow listing for an item's badges — stub.

    Surfaced in :file:`partials/_badge_row.html` as the ``hx-get`` target
    for the "+N more" button when an item has more than 3 badges.
    Today no items have badges populated yet (Phase 3 hasn't run); when
    badges first appear, this route will start receiving HTMX requests.

    Returns 501 Not Implemented (rather than 404) so monitoring can tell
    "user clicked overflow before the listing is built" apart from "user
    typo'd a URL". Same convention as ``admin.data_debt`` (E5),
    ``public.item_detail`` (E3), and ``public.upcoming_hearings_rss`` (E3).

    TODO(F-track): build the real overflow-badges endpoint that returns
    an HTML fragment listing the remaining ``item.badges[3:]`` chips with
    the same BadgeChip shape as the inline top-3.
    """
    return (
        "Badge overflow listing is a planned feature — implementation pending.",
        501,
    )


@bp.route("/al/<slug>/council/")
def city_council(slug):
    """Council member cards for a city."""
    municipality = query.get_municipality(slug)
    if not municipality:
        abort(404)

    members = query.list_council_members(slug)

    return render_template(
        "council.html",
        municipality=municipality,
        members=members,
    )


@bp.route("/search")
def search():
    """Search results page — scoped to city or cross-city."""
    q = request.args.get("q", "").strip()
    city = request.args.get("city")
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 20
    offset = (page - 1) * per_page

    results = []
    if q:
        results = query.search_agenda_items(
            q,
            municipality_slug=city,
            limit=per_page,
            offset=offset,
        )

    municipalities = query.list_municipalities()

    from docket.services.query import coverage_counts_for_items
    result_ids = [it['id'] if isinstance(it, dict) else it.id for it in results]
    coverage_counts = coverage_counts_for_items(result_ids)

    return render_template(
        "search.html",
        query=q,
        results=results,
        city=city,
        municipalities=municipalities,
        page=page,
        coverage_counts=coverage_counts,
    )


@bp.route("/topics/")
def topics_index():
    """Browse by topic — all topics with counts."""
    city = request.args.get("city")
    topics = query.topic_counts(municipality_slug=city)
    all_topic_defs = all_topics()
    municipalities = query.list_municipalities()

    return render_template(
        "topics.html",
        topics=topics,
        all_topics=all_topic_defs,
        city=city,
        municipalities=municipalities,
    )


@bp.route("/about/")
def about():
    """About docket.pub — project overview."""
    return render_template("about.html")


@bp.route("/about/how-we-read-minutes/")
def about_methodology():
    """How docket.pub reads agendas, minutes, and votes."""
    return render_template("about_methodology.html")


@bp.route("/about/corrections/")
def about_corrections():
    """Corrections policy."""
    return render_template("about_corrections.html")


@bp.route("/councilors/")
def councilors_index():
    """City picker for finding your councilor."""
    municipalities = query.list_municipalities()
    return render_template("councilors.html", municipalities=municipalities)


@bp.route("/topics/<topic>/")
def topic_detail(topic):
    """Agenda items for a specific topic."""
    city = request.args.get("city")
    display_name = get_topic_display_name(topic)
    if not display_name:
        abort(404)

    page = max(1, request.args.get("page", 1, type=int))
    per_page = 20
    offset = (page - 1) * per_page

    items = query.list_agenda_items_by_topic(
        topic,
        municipality_slug=city,
        limit=per_page,
        offset=offset,
    )

    from docket.services.query import coverage_counts_for_items
    topic_item_ids = [it['id'] if isinstance(it, dict) else it.id for it in items]
    coverage_counts = coverage_counts_for_items(topic_item_ids)

    return render_template(
        "topic_detail.html",
        topic=topic,
        topic_name=display_name,
        items=items,
        city=city,
        page=page,
        coverage_counts=coverage_counts,
    )


# --- HTMX rail partials (return HTML fragments, no base template) -----------


@bp.route("/al/<slug>/_rail/default")
def rail_default(slug):
    """Source rail default state."""
    municipality = query.get_municipality(slug)
    if not municipality:
        abort(404)
    result = query.list_meetings(slug, limit=1)
    return render_template(
        "partials/rail_default.html",
        municipality=municipality,
        meeting_count=result.total,
    )


@bp.route("/al/<slug>/_rail/meeting/<int:meeting_id>")
def rail_meeting(slug, meeting_id):
    """Source rail for a selected meeting."""
    municipality = query.get_municipality(slug)
    meeting = query.get_meeting(meeting_id)
    if not municipality or not meeting:
        abort(404)
    items = query.list_agenda_items(meeting_id)
    votes = query.list_votes(meeting_id)
    return render_template(
        "partials/rail_meeting.html",
        municipality=municipality,
        meeting=meeting,
        item_count=len(items),
        votes=votes,
    )


@bp.route("/al/<slug>/_rail/member/<int:member_id>")
def rail_member(slug, member_id):
    """Source rail for a selected council member."""
    member = query.get_council_member(member_id)
    if not member:
        abort(404)
    vote_summary = query.get_member_vote_summary(member_id)
    return render_template(
        "partials/rail_member.html",
        member=member,
        vote_summary=vote_summary,
    )
