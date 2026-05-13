"""Tests for query.list_agenda_items — A8 v3 column exposure.

Two layers of coverage:

1. **DB-backed integration** — exercise the real ``list_agenda_items``
   SELECT against a freshly seeded meeting on the local docket_db so we
   confirm the lean ``extracted_facts`` jsonb_extract_path shape, the
   badges JOIN, and the v3 flat columns all populate correctly. Mirrors
   ``test_query_list_votes.py`` fixture style.

2. **Dispatcher round-trip** — render
   ``partials/smart_brevity_card.html`` against constructed
   ``AgendaItem`` instances (no DB) to confirm the dispatcher's gate
   conditions work when fed the real dataclass shape. Today the
   dispatcher tests in ``test_smart_brevity_card_dispatcher.py`` use
   plain dicts, which masked the regression where ``AgendaItem`` simply
   didn't expose ``processing_status`` / ``data_quality`` /
   ``ai_rewrite_version``.

Pure UI render tests don't touch the DB; integration tests insert real
rows and clean up via meetings → agenda_items CASCADE.
"""

from __future__ import annotations

import pytest
import psycopg2.extras
from flask import Flask, render_template

from docket.db import db
from docket.models.agenda import AgendaItem
from docket.services.query import list_agenda_items


# ---------------------------------------------------------------------------
# Flask app fixture for dispatcher rendering (mirrors
# tests/unit/test_smart_brevity_card_dispatcher.py)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    flask_app = Flask(
        "test_list_agenda_items_dispatcher",
        template_folder="src/docket/web/templates",
    )

    from docket.web import source_security
    from docket.web.filters import register as register_filters

    register_filters(flask_app)

    @flask_app.template_filter("topic_name")
    def _topic_name(slug):
        return slug or ""

    flask_app.jinja_env.globals["is_source_url_safe"] = (
        lambda url: source_security.is_url_safe(
            url,
            frozenset({"example.com", "birminghamal.gov"}),
        )
    )
    return flask_app


def _render(app, item):
    # PR C: shell-based variants use url_for('public.meeting_detail', ...).
    if "public.meeting_detail" not in {r.endpoint for r in app.url_map.iter_rules()}:
        app.add_url_rule(
            "/c/<slug>/meetings/<int:meeting_id>",
            endpoint="public.meeting_detail",
            view_func=lambda slug, meeting_id: "",
        )
    with app.test_request_context():
        return render_template(
            "partials/smart_brevity_card.html",
            item=item,
            municipality={"slug": "birmingham", "id": 1},
        )


# A minimum AgendaItem requires the 13 positional fields. Helper.
def _make_item(**overrides) -> AgendaItem:
    base = dict(
        id=1,
        meeting_id=1,
        external_id=None,
        item_number="1",
        title="Test item",
        description=None,
        section=None,
        is_consent=False,
        sponsor=None,
        dollars_amount=None,
        topic=None,
        significance_score=None,
        consent_placement_score=None,
    )
    base.update(overrides)
    return AgendaItem(**base)


# ---------------------------------------------------------------------------
# Dataclass-level: NULL handling + dispatcher routing
# ---------------------------------------------------------------------------


