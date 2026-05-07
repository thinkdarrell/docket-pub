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
        assert "mailto:ops@docket.test" in html
        assert "Missing hearing date for item 99" in html
        assert "Report missing date" in html

        # _external=True item_detail URL appears in the body.
        assert "https://docket.test/mobile/items/99" in html

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
