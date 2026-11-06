"""Integration tests for `_backfill_video_timestamps`.

When a meeting's items were inserted from the pre-recording agenda PDF
(no video timestamps), the items need to be enriched with timestamps
after the meeting is recorded and reconciled to a clip_id. This test
verifies the backfill path.

Match strategy: extract `ITEM N` from each MediaPlayer index-point's
title and UPDATE existing agenda_items.video_timestamp_seconds where
item_number matches. Idempotent — second call is a cheap no-op.

The same pass writes the index point's Granicus chapter id over an id
that is not one (`TestBackfillWritesChapterIds`), and
`correct_chapter_ids` runs it for the meetings the precheck never
fetches again (`TestCorrectChapterIds`).
"""

import logging
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


    def test_unnumbered_item_does_not_force_a_refetch(self, seeded):
        """The minutes-approval line has no item number, so it can never be
        matched to a MediaPlayer index point. It must not keep the precheck
        from short-circuiting, or every ingest run re-fetches the page."""
        adapter = MagicMock()
        adapter.fetch_agenda_items.return_value = [
            _media_item(item_num=1, timestamp=10.0, position=1),
            _media_item(item_num=2, timestamp=50.0, position=2),
            _media_item(item_num=3, timestamp=120.0, position=3),
        ]
        assert _backfill_video_timestamps(adapter, seeded["meeting_id"], _meeting()) == 3
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agenda_items (meeting_id, external_id, item_number, title, is_consent)
                   VALUES (%s, '1981-minutes-approval', NULL,
                           'APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3 – 24, 2026', FALSE)""",
                (seeded["meeting_id"],),
            )
            conn.commit()
        adapter.fetch_agenda_items.reset_mock()

        assert _backfill_video_timestamps(adapter, seeded["meeting_id"], _meeting()) == 0
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


# ---------------------------------------------------------------------------
# The chapter id is written with the timestamp
# ---------------------------------------------------------------------------
#
# A real MediaPlayer index point carries the Granicus chapter id in `data-id`,
# all digits, and the adapter hands it over as the point's external_id. The
# tests above keep mock ids such as `clip1981-1`, which are not chapter ids,
# so their items keep the ids the agenda PDF gave them.

PLAYER = "https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id="


def _point(item_num: int, timestamp: float, external_id: str) -> RawAgendaItem:
    """A MediaPlayer index point titled `ITEM N`, carrying `external_id`."""
    return RawAgendaItem(
        external_id=external_id,
        meeting_external_id="1981",
        item_number="1",  # the player's position in its list; never read by the backfill
        title=f"ITEM {item_num} - Some agenda body text",
        description=None,
        section=None,
        is_consent=False,
        sponsor=None,
        video_timestamp_seconds=timestamp,
    )


def _add_item(meeting_id: int, external_id: str | None, item_number: str | None,
              timestamp: float | None = None) -> int:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO agenda_items (meeting_id, external_id, item_number, title,
                                         is_consent, video_timestamp_seconds)
               VALUES (%s, %s, %s, %s, FALSE, %s) RETURNING id""",
            (meeting_id, external_id, item_number, f"Item {item_number} body text", timestamp),
        )
        return cur.fetchone()[0]


def _add_meeting(muni_id: int, external_id: str, meeting_date: date,
                 items: list[tuple[str | None, str | None, float | None]]) -> int:
    """Insert a meeting and its items, each `(external_id, item_number, timestamp)`."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, external_id, title, meeting_date,
                                     meeting_type, agenda_url, video_url, source_url)
               VALUES (%s, %s, 'Regular City Council Meeting', %s, 'council',
                       'http://x', %s, 'http://x')
               RETURNING id""",
            (muni_id, external_id, meeting_date, PLAYER + external_id),
        )
        meeting_id = cur.fetchone()[0]
    for item_external_id, item_number, timestamp in items:
        _add_item(meeting_id, item_external_id, item_number, timestamp)
    return meeting_id


