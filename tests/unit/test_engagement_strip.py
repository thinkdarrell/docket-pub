"""Snapshot tests for the engagement strip partial.

Covers ``partials/engagement_strip.html`` — the 4-state branch defined
in spec §6.3 (decision #70). Each test builds an `item` + `city`
dict that lands on exactly one branch and asserts the rendered HTML
carries the matching CSS class (or, for the auto-hide branch, no
strip markup at all).

The partial calls ``url_for('public.upcoming_hearings_rss', ...)`` and
``url_for('public.item_detail', ...)`` for the awaiting-hearing-date
state. We register stub endpoints under those names on the test Flask
app so ``url_for`` resolves without standing up the real public
blueprint (DB-free, network-free).

Pure UI: no Anthropic, no DB, no integration setup.
"""

from __future__ import annotations

from datetime import date

import pytest
from flask import Blueprint, Flask, render_template


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    """Minimal Flask app pointed at the docket templates + filters.

    Registers:
      - ``format_date`` Jinja filter (real implementation from
        ``docket.web.filters``).
      - A stub ``public`` blueprint with two endpoints
        (``upcoming_hearings_rss`` and ``item_detail``) so
        ``url_for(...)`` calls in the partial don't BuildError.
      - ``ADMIN_EMAIL`` on app.config (mirrors what the production
        ``create_app()`` does — the partial reads ``config.ADMIN_EMAIL``
        from Jinja, which resolves to ``app.config['ADMIN_EMAIL']``).
    """
    flask_app = Flask(
        "test_engagement_strip",
        template_folder="src/docket/web/templates",
    )

    flask_app.config["ADMIN_EMAIL"] = "ops@docket.test"
    # SERVER_NAME lets `_external=True` url_for work without a request ctx.
    flask_app.config["SERVER_NAME"] = "docket.test"
    flask_app.config["PREFERRED_URL_SCHEME"] = "https"

    # Wire the real format_date filter (production parity).
    from docket.web.filters import register as register_filters

    register_filters(flask_app)

    # Stub public blueprint with the two endpoints the partial uses.
    public_bp = Blueprint("public", __name__)

    @public_bp.route("/<city>/upcoming-hearings.rss")
    def upcoming_hearings_rss(city):  # pragma: no cover - never invoked
        return ""

    @public_bp.route("/<city>/items/<int:item_id>")
    def item_detail(city, item_id):  # pragma: no cover - never invoked
        return ""

    flask_app.register_blueprint(public_bp)

    return flask_app


def _render(app, item, city):
    """Render the partial with ``item`` and ``city`` in scope."""
    with app.app_context():
        return render_template(
            "partials/engagement_strip.html", item=item, city=city
        )


# ---------------------------------------------------------------------------
# Per-state tests
# ---------------------------------------------------------------------------


