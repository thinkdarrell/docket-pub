"""Integration tests for migration 015_search_vector_v3.

Verifies that the upgraded trigger function correctly indexes:
- headline (weight A, same tier as title)
- why_it_matters (weight B, same tier as description)
- extracted_facts->>'counterparty' (weight B — vendor names)
- extracted_facts->'location'->>'address' (weight C)
- extracted_facts->'location'->>'neighborhood' (weight C)
- extracted_facts->'location'->>'parcel_id' (weight C)
- Pre-v3 items (title only) still work
- Weight ordering: headline (A) ranks above JSONB-location (C) for same keyword
"""

from __future__ import annotations

import json

import pytest

from docket.db import db
from docket.migrations.runner import apply_migrations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_any_meeting_id(cur) -> int:
    cur.execute("SELECT id FROM meetings LIMIT 1")
    row = cur.fetchone()
    if row is None:
        pytest.skip("No meetings in DB — run migrations and seed data first")
    return row[0]


def _insert_item(cur, meeting_id: int, **kwargs) -> int:
    """Insert a minimal agenda_item and return its id."""
    fields = {"title": "Test item", "description": None, "summary": None}
    fields.update(kwargs)

    # Build a dynamic INSERT for whichever columns are provided
    col_names = list(fields.keys())
    placeholders = ", ".join(["%s"] * len(col_names))
    columns = ", ".join(col_names)

    cur.execute(
        f"""
        INSERT INTO agenda_items (meeting_id, {columns})
        VALUES (%s, {placeholders})
        RETURNING id
        """,
        [meeting_id] + list(fields.values()),
    )
    return cur.fetchone()[0]


def _matches(cur, item_id: int, query_term: str) -> bool:
    """Return True if the item's search_vector matches the tsquery term."""
    cur.execute(
        """
        SELECT search_vector @@ to_tsquery('english', %s)
        FROM agenda_items
        WHERE id = %s
        """,
        [query_term, item_id],
    )
    row = cur.fetchone()
    return bool(row and row[0])


# ---------------------------------------------------------------------------
# Fixtures / setup
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def apply_all_migrations():
    """Ensure all migrations including 015 are applied before each test."""
    with db() as conn:
        apply_migrations(conn)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_trigger_includes_headline():
    """Trigger indexes headline at weight A; 'hvac' should match."""
    with db() as conn, conn.cursor() as cur:
        meeting_id = _get_any_meeting_id(cur)
        item_id = _insert_item(
            cur,
            meeting_id,
            title="Council awards contract",
            headline="Council awards $4.2M HVAC contract",
        )
        try:
            assert _matches(cur, item_id, "hvac"), (
                "search_vector should match 'hvac' from headline"
            )
        finally:
            cur.execute("DELETE FROM agenda_items WHERE id = %s", [item_id])


def test_trigger_includes_why_it_matters():
    """Trigger indexes why_it_matters at weight B; 'utility' should match."""
    with db() as conn, conn.cursor() as cur:
        meeting_id = _get_any_meeting_id(cur)
        item_id = _insert_item(
            cur,
            meeting_id,
            title="Rate schedule amendment",
            why_it_matters="Higher utility bills for residents in Wards 4-7",
        )
        try:
            assert _matches(cur, item_id, "utility"), (
                "search_vector should match 'utility' from why_it_matters"
            )
        finally:
            cur.execute("DELETE FROM agenda_items WHERE id = %s", [item_id])


def test_trigger_includes_counterparty_from_jsonb():
    """Trigger indexes extracted_facts->>'counterparty' at weight B."""
    with db() as conn, conn.cursor() as cur:
        meeting_id = _get_any_meeting_id(cur)
        facts = json.dumps({"counterparty": "Southeastern Sealcoating"})
        item_id = _insert_item(
            cur,
            meeting_id,
            title="Street resurfacing contract",
            extracted_facts=facts,
        )
        try:
            assert _matches(cur, item_id, "Southeastern"), (
                "search_vector should match vendor name from extracted_facts.counterparty"
            )
            assert _matches(cur, item_id, "Sealcoating"), (
                "search_vector should match 'Sealcoating' from extracted_facts.counterparty"
            )
        finally:
            cur.execute("DELETE FROM agenda_items WHERE id = %s", [item_id])


