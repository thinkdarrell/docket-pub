"""Integration tests for `_backfill_video_timestamps`.

When a meeting's items were inserted from the pre-recording agenda PDF
(no video timestamps), the items need to be enriched with timestamps
after the meeting is recorded and reconciled to a clip_id. This test
verifies the backfill path.

Match strategy: extract `ITEM N` from each MediaPlayer index-point's
title and UPDATE existing agenda_items.video_timestamp_seconds where
item_number matches. Idempotent — second call is a cheap no-op.
"""

from datetime import date
from unittest.mock import MagicMock

import pytest

from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.models.protocol import RawAgendaItem, RawMeeting
from docket.services.ingest import (
    _backfill_video_timestamps,
    _ingest_agenda_items,
)


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Integration tests require local DB; will not run against Railway prod",
)


TEST_SLUG = "test_backfill_ts"


@pytest.fixture
def seeded():
    """Seed a clip-id meeting with PDF-derived items (no timestamps)."""
    state: dict = {}
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO municipalities (slug, name, state, adapter_class, adapter_config, active)
            VALUES (%s, 'Test Backfill TS', 'AL', 'GranicusAdapter',
                    '{"view_id": 2, "base_url": "https://bhamal.granicus.com"}'::jsonb, TRUE)
            ON CONFLICT (slug) DO UPDATE SET active = TRUE
            RETURNING id
            """,
            (TEST_SLUG,),
        )
        muni_id = cur.fetchone()[0]
        state["muni_id"] = muni_id

        # Clean any leftover state
        cur.execute("DELETE FROM meetings WHERE municipality_id = %s", (muni_id,))

        # Insert a meeting (post-reconciliation: external_id is clip-id shape,
        # but items came from the pre-recording PDF)
        cur.execute(
            """
            INSERT INTO meetings (
                municipality_id, external_id, title, meeting_date,
                meeting_type, agenda_url, source_url
            ) VALUES (%s, '1981', 'Regular City Council Meeting', %s,
                      'council', 'http://x', 'http://x')
            RETURNING id
            """,
            (muni_id, date(2026, 5, 19)),
        )
        meeting_id = cur.fetchone()[0]
        state["meeting_id"] = meeting_id

        # Insert 3 agenda items (item_number 1, 2, 3) with NULL timestamps —
        # simulating the post-PDF, pre-recording state
        for n in (1, 2, 3):
            cur.execute(
                """
                INSERT INTO agenda_items (
                    meeting_id, external_id, item_number, title,
                    is_consent, video_timestamp_seconds
                ) VALUES (%s, %s, %s, %s, FALSE, NULL)
                """,
                (meeting_id, f"event-2692-{n}", str(n), f"Item {n} body text"),
            )

        # Mark agenda_items_scraped=TRUE so the function takes the backfill path
        cur.execute(
            "INSERT INTO processing_status (meeting_id, agenda_items_scraped, last_processed) "
            "VALUES (%s, TRUE, NOW())",
            (meeting_id,),
        )
    yield state
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE municipality_id = %s", (state["muni_id"],))


def _meeting() -> RawMeeting:
    return RawMeeting(
        external_id="1981",
        municipality_slug=TEST_SLUG,
        title="Regular City Council Meeting",
        meeting_date=date(2026, 5, 19),
        meeting_type="council",
        agenda_url="https://bhamal.granicus.com/AgendaViewer.php?view_id=2&clip_id=1981",
        minutes_url=None,
        video_url="https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=1981",
        source_url="https://bhamal.granicus.com/player/clip/1981?view_id=2",
    )


def _media_item(item_num: int, timestamp: float, position: int) -> RawAgendaItem:
    """Mock a MediaPlayer index-point. Title contains `ITEM N` so the
    backfill matcher can extract the real item number."""
    return RawAgendaItem(
        external_id=f"clip1981-{position}",
        meeting_external_id="1981",
        item_number=str(position),  # MediaPlayer uses position-in-list, not agenda #
        title=f"ITEM {item_num} - Some agenda body text",
        description=None,
        section=None,
        is_consent=False,
        sponsor=None,
        video_timestamp_seconds=timestamp,
    )


def _ts_by_item(meeting_id: int) -> dict[str, float | None]:
    """Snapshot agenda_items video_timestamp_seconds keyed by item_number."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT item_number, video_timestamp_seconds FROM agenda_items "
            "WHERE meeting_id = %s",
            (meeting_id,),
        )
        return {r["item_number"]: r["video_timestamp_seconds"] for r in cur.fetchall()}