class TestEngagementStripStates:
    def test_state_1_next_steps_populated(self, app):
        """All four next_steps fields plus master-calendar tail link."""
        item = {
            "id": 42,
            "next_steps": {
                "public_hearing_date": date(2026, 5, 15),
                "public_hearing_time": "6:00 PM",
                "committee_referral": "Planning Committee",
                "comment_period_end": date(2026, 5, 10),
                "implementation_date": date(2026, 6, 1),
            },
            "extracted_facts": None,
        }
        city = {
            "slug": "birmingham",
            "name": "Birmingham",
            "master_calendar_url": "https://www.birminghamal.gov/calendar",
        }
        html = _render(app, item, city)

        # Base class only — no awaiting / fallback modifier.
        assert 'class="engagement-strip"' in html
        assert "engagement-strip--awaiting" not in html
        assert "engagement-strip--fallback" not in html

        # Populated fields all render.
        assert "May 15, 2026" in html
        assert "6:00 PM" in html
        assert "Planning Committee" in html
        assert "May 10, 2026" in html
        assert "June 1, 2026" in html

        # Master calendar tail link.
        assert "https://www.birminghamal.gov/calendar" in html
        assert "City master calendar" in html

    def test_state_2_awaiting_hearing(self, app):
        """action_type=public_hearing_set + no public_hearing_date → awaiting state."""
        item = {
            "id": 99,
            "next_steps": None,
            "extracted_facts": {"action_type": "public_hearing_set"},
        }
        city = {
            "slug": "mobile",
            "name": "Mobile",
            "master_calendar_url": None,
        }
        html = _render(app, item, city)

        assert "engagement-strip--awaiting" in html
        assert "Awaiting hearing date" in html

        # RSS link goes through the stub endpoint.
        assert "/mobile/upcoming-hearings.rss" in html
        assert "Subscribe to upcoming hearings RSS" in html

        # mailto: link with ADMIN_EMAIL + item id in the subject.
        # Subject and body are RFC 6068 compliant (urlencoded) so spaces
        # become %20, colons become %3A, etc.
        assert "mailto:ops@docket.test" in html
        assert "subject=Missing%20hearing%20date%20for%20item%2099" in html
        assert "Report missing date" in html

        # _external=True item_detail URL appears (urlencoded) in the body.
        # CRLF separators become %0D%0A%0D%0A through Jinja's urlencode.
        assert "body=Item%20URL%3A%20https%3A//docket.test/mobile/items/99" in html
        assert "%0D%0A%0D%0A" in html

    def test_state_3_master_calendar_fallback(self, app):
        """No next_steps + no awaiting context → just calendar fallback."""
        item = {
            "id": 7,
            "next_steps": None,
            "extracted_facts": None,
        }
        city = {
            "slug": "homewood",
            "name": "Homewood",
            "master_calendar_url": "https://homewoodal.org/calendar",
        }
        html = _render(app, item, city)

        assert "engagement-strip--fallback" in html
        assert "https://homewoodal.org/calendar" in html
        assert "Check Homewood's master calendar" in html
        # Awaiting copy must NOT leak in.
        assert "Awaiting hearing date" not in html

    def test_state_4_auto_hides(self, app):
        """No next_steps, no awaiting context, no calendar URL → empty render."""
        item = {
            "id": 1,
            "next_steps": None,
            "extracted_facts": None,
        }
        city = {
            "slug": "vestavia",
            "name": "Vestavia Hills",
            "master_calendar_url": None,
        }
        html = _render(app, item, city)

        # Strip MUST NOT render.
        assert "engagement-strip" not in html
        # Stripped of whitespace, body is empty (no placeholder text).
        assert html.strip() == ""


# ---------------------------------------------------------------------------
# Defensive / edge cases
# ---------------------------------------------------------------------------


