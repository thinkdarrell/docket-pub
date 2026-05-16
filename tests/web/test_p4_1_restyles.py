"""Route smoke tests for P4-1 — detail page restyles.

Verifies the new header layout (back link, eyebrow with chip, h1 token),
the 4-card NumStat strip on meeting_detail, the dollar-chip/related-items
conditional rendering on item_detail, and breadcrumbs + card grid on
topic_detail.

Heavy data assertions live elsewhere; these tests check the DOM contract.
"""

from __future__ import annotations

from datetime import datetime

import psycopg2.extras
import pytest

from docket.db import db


def _cleanup() -> None:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE title LIKE 'P41_TEST_%'")
            cur.execute("DELETE FROM meetings WHERE title LIKE 'P41_TEST_%'")
            cur.execute("DELETE FROM municipalities WHERE slug LIKE 'p41test_%'")
        conn.commit()


@pytest.fixture
def city_with_meeting_and_items():
    """One city + one meeting + a few agenda items shaped for restyle assertions."""
    _cleanup()
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO municipalities (slug, name, state, adapter_class, active)
                   VALUES ('p41test_city', 'P41 City', 'AL',
                           'docket.adapters.granicus.GranicusAdapter', TRUE)
                   RETURNING id""",
            )
            muni_id = cur.fetchone()["id"]

            cur.execute(
                """INSERT INTO meetings
                   (municipality_id, external_id, title, meeting_date, meeting_type)
                   VALUES (%s, 'p41test_mtg1', 'P41_TEST_Council Regular Meeting',
                           %s, 'regular')
                   RETURNING id""",
                (muni_id, datetime(2026, 5, 1)),
            )
            meeting_id = cur.fetchone()["id"]

            # Item A — substantive, with dollars, with topic "budget", with sponsor.
            cur.execute(
                """INSERT INTO agenda_items
                   (meeting_id, external_id, item_number, title, summary,
                    dollars_amount, topic, sponsor, is_consent,
                    processing_status, ai_rewrite_version, data_quality, headline,
                    why_it_matters)
                   VALUES (%s, 'p41_item_a', '5', 'P41_TEST_Item with dollars',
                           'Brief summary A.',
                           500000, 'budget', 'Council Member Doe', FALSE,
                           'completed', 3, 'ok',
                           'Budget headline A', 'Why A matters.')
                   RETURNING id""",
                (meeting_id,),
            )
            item_a_id = cur.fetchone()["id"]

            # Item B — substantive, NO dollars, with same topic & sponsor (so A has
            # related-by-topic AND related-by-sponsor hits via B).
            # Different meeting so the by-topic/by-sponsor helpers don't filter it.
            cur.execute(
                """INSERT INTO meetings
                   (municipality_id, external_id, title, meeting_date, meeting_type)
                   VALUES (%s, 'p41test_mtg2', 'P41_TEST_Earlier Meeting',
                           %s, 'regular')
                   RETURNING id""",
                (muni_id, datetime(2026, 4, 1)),
            )
            meeting2_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO agenda_items
                   (meeting_id, external_id, item_number, title,
                    dollars_amount, topic, sponsor, is_consent,
                    processing_status, ai_rewrite_version, data_quality, headline,
                    why_it_matters)
                   VALUES (%s, 'p41_item_b', '3', 'P41_TEST_Related item B',
                           NULL, 'budget', 'Council Member Doe', FALSE,
                           'completed', 3, 'ok',
                           'Related headline B', 'Why B matters.')
                   RETURNING id""",
                (meeting2_id,),
            )

            # Item C — no topic, no sponsor (so related lists are empty for it).
            cur.execute(
                """INSERT INTO agenda_items
                   (meeting_id, external_id, item_number, title,
                    dollars_amount, topic, sponsor, is_consent,
                    processing_status, ai_rewrite_version, data_quality)
                   VALUES (%s, 'p41_item_c', '7', 'P41_TEST_Bare item',
                           NULL, NULL, NULL, FALSE,
                           'completed', 3, 'ok')
                   RETURNING id""",
                (meeting_id,),
            )
            item_c_id = cur.fetchone()["id"]

        conn.commit()

    yield {
        "city_slug": "p41test_city",
        "muni_id": muni_id,
        "meeting_id": meeting_id,
        "item_a_id": item_a_id,
        "item_c_id": item_c_id,
    }
    _cleanup()