class TestBackfillUpdatesTimestamps:
    """Core path: MediaPlayer items match by extracted ITEM N → UPDATE."""

    def test_all_three_items_get_timestamps(self, seeded):
        # Adapter returns 3 MediaPlayer items, one per agenda item
        adapter = MagicMock()
        adapter.fetch_agenda_items.return_value = [
            _media_item(item_num=1, timestamp=10.0, position=1),
            _media_item(item_num=2, timestamp=50.0, position=2),
            _media_item(item_num=3, timestamp=120.0, position=3),
        ]
        updated = _backfill_video_timestamps(adapter, seeded["meeting_id"], _meeting())
        assert updated == 3
        ts = _ts_by_item(seeded["meeting_id"])
        assert ts == {"1": 10.0, "2": 50.0, "3": 120.0}

    def test_partial_match_only_updates_what_matches(self, seeded):
        """If MediaPlayer has timestamps for items 1 and 3 but not 2 (e.g.,
        item 2 was withdrawn during the meeting), 1 and 3 still backfill."""
        adapter = MagicMock()
        adapter.fetch_agenda_items.return_value = [
            _media_item(item_num=1, timestamp=10.0, position=1),
            _media_item(item_num=3, timestamp=120.0, position=2),
        ]
        updated = _backfill_video_timestamps(adapter, seeded["meeting_id"], _meeting())
        assert updated == 2
        ts = _ts_by_item(seeded["meeting_id"])
        assert ts == {"1": 10.0, "2": None, "3": 120.0}

    def test_idempotent_second_call_no_op(self, seeded):
        """Running backfill twice in a row doesn't double-update or fetch
        from the adapter on the second call (null_count is 0)."""
        adapter = MagicMock()
        adapter.fetch_agenda_items.return_value = [
            _media_item(item_num=1, timestamp=10.0, position=1),
            _media_item(item_num=2, timestamp=50.0, position=2),
            _media_item(item_num=3, timestamp=120.0, position=3),
        ]
        first = _backfill_video_timestamps(adapter, seeded["meeting_id"], _meeting())
        assert first == 3
        # Reset mock so we can assert the second call doesn't touch the adapter
        adapter.fetch_agenda_items.reset_mock()
        second = _backfill_video_timestamps(adapter, seeded["meeting_id"], _meeting())
        assert second == 0
        adapter.fetch_agenda_items.assert_not_called()


class TestBackfillEdgeCases:
    def test_no_media_items_returns_zero(self, seeded):
        """If the MediaPlayer fetch returns no items (e.g., page didn't load
        the way we expected), backfill is a no-op rather than crashing."""
        adapter = MagicMock()
        adapter.fetch_agenda_items.return_value = []
        result = _backfill_video_timestamps(adapter, seeded["meeting_id"], _meeting())
        assert result == 0
        ts = _ts_by_item(seeded["meeting_id"])
        # Nothing changed
        assert all(v is None for v in ts.values())

    def test_media_items_without_item_n_in_title_dont_match(self, seeded):
        """Procedural items like 'Roll Call' don't have 'ITEM N' in the title.
        Backfill skips them rather than guessing."""
        adapter = MagicMock()
        adapter.fetch_agenda_items.return_value = [
            RawAgendaItem(
                external_id="clip1981-0",
                meeting_external_id="1981",
                item_number="1",
                title="Roll Call",  # No "ITEM N" pattern
                description=None,
                section=None,
                is_consent=False,
                sponsor=None,
                video_timestamp_seconds=5.0,
            )
        ]
        result = _backfill_video_timestamps(adapter, seeded["meeting_id"], _meeting())
        assert result == 0


class TestIngestAgendaItemsRoutesToBackfill:
    """`_ingest_agenda_items` with already_scraped=TRUE on a clip-id meeting
    should route to backfill."""

    def test_already_scraped_clip_meeting_triggers_backfill(self, seeded):
        adapter = MagicMock()
        adapter.fetch_agenda_items.return_value = [
            _media_item(item_num=1, timestamp=10.0, position=1),
        ]
        # The meeting is already_scraped=TRUE and external_id is clip-shape
        # (not event-*), so we should take the backfill path
        updated = _ingest_agenda_items(seeded["muni_id"], adapter, _meeting())
        assert updated == 1
        # Adapter was called (to fetch MediaPlayer items)
        adapter.fetch_agenda_items.assert_called_once()
