"""Snapshot tests for the source-anchor adaptive button partial.

Covers ``partials/source_anchor_button.html`` — the adaptive button
defined in spec §6.4. Each test builds an ``item`` dict with a
``source_anchor`` shape that matches one branch of the priority order
and asserts the rendered HTML carries the expected URL, scheme guard,
and target/rel hardening.

Also pins the contract for the ``format_timestamp`` Jinja filter
introduced alongside the partial (used by the video-deep-link branch),
and the ``admin.data_debt`` route stub that the OCR-needed branch's
admin link points to (without the stub, ``url_for`` would raise
``BuildError`` at render time — same lesson as E3 deferred routes).

Pure UI: no Anthropic, no DB, no integration setup.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from flask import Blueprint, Flask, render_template


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    """Minimal Flask app pointed at the docket templates + filters.

    Registers:
      - All real Jinja filters via ``docket.web.filters.register`` so
        ``format_timestamp`` (and ``order_badges`` / ``format_date``)
        work in production parity.
      - A stub ``admin`` blueprint exposing ``admin.data_debt`` so
        ``url_for(...)`` in the OCR-needed branch resolves without
        standing up the real admin blueprint (which requires a session
        / DB). The actual production stub is in :mod:`docket.web.admin`
        and 404s — these tests don't hit the route, only ``url_for``.
      - A SECRET_KEY so we can flip the session.
    """
    flask_app = Flask(
        "test_source_anchor",
        template_folder="src/docket/web/templates",
    )
    flask_app.config["SECRET_KEY"] = "test-only-not-a-real-secret"

    from docket.web.filters import register as register_filters

    register_filters(flask_app)

    admin_bp = Blueprint("admin", __name__)

    @admin_bp.route("/admin/data-debt/")
    def data_debt():  # pragma: no cover - never invoked
        return ""

    flask_app.register_blueprint(admin_bp)
    return flask_app


def _render(app, item, *, admin: bool = False):
    """Render the partial with ``item`` in scope, optionally admin-logged-in."""
    with app.test_request_context():
        if admin:
            from flask import session

            session["admin_user"] = "tester"
        return render_template(
            "partials/source_anchor_button.html", item=item
        )


# ---------------------------------------------------------------------------
# PDF branches
# ---------------------------------------------------------------------------


class TestPdfBranches:
    def test_pdf_with_bbox_and_page_renders_region_label(self, app):
        item = {
            "id": 1,
            "source_anchor": {
                "type": "pdf",
                "url": "https://example.com/agenda.pdf",
                "page": 7,
                "bbox": [10, 20, 100, 120],
            },
        }
        html = _render(app, item)
        assert 'href="https://example.com/agenda.pdf#page=7"' in html
        assert "PDF page 7 (region)" in html
        assert 'class="view-source"' in html
        assert 'target="_blank"' in html
        assert 'rel="noopener noreferrer"' in html

    def test_pdf_with_page_no_bbox_renders_page_label(self, app):
        item = {
            "id": 1,
            "source_anchor": {
                "type": "pdf",
                "url": "https://example.com/agenda.pdf",
                "page": 12,
            },
        }
        html = _render(app, item)
        assert 'href="https://example.com/agenda.pdf#page=12"' in html
        assert "PDF page 12" in html
        assert "(region)" not in html

    def test_pdf_bare_no_page_renders_doc_label(self, app):
        item = {
            "id": 1,
            "source_anchor": {
                "type": "pdf",
                "url": "https://example.com/agenda.pdf",
            },
        }
        html = _render(app, item)
        assert 'href="https://example.com/agenda.pdf"' in html
        assert "View Source: PDF" in html
        # No page anchor.
        assert "#page=" not in html
        # Not the bbox-region wording.
        assert "(region)" not in html

    def test_pdf_with_bbox_but_no_page_falls_through_to_bare_pdf(self, app):
        """If ``bbox`` is set but ``page`` isn't, neither bbox-page nor
        page-only branch fires — the bare PDF branch handles it. Defensive:
        a bbox without a page can't render a usable ``#page=`` fragment."""
        item = {
            "id": 1,
            "source_anchor": {
                "type": "pdf",
                "url": "https://example.com/agenda.pdf",
                "bbox": [10, 20, 100, 120],
            },
        }
        html = _render(app, item)
        assert 'href="https://example.com/agenda.pdf"' in html
        assert "View Source: PDF" in html
        assert "(region)" not in html
        assert "#page=" not in html