class TestAgendaItemDataclass:
    def test_from_row_handles_all_v3_columns_missing(self):
        """An old row predating migration 013 still maps cleanly — every
        v3 field becomes None and dataclass construction doesn't raise."""
        row = {
            "id": 7,
            "meeting_id": 1,
            "title": "Pre-v3 item",
            "is_consent": False,
        }
        item = AgendaItem.from_row(row)

        assert item.id == 7
        assert item.title == "Pre-v3 item"
        assert item.processing_status is None
        assert item.data_quality is None
        assert item.data_debt_priority is None
        assert item.ai_rewrite_version is None
        assert item.ai_extraction_version is None
        assert item.ai_confidence is None
        assert item.headline is None
        assert item.why_it_matters is None
        assert item.source_anchor is None
        assert item.extracted_facts is None
        assert item.next_steps is None
        assert item.badges == []  # never None — sentinel for "no badges"

    def test_from_row_maps_v3_columns_when_present(self):
        row = {
            "id": 8,
            "meeting_id": 1,
            "title": "v3 item",
            "is_consent": False,
            "data_quality": "ok",
            "data_debt_priority": "normal",
            "processing_status": "completed",
            "ai_extraction_version": 1,
            "ai_rewrite_version": 3,
            "ai_confidence": "high",
            "headline": "Sole-source: $1.8M",
            "why_it_matters": "Higher per-camera rates affect budget.",
            "source_anchor": {"type": "pdf", "url": "https://example.com/x.pdf", "page": 12},
            "extracted_facts": {
                "counterparty": "Flock Safety Inc.",
                "funding_source": "general_fund",
                "action_type": "contract_amendment",
            },
            "badges": [{"slug": "sole_source", "kind": "process", "name": "Sole-source", "icon": "🤝", "description": "x", "confidence": 1.0}],
        }
        item = AgendaItem.from_row(row)
        assert item.processing_status == "completed"
        assert item.ai_rewrite_version == 3
        assert item.headline == "Sole-source: $1.8M"
        assert item.source_anchor["page"] == 12
        assert item.extracted_facts["counterparty"] == "Flock Safety Inc."
        assert len(item.badges) == 1
        assert item.badges[0]["slug"] == "sole_source"

    def test_next_steps_exposed_at_top_level_for_engagement_strip(self):
        """Bug fix: ``partials/engagement_strip.html`` reads
        ``item.next_steps`` directly. Without lifting the sub-key onto
        the dataclass, the strip would never render against an
        ``AgendaItem`` instance even when the data is present in the
        lean ``extracted_facts`` projection.
        """
        row = {
            "id": 9,
            "meeting_id": 1,
            "title": "Hearing-bearing item",
            "is_consent": False,
            "extracted_facts": {
                "public_hearing_date": "2026-06-01",  # ignored — not under next_steps
                "next_steps": {
                    "public_hearing_date": "2026-06-01",
                    "comment_period_end": "2026-05-25",
                },
            },
        }
        item = AgendaItem.from_row(row)
        assert item.next_steps == {
            "public_hearing_date": "2026-06-01",
            "comment_period_end": "2026-05-25",
        }
        # extracted_facts itself is left intact (the lean projection still
        # lives there too — top-level field is an alias, not a move).
        assert item.extracted_facts["next_steps"]["comment_period_end"] == "2026-05-25"

    def test_next_steps_none_when_extracted_facts_missing_subkey(self):
        """``extracted_facts`` populated but no ``next_steps`` key —
        ``item.next_steps`` is None so Jinja's ``{% if item.next_steps %}``
        guard collapses cleanly to falsy."""
        row = {
            "id": 10,
            "meeting_id": 1,
            "title": "Cost-only item",
            "is_consent": False,
            "extracted_facts": {"counterparty": "Acme Corp."},
        }
        item = AgendaItem.from_row(row)
        assert item.next_steps is None

    def test_next_steps_none_when_extracted_facts_null(self):
        """``extracted_facts`` is None (Wave 0 / pre-v3 row) —
        ``next_steps`` must default to None without raising."""
        row = {
            "id": 11,
            "meeting_id": 1,
            "title": "Pre-v3 item",
            "is_consent": False,
            "extracted_facts": None,
        }
        item = AgendaItem.from_row(row)
        assert item.next_steps is None

    def test_lifted_subkeys_from_full_extracted_facts(self):
        """All five lifted top-level fields populate from the matching
        ``extracted_facts`` sub-keys when present (A8 fix-up). Mirrors
        the ``next_steps`` lift but for the full Stage 1 set."""
        row = {
            "id": 12,
            "meeting_id": 1,
            "title": "Full v3 item",
            "is_consent": False,
            "extracted_facts": {
                "counterparty": "Flock Safety Inc.",
                "funding_source": "general_fund",
                "procurement_method": "sole_source",
                "action_type": "contract_amendment",
                "location": {"ward_or_district": "Wards 4-7"},
                "next_steps": {"public_hearing_date": "2026-06-01"},
            },
        }
        item = AgendaItem.from_row(row)
        assert item.counterparty == "Flock Safety Inc."
        assert item.funding_source == "general_fund"
        assert item.procurement_method == "sole_source"
        assert item.action_type == "contract_amendment"
        assert item.location == {"ward_or_district": "Wards 4-7"}
        assert item.next_steps == {"public_hearing_date": "2026-06-01"}
        # Additive lift — extracted_facts itself still carries everything.
        assert item.extracted_facts["counterparty"] == "Flock Safety Inc."

    def test_lifted_subkeys_none_when_extracted_facts_is_string(self):
        """Defensive: a malformed ``extracted_facts`` (e.g., a bare JSONB
        string somehow making it through the lean SELECT) collapses every
        lifted sub-key to None instead of raising. The type-guarded lift
        means partials never see a TypeError."""
        row = {
            "id": 13,
            "meeting_id": 1,
            "title": "Malformed string item",
            "is_consent": False,
            "extracted_facts": "malformed garbage string",
        }
        item = AgendaItem.from_row(row)
        assert item.next_steps is None
        assert item.counterparty is None
        assert item.funding_source is None
        assert item.procurement_method is None
        assert item.action_type is None
        assert item.location is None

    def test_lifted_subkeys_none_when_extracted_facts_is_list(self):
        """Defensive: a list ``extracted_facts`` (Stage 1 emitting an
        array by mistake) also collapses cleanly to None on every
        lifted field."""
        row = {
            "id": 14,
            "meeting_id": 1,
            "title": "Malformed list item",
            "is_consent": False,
            "extracted_facts": [1, 2, 3],
        }
        item = AgendaItem.from_row(row)
        assert item.next_steps is None
        assert item.counterparty is None
        assert item.funding_source is None
        assert item.procurement_method is None
        assert item.action_type is None
        assert item.location is None

    def test_lifted_subkeys_type_guarded_on_individual_keys(self):
        """Each sub-key lift is independently type-guarded. A wrong-type
        value on one key (e.g., ``counterparty`` is an int instead of a
        str) collapses just that one to None, leaving the others to
        populate normally from their valid sibling values."""
        row = {
            "id": 15,
            "meeting_id": 1,
            "title": "Mixed-type item",
            "is_consent": False,
            "extracted_facts": {
                "counterparty": 42,                       # wrong type — int
                "funding_source": "general_fund",         # OK
                "procurement_method": ["a", "b"],         # wrong type — list
                "action_type": "contract_amendment",      # OK
                "location": "not a dict",                 # wrong type — str
                "next_steps": "not a dict either",        # wrong type — str
            },
        }
        item = AgendaItem.from_row(row)
        assert item.counterparty is None
        assert item.funding_source == "general_fund"
        assert item.procurement_method is None
        assert item.action_type == "contract_amendment"
        assert item.location is None
        assert item.next_steps is None