class TestEngagementStripEdges:
    def test_partial_next_steps_renders_only_populated_fields(self, app):
        """Only ``committee_referral`` set — no calendar / comment / impl markers leak."""
        item = {
            "id": 5,
            "next_steps": {
                "committee_referral": "Public Safety Committee",
                # All other fields absent.
            },
            "extracted_facts": None,
        }
        city = {
            "slug": "birmingham",
            "name": "Birmingham",
            "master_calendar_url": None,  # no tail link either
        }
        html = _render(app, item, city)

        assert 'class="engagement-strip"' in html
        assert "engagement-strip--awaiting" not in html
        assert "engagement-strip--fallback" not in html

        assert "Public Safety Committee" in html

        # None of the date markers should appear.
        assert "Public hearing" not in html
        assert "Comment by" not in html
        assert "Effective" not in html
        # No master-calendar tail link.
        assert "City master calendar" not in html

    def test_state_1_with_iso_string_dates(self, app):
        """JSONB next_steps round-trip through psycopg as ISO strings sometimes
        — ``format_date`` should parse them rather than crash."""
        item = {
            "id": 21,
            "next_steps": {
                "public_hearing_date": "2026-07-04",
                "comment_period_end": "2026-06-30",
            },
            "extracted_facts": None,
        }
        city = {
            "slug": "birmingham",
            "name": "Birmingham",
            "master_calendar_url": None,
        }
        html = _render(app, item, city)
        assert 'class="engagement-strip"' in html
        assert "July 4, 2026" in html
        assert "June 30, 2026" in html

    def test_state_2_does_not_trigger_when_hearing_date_present(self, app):
        """If action_type=public_hearing_set BUT public_hearing_date is set,
        we land on state 1 (the populated state), not the awaiting state."""
        item = {
            "id": 33,
            "next_steps": {"public_hearing_date": date(2026, 8, 1)},
            "extracted_facts": {"action_type": "public_hearing_set"},
        }
        city = {
            "slug": "mobile",
            "name": "Mobile",
            "master_calendar_url": None,
        }
        html = _render(app, item, city)

        assert 'class="engagement-strip"' in html
        assert "engagement-strip--awaiting" not in html
        assert "Awaiting hearing date" not in html
        assert "August 1, 2026" in html

    def test_awaiting_state_handles_missing_extracted_facts(self, app):
        """``extracted_facts`` keyed but None — ``or {}`` guard prevents crash;
        the awaiting branch should not trigger."""
        item = {
            "id": 4,
            "next_steps": None,
            "extracted_facts": None,
        }
        city = {
            "slug": "vestavia",
            "name": "Vestavia Hills",
            "master_calendar_url": "https://example.com/cal",
        }
        # No crash — falls through to fallback branch (state 3).
        html = _render(app, item, city)
        assert "engagement-strip--fallback" in html

    def test_state_1_emoji_and_bullet_fidelity(self, app):
        """Spec §6.3 fidelity check: state 1 must surface the four emoji
        markers (📅 hearing, 🏛️ committee, 📝 comment, ▶️ impl) in order
        and use ``•`` bullet separators between fields. Locks the visual
        contract that the spec-compliance review flagged as a test gap."""
        item = {
            "id": 11,
            "next_steps": {
                "public_hearing_date": date(2026, 5, 15),
                "committee_referral": "Planning Committee",
                "comment_period_end": date(2026, 5, 10),
                "implementation_date": date(2026, 6, 1),
            },
            "extracted_facts": None,
        }
        city = {
            "slug": "birmingham",
            "name": "Birmingham",
            "master_calendar_url": None,
        }
        html = _render(app, item, city)

        # All four emoji markers present.
        assert "📅" in html
        assert "🏛️" in html
        assert "📝" in html
        assert "▶️" in html

        # Order in source matches spec: hearing → committee → comment → impl.
        idx_cal = html.index("📅")
        idx_committee = html.index("🏛️")
        idx_comment = html.index("📝")
        idx_impl = html.index("▶️")
        assert idx_cal < idx_committee < idx_comment < idx_impl

        # Bullet separators appear between fields (3 bullets for 4 fields).
        assert html.count("•") >= 3

    def test_empty_next_steps_dict_falls_through(self, app):
        """``next_steps={}`` should be treated identically to ``None`` —
        ``has_any`` is falsy on every empty key, so without action_type
        context or a calendar URL we land on state 4 (no markup)."""
        item = {"id": 1, "next_steps": {}, "extracted_facts": None}
        city = {"slug": "x", "name": "X", "master_calendar_url": None}
        html = _render(app, item, city)
        assert "engagement-strip" not in html

    def test_action_type_public_hearing_set_with_only_committee_referral_lands_state_1(
        self, app
    ):
        """If facts.action_type=public_hearing_set AND committee_referral
        is set but public_hearing_date is null, state 1 still wins
        (``has_any`` covers any of the four next_steps fields)."""
        item = {
            "id": 1,
            "next_steps": {"committee_referral": "Planning Committee"},
            "extracted_facts": {"action_type": "public_hearing_set"},
        }
        city = {
            "slug": "bham",
            "name": "Birmingham",
            "master_calendar_url": None,
        }
        html = _render(app, item, city)
        assert 'class="engagement-strip"' in html
        assert "engagement-strip--awaiting" not in html
        assert "Planning Committee" in html

    def test_external_links_open_in_new_tab_with_full_rel(self, app):
        """All external links (state 1 calendar tail, state 2 RSS,
        state 3 calendar) carry ``target="_blank"`` plus
        ``rel="noopener noreferrer"`` — production parity with
        meeting_detail.html, _source_link_stub.html, footer.html. The
        mailto: link must NOT carry target/rel."""
        # State 1: master-calendar tail link.
        item = {
            "id": 1,
            "next_steps": {"committee_referral": "Planning"},
            "extracted_facts": None,
        }
        city = {
            "slug": "bham",
            "name": "Birmingham",
            "master_calendar_url": "https://birminghamal.gov/calendar",
        }
        html = _render(app, item, city)
        assert 'target="_blank"' in html
        assert 'rel="noopener noreferrer"' in html

        # State 2: RSS link.
        item2 = {
            "id": 99,
            "next_steps": None,
            "extracted_facts": {"action_type": "public_hearing_set"},
        }
        city2 = {"slug": "mobile", "name": "Mobile", "master_calendar_url": None}
        html2 = _render(app, item2, city2)
        assert 'target="_blank"' in html2
        assert 'rel="noopener noreferrer"' in html2
        # The mailto: link must NOT have target or rel.
        # Find the mailto: anchor and verify its tag has neither attr.
        mailto_idx = html2.index("mailto:")
        # Walk back to opening "<a" of that anchor.
        anchor_open = html2.rfind("<a ", 0, mailto_idx)
        anchor_close = html2.index(">", mailto_idx)
        mailto_tag = html2[anchor_open : anchor_close + 1]
        assert "target=" not in mailto_tag
        assert "rel=" not in mailto_tag

        # State 3: fallback calendar link.
        item3 = {"id": 1, "next_steps": None, "extracted_facts": None}
        city3 = {
            "slug": "homewood",
            "name": "Homewood",
            "master_calendar_url": "https://homewoodal.org/cal",
        }
        html3 = _render(app, item3, city3)
        assert 'target="_blank"' in html3
        assert 'rel="noopener noreferrer"' in html3


