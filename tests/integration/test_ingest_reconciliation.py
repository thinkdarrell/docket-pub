"""Integration tests for _upsert_meetings event-* → clip_id reconciliation.

When a meeting transitions from Granicus's #upcoming table to #archive,
its identifier flips from event_id to clip_id. The adapter emits the
two as distinct RawMeetings on successive ingest ticks. This service
must match them on (municipality, date, normalize_title(title)) and
upgrade the existing event-* row's external_id in place — rather than
inserting a duplicate.

Dual-tier match guard per spec:
  1. Exact match on normalize_title — preferred path.
  2. Date-only fallback — only when exactly one event-* row exists
     for that municipality on that date. Otherwise refuse to guess
     (log warning, insert new row).
"""

from datetime import date

import pytest

from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.models.protocol import RawMeeting
from docket.services.ingest import _upsert_meetings


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Integration tests require local DB; will not run against Railway prod",
)


TEST_SLUG = "test_recon_uppr"


@pytest.fixture
def muni_id():
    """Seed a unique test municipality. Cleans meetings before + after."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO municipalities (slug, name, state, adapter_class, adapter_config, active)
            VALUES (%s, 'Test Reconciliation', 'AL', 'GranicusAdapter',
                    '{"view_id": 1, "base_url": "https://example.com"}'::jsonb, TRUE)
            ON CONFLICT (slug) DO UPDATE SET active = TRUE
            RETURNING id
            """,
            (TEST_SLUG,),
        )
        mid = cur.fetchone()[0]
        cur.execute("DELETE FROM meetings WHERE municipality_id = %s", (mid,))
    yield mid
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE municipality_id = %s", (mid,))


def _meeting(external_id: str, title: str, meeting_date: date = date(2026, 5, 19)) -> RawMeeting:
    """Build a RawMeeting fixture; agenda/source URLs derived from external_id."""
    base = "https://bhamal.granicus.com"
    if external_id.startswith("event-"):
        event_id = external_id.removeprefix("event-")
        url = f"{base}/AgendaViewer.php?view_id=2&event_id={event_id}"
        return RawMeeting(
            external_id=external_id,
            municipality_slug=TEST_SLUG,
            title=title,
            meeting_date=meeting_date,
            meeting_type="council",
            agenda_url=url,
            minutes_url=None,
            video_url=None,
            source_url=url,
        )
    return RawMeeting(
        external_id=external_id,
        municipality_slug=TEST_SLUG,
        title=title,
        meeting_date=meeting_date,
        meeting_type="council",
        agenda_url=f"{base}/AgendaViewer.php?view_id=2&clip_id={external_id}",
        minutes_url=None,
        video_url=f"{base}/MediaPlayer.php?view_id=2&clip_id={external_id}",
        source_url=f"{base}/player/clip/{external_id}?view_id=2",
    )