# ── meeting_detail ───────────────────────────────────────────────────────────


def test_meeting_detail_renders_back_link(client, city_with_meeting_and_items):
    fx = city_with_meeting_and_items
    resp = client.get(f"/al/{fx['city_slug']}/meetings/{fx['meeting_id']}/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'class="back-link' in body
    assert "Back to P41 City" in body


def test_meeting_detail_renders_kpi_strip(client, city_with_meeting_and_items):
    """3-card NumStat strip: Agenda items / Votes / Total dollars.
    'Dollar items' folded into the Total-dollars sub-line so the top strip
    is visually 3-vs-4 distinct from the city KPI explainer stack below
    (resolves a brief two-strip readability concern surfaced during P4-1
    visual review)."""
    fx = city_with_meeting_and_items
    body = client.get(
        f"/al/{fx['city_slug']}/meetings/{fx['meeting_id']}/"
    ).get_data(as_text=True)
    assert 'class="kpi-strip"' in body
    # 3 NumStat labels present
    assert "Agenda items" in body
    assert "Votes" in body
    assert "Total dollars" in body
    # 4th card removed — its data lives in the Total-dollars sub-line.
    assert 'label="Dollar items"' not in body
    assert "kpi-strip--quad" not in body


def test_meeting_detail_total_dollars_formatted(client, city_with_meeting_and_items):
    """One $500k item exists; total renders pre-formatted (not raw 500000)."""
    fx = city_with_meeting_and_items
    body = client.get(
        f"/al/{fx['city_slug']}/meetings/{fx['meeting_id']}/"
    ).get_data(as_text=True)
    assert "$500,000" in body
    assert "Total dollars" in body


def test_meeting_detail_eyebrow_has_type_pill(client, city_with_meeting_and_items):
    fx = city_with_meeting_and_items
    body = client.get(
        f"/al/{fx['city_slug']}/meetings/{fx['meeting_id']}/"
    ).get_data(as_text=True)
    assert "detail-eyebrow" in body
    assert "meeting-type-pill" in body


# ── item_detail ──────────────────────────────────────────────────────────────


def test_item_detail_renders_back_link(client, city_with_meeting_and_items):
    fx = city_with_meeting_and_items
    body = client.get(
        f"/al/{fx['city_slug']}/items/{fx['item_a_id']}/"
    ).get_data(as_text=True)
    assert 'class="back-link' in body
    assert "Back to meeting" in body


def test_item_detail_renders_dollar_chip_when_present(client, city_with_meeting_and_items):
    """Item A has dollars_amount=$500k → dollar_tier partial renders."""
    fx = city_with_meeting_and_items
    body = client.get(
        f"/al/{fx['city_slug']}/items/{fx['item_a_id']}/"
    ).get_data(as_text=True)
    assert "item-detail-hero-dollar" in body
    assert 'class="dollars dollars--' in body  # dollar_tier partial output


def test_item_detail_omits_dollar_chip_when_absent(client, city_with_meeting_and_items):
    """Item C has no dollars_amount → no dollar chip in hero."""
    fx = city_with_meeting_and_items
    body = client.get(
        f"/al/{fx['city_slug']}/items/{fx['item_c_id']}/"
    ).get_data(as_text=True)
    assert "item-detail-hero-dollar" not in body


def test_item_detail_renders_related_by_topic_when_hits(
    client, city_with_meeting_and_items
):
    """Item A shares topic with Item B (different meeting) → related-by-topic shows."""
    fx = city_with_meeting_and_items
    body = client.get(
        f"/al/{fx['city_slug']}/items/{fx['item_a_id']}/"
    ).get_data(as_text=True)
    assert "related-items--topic" in body
    assert "Related headline B" in body


def test_item_detail_omits_related_by_topic_when_none(
    client, city_with_meeting_and_items
):
    """Item C has no topic → related-by-topic section absent."""
    fx = city_with_meeting_and_items
    body = client.get(
        f"/al/{fx['city_slug']}/items/{fx['item_c_id']}/"
    ).get_data(as_text=True)
    assert "related-items--topic" not in body
    assert "related-items--sponsor" not in body


def test_item_detail_renders_related_by_sponsor_when_hits(
    client, city_with_meeting_and_items
):
    """Item A shares sponsor with Item B → related-by-sponsor shows."""
    fx = city_with_meeting_and_items
    body = client.get(
        f"/al/{fx['city_slug']}/items/{fx['item_a_id']}/"
    ).get_data(as_text=True)
    assert "related-items--sponsor" in body
    assert "More from Council Member Doe" in body


def test_item_detail_renders_byline(client, city_with_meeting_and_items):
    fx = city_with_meeting_and_items
    body = client.get(
        f"/al/{fx['city_slug']}/items/{fx['item_a_id']}/"
    ).get_data(as_text=True)
    assert "item-byline" in body
    assert "Council Member Doe" in body


# ── topic_detail ─────────────────────────────────────────────────────────────


def test_topic_detail_renders_breadcrumbs(client, city_with_meeting_and_items):
    """Cross-city topic page renders the 3-crumb trail."""
    body = client.get("/topics/budget/").get_data(as_text=True)
    assert 'class="breadcrumbs' in body
    assert ">Home<" in body
    assert ">Topics<" in body
    # Last crumb is the topic display name; rendered as breadcrumbs-current
    assert "breadcrumbs-current" in body


def test_topic_detail_title_cross_city_omits_city(
    client, city_with_meeting_and_items
):
    """Cross-city: <title> ends 'Topics — docket.pub' — no city segment."""
    body = client.get("/topics/budget/").get_data(as_text=True)
    # The title block ends '— Topics — docket.pub' without a city in between.
    assert "<title>" in body
    title_chunk = body.split("<title>")[1].split("</title>")[0]
    assert "Topics" in title_chunk
    assert "P41 City" not in title_chunk  # city is not in cross-city title


def test_topic_detail_title_city_scoped_includes_city(
    client, city_with_meeting_and_items
):
    """City-scoped: <title> includes the city slug humanized."""
    fx = city_with_meeting_and_items
    body = client.get(f"/topics/budget/?city={fx['city_slug']}").get_data(as_text=True)
    title_chunk = body.split("<title>")[1].split("</title>")[0]
    assert "Topics" in title_chunk
    # The slug humanizes to "P41Test City" via title-casing the slug; the spec
    # just requires *a* city segment — check that the slug stem is present.
    assert "P41Test" in title_chunk or "P41test" in title_chunk


def test_topic_detail_renders_card_grid_not_feed_row(
    client, city_with_meeting_and_items
):
    """Restyle: items render as smart-brevity-card grid, not the old feed-row table."""
    body = client.get("/topics/budget/").get_data(as_text=True)
    assert "smart-brevity-card" in body
    # The old DOM hooks must be gone:
    assert "feed-table" not in body
    assert "feed-row" not in body


def test_topic_detail_cards_include_meeting_context(
    client, city_with_meeting_and_items
):
    """show_meeting_context=True surfaces the meeting date in each card."""
    body = client.get("/topics/budget/").get_data(as_text=True)
    # Item B's meeting date (April 1, 2026) should be visible in its card.
    assert "April 1, 2026" in body or "Apr 1, 2026" in body