# ---------------------------------------------------------------------------
# format_date direct unit tests (decision #70 docstring contract)
# ---------------------------------------------------------------------------


class TestFormatDateFilter:
    """Direct unit tests for ``docket.web.filters.format_date`` covering
    the defensive contract documented in its docstring: ``None`` → ``""``,
    malformed strings fall through unchanged, ISO date-only strings are
    parsed correctly on Python 3.10+ (where ``datetime.fromisoformat``
    rejects bare ``YYYY-MM-DD``)."""

    def test_none_returns_empty_string(self):
        from docket.web.filters import format_date

        assert format_date(None) == ""

    def test_malformed_string_falls_through_unchanged(self):
        from docket.web.filters import format_date

        assert format_date("not-a-date") == "not-a-date"

    def test_iso_date_only_string_parses_on_python_3_10(self):
        """``datetime.fromisoformat('2026-07-04')`` raises ValueError on
        Python 3.10. Verify the date-first parse order recovers."""
        from docket.web.filters import format_date

        assert format_date("2026-07-04") == "July 4, 2026"

    def test_iso_datetime_string_still_parses(self):
        from docket.web.filters import format_date

        assert format_date("2026-07-04T13:45:00") == "July 4, 2026"

    def test_date_object_formats_directly(self):
        from docket.web.filters import format_date

        assert format_date(date(2026, 5, 15)) == "May 15, 2026"


# ---------------------------------------------------------------------------
# Card partial → engagement strip alias regression
# ---------------------------------------------------------------------------


