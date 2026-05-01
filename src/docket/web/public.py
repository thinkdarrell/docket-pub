"""Public-facing routes — citizen UI.

Thin routes that call into docket.services.query and render templates.
Business logic stays in services, not here.
"""

from __future__ import annotations

from flask import Blueprint, abort, render_template, request

from docket.enrichment.dollars import classify_dollar_tier
from docket.enrichment.topics import all_topics, get_topic_display_name
from docket.services import query

bp = Blueprint("public", __name__)


# --- Template context helpers -----------------------------------------------


@bp.app_template_filter("dollar_tier")
def dollar_tier_filter(amount):
    """Jinja2 filter: {{ item.dollars_amount | dollar_tier }}"""
    if amount is None:
        return ""
    return classify_dollar_tier(amount)


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


@bp.route("/al/<slug>/")
def city_overview(slug):
    """City landing page — full overview with all sections."""
    municipality = query.get_municipality(slug)
    if not municipality:
        abort(404)

    from datetime import datetime

    result = query.list_meetings(slug, limit=6)
    topics = query.topic_counts(municipality_slug=slug)
    members = query.list_council_members(slug)
    recent = query.list_recent_meetings(days=7, limit=4)
    upcoming = query.list_upcoming_meetings(days=14, limit=4)
    notable = query.list_high_dollar_items(municipality_slug=slug, limit=6)
    stats = query.dashboard_stats()

    # Filter timeline to this city
    recent_city = [m for m in recent if m.get("municipality_slug") == slug]
    upcoming_city = [m for m in upcoming if m.get("municipality_slug") == slug]

    return render_template(
        "city.html",
        municipality=municipality,
        meetings=result.meetings,
        meeting_count=result.total,
        topics=topics,
        members=members,
        recent_meetings=recent_city,
        upcoming_meetings=upcoming_city,
        notable_items=notable,
        stats=stats,
        now=datetime.now(),
    )


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
    if not meeting:
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