def _set(meeting_id: int, item_number: str, **columns) -> None:
    """Set columns of the meeting's item(s) numbered `item_number`."""
    assignments = ", ".join(f"{name} = %s" for name in columns)
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE agenda_items SET {assignments} WHERE meeting_id = %s AND item_number = %s",
            (*columns.values(), meeting_id, item_number),
        )


def _rows(meeting_id: int) -> list[tuple[str | None, str | None, float | None]]:
    """The meeting's items as `(item_number, external_id, timestamp)`, in row order."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT item_number, external_id, video_timestamp_seconds FROM agenda_items "
            "WHERE meeting_id = %s ORDER BY id",
            (meeting_id,),
        )
        return [(r["item_number"], r["external_id"], r["video_timestamp_seconds"])
                for r in cur.fetchall()]


def _messages(caplog, level: int) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.name == "docket.services.ingest" and r.levelno == level]


class TestBackfillWritesChapterIds:
    """An item whose timestamp is filled from the player page gets that cue
    point's chapter id in the same write."""

    def test_numeric_point_ids_fill_the_timestamp_and_the_chapter_id_together(self, seeded, caplog):
        meeting_id = seeded["meeting_id"]
        # 120 items, more than one page of execute_values' default 100: the
        # meeting is still written by one statement, whose row count comes back.
        for n in range(4, 121):
            _add_item(meeting_id, f"event-2692-{n}", str(n))
        adapter = MagicMock()
        adapter.fetch_agenda_items.return_value = (
            [_point(n, n * 10.0, str(371100 + n)) for n in range(1, 121)]
            # A later point that names item 1 again: the first point gives both columns.
            + [_point(1, 5000.0, "379999")]
        )

        with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
            changed = _backfill_video_timestamps(adapter, meeting_id, _meeting())

        assert changed == 120
        assert _rows(meeting_id) == [
            (str(n), str(371100 + n), n * 10.0) for n in range(1, 121)
        ]
        assert _messages(caplog, logging.INFO) == [
            "meeting 1981: 120 video timestamps filled, 120 chapter ids rewritten"
        ]
        assert _messages(caplog, logging.WARNING) == []
        # Nothing but the two columns moved.
        with db_cursor() as cur:
            cur.execute("SELECT title FROM agenda_items WHERE meeting_id = %s AND item_number = '2'",
                        (meeting_id,))
            assert cur.fetchone()["title"] == "Item 2 body text"

        # A second call finds no numbered item without a timestamp and asks nothing.
        adapter.fetch_agenda_items.reset_mock()
        assert _backfill_video_timestamps(adapter, meeting_id, _meeting()) == 0
        adapter.fetch_agenda_items.assert_not_called()

    def test_item_that_has_its_timestamp_gets_its_chapter_id_when_the_pass_runs(self, seeded, caplog):
        meeting_id = seeded["meeting_id"]
        # Items 1 and 2 were cued by an earlier run that wrote no chapter id
        # (item 1 at a second the clerk has since moved; item 2 has no id at
        # all). Item 3 still lacks its timestamp, so the pass runs.
        _set(meeting_id, "1", video_timestamp_seconds=11.0)
        _set(meeting_id, "2", video_timestamp_seconds=50.0, external_id=None)
        adapter = MagicMock()
        adapter.fetch_agenda_items.return_value = [
            _point(1, 10.0, "371101"),
            _point(2, 50.0, "371102"),
            _point(3, 120.0, "371103"),
        ]

        with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
            changed = _backfill_video_timestamps(adapter, meeting_id, _meeting())

        assert changed == 3
        assert _rows(meeting_id) == [
            ("1", "371101", 11.0),   # the stored second is kept; only a NULL is filled
            ("2", "371102", 50.0),
            ("3", "371103", 120.0),
        ]
        assert _messages(caplog, logging.INFO) == [
            "meeting 1981: 1 video timestamps filled, 3 chapter ids rewritten"
        ]

    def test_point_whose_id_is_not_a_chapter_id_fills_the_timestamp_and_leaves_the_id(self, seeded, caplog):
        meeting_id = seeded["meeting_id"]
        before = _rows(meeting_id)
        adapter = MagicMock()
        adapter.fetch_agenda_items.return_value = [
            _point(1, 10.0, "1981-0"),      # the adapter's fallback id for a point with no data-id
            _point(2, 50.0, "371102"),
            _point(3, 120.0, "3711O3"),     # a letter O: not all digits
        ]

        # A dry run computes the same count and writes nothing.
        with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
            assert _backfill_video_timestamps(adapter, meeting_id, _meeting(), dry_run=True) == 3
        assert _rows(meeting_id) == before
        assert _messages(caplog, logging.INFO) == [
            "meeting 1981: 3 video timestamps filled, 1 chapter ids rewritten (dry run, nothing written)"
        ]

        assert _backfill_video_timestamps(adapter, meeting_id, _meeting()) == 3
        assert _rows(meeting_id) == [
            ("1", "event-2692-1", 10.0),
            ("2", "371102", 50.0),
            ("3", "event-2692-3", 120.0),
        ]
        # An id left alone because the point has none to give is not a warning.
        assert _messages(caplog, logging.WARNING) == []

    def test_duplicated_number_and_taken_chapter_id_are_left_alone(self, seeded, caplog):
        meeting_id = seeded["meeting_id"]
        second_two = _add_item(meeting_id, "event-2692-2b", "2")       # item number 2, twice
        _add_item(meeting_id, "371103", None)                          # an un-numbered row holds 371103
        _add_item(meeting_id, "event-2692-4", "4")
        _add_item(meeting_id, "event-2692-5", "5")
        adapter = MagicMock()
        adapter.fetch_agenda_items.return_value = [
            _point(1, 10.0, "371101"),
            _point(2, 50.0, "371102"),
            _point(3, 120.0, "371103"),
            # One chapter id under two item numbers; the point for item 5 comes first.
            _point(5, 200.0, "371150"),
            _point(4, 300.0, "371150"),
        ]

        with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
            changed = _backfill_video_timestamps(adapter, meeting_id, _meeting())   # no UniqueViolation

        assert changed == 6
        expected = [
            ("1", "371101", 10.0),          # the rest of the meeting is still corrected
            ("2", "event-2692-2", 50.0),    # both rows numbered 2 get the timestamp, neither the id
            ("3", "event-2692-3", 120.0),   # 371103 is held by another row
            ("2", "event-2692-2b", 50.0),
            (None, "371103", None),
            ("4", "event-2692-4", 300.0),   # 371150 went to item 5, whose point came first
            ("5", "371150", 200.0),
        ]
        assert _rows(meeting_id) == expected
        assert _messages(caplog, logging.INFO) == [
            "meeting 1981: 6 video timestamps filled, 2 chapter ids rewritten"
        ]
        warnings = _messages(caplog, logging.WARNING)
        assert len(warnings) == 4
        assert sum("chapter id 371102 not written" in w and "item number 2 is on 2 rows" in w
                   for w in warnings) == 2
        assert sum(f"agenda item {second_two} " in w for w in warnings) == 1
        assert sum("chapter id 371103 not written" in w and "another row" in w for w in warnings) == 1
        assert sum("chapter id 371150 not written" in w and "another row" in w for w in warnings) == 1

        # Run again with the precheck skipped: the same ids are left alone
        # again, nothing changes, and nothing raises.
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
            assert _backfill_video_timestamps(adapter, meeting_id, _meeting(), force=True) == 0
        assert _rows(meeting_id) == expected
        assert len(_messages(caplog, logging.WARNING)) == 4
        assert _messages(caplog, logging.INFO) == []


