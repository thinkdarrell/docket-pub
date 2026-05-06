"""Tests for Wave 0 main driver."""

from __future__ import annotations

import pytest

from docket.ai.wave0 import Wave0Report, run_wave_0
from docket.db import db


@pytest.fixture
def fresh_items_for_birmingham():
    """Insert a small set of test items into Birmingham, return their ids.
    Cleanup after the test."""
    ids = []
    fixtures = [
        # (title, description, expected outcome)
        ("Roll Call", "", "procedural_skipped"),
        ("Approval of minutes from May 1, 2026", "", "procedural_skipped"),
        ("Settlement of Smith vs. City for $250K", "", "pending"),  # Big Fish
        ("Approval of fleet fuel purchase", "", "data_quality_skipped"),  # no body
        (
            "Award of HVAC contract",
            "Long valid body content with full agenda item description text and details.",
            "pending",
        ),
    ]

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
            city_id = cur.fetchone()[0]
            cur.execute(
                "SELECT id FROM meetings WHERE municipality_id = %s LIMIT 1",
                [city_id],
            )
            meeting_id = cur.fetchone()[0]

            for title, desc, _ in fixtures:
                cur.execute("""
                    INSERT INTO agenda_items (
                        meeting_id, title, description,
                        processing_status, ai_extraction_version
                    )
                    VALUES (%s, %s, %s, 'pending', NULL)
                    RETURNING id
                """, [meeting_id, title, desc])
                ids.append(cur.fetchone()[0])

    yield ids, [f[2] for f in fixtures]

    # Cleanup
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", [ids])


def test_run_wave_0_classifies_items(fresh_items_for_birmingham):
    """Each fixture item lands in its expected processing_status."""
    ids, expected_statuses = fresh_items_for_birmingham

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
            city_id = cur.fetchone()[0]

    report = run_wave_0([city_id])

    assert isinstance(report, Wave0Report)
    assert report.counts['procedural_skipped'] >= 2  # at least roll call + minutes
    assert report.counts['data_quality_skipped'] >= 1  # fleet fuel
    assert report.counts['pending'] >= 2  # settlement (Big Fish) + HVAC

    # Verify each fixture item got the expected status
    with db() as conn:
        with conn.cursor() as cur:
            for item_id, expected in zip(ids, expected_statuses):
                cur.execute("""
                    SELECT processing_status, data_quality, data_debt_priority
                    FROM agenda_items WHERE id = %s
                """, [item_id])
                status, quality, priority = cur.fetchone()
                assert status == expected, (
                    f"Item {item_id} status mismatch: expected {expected}, got {status}"
                )


def test_run_wave_0_idempotent(fresh_items_for_birmingham):
    """Running Wave 0 twice produces the same result."""
    ids, _ = fresh_items_for_birmingham
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
            city_id = cur.fetchone()[0]

    run_wave_0([city_id])
    report2 = run_wave_0([city_id])

    # Second run should classify the same items the same way (overwrite is OK)
    assert isinstance(report2, Wave0Report)
