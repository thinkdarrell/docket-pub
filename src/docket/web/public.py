"""Public-facing routes — citizen UI.

Thin routes that call into docket.services.query and render templates.
Business logic stays in services, not here.
"""

from __future__ import annotations

from datetime import date

from flask import Blueprint, abort, render_template, request

from docket.enrichment.topics import all_topics, get_topic_display_name
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


@bp.route("/al/<slug>/")
def city_overview(slug):
    """City landing page — full overview with all sections."""
    municipality = query.get_municipality(slug)
    if not municipality:
        abort(404)

    from datetime import datetime
    import time

    now_ts = time.time()
    cached = _overview_cache.get(slug)
    if cached and (now_ts - cached[0]) < _CACHE_TTL:
        return cached[1]

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
        now=datetime.now(),
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
    )


@bp.route("/al/<slug>/items/<int:item_id>/")
def item_detail(slug, item_id):
    """Per-item detail page — stub for E5."""
    # TODO(E5): wire up item-detail page
    abort(404)


@bp.route("/al/<slug>/<badge_slug>/")
def category_landing(slug: str, badge_slug: str):
    """Category landing page for a priority badge in a city.

    Renders spec §6.5: header (badge icon + name + city), KPI strip,
    volume timeline (F3 lands the real partial; F2 ships an empty stub),
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
    cross_filters = [s.strip() for s in raw.split(",") if s.strip()]

    # Defensive offset parsing: bad input becomes 0 (never crashes the
    # route); negative input clamped to 0 (a -5 offset would otherwise
    # confuse the SQL planner / leak past data).
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)

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
    )
    items = items_plus_one[:25]
    next_offset = (offset + 25) if len(items_plus_one) > 25 else None

    current_year = date.today().year
    kpis = query.category_kpis(
        municipality["id"],
        badge_slug,
        year=current_year,
        cross_filter_slugs=cross_filters,
    )

    # Volume timeline window: 5-year rolling, inclusive of current_year
    # (decision #95). Same `date.today().year` anchor the KPI strip uses
    # so the two surfaces stay aligned without separate config.
    timeline_start = date(current_year - 4, 1, 1)
    timeline_end = date(current_year, 12, 31)
    timeline = query.badge_volume_series(
        municipality["id"],
        badge_slug,
        start_date=timeline_start,
        end_date=timeline_end,
    )
    mayoral_terms = query.mayoral_term_overlay(
        municipality["id"],
        timeline_start,
        timeline_end,
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

    return render_template(
        "category_landing.html",
        municipality=municipality,
        badge=badge,
        items=items,
        kpis=kpis,
        timeline=timeline,
        mayoral_terms=mayoral_terms,
        year_ticks=timeline_year_ticks,
        cross_filters=cross_filters,
        cross_filter_badges=cross_filter_badges,
        offset=offset,
        next_offset=next_offset,
        current_year=current_year,
    )


@bp.route("/al/<string:city>/hearings.rss")
def upcoming_hearings_rss(city):
    """Upcoming public hearings RSS feed — stub for F5."""
    # TODO(F5): build upcoming hearings RSS feed
    abort(404)


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

    return render_template(
        "search.html",
        query=q,
        results=results,
        city=city,
        municipalities=municipalities,
        page=page,
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

    return render_template(
        "topic_detail.html",
        topic=topic,
        topic_name=display_name,
        items=items,
        city=city,
        page=page,
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