# ---------------------------------------------------------------------------
# HTML branches
# ---------------------------------------------------------------------------


class TestHtmlBranches:
    def test_html_with_anchor_renders_concatenated_href(self, app):
        item = {
            "id": 1,
            "source_anchor": {
                "type": "html",
                "url": "https://example.com/agenda",
                "anchor": "#item-42",
            },
        }
        html = _render(app, item)
        assert 'href="https://example.com/agenda#item-42"' in html
        assert "View Source: agenda item" in html
        assert 'target="_blank"' in html
        assert 'rel="noopener noreferrer"' in html

    def test_html_without_anchor_falls_through_to_bare_url(self, app):
        """``type=html`` with no ``anchor`` field — bare URL branch wins."""
        item = {
            "id": 1,
            "source_anchor": {
                "type": "html",
                "url": "https://example.com/agenda",
            },
        }
        html = _render(app, item)
        assert 'href="https://example.com/agenda"' in html
        assert "View Source →" in html
        # Not the html-anchor-specific copy.
        assert "View Source: agenda item" not in html


# ---------------------------------------------------------------------------
# Video branches
# ---------------------------------------------------------------------------


class TestVideoBranches:
    def test_video_with_timestamp_seconds_renders_t_query(self, app):
        item = {
            "id": 1,
            "source_anchor": {
                "type": "video",
                "url": "https://video.example.com/meeting/123",
                "timestamp_seconds": 3725,  # 1:02:05
            },
        }
        html = _render(app, item)
        assert (
            'href="https://video.example.com/meeting/123?t=3725"' in html
        )
        # format_timestamp output appears in the label.
        assert "video at 1:02:05" in html
        assert 'target="_blank"' in html
        assert 'rel="noopener noreferrer"' in html

    def test_video_without_timestamp_falls_through_to_bare_url(self, app):
        item = {
            "id": 1,
            "source_anchor": {
                "type": "video",
                "url": "https://video.example.com/meeting/123",
            },
        }
        html = _render(app, item)
        assert 'href="https://video.example.com/meeting/123"' in html
        assert "View Source →" in html
        # Not the video-specific copy.
        assert "video at" not in html
        assert "?t=" not in html

    def test_video_with_short_timestamp_uses_minute_seconds_format(self, app):
        item = {
            "id": 1,
            "source_anchor": {
                "type": "video",
                "url": "https://video.example.com/meeting/x",
                "timestamp_seconds": 65,
            },
        }
        html = _render(app, item)
        assert 'href="https://video.example.com/meeting/x?t=65"' in html
        # 65 seconds → 1:05 (no hour component).
        assert "video at 1:05" in html


# ---------------------------------------------------------------------------
# Bare-URL fallback
# ---------------------------------------------------------------------------


class TestBareUrlFallback:
    def test_anchor_with_only_url_renders_view_source(self, app):
        """No type, just a URL — bare ``View Source →`` link."""
        item = {
            "id": 1,
            "source_anchor": {"url": "https://example.com/something.pdf"},
        }
        html = _render(app, item)
        assert 'href="https://example.com/something.pdf"' in html
        assert "View Source →" in html
        assert 'class="view-source"' in html
        assert 'target="_blank"' in html

    def test_unknown_type_with_url_falls_through_to_bare(self, app):
        """``type=audio`` (or any unknown) is unhandled — bare branch
        catches it via the ``elif _is_safe`` fallback."""
        item = {
            "id": 1,
            "source_anchor": {
                "type": "audio",
                "url": "https://example.com/podcast.mp3",
            },
        }
        html = _render(app, item)
        assert 'href="https://example.com/podcast.mp3"' in html
        assert "View Source →" in html


# ---------------------------------------------------------------------------
# OCR-needed branch (admin gating)
# ---------------------------------------------------------------------------


