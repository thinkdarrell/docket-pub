# tests/unit/test_query_coverage.py
"""Unit tests for editorial coverage read helpers."""
from __future__ import annotations

from datetime import datetime

from docket.models.coverage import CoverageEntry, Outlet


def test_coverage_entry_display_byline_uses_snapshot_when_set():
    entry = CoverageEntry(
        id=1, kind='note', status='published', source='manual',
        body='test', partner_credit=None,
        outlet_id=None, external_url=None, headline=None,
        reporter_byline=None, excerpt=None, article_published_at=None,
        author_id=1, byline='Darrell Nance',
        created_at=datetime.now(), updated_at=datetime.now(),
        published_at=datetime.now(), featured_until=None,
        author_display_name='changed-after-publish', author_username='darrell',
    )
    assert entry.display_byline() == 'Darrell Nance'


def test_coverage_entry_display_byline_falls_back_to_display_name_when_null():
    entry = CoverageEntry(
        id=1, kind='note', status='draft', source='manual',
        body='test', partner_credit=None,
        outlet_id=None, external_url=None, headline=None,
        reporter_byline=None, excerpt=None, article_published_at=None,
        author_id=1, byline=None,
        created_at=datetime.now(), updated_at=datetime.now(),
        published_at=None, featured_until=None,
        author_display_name='Darrell Nance', author_username='darrell',
    )
    assert entry.display_byline() == 'Darrell Nance'


def test_coverage_entry_display_byline_falls_back_to_username_when_no_display_name():
    entry = CoverageEntry(
        id=1, kind='note', status='draft', source='manual',
        body='test', partner_credit=None,
        outlet_id=None, external_url=None, headline=None,
        reporter_byline=None, excerpt=None, article_published_at=None,
        author_id=1, byline=None,
        created_at=datetime.now(), updated_at=datetime.now(),
        published_at=None, featured_until=None,
        author_display_name=None, author_username='darrell',
    )
    assert entry.display_byline() == 'darrell'