# ---------------------------------------------------------------------------
# Dispatcher round-trip: build an AgendaItem and feed it through the
# Smart Brevity Card dispatcher, asserting the routing gate fires
# correctly. Catches the regression where AgendaItem didn't expose the
# v3 columns and Jinja Undefined silently turned every gate falsy.
# ---------------------------------------------------------------------------


class TestDispatcherWithAgendaItemDataclass:
    def test_null_v3_fields_route_to_pending(self, app):
        """No v3 columns set, no v2 summary either → pending."""
        item = _make_item(title="Bare item")
        html = _render(app, item)
        assert 'data-variant="pending"' in html

    def test_null_v3_fields_with_v2_summary_route_to_v2_fallback(self, app):
        """All v3 columns NULL but v2 summary present → v2_fallback. The
        defensive contract: existing v2 production shape keeps working."""
        item = _make_item(
            title="Legacy item",
            summary="A v2 summary that should still render.",
        )
        html = _render(app, item)
        assert 'data-variant="v2_fallback"' in html
        assert "A v2 summary that should still render." in html

    def test_data_quality_no_text_layer_routes_to_degraded(self, app):
        """Wave 0 routing — data_quality classifies the source as degraded."""
        item = _make_item(
            title="OCR-needed item",
            data_quality="no_text_layer",
            processing_status="data_quality_skipped",
        )
        html = _render(app, item)
        assert 'data-variant="degraded"' in html
        # PR C: phrasing changed to "OCR needed".
        assert "OCR needed" in html

    def test_processing_status_failed_permanent_routes_to_failed(self, app):
        item = _make_item(
            title="Failed item",
            processing_status="failed_permanent",
        )
        html = _render(app, item)
        assert 'data-variant="failed"' in html
        # PR C: pill text lowercase.
        assert "processing error" in html

    def test_processing_status_procedural_skipped_routes_to_procedural(self, app):
        item = _make_item(
            title="Roll Call",
            processing_status="procedural_skipped",
            data_quality="ok",
        )
        html = _render(app, item)
        assert 'data-variant="procedural"' in html
        assert "Roll Call" in html

    def test_processing_status_cross_stage_conflict_routes_to_verification_pending(self, app):
        item = _make_item(
            title="Conflicting item",
            headline="Conflicting headline",
            why_it_matters="Stage 1 and Stage 2 disagree.",
            processing_status="cross_stage_conflict",
            data_quality="ok",
            ai_rewrite_version=3,
        )
        html = _render(app, item)
        assert 'data-variant="verification_pending"' in html
        assert "Verification in progress" in html

    def test_ai_rewrite_version_3_routes_to_smart_brevity(self, app):
        """Full v3 happy path: ai_rewrite_version=3 + completed status →
        card_smart_brevity, with headline + why_it_matters + facts strip
        + source-anchor button all rendered."""
        from decimal import Decimal

        item = _make_item(
            title="Title fallback",
            dollars_amount=Decimal("1800000"),
            data_quality="ok",
            processing_status="completed",
            ai_rewrite_version=3,
            headline="Sole-source: Flock licenses extended 5 years for $1.8M",
            why_it_matters="Higher per-camera rates affect surveillance budget.",
            source_anchor={
                "type": "pdf",
                "url": "https://example.com/flock.pdf",
                "page": 12,
            },
            counterparty="Flock Safety Inc.",
            funding_source="general_fund",
            procurement_method="sole_source",
            action_type="contract_amendment",
        )
        html = _render(app, item)
        assert 'data-variant="smart_brevity"' in html
        # Headline preferred over title
        assert "Sole-source: Flock licenses extended" in html
        assert "Title fallback" not in html
        # Why it matters block
        assert "surveillance budget" in html
        # Facts strip
        assert "Flock Safety Inc." in html
        # NOTE: The source-anchor PDF page link no longer renders on
        # category-landing cards per the PR C compact-scan redesign —
        # source links are accessed via the headline-link → meeting_detail
        # page. Same for the dollar-tier markup, which now lives on the
        # shell's meta line as a `dollar-chip--<color>` element rather
        # than inline in the facts strip.