class TestNoTextLayerBranch:
    def test_no_text_layer_admin_sees_admin_queue_link(self, app):
        item = {
            "id": 99,
            "source_anchor": None,
            "data_quality": "no_text_layer",
        }
        html = _render(app, item, admin=True)
        assert "Source needs OCR" in html
        assert "view-source--unavailable" in html
        assert "/admin/data-debt/" in html
        assert "highlight=99" in html
        assert "[admin queue]" in html

    def test_no_text_layer_non_admin_hides_admin_queue_link(self, app):
        item = {
            "id": 99,
            "source_anchor": None,
            "data_quality": "no_text_layer",
        }
        html = _render(app, item, admin=False)
        assert "Source needs OCR" in html
        assert "view-source--unavailable" in html
        # Admin queue link must NOT leak to public.
        assert "[admin queue]" not in html
        assert "/admin/data-debt/" not in html

    def test_no_text_layer_with_safe_url_prefers_url_branch(self, app):
        """If both ``no_text_layer`` and a working URL are present, the
        URL branches win — the OCR-needed message is the no-URL fallback."""
        item = {
            "id": 99,
            "source_anchor": {"url": "https://example.com/scan.pdf"},
            "data_quality": "no_text_layer",
        }
        html = _render(app, item)
        assert 'href="https://example.com/scan.pdf"' in html
        assert "Source needs OCR" not in html


# ---------------------------------------------------------------------------
# No-render paths
# ---------------------------------------------------------------------------


class TestNoRender:
    def test_missing_source_anchor_and_quality_ok_renders_nothing(self, app):
        item = {"id": 1, "source_anchor": None, "data_quality": "ok"}
        html = _render(app, item)
        assert html.strip() == ""

    def test_empty_source_anchor_dict_renders_nothing(self, app):
        item = {"id": 1, "source_anchor": {}, "data_quality": "ok"}
        html = _render(app, item)
        assert html.strip() == ""

    def test_no_source_anchor_key_at_all_renders_nothing(self, app):
        """``item`` lacks the ``source_anchor`` key entirely — Jinja's
        Undefined coerces to ``or {}`` and we land on no-render."""
        item = {"id": 1, "data_quality": "ok"}
        html = _render(app, item)
        assert html.strip() == ""


# ---------------------------------------------------------------------------
# Scheme allowlist
# ---------------------------------------------------------------------------


class TestSchemeAllowlist:
    """Mirrors :class:`TestSourceLinkSchemeValidation` for the new
    button. The allowlist must reject ``javascript:``, ``data:``, and
    protocol-relative ``//host/path`` URLs even when ``type`` claims a
    specific shape — the type alone does not certify safety."""

    def test_javascript_url_rejected(self, app):
        item = {
            "id": 1,
            "source_anchor": {
                "type": "pdf",
                "url": "javascript:alert(1)",
                "page": 3,
            },
        }
        html = _render(app, item)
        assert html.strip() == ""
        assert "javascript:" not in html

    def test_data_url_rejected(self, app):
        item = {
            "id": 1,
            "source_anchor": {
                "url": "data:text/html,<script>alert(1)</script>",
            },
        }
        html = _render(app, item)
        assert html.strip() == ""
        assert "data:text/html" not in html

    def test_protocol_relative_url_rejected(self, app):
        item = {
            "id": 1,
            "source_anchor": {
                "type": "html",
                "url": "//evil.example/x",
                "anchor": "#item-1",
            },
        }
        html = _render(app, item)
        assert html.strip() == ""
        assert "evil.example" not in html

    def test_relative_url_rejected_unlike_legacy_stub(self, app):
        """Decision: the new button rejects site-relative ``/foo`` URLs
        because v3 ``source_anchor`` always carries an absolute origin
        (PDF on city CDN, video on Granicus, HTML on city site). The
        legacy ``_source_link_stub.html`` still allows ``/`` for v2
        items where the URL is sometimes relative — but v3 doesn't
        emit those, so the stricter allowlist is safe here."""
        item = {
            "id": 1,
            "source_anchor": {"url": "/uploads/agenda-2024.pdf"},
        }
        html = _render(app, item)
        assert html.strip() == ""

    def test_javascript_url_with_no_text_layer_falls_through_to_ocr_label(
        self, app
    ):
        """A malicious URL combined with ``no_text_layer`` shouldn't
        emit the link AND shouldn't suppress the OCR-needed fallback —
        scheme rejection means the URL branches fail, and the
        ``no_text_layer`` branch takes over."""
        item = {
            "id": 99,
            "source_anchor": {"url": "javascript:alert(1)"},
            "data_quality": "no_text_layer",
        }
        html = _render(app, item)
        assert "javascript:" not in html
        assert "Source needs OCR" in html


# ---------------------------------------------------------------------------
# Malformed input
# ---------------------------------------------------------------------------