def test_trigger_includes_address_from_jsonb():
    """Trigger indexes extracted_facts->'location'->>'address' at weight C."""
    with db() as conn, conn.cursor() as cur:
        meeting_id = _get_any_meeting_id(cur)
        facts = json.dumps({"location": {"address": "5th Avenue South"}})
        item_id = _insert_item(
            cur,
            meeting_id,
            title="Property demolition",
            extracted_facts=facts,
        )
        try:
            assert _matches(cur, item_id, "avenue"), (
                "search_vector should match 'avenue' from extracted_facts.location.address"
            )
        finally:
            cur.execute("DELETE FROM agenda_items WHERE id = %s", [item_id])


def test_trigger_includes_neighborhood_from_jsonb():
    """Trigger indexes extracted_facts->'location'->>'neighborhood' at weight C."""
    with db() as conn, conn.cursor() as cur:
        meeting_id = _get_any_meeting_id(cur)
        facts = json.dumps({"location": {"neighborhood": "Highland Park"}})
        item_id = _insert_item(
            cur,
            meeting_id,
            title="Rezoning request",
            extracted_facts=facts,
        )
        try:
            assert _matches(cur, item_id, "highland"), (
                "search_vector should match 'highland' from extracted_facts.location.neighborhood"
            )
        finally:
            cur.execute("DELETE FROM agenda_items WHERE id = %s", [item_id])


def test_trigger_includes_parcel_id_from_jsonb():
    """Trigger indexes extracted_facts->'location'->>'parcel_id' at weight C."""
    with db() as conn, conn.cursor() as cur:
        meeting_id = _get_any_meeting_id(cur)
        # Parcel IDs are alphanumeric tokens — use a distinctive one
        facts = json.dumps({"location": {"parcel_id": "PARCEL007XYZ"}})
        item_id = _insert_item(
            cur,
            meeting_id,
            title="Blight abatement",
            extracted_facts=facts,
        )
        try:
            # to_tsvector lowercases and stemming may strip some suffixes,
            # but a plain token match on the full parcel string should work
            # when queried as a plain tsquery token (lowercased)
            assert _matches(cur, item_id, "parcel007xyz"), (
                "search_vector should match parcel_id token from extracted_facts"
            )
        finally:
            cur.execute("DELETE FROM agenda_items WHERE id = %s", [item_id])


def test_trigger_unchanged_for_pre_v3_rows():
    """Pre-v3 items (title only, no headline/extracted_facts) still match on title."""
    with db() as conn, conn.cursor() as cur:
        meeting_id = _get_any_meeting_id(cur)
        item_id = _insert_item(
            cur,
            meeting_id,
            title="Procurement of fire department equipment",
        )
        try:
            assert _matches(cur, item_id, "procurement"), (
                "Legacy (pre-v3) items should still match on title"
            )
            assert _matches(cur, item_id, "fire"), (
                "Legacy items should match any title token"
            )
        finally:
            cur.execute("DELETE FROM agenda_items WHERE id = %s", [item_id])


def test_search_ranking_uses_weights():
    """Headline-match (weight A) ranks higher than JSONB location-match (weight C) for same keyword."""
    with db() as conn, conn.cursor() as cur:
        meeting_id = _get_any_meeting_id(cur)
        # item_a: keyword 'sealcoating' in headline (weight A)
        item_a = _insert_item(
            cur,
            meeting_id,
            title="Street maintenance contract",
            headline="Council approves sealcoating contract",
        )
        # item_b: keyword 'sealcoating' in extracted_facts location neighborhood (weight C)
        facts = json.dumps({"location": {"neighborhood": "Sealcoating District"}})
        item_b = _insert_item(
            cur,
            meeting_id,
            title="Neighborhood improvement grant",
            extracted_facts=facts,
        )
        try:
            cur.execute(
                """
                SELECT id, ts_rank(search_vector, to_tsquery('english', 'sealcoat')) AS rank
                FROM agenda_items
                WHERE id IN (%s, %s)
                  AND search_vector @@ to_tsquery('english', 'sealcoat')
                ORDER BY rank DESC
                """,
                [item_a, item_b],
            )
            rows = cur.fetchall()
            assert len(rows) == 2, "Both items should match 'sealcoat' (stemmed)"
            top_id = rows[0][0]
            assert top_id == item_a, (
                f"Headline-match (item {item_a}, weight A) should outrank "
                f"neighborhood-match (item {item_b}, weight C); got top_id={top_id}"
            )
        finally:
            cur.execute("DELETE FROM agenda_items WHERE id IN (%s, %s)", [item_a, item_b])
