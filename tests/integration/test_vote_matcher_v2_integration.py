"""End-to-end test of the v2 substantive matcher against captured fixture data.

Inserts vote 1342 + agenda items into a test database, runs match_votes_for_meeting,
and asserts the expected link appears.
"""

from __future__ import annotations

import pytest

from tests.fixtures.vote_matcher_v2 import (
    VOTE_1342_RAW_TEXT,
    VOTE_1342_MATCH_CONTEXT,
    AGENDA_ITEM_1256,
    DISTRACTOR_AGENDA_ITEMS,
)


@pytest.mark.integration
def test_match_votes_links_vote_1342_to_quitclaim_item():
    """Vote 1342 (Shield Property Solutions, $11,155.25) must link to item 1256.

    Uses the project's local docket_db. Reads the actual `municipalities` row
    for Birmingham (created by migration 002) rather than inserting one; uses
    fixed high-numbered IDs (98026, 991256, etc.) to avoid clashing with any
    real ingested data, and cleans up after itself in a finally block.
    """
    from docket.analysis.vote_matcher import match_votes_for_meeting
    from docket.db import db_cursor

    MEETING_ID = 98026
    VOTE_ID = 991342
    ITEM_OFFSET = 990000  # add to fixture IDs to avoid collisions

    try:
        with db_cursor() as cur:
            cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
            row = cur.fetchone()
            assert row, "Birmingham municipality must be seeded (migration 002)"
            muni_id = row["id"]

            cur.execute(
                """INSERT INTO meetings (id, municipality_id, meeting_date, title, source_url)
                   VALUES (%s, %s, '2025-12-16', 'Regular City Council Meeting', '')
                   ON CONFLICT (id) DO NOTHING""",
                (MEETING_ID, muni_id),
            )
            for item in [AGENDA_ITEM_1256] + DISTRACTOR_AGENDA_ITEMS:
                cur.execute(
                    """INSERT INTO agenda_items (id, meeting_id, item_number, title, description, is_consent)
                       VALUES (%s, %s, %s, %s, %s, FALSE)
                       ON CONFLICT (id) DO NOTHING""",
                    (item["id"] + ITEM_OFFSET, MEETING_ID, item["item_number"],
                     item["title"], item.get("description", "")),
                )
            cur.execute(
                """INSERT INTO votes
                    (id, meeting_id, source, raw_text, match_context, yeas, nays, abstentions, result)
                   VALUES (%s, %s, 'minutes_text', %s, %s, 7, 0, 0, 'passed')
                   ON CONFLICT (id) DO NOTHING""",
                (VOTE_ID, MEETING_ID, VOTE_1342_RAW_TEXT, VOTE_1342_MATCH_CONTEXT),
            )

        # Run the matcher
        result = match_votes_for_meeting(MEETING_ID)
        assert result["substantive_matched"] >= 1, (
            f"Expected at least one substantive match, got {result}"
        )

        # Assert the expected link
        with db_cursor() as cur:
            cur.execute(
                """SELECT agenda_item_id, match_method, match_confidence
                   FROM vote_agenda_items WHERE vote_id = %s AND is_active = TRUE""",
                (VOTE_ID,),
            )
            rows = cur.fetchall()

        linked_item_ids = {r["agenda_item_id"] for r in rows}
        expected_item_id = AGENDA_ITEM_1256["id"] + ITEM_OFFSET
        assert expected_item_id in linked_item_ids, (
            f"Expected link to item {expected_item_id} (Shield Property Solutions); "
            f"got links to {linked_item_ids}"
        )

        # Distractors must NOT be linked
        distractor_ids = {it["id"] + ITEM_OFFSET for it in DISTRACTOR_AGENDA_ITEMS}
        assert not (linked_item_ids & distractor_ids), (
            f"Distractor items got linked: {linked_item_ids & distractor_ids}"
        )
    finally:
        # Cleanup — order matters (FK chain)
        with db_cursor() as cur:
            cur.execute("DELETE FROM vote_agenda_items WHERE vote_id = %s", (VOTE_ID,))
            cur.execute("DELETE FROM votes WHERE id = %s", (VOTE_ID,))
            cur.execute("DELETE FROM agenda_items WHERE meeting_id = %s", (MEETING_ID,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (MEETING_ID,))