class TestMalformedInput:
    def test_source_anchor_as_string_renders_nothing(self, app):
        """Defensive: if ``source_anchor`` round-trips as a string
        (e.g. unparsed JSONB), no branch should fire and no traceback
        should escape to the response."""
        item = {
            "id": 1,
            "source_anchor": "https://example.com/oops.pdf",
            "data_quality": "ok",
        }
        html = _render(app, item)
        assert html.strip() == ""

    def test_source_anchor_as_list_renders_nothing(self, app):
        item = {
            "id": 1,
            "source_anchor": ["https://example.com/oops.pdf"],
            "data_quality": "ok",
        }
        html = _render(app, item)
        assert html.strip() == ""

    def test_source_anchor_none_with_no_text_layer_still_renders_ocr_label(
        self, app
    ):
        """``None`` source_anchor + ``no_text_layer`` must still surface
        the OCR-needed fallback. ``or {}`` coerces None to empty dict;
        no URL branches match; ``data_quality`` branch wins."""
        item = {
            "id": 99,
            "source_anchor": None,
            "data_quality": "no_text_layer",
        }
        html = _render(app, item)
        assert "Source needs OCR" in html


# ---------------------------------------------------------------------------
# format_timestamp filter — direct unit tests
# ---------------------------------------------------------------------------


class TestFormatTimestampFilter:
    """Direct unit tests for ``docket.web.filters.format_timestamp``
    covering the spec §6.4 contract: ``M:SS`` under one hour,
    ``H:MM:SS`` from one hour up, defensive empty string for negative
    / non-int / None."""

    def test_zero_seconds(self):
        from docket.web.filters import format_timestamp

        assert format_timestamp(0) == "0:00"

    def test_under_one_minute(self):
        from docket.web.filters import format_timestamp

        assert format_timestamp(45) == "0:45"

    def test_one_minute_five_seconds(self):
        from docket.web.filters import format_timestamp

        assert format_timestamp(65) == "1:05"

    def test_exactly_one_hour(self):
        from docket.web.filters import format_timestamp

        assert format_timestamp(3600) == "1:00:00"

    def test_one_hour_two_minutes_five_seconds(self):
        from docket.web.filters import format_timestamp

        assert format_timestamp(3725) == "1:02:05"

    def test_just_under_one_hour_uses_minute_format(self):
        from docket.web.filters import format_timestamp

        # 59:59 — still under an hour, no hour component.
        assert format_timestamp(3599) == "59:59"

    def test_negative_returns_empty_string(self):
        from docket.web.filters import format_timestamp

        assert format_timestamp(-1) == ""
        assert format_timestamp(-3600) == ""

    def test_none_returns_empty_string(self):
        from docket.web.filters import format_timestamp

        assert format_timestamp(None) == ""

    def test_non_numeric_string_returns_empty_string(self):
        from docket.web.filters import format_timestamp

        assert format_timestamp("not-a-number") == ""

    def test_numeric_string_coerced_to_int(self):
        """JSONB integers can round-trip as strings depending on driver
        — accept ``"3725"`` rather than crash."""
        from docket.web.filters import format_timestamp

        assert format_timestamp("3725") == "1:02:05"

    def test_float_truncated_to_int(self):
        from docket.web.filters import format_timestamp

        # 65.7 → floor to 65 → "1:05"
        assert format_timestamp(65.7) == "1:05"

    def test_bool_returns_empty_string(self):
        """``isinstance(True, int)`` is True in Python — explicit reject
        so a stray boolean doesn't render as ``0:01`` / ``0:00``."""
        from docket.web.filters import format_timestamp

        assert format_timestamp(True) == ""
        assert format_timestamp(False) == ""


# ---------------------------------------------------------------------------
# admin.data_debt route stub registration
# ---------------------------------------------------------------------------