def _meeting_rows(muni_id: int) -> list[tuple]:
    """Return all (external_id, title, meeting_date) rows for a muni, sorted."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT external_id, title, meeting_date FROM meetings "
            "WHERE municipality_id = %s ORDER BY external_id",
            (muni_id,),
        )
        return [(r["external_id"], r["title"], r["meeting_date"]) for r in cur.fetchall()]


class TestBaselineBehavior:
    """Existing _upsert_meetings behavior preserved (no reconciliation triggered)."""

    def test_event_insert_creates_row(self, muni_id):
        inserted, updated = _upsert_meetings(
            muni_id, [_meeting("event-2692", "Regular City Council Meeting")]
        )
        assert (inserted, updated) == (1, 0)
        assert _meeting_rows(muni_id) == [
            ("event-2692", "Regular City Council Meeting", date(2026, 5, 19))
        ]

    def test_clip_insert_with_no_event_creates_row(self, muni_id):
        inserted, updated = _upsert_meetings(
            muni_id, [_meeting("1980", "Regular City Council Meeting")]
        )
        assert (inserted, updated) == (1, 0)

    def test_event_row_reupsert_is_update(self, muni_id):
        """Re-upserting an event-* row updates fields, not insert."""
        _upsert_meetings(muni_id, [_meeting("event-2692", "Regular City Council Meeting")])
        inserted, updated = _upsert_meetings(
            muni_id, [_meeting("event-2692", "Regular City Council Meeting - Updated")]
        )
        assert (inserted, updated) == (0, 1)
        rows = _meeting_rows(muni_id)
        assert rows == [("event-2692", "Regular City Council Meeting - Updated", date(2026, 5, 19))]


class TestReconciliationUpgrade:
    """The core upgrade path: event-* → clip_id when the meeting is recorded."""

    def test_exact_title_match_upgrades_in_place(self, muni_id):
        """Primary case: same date, same normalized title → upgrade."""
        _upsert_meetings(muni_id, [_meeting("event-2692", "Regular City Council Meeting")])
        inserted, updated = _upsert_meetings(
            muni_id, [_meeting("1981", "Regular City Council Meeting")]
        )
        assert (inserted, updated) == (0, 1)
        # Single row, external_id flipped from event-2692 → 1981
        assert _meeting_rows(muni_id) == [
            ("1981", "Regular City Council Meeting", date(2026, 5, 19))
        ]

    def test_minor_title_drift_still_matches(self, muni_id):
        """normalize_title handles case/whitespace/punctuation drift."""
        _upsert_meetings(muni_id, [_meeting("event-2692", "Regular City Council Meeting")])
        inserted, updated = _upsert_meetings(
            muni_id, [_meeting("1981", "Regular  City Council Meeting.")]
        )
        assert (inserted, updated) == (0, 1)
        # Upgraded; title stored is the new clip-row title verbatim
        rows = _meeting_rows(muni_id)
        assert rows[0][0] == "1981"
        assert "Regular" in rows[0][1]

    def test_cancelled_suffix_stripped_for_match(self, muni_id):
        """An event-* row with '- Cancelled' suffix still matches its
        clip arrival (suffix is stripped in normalize_title)."""
        _upsert_meetings(
            muni_id,
            [_meeting("event-2692", "Regular City Council Meeting - Cancelled (Next Reg)")],
        )
        inserted, updated = _upsert_meetings(
            muni_id, [_meeting("1981", "Regular City Council Meeting")]
        )
        assert (inserted, updated) == (0, 1)


class TestDateOnlyFallback:
    """Per spec: when exact title match fails, date-only fallback is
    permitted *only* if exactly one event-* row exists on that date."""

    def test_single_event_row_different_title_upgrades_via_fallback(self, muni_id):
        """Title was edited between ticks but exactly one event-* row
        for that date → fall back to date-only match."""
        _upsert_meetings(muni_id, [_meeting("event-2692", "Special Called Meeting")])
        inserted, updated = _upsert_meetings(
            muni_id, [_meeting("1981", "Regular City Council Meeting")]
        )
        # Fallback fires — the single event-* row is upgraded
        assert (inserted, updated) == (0, 1)
        assert _meeting_rows(muni_id) == [
            ("1981", "Regular City Council Meeting", date(2026, 5, 19))
        ]


class TestRefuseToGuess:
    """Per spec: more than one event-* row on the same date with no
    exact-title match → refuse to guess. Log + insert as new row."""

    def test_two_event_rows_one_title_match_picks_correct_one(self, muni_id):
        """Two event rows on the same date — exact title match still works."""
        _upsert_meetings(muni_id, [
            _meeting("event-100", "Pre-Council Meeting"),
            _meeting("event-101", "Regular City Council Meeting"),
        ])
        inserted, updated = _upsert_meetings(
            muni_id, [_meeting("1981", "Regular City Council Meeting")]
        )
        assert (inserted, updated) == (0, 1)
        external_ids = sorted(r[0] for r in _meeting_rows(muni_id))
        # event-100 untouched; event-101 upgraded to 1981
        assert external_ids == ["1981", "event-100"]

    def test_two_event_rows_no_title_match_inserts_new(self, muni_id):
        """Two event-* rows same date, archive title matches neither —
        refuse to guess. Insert new row (cosmetic duplicate is recoverable;
        mis-mapping is not)."""
        _upsert_meetings(muni_id, [
            _meeting("event-100", "Pre-Council Meeting"),
            _meeting("event-101", "Special Called Meeting"),
        ])
        inserted, updated = _upsert_meetings(
            muni_id, [_meeting("1981", "Regular City Council Meeting")]
        )
        assert (inserted, updated) == (1, 0)
        external_ids = sorted(r[0] for r in _meeting_rows(muni_id))
        # Three rows — both event-* preserved, plus the new clip
        assert external_ids == ["1981", "event-100", "event-101"]


class TestScopingGuards:
    """Reconciliation must respect (muni, date) scope."""

    def test_event_row_on_different_date_not_upgraded(self, muni_id):
        """Date scope: an event-* row on a different date must not be
        upgraded by a clip arrival on this date."""
        _upsert_meetings(
            muni_id,
            [_meeting("event-2692", "Regular City Council Meeting", meeting_date=date(2026, 5, 12))],
        )
        inserted, updated = _upsert_meetings(
            muni_id,
            [_meeting("1981", "Regular City Council Meeting", meeting_date=date(2026, 5, 19))],
        )
        # event-2692 (5/12) is untouched; 1981 (5/19) is a fresh insert
        assert (inserted, updated) == (1, 0)
        external_ids = sorted(r[0] for r in _meeting_rows(muni_id))
        assert external_ids == ["1981", "event-2692"]

    def test_existing_clip_takes_precedence_over_reconciliation(self, muni_id):
        """If a row with the exact clip_id external_id already exists,
        UPDATE it directly — do not attempt reconciliation. (Edge case:
        an orphan event-* row from a pre-reconciliation deploy should
        be left in place; admin can clean up manually.)"""
        # Seed both rows directly via SQL (bypassing _upsert_meetings,
        # which would normally reconcile and prevent this state).
        with db() as conn, conn.cursor() as cur:
            for ext_id in ("event-2692", "1981"):
                cur.execute(
                    """
                    INSERT INTO meetings (
                        municipality_id, external_id, title, meeting_date,
                        meeting_type, agenda_url, source_url
                    ) VALUES (%s, %s, 'Regular City Council Meeting', %s,
                              'council', 'http://x', 'http://x')
                    """,
                    (muni_id, ext_id, date(2026, 5, 19)),
                )

        # Adapter re-emits the clip row — should UPDATE it, leave event alone
        inserted, updated = _upsert_meetings(
            muni_id, [_meeting("1981", "Regular City Council Meeting")]
        )
        assert (inserted, updated) == (0, 1)
        external_ids = sorted(r[0] for r in _meeting_rows(muni_id))
        assert external_ids == ["1981", "event-2692"]


class TestSameTickTransition:
    """Defensive: if the adapter ever returns BOTH event-* and clip rows
    in the same ingest tick (shouldn't happen with Granicus, but safe to
    verify), the reconciliation still yields a single row."""

    def test_event_and_clip_in_same_tick_yield_one_row(self, muni_id):
        """Reconciliation must read-its-own-writes within one transaction."""
        inserted, updated = _upsert_meetings(muni_id, [
            _meeting("event-2692", "Regular City Council Meeting"),
            _meeting("1981", "Regular City Council Meeting"),
        ])
        # event-2692 INSERTed, then 1981 reconciles and upgrades it
        assert (inserted, updated) == (1, 1)
        assert _meeting_rows(muni_id) == [
            ("1981", "Regular City Council Meeting", date(2026, 5, 19))
        ]