# ---------------------------------------------------------------------------
# Engagement strip integration: a constructed AgendaItem (no DB) flows
# through ``partials/engagement_strip.html`` and renders the next_steps
# fields. Locks the bug fix — without the top-level ``next_steps``
# alias, the partial would silently render empty.
# ---------------------------------------------------------------------------


class TestEngagementStripWithAgendaItemDataclass:
    def test_engagement_strip_renders_with_next_steps_populated(self, app):
        """An AgendaItem whose extracted_facts.next_steps carries a
        public_hearing_date renders the hearing date through the
        engagement strip via the top-level ``next_steps`` alias."""
        from flask import Blueprint, render_template

        # Register the stub public blueprint on this app if not already
        # present (the dispatcher fixture above doesn't include it).
        if "public" not in app.blueprints:
            public_bp = Blueprint("public", __name__)

            @public_bp.route("/<city>/upcoming-hearings.rss")
            def upcoming_hearings_rss(city):  # pragma: no cover
                return ""

            @public_bp.route("/<city>/items/<int:item_id>")
            def item_detail(city, item_id):  # pragma: no cover
                return ""

            app.register_blueprint(public_bp)
            app.config["SERVER_NAME"] = "docket.test"
            app.config["PREFERRED_URL_SCHEME"] = "https"
            app.config["ADMIN_EMAIL"] = "ops@docket.test"

        item = AgendaItem.from_row({
            "id": 42,
            "meeting_id": 1,
            "title": "Public hearing item",
            "is_consent": False,
            "extracted_facts": {
                "next_steps": {"public_hearing_date": "2026-07-04"},
            },
        })
        # Sanity: top-level alias populated.
        assert item.next_steps == {"public_hearing_date": "2026-07-04"}

        city = {
            "slug": "birmingham",
            "name": "Birmingham",
            "master_calendar_url": None,
        }
        with app.app_context():
            html = render_template(
                "partials/engagement_strip.html", item=item, city=city
            )
        # State-1 markup — populated branch — and the formatted hearing
        # date (format_date filter renders ISO strings as "Month D, YYYY").
        assert 'class="engagement-strip"' in html
        assert "engagement-strip--awaiting" not in html
        assert "engagement-strip--fallback" not in html
        assert "Public hearing" in html
        assert "July 4, 2026" in html


# ---------------------------------------------------------------------------
# Lean shape contract: extracted_facts contains ONLY the keys the v3
# cards render, never the full Stage 1 JSONB blob.
# ---------------------------------------------------------------------------


