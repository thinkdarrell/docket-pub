"""Live smoke tests for B5 — pipeline.process_item against real Anthropic.

Gated on ANTHROPIC_API_KEY. Costs ~$0.003 per run (one Stage 1 + one
Stage 2 Haiku call). Run manually before merging to main; skipped
automatically in CI without the env var.
"""

from __future__ import annotations

import os

import pytest

from docket.db import db


pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set; skipping live smoke test.",
)


@pytest.fixture
def live_bag():
    """Reuse the _Bag pattern. Defined here to keep tests/live/
    self-contained (per project convention)."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM municipalities WHERE slug = 'birmingham'"
        )
        city_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
            VALUES (%s, 'B5 live smoke', '2026-04-15', 'council')
            RETURNING id
            """,
            (city_id,),
        )
        meeting_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO agenda_items
              (meeting_id, title, description, dollars_amount, is_consent,
               data_quality, data_debt_priority,
               processing_status)
            VALUES (%s,
                    'Award $1.2M HVAC contract to Acme Industries (sole source)',
                    'The Council considers awarding a $1,200,000 sole-source '
                    'contract to Acme Industries for replacement of HVAC systems '
                    'in 14 city buildings. Funding from the general fund.',
                    1200000, FALSE,
                    'ok'::data_quality_enum,
                    'normal'::data_debt_priority_enum,
                    'pending'::processing_status_enum)
            RETURNING id
            """,
            (meeting_id,),
        )
        item_id = cur.fetchone()[0]

    yield {"city_id": city_id, "meeting_id": meeting_id, "item_id": item_id}

    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM agenda_item_badges WHERE agenda_item_id = %s",
                     (item_id,))
        cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
        cur.execute("DELETE FROM meetings WHERE id = %s", (meeting_id,))


@pytest.mark.live
def test_pipeline_live_substantive_item_completes(live_bag):
    """Real Anthropic calls. A clearly-substantive item (sole-source
    $1.2M contract) should complete with headline + sole_source +
    legal_settlement-ish badges, and final status='completed'.

    Asserts the end-to-end contract without asserting specific text
    (LLM outputs vary)."""
    from docket.ai import pipeline
    from docket.db import db_cursor

    # Build the duck-typed item from the seeded row.
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT ai.id, ai.meeting_id, ai.title, ai.description,
                   ai.sponsor, ai.dollars_amount, ai.topic, ai.is_consent,
                   m.municipality_id AS city_id,
                   muni.name AS city_name
              FROM agenda_items ai
              JOIN meetings m ON m.id = ai.meeting_id
              JOIN municipalities muni ON muni.id = m.municipality_id
             WHERE ai.id = %s
            """,
            (live_bag["item_id"],),
        )
        row = dict(cur.fetchone())

    # source_type / raw_text are duck-typed but no column exists.
    row["source_type"] = "agenda"
    row["raw_text"] = None

    class _Item:
        def __init__(self, d):
            self.__dict__.update(d)
    item = _Item(row)

    status = pipeline.process_item(item)
    assert status == "completed", f"Expected completed; got {status}"

    with db_cursor() as cur:
        cur.execute(
            """
            SELECT headline, why_it_matters, significance_score,
                   processing_status::text
              FROM agenda_items WHERE id = %s
            """,
            (live_bag["item_id"],),
        )
        final = dict(cur.fetchone())

    assert final["headline"] and len(final["headline"]) >= 10
    assert final["why_it_matters"]
    assert final["processing_status"] == "completed"

    # Sole-source + large $$$ should fire badges.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT badge_slug FROM agenda_item_badges WHERE agenda_item_id = %s",
            (live_bag["item_id"],),
        )
        slugs = {row[0] for row in cur.fetchall()}
    # SUG-4: defensive against minor Haiku classification variance.
    # Sole-source $1.2M HVAC contract should fire at least one process
    # badge. 'sole_source' is the strongest signal; allow
    # 'emergency_action' as a secondary if Haiku ever interprets the
    # description differently. Both are deterministic-match badges
    # that fire off Stage 1 facts.
    assert slugs, f"expected at least one badge; got none (final={final})"
    assert "sole_source" in slugs or "emergency_action" in slugs, (
        f"expected sole_source or emergency_action; got {slugs}"
    )