class TestCardPartialCityAlias:
    """The route handler passes ``municipality`` to the parent template.
    The card partials (``card_smart_brevity.html`` /
    ``card_verification_pending.html``) shim ``city = municipality`` so
    that ``engagement_strip.html``'s spec-canonical ``city.X`` references
    resolve. Without the shim:

    - States 1 + 3 silently degrade (the ``{% if city ... %}`` guards
      hide the calendar tail link).
    - State 2 raises ``UndefinedError`` / ``BuildError`` because
      ``city.slug`` is undefined.

    These regression tests pin the alias so a future refactor that drops
    the ``{% set city = municipality %}`` line is caught.
    """

    @pytest.fixture(scope="class")
    def card_app(self):
        """Flask app wired with the dispatcher's filter dependencies plus
        the same stub blueprint as the strip-level fixture (engagement
        strip references ``public.upcoming_hearings_rss`` /
        ``public.item_detail`` via ``url_for``)."""
        flask_app = Flask(
            "test_card_partial_city_alias",
            template_folder="src/docket/web/templates",
        )

        flask_app.config["ADMIN_EMAIL"] = "ops@docket.test"
        flask_app.config["SERVER_NAME"] = "docket.test"
        flask_app.config["PREFERRED_URL_SCHEME"] = "https"

        from docket.enrichment.dollars import classify_dollar_tier
        from docket.web.filters import register as register_filters

        register_filters(flask_app)

        @flask_app.template_filter("dollar_tier")
        def _dollar_tier(amount):
            if amount is None:
                return ""
            return classify_dollar_tier(amount)

        @flask_app.template_filter("topic_name")
        def _topic_name(slug):
            return slug or ""

        public_bp = Blueprint("public", __name__)

        @public_bp.route("/<city>/upcoming-hearings.rss")
        def upcoming_hearings_rss(city):  # pragma: no cover
            return ""

        @public_bp.route("/<city>/items/<int:item_id>")
        def item_detail(city, item_id):  # pragma: no cover
            return ""

        flask_app.register_blueprint(public_bp)
        return flask_app

    def test_card_smart_brevity_with_municipality_only_resolves_city(self, card_app):
        """Render ``card_smart_brevity.html`` with ``municipality`` only
        (no ``city`` in scope, mirroring the route handler) and verify
        the engagement-strip's calendar tail link appears — proving the
        ``{% set city = municipality %}`` shim works end-to-end."""
        item = {
            "id": 1,
            "title": "Test item",
            "processing_status": "completed",
            "ai_rewrite_version": 3,
            "headline": "Test headline",
            "why_it_matters": "Test impact statement.",
            "next_steps": {"committee_referral": "Planning Committee"},
            "extracted_facts": {},
            "badges": [],
            "source_anchor": {"url": "https://example.com/agenda.pdf"},
        }
        municipality = {
            "slug": "bham",
            "name": "Birmingham",
            "master_calendar_url": "https://birminghamal.gov/calendar",
        }
        with card_app.app_context(), card_app.test_request_context():
            html = render_template(
                "partials/card_smart_brevity.html",
                item=item,
                municipality=municipality,
            )
        # Engagement-strip's state-1 fields render.
        assert "Planning Committee" in html
        # Master calendar tail link survives the alias shim — this is the
        # specific assertion that catches "someone removed `set city = municipality`".
        assert "https://birminghamal.gov/calendar" in html
        assert "City master calendar" in html

    def test_card_verification_pending_with_municipality_only_resolves_city(
        self, card_app
    ):
        """Same alias regression for the verification_pending variant."""
        item = {
            "id": 2,
            "title": "Test item",
            "processing_status": "cross_stage_conflict",
            "ai_rewrite_version": 3,
            "headline": "Test headline",
            "why_it_matters": "Test impact statement.",
            "next_steps": {"committee_referral": "Public Safety Committee"},
            "extracted_facts": {},
            "badges": [],
            "source_anchor": {"url": "https://example.com/agenda.pdf"},
        }
        municipality = {
            "slug": "mobile",
            "name": "Mobile",
            "master_calendar_url": "https://mobile.example.com/cal",
        }
        with card_app.app_context(), card_app.test_request_context():
            html = render_template(
                "partials/card_verification_pending.html",
                item=item,
                municipality=municipality,
            )
        assert "Public Safety Committee" in html
        assert "https://mobile.example.com/cal" in html
        assert "City master calendar" in html

    def test_engagement_strip_without_city_silently_degrades(self, card_app):
        """If ``engagement_strip.html`` is rendered with no ``city`` in
        scope (i.e. the alias shim is absent), state-1 still renders the
        populated next_steps fields but the calendar tail link disappears.
        This proves why the shim is needed — the partial-level guards are
        defensive but they hide real data."""
        item = {
            "id": 1,
            "next_steps": {"committee_referral": "Planning Committee"},
            "extracted_facts": None,
        }
        with card_app.app_context():
            # Note: no ``city`` kwarg — emulates parent template that only
            # has ``municipality``.
            html = render_template(
                "partials/engagement_strip.html", item=item
            )
        assert "Planning Committee" in html
        # No calendar tail link — proves the silent degradation that the
        # shim prevents.
        assert "City master calendar" not in html


# ---------------------------------------------------------------------------
# Production blueprint stub-route registration
# ---------------------------------------------------------------------------


class TestPublicBlueprintStubRoutes:
    """``engagement_strip.html`` state 2 calls
    ``url_for('public.item_detail', ...)`` and
    ``url_for('public.upcoming_hearings_rss', city=...)``. The production
    blueprint must register both endpoints (even as 404 stubs) so
    ``url_for`` doesn't raise ``BuildError`` at render time. These tests
    pin the registration."""

    def test_item_detail_url_resolves(self):
        from docket.web import create_app

        app = create_app()
        with app.test_request_context():
            from flask import url_for

            url = url_for("public.item_detail", slug="bham", item_id=1)
            assert "/al/bham/items/1" in url

    def test_upcoming_hearings_rss_url_resolves(self):
        from docket.web import create_app

        app = create_app()
        with app.test_request_context():
            from flask import url_for

            url = url_for("public.upcoming_hearings_rss", city="bham")
            assert "/al/bham/hearings.rss" in url