LEAN_FACTS_KEYS = frozenset({
    "counterparty",
    "funding_source",
    "procurement_method",
    "action_type",
    "location",
    "next_steps",
})


# ---------------------------------------------------------------------------
# DB-backed integration tests — real list_agenda_items() roundtrip
# ---------------------------------------------------------------------------


@pytest.fixture
def meeting_with_v3_items():
    """A meeting with one v3-completed item, one Wave-0-degraded item,
    one v2-only item, one bare/pending item. CASCADE handles cleanup.

    Idempotent — deletes any prior TEST_A8 rows on entry.
    """
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM meetings WHERE title = 'TEST_A8' AND meeting_date = '2099-02-01'"
            )
        conn.commit()

    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM municipalities ORDER BY id LIMIT 1")
            muni_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   VALUES (%s, 'TEST_A8', '2099-02-01', 'council') RETURNING id""",
                (muni_id,),
            )
            mid = cur.fetchone()["id"]

            # Item 1: v3-completed, full v3 shape with badges
            cur.execute(
                """INSERT INTO agenda_items (
                       meeting_id, title, item_number, is_consent,
                       data_quality, processing_status, ai_rewrite_version,
                       ai_extraction_version, ai_confidence,
                       headline, why_it_matters,
                       source_anchor, extracted_facts
                   ) VALUES (%s, 'V3 Item', '1', FALSE,
                       'ok', 'completed', 3,
                       1, 'high',
                       'Sole-source: $1.8M Flock', 'Higher per-camera rates.',
                       %s::jsonb, %s::jsonb)
                   RETURNING id""",
                (
                    mid,
                    psycopg2.extras.Json({
                        "type": "pdf",
                        "url": "https://example.com/x.pdf",
                        "page": 12,
                    }),
                    psycopg2.extras.Json({
                        "counterparty": "Flock Safety Inc.",
                        "funding_source": "general_fund",
                        "procurement_method": "sole_source",
                        "action_type": "contract_amendment",
                        "location": {"ward_or_district": "Wards 4-7"},
                        "next_steps": {"public_hearing_date": "2099-03-01"},
                        # extra keys that should NOT survive the lean shape
                        "parcels_affected": 12,
                        "acres_affected": 4.5,
                    }),
                ),
            )
            v3_item_id = cur.fetchone()["id"]

            # Attach a process badge to the v3 item via existing template
            cur.execute(
                """INSERT INTO agenda_item_badges (
                       agenda_item_id, city_id, badge_slug, kind,
                       confidence, source
                   ) VALUES (%s, %s, 'sole_source', 'process', 1.0, 'deterministic')""",
                (v3_item_id, muni_id),
            )

            # Attach a second badge to the v3 item with status='flagged'
            # so the reader-gate test can confirm flagged badges are
            # filtered out of the public meeting-detail render.
            cur.execute(
                """INSERT INTO agenda_item_badges (
                       agenda_item_id, city_id, badge_slug, kind,
                       confidence, source, status
                   ) VALUES (%s, %s, 'blight_accountability', 'policy',
                       0.4, 'llm', 'flagged')""",
                (v3_item_id, muni_id),
            )

            # Item 2: Wave-0 degraded
            cur.execute(
                """INSERT INTO agenda_items (
                       meeting_id, title, item_number, is_consent,
                       data_quality, data_debt_priority, processing_status
                   ) VALUES (%s, 'Degraded Item', '2', FALSE,
                       'no_text_layer', 'high', 'data_quality_skipped')
                   RETURNING id""",
                (mid,),
            )
            degraded_item_id = cur.fetchone()["id"]

            # Item 3: v2-only (legacy summary, no v3)
            cur.execute(
                """INSERT INTO agenda_items (
                       meeting_id, title, item_number, is_consent,
                       summary
                   ) VALUES (%s, 'Legacy v2 Item', '3', FALSE,
                       'A pre-v3 summary.')
                   RETURNING id""",
                (mid,),
            )
            v2_item_id = cur.fetchone()["id"]

            # Item 4: brand-new (no AI processing yet — all v3 cols default
            # except processing_status = 'pending')
            cur.execute(
                """INSERT INTO agenda_items (
                       meeting_id, title, item_number, is_consent
                   ) VALUES (%s, 'Bare Pending Item', '4', FALSE)
                   RETURNING id""",
                (mid,),
            )
            bare_item_id = cur.fetchone()["id"]

            # Item 5: withdrawn — the council removed this from the agenda.
            # Should not appear in citizen meeting-detail rendering after
            # the PR A reader-gate fix.
            cur.execute(
                """INSERT INTO agenda_items (
                       meeting_id, title, item_number, is_consent,
                       processing_status
                   ) VALUES (%s, 'WITHDRAWN ITEM 5. A Resolution',
                       '5', FALSE, 'withdrawn')
                   RETURNING id""",
                (mid,),
            )
            withdrawn_item_id = cur.fetchone()["id"]

        conn.commit()

    yield {
        "meeting_id": mid,
        "v3_item_id": v3_item_id,
        "degraded_item_id": degraded_item_id,
        "v2_item_id": v2_item_id,
        "bare_item_id": bare_item_id,
        "withdrawn_item_id": withdrawn_item_id,
    }

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = %s", (mid,))
        conn.commit()


class TestListAgendaItemsDB:
    def test_returns_all_items_ordered_by_item_number(self, meeting_with_v3_items):
        items = list_agenda_items(meeting_with_v3_items["meeting_id"])
        assert len(items) == 4
        assert [i.item_number for i in items] == ["1", "2", "3", "4"]

    def test_v3_item_exposes_v3_columns(self, meeting_with_v3_items):
        items = list_agenda_items(meeting_with_v3_items["meeting_id"])
        v3 = next(i for i in items if i.item_number == "1")

        assert v3.processing_status == "completed"
        assert v3.data_quality == "ok"
        assert v3.ai_rewrite_version == 3
        assert v3.ai_extraction_version == 1
        assert v3.ai_confidence == "high"
        assert v3.headline == "Sole-source: $1.8M Flock"
        assert v3.why_it_matters == "Higher per-camera rates."

    def test_v3_item_source_anchor_full_jsonb(self, meeting_with_v3_items):
        items = list_agenda_items(meeting_with_v3_items["meeting_id"])
        v3 = next(i for i in items if i.item_number == "1")

        assert v3.source_anchor is not None
        assert v3.source_anchor["type"] == "pdf"
        assert v3.source_anchor["url"] == "https://example.com/x.pdf"
        assert v3.source_anchor["page"] == 12

    def test_v3_item_extracted_facts_is_lean(self, meeting_with_v3_items):
        """Locks in the lean-list contract — extra keys (parcels_affected,
        acres_affected) from the source JSONB do NOT round-trip on the
        list-page shape. Only the 6 keys the v3 cards render survive.

        The fixture populates ALL 6 lean keys (counterparty,
        funding_source, procurement_method, action_type, location,
        next_steps) so jsonb_strip_nulls does not drop any — that lets
        us assert exact equality (``==``) on the key set, not just
        subset (``<=``). Equality catches accidental key additions on
        the SELECT side; subset would silently allow drift.
        """
        items = list_agenda_items(meeting_with_v3_items["meeting_id"])
        v3 = next(i for i in items if i.item_number == "1")

        assert v3.extracted_facts is not None
        # Lean shape: exact match on the 6 documented keys (==, not <=).
        # Fixture populates all 6 so jsonb_strip_nulls keeps every one.
        assert set(v3.extracted_facts.keys()) == LEAN_FACTS_KEYS
        # Cards-relevant keys actually populated
        assert v3.extracted_facts["counterparty"] == "Flock Safety Inc."
        assert v3.extracted_facts["funding_source"] == "general_fund"
        assert v3.extracted_facts["action_type"] == "contract_amendment"
        assert v3.extracted_facts["procurement_method"] == "sole_source"
        assert v3.extracted_facts["location"]["ward_or_district"] == "Wards 4-7"
        assert v3.extracted_facts["next_steps"]["public_hearing_date"] == "2099-03-01"
        # Extra keys must NOT have leaked
        assert "parcels_affected" not in v3.extracted_facts
        assert "acres_affected" not in v3.extracted_facts

    def test_v3_item_next_steps_lifted_to_top_level(self, meeting_with_v3_items):
        """Round-trip: the lean ``extracted_facts.next_steps`` sub-dict
        is also exposed at ``item.next_steps`` so the engagement strip
        partial works against the dataclass."""
        items = list_agenda_items(meeting_with_v3_items["meeting_id"])
        v3 = next(i for i in items if i.item_number == "1")
        assert v3.next_steps == {"public_hearing_date": "2099-03-01"}

        # Items without a next_steps sub-key get None at the top level.
        degraded = next(i for i in items if i.item_number == "2")
        assert degraded.next_steps is None
        bare = next(i for i in items if i.item_number == "4")
        assert bare.next_steps is None

    def test_v3_item_badges_aggregated(self, meeting_with_v3_items):
        items = list_agenda_items(meeting_with_v3_items["meeting_id"])
        v3 = next(i for i in items if i.item_number == "1")

        assert v3.badges is not None
        assert len(v3.badges) == 1
        chip = v3.badges[0]
        assert chip["slug"] == "sole_source"
        assert chip["kind"] == "process"
        # Filled from priority_badge_templates JOIN
        assert chip["name"] == "Sole-source / no-bid"
        assert chip["icon"] == "🤝"
        # Confidence is preserved (NUMERIC → float/Decimal)
        assert float(chip["confidence"]) == 1.0

    def test_degraded_item_exposes_data_quality(self, meeting_with_v3_items):
        items = list_agenda_items(meeting_with_v3_items["meeting_id"])
        degraded = next(i for i in items if i.item_number == "2")

        assert degraded.data_quality == "no_text_layer"
        assert degraded.data_debt_priority == "high"
        assert degraded.processing_status == "data_quality_skipped"
        assert degraded.headline is None
        assert degraded.extracted_facts is None
        assert degraded.badges == []

    def test_v2_item_keeps_legacy_summary_path(self, meeting_with_v3_items):
        """Defensive contract: legacy items have v3 columns NULL and the
        v2 summary still flows through unchanged."""
        items = list_agenda_items(meeting_with_v3_items["meeting_id"])
        v2 = next(i for i in items if i.item_number == "3")

        assert v2.summary == "A pre-v3 summary."
        assert v2.headline is None
        assert v2.why_it_matters is None
        assert v2.processing_status == "pending"  # default
        assert v2.ai_rewrite_version is None
        assert v2.extracted_facts is None
        assert v2.badges == []

    def test_bare_item_processes_status_default_pending(self, meeting_with_v3_items):
        items = list_agenda_items(meeting_with_v3_items["meeting_id"])
        bare = next(i for i in items if i.item_number == "4")

        # Migration 013 defaulted processing_status to 'pending'
        assert bare.processing_status == "pending"
        assert bare.data_quality is None
        assert bare.summary is None
        assert bare.headline is None
        assert bare.extracted_facts is None
        assert bare.badges == []

    def test_flagged_badges_hidden_from_citizen_render(self, meeting_with_v3_items):
        """Refactor #2 retro finding: list_agenda_items must filter the
        per-item badge JSONB-agg to status='applied' so flagged policy-
        badge suggestions never reach citizen meeting-detail pages.

        Fixture seeds: v3 item carries (a) a 'sole_source' badge with
        default status='applied' and (b) a 'blight_accountability' badge
        with status='flagged'. Reader must return only the applied one.
        """
        items = list_agenda_items(meeting_with_v3_items["meeting_id"])
        v3 = next(i for i in items if i.id == meeting_with_v3_items["v3_item_id"])

        slugs = {b["slug"] for b in v3.badges}
        assert "sole_source" in slugs, (
            "applied badge must still render"
        )
        assert "blight_accountability" not in slugs, (
            "flagged badge must NOT reach citizens"
        )

    def test_withdrawn_items_hidden_from_citizen_render(self, meeting_with_v3_items):
        """Refactor #2 retro finding: list_agenda_items must hide items
        with processing_status='withdrawn' so council-removed items don't
        render as 'awaiting summary' on citizen meeting-detail pages.

        Fixture seeds five items: v3, degraded, v2, pending, withdrawn.
        Reader must return only the first four; the withdrawn id must
        not appear in the result set.
        """
        items = list_agenda_items(meeting_with_v3_items["meeting_id"])
        item_ids = {i.id for i in items}

        assert meeting_with_v3_items["withdrawn_item_id"] not in item_ids, (
            "withdrawn item must not appear in citizen render"
        )
        # Four non-withdrawn items remain — same shape the original
        # test_returns_all_items_ordered_by_item_number assertion uses
        # (which itself depends on this same SQL predicate).
        assert len(items) == 4


# ---------------------------------------------------------------------------
# Natural-sort ORDER BY contract — locks the post-A8 behavior of
# list_agenda_items for mixed-format Birmingham item_numbers.
# Pre-A8 the SQL did `ORDER BY ai.item_number` (TEXT sort), which placed
# "10" before "2" because '1' < '2' lexicographically. Birmingham items
# look like 1, 2, 10, 10A, 10B, 11, A.1, A.2 — so the new ORDER BY pulls
# the leading numeric prefix and sorts numerically, breaking ties on the
# full string and pushing items without a leading digit (and NULL
# item_numbers) to the very end.
# ---------------------------------------------------------------------------


@pytest.fixture
def meeting_with_sortable_items(request):
    """Insert a TEST_SORT meeting and seed it with the item_numbers
    listed in the indirect parameter. The fixture yields the meeting_id
    and CASCADE-cleans on teardown.

    Each entry in ``request.param`` is either a string item_number
    (inserted as-is) or None (inserted as a NULL item_number). Title is
    derived from the item_number for debugging — irrelevant to the sort.
    """
    item_numbers: list[str | None] = list(request.param)

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM meetings WHERE title = 'TEST_SORT' AND meeting_date = '2099-03-01'"
            )
        conn.commit()

    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM municipalities ORDER BY id LIMIT 1")
            muni_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   VALUES (%s, 'TEST_SORT', '2099-03-01', 'council') RETURNING id""",
                (muni_id,),
            )
            mid = cur.fetchone()["id"]

            for n in item_numbers:
                title = f"Item {n!r}"
                cur.execute(
                    """INSERT INTO agenda_items (
                           meeting_id, title, item_number, is_consent
                       ) VALUES (%s, %s, %s, FALSE)""",
                    (mid, title, n),
                )
        conn.commit()

    yield mid

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = %s", (mid,))
        conn.commit()