class TestAdminDataDebtRouteStub:
    """The OCR-needed branch of the source-anchor button calls
    ``url_for('admin.data_debt', highlight=item.id)`` unconditionally
    when ``session.admin_user`` is truthy. Without route registration
    Flask raises ``BuildError`` at render time. Pin both that the
    endpoint exists on the production blueprint and that it 404s (the
    page itself is a future task — same pattern E3 used for
    ``public.item_detail`` and ``public.upcoming_hearings_rss``)."""

    def test_data_debt_url_resolves(self):
        from docket.web import create_app

        app = create_app()
        with app.test_request_context():
            from flask import url_for

            url = url_for("admin.data_debt", highlight=42)
            assert "/admin/data-debt/" in url
            assert "highlight=42" in url

    def test_data_debt_returns_404_until_built(self):
        """Stub returns 404 (E3 pattern). Hitting the route requires an
        admin session because the admin blueprint's ``before_request``
        gates everything; verify the gate first, then verify the
        authenticated path 404s instead of 500ing."""
        from docket.web import create_app

        app = create_app()
        app.config["SECRET_KEY"] = "test-only"

        with app.test_client() as client:
            # Unauthed: should redirect to login, not 500.
            resp = client.get("/admin/data-debt/")
            assert resp.status_code in (302, 303)
            assert "/admin/login" in resp.headers.get("Location", "")

            # Authed: stub aborts 404.
            with client.session_transaction() as sess:
                sess["admin_user"] = "tester"
            resp = client.get("/admin/data-debt/")
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Forcing-function tests for E4 TODO cleanups
# ---------------------------------------------------------------------------
#
# These three tests are intentionally ``xfail(strict=True)``. They describe
# the *desired* future state, not the current state — when the underlying
# cleanup lands, each test will start passing, and ``strict=True`` will flip
# it from XFAIL into a real FAILED. That forces the developer doing the
# cleanup to come back and remove the ``xfail`` mark, which doubles as
# confirmation that the cleanup actually happened end-to-end. Don't
# "fix" these by relaxing strictness — fix them by retiring the TODO.


class TestForcingFunctionsForE4Cleanups:
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "admin.data_debt is currently a 404 stub; remove this xfail "
            "when the queue page lands"
        ),
    )
    def test_data_debt_returns_200_when_queue_page_lands(self):
        """When the data-debt queue page is built (likely F-track), the
        route should return 200 for an authenticated admin and accept the
        ``?highlight=N`` query arg the source-anchor button passes. While
        the route still ``abort(404)``s this xfails; once it lands the
        ``strict=True`` flips to FAILED and the developer retires the mark."""
        from docket.web import create_app

        app = create_app()
        app.config["SECRET_KEY"] = "test-only"

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["admin_user"] = "tester"
            resp = client.get("/admin/data-debt/?highlight=42")
            assert resp.status_code == 200

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "_source_link_stub.html still in use by 4 v2 cards "
            "(card_failed, card_degraded, card_v2_fallback, card_pending); "
            "remove this xfail and delete the stub when A8 ships and "
            "migrates them to source_anchor_button"
        ),
    )
    def test_source_link_stub_is_retired(self):
        """A8 extends ``AgendaItem`` so ``source_anchor`` is exposed for
        every item shape. Once that lands, the 4 v2 cards still using
        ``_source_link_stub.html`` (``card_failed``, ``card_degraded``,
        ``card_v2_fallback``, ``card_pending``) should switch to
        ``source_anchor_button.html`` and the stub file should be deleted."""
        templates_dir = (
            Path(__file__).parent.parent.parent
            / "src/docket/web/templates"
        )
        stub_path = templates_dir / "partials/_source_link_stub.html"
        assert not stub_path.exists(), (
            f"{stub_path} should be deleted after A8"
        )

        # Also assert no card template includes the stub.
        partials_dir = templates_dir / "partials"
        for tpl in partials_dir.glob("card_*.html"):
            content = tpl.read_text()
            assert "_source_link_stub" not in content, (
                f"{tpl} still includes the stub"
            )

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "spec §6.4 uses truthy `if anchor.timestamp_seconds` so 0 "
            "falls through to bare URL; remove this xfail and switch the "
            "Jinja to `is not none` if Stage 1 emits 0 as a legitimate "
            "start-of-meeting anchor"
        ),
    )
    def test_video_timestamp_zero_renders_as_start_of_meeting(self, app):
        """Stage 1 may eventually emit ``timestamp_seconds=0`` as a
        legitimate "start of meeting" anchor (vs. the current behavior
        where ``0`` is falsy and falls through to the bare URL branch).
        When that happens, the Jinja ``{% if anchor.timestamp_seconds %}``
        guard needs to flip to ``is not none`` and the video branch
        should render normally with a ``0:00`` label and ``?t=0`` query."""
        item = {
            "id": 1,
            "source_anchor": {
                "type": "video",
                "url": "https://example.com/video",
                "timestamp_seconds": 0,
            },
        }
        html = _render(app, item)
        assert "0:00" in html
        assert "?t=0" in html