class TestCorrectChapterIds:
    """`correct_chapter_ids` reaches the meetings the ingest precheck never
    fetches again: every numbered item has its timestamp, and some still
    carry an id that is not a chapter id."""

    def test_correct_chapter_ids_visits_only_meetings_with_a_cued_non_chapter_id(
            self, seeded, monkeypatch, capsys):
        from docket.services import ingest

        muni_id = seeded["muni_id"]
        a = seeded["meeting_id"]                        # clip 1981, 2026-05-19
        for n, ts in (("1", 10.0), ("2", 50.0), ("3", 120.0)):
            _set(a, n, video_timestamp_seconds=ts)      # cued, still on agenda-PDF ids
        # Item 2 already holds a chapter id, another than its point's: it is kept.
        older = _add_meeting(muni_id, "1960", date(2026, 4, 1), [
            ("event-2600-1", "1", 15.0), ("371299", "2", 60.0)])
        # Inserted last and dated latest, so "newest first" is not row order.
        # Its one cued item has no id at all, which is also not a chapter id.
        no_id = _add_meeting(muni_id, "1985", date(2026, 5, 21), [(None, "1", 20.0)])
        corrected = _add_meeting(muni_id, "1975", date(2026, 5, 12), [
            ("371301", "1", 10.0), ("371302", "2", 50.0)])
        uncued = _add_meeting(muni_id, "1990", date(2026, 5, 26), [
            ("event-2710-1", "1", None), ("1990-minutes-approval", None, 5.0)])
        upcoming = _add_meeting(muni_id, "event-2720", date(2026, 6, 2), [
            ("event-2720-1", "1", 10.0)])
        with db_cursor() as cur:
            cur.execute("SELECT id FROM municipalities WHERE slug = 'homewood'")
            other_city = cur.fetchone()["id"]
        elsewhere = _add_meeting(other_city, "1981", date(2026, 5, 19), [
            ("event-2692-1", "1", 10.0)])

        points = {
            "1981": [_point(1, 10.0, "371101"), _point(2, 50.0, "371102"), _point(3, 120.0, "371103")],
            "1960": [_point(1, 15.0, "371200"), _point(2, 60.0, "371201")],
            "1985": [_point(1, 20.0, "371401")],
        }
        failing: set[str] = set()

        def fetch(raw_meeting):
            if raw_meeting.external_id in failing:
                raise RuntimeError("player page 503")
            return points[raw_meeting.external_id]

        adapter = MagicMock()
        adapter.fetch_agenda_items.side_effect = fetch
        built = []

        def fake_get_adapter(adapter_class, slug, config):
            built.append((adapter_class, slug, config))
            return adapter

        monkeypatch.setattr(ingest, "get_adapter", fake_get_adapter)

        def fetched() -> list[str]:
            return [c.args[0].external_id for c in adapter.fetch_agenda_items.call_args_list]

        untouched = {m: _rows(m) for m in (corrected, uncued, upcoming, elsewhere)}
        row_a = {"meeting_id": a, "external_id": "1981", "meeting_date": date(2026, 5, 19)}
        row_older = {"meeting_id": older, "external_id": "1960", "meeting_date": date(2026, 4, 1)}
        row_no_id = {"meeting_id": no_id, "external_id": "1985", "meeting_date": date(2026, 5, 21)}
        try:
            # The ingest precheck is unchanged: every numbered item has its
            # timestamp, so an ordinary pass asks Granicus nothing.
            assert _backfill_video_timestamps(adapter, a, _meeting()) == 0
            assert fetched() == []

            from docket.services.ingest import correct_chapter_ids
            from scripts.correct_agenda_chapter_ids import main

            # A dry run lists the three meetings, newest first, and writes nothing.
            before = {m: _rows(m) for m in (a, older, no_id)}
            assert correct_chapter_ids(TEST_SLUG, dry_run=True) == [
                {**row_no_id, "changed": 1, "error": None},
                {**row_a, "changed": 3, "error": None},
                {**row_older, "changed": 1, "error": None},
            ]
            assert {m: _rows(m) for m in (a, older, no_id)} == before
            assert fetched() == ["1985", "1981", "1960"]
            assert built == [("GranicusAdapter", TEST_SLUG,
                              {"view_id": 2, "base_url": "https://bhamal.granicus.com"})]
            raw = adapter.fetch_agenda_items.call_args_list[2].args[0]
            assert raw == RawMeeting(
                external_id="1960", municipality_slug=TEST_SLUG,
                title="Regular City Council Meeting", meeting_date=date(2026, 4, 1),
                meeting_type="council", agenda_url="http://x", minutes_url=None,
                video_url=PLAYER + "1960", source_url="http://x")

            # The limit counts meetings.
            assert correct_chapter_ids(TEST_SLUG, limit=1, dry_run=True) == [
                {**row_no_id, "changed": 1, "error": None}]

            # One meeting whose player page cannot be read does not stop the next.
            failing.add("1981")
            assert correct_chapter_ids(TEST_SLUG, dry_run=True) == [
                {**row_no_id, "changed": 1, "error": None},
                {**row_a, "changed": 0, "error": "RuntimeError: player page 503"},
                {**row_older, "changed": 1, "error": None},
            ]
            capsys.readouterr()
            assert main(["--city", TEST_SLUG, "--dry-run"]) == 1
            assert capsys.readouterr().out.splitlines() == [
                f"meeting {no_id} clip 1985 2026-05-21: 1 rows would change",
                f"meeting {a} clip 1981 2026-05-19: failed (RuntimeError: player page 503)",
                f"meeting {older} clip 1960 2026-04-01: 1 rows would change",
                "3 meetings, 2 rows",
            ]
            failing.clear()

            # The script prints one line per meeting and the totals.
            assert main(["--city", TEST_SLUG, "--dry-run"]) == 0
            assert capsys.readouterr().out.splitlines() == [
                f"meeting {no_id} clip 1985 2026-05-21: 1 rows would change",
                f"meeting {a} clip 1981 2026-05-19: 3 rows would change",
                f"meeting {older} clip 1960 2026-04-01: 1 rows would change",
                "3 meetings, 5 rows",
            ]
            assert main(["--city", TEST_SLUG, "--dry-run", "--limit", "2"]) == 0
            assert capsys.readouterr().out.splitlines()[-1] == "2 meetings, 4 rows"
            assert {m: _rows(m) for m in (a, older, no_id)} == before

            # The real run rewrites.
            adapter.fetch_agenda_items.reset_mock()
            assert main(["--city", TEST_SLUG, "--limit", "1"]) == 0
            assert capsys.readouterr().out.splitlines() == [
                f"meeting {no_id} clip 1985 2026-05-21: 1 rows changed",
                "1 meetings, 1 rows",
            ]
            assert _rows(no_id) == [("1", "371401", 20.0)]
            assert {m: _rows(m) for m in (a, older)} == {m: before[m] for m in (a, older)}
            adapter.fetch_agenda_items.reset_mock()
            assert correct_chapter_ids(TEST_SLUG) == [
                {**row_a, "changed": 3, "error": None},
                {**row_older, "changed": 1, "error": None},
            ]
            assert fetched() == ["1981", "1960"]
            assert _rows(a) == [("1", "371101", 10.0), ("2", "371102", 50.0), ("3", "371103", 120.0)]
            assert _rows(older) == [("1", "371200", 15.0), ("2", "371299", 60.0)]
            assert {m: _rows(m) for m in untouched} == untouched

            # A second run lists no meeting and asks Granicus nothing.
            adapter.fetch_agenda_items.reset_mock()
            assert correct_chapter_ids(TEST_SLUG) == []
            assert fetched() == []
            assert main(["--city", TEST_SLUG]) == 0
            assert capsys.readouterr().out.splitlines() == ["0 meetings, 0 rows"]

            # A city that does not exist is an error, not an empty list.
            with pytest.raises(ValueError, match="no_such_city"):
                correct_chapter_ids("no_such_city")
            assert main(["--city", "no_such_city"]) == 1
            assert capsys.readouterr().out == ""
        finally:
            with db() as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM meetings WHERE id = %s", (elsewhere,))