class TestNaturalSortByItemNumber:
    """Lock the natural-sort ORDER BY behavior. Pre-A8 the query did
    TEXT sort; '10' sorted before '2'. Post-fix, leading-numeric prefix
    sorts numerically; ties broken alphabetically; non-numeric prefixes
    and NULL item_numbers sort last."""

    @pytest.mark.parametrize(
        "meeting_with_sortable_items",
        [["1", "2", "10", "11", "20"]],
        indirect=True,
    )
    def test_purely_numeric_items_sort_numerically(self, meeting_with_sortable_items):
        items = list_agenda_items(meeting_with_sortable_items)
        assert [i.item_number for i in items] == ["1", "2", "10", "11", "20"]

    @pytest.mark.parametrize(
        "meeting_with_sortable_items",
        [["10A", "10B", "10C", "11", "11A"]],
        indirect=True,
    )
    def test_alphanumeric_items_sort_by_numeric_prefix_then_alpha(
        self, meeting_with_sortable_items
    ):
        items = list_agenda_items(meeting_with_sortable_items)
        assert [i.item_number for i in items] == ["10A", "10B", "10C", "11", "11A"]

    @pytest.mark.parametrize(
        "meeting_with_sortable_items",
        [["1", "A.1", "2", "A.2"]],
        indirect=True,
    )
    def test_non_numeric_items_sort_last(self, meeting_with_sortable_items):
        # Numeric items first by leading prefix; non-numeric items fall
        # into the 999999 sentinel bucket and tie-break alphabetically
        # by full string.
        items = list_agenda_items(meeting_with_sortable_items)
        assert [i.item_number for i in items] == ["1", "2", "A.1", "A.2"]

    @pytest.mark.parametrize(
        "meeting_with_sortable_items",
        [["1", None, "2", None]],
        indirect=True,
    )
    def test_null_item_numbers_sort_at_end(self, meeting_with_sortable_items):
        items = list_agenda_items(meeting_with_sortable_items)
        # Numeric items first, then NULLs at the very end. Two NULLs in
        # a row can land in either source-row order — assert membership
        # for the NULL tail rather than identity.
        assert [i.item_number for i in items[:2]] == ["1", "2"]
        assert items[2].item_number is None
        assert items[3].item_number is None

    @pytest.mark.parametrize(
        "meeting_with_sortable_items",
        [["1", "2", "3", "10", "10A", "10B", "11", "20", "A.1"]],
        indirect=True,
    )
    def test_mixed_real_world_birmingham_pattern(self, meeting_with_sortable_items):
        items = list_agenda_items(meeting_with_sortable_items)
        assert [i.item_number for i in items] == [
            "1", "2", "3", "10", "10A", "10B", "11", "20", "A.1",
        ]
