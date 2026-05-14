# src/docket/models/coverage.py
"""Editorial coverage dataclasses.

Mirrors the row shapes from migration 027. ``display_byline()`` returns
the snapshotted ``byline`` if set (post-publish), else falls back to the
author's live ``display_name`` or ``username`` (drafts).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


CoverageKind = Literal['note', 'citation']
CoverageStatus = Literal['draft', 'proposed', 'published', 'rejected']
CoverageSource = Literal['manual', 'ai_proposal', 'press_scraper']
CoverageSubjectType = Literal['agenda_item', 'meeting', 'council_member', 'badge']


@dataclass(frozen=True)
class Outlet:
    id: int
    slug: str
    name: str
    homepage: str | None
    is_active: bool
    created_at: datetime


@dataclass(frozen=True)
class CoverageSubjectLink:
    subject_type: CoverageSubjectType
    subject_id: int | None
    subject_slug: str | None
    # Optional human-readable label hydrated by the reader for chip rendering.
    label: str | None = None
    # City slug, hydrated for item/meeting/member subjects — None for badge
    # subjects (badges are global; category_landing pages are per-city).
    # Lets the subjects footer template build correct url_for() URLs without
    # a second query per row.
    city_slug: str | None = None


@dataclass(frozen=True)
class CoverageEntry:
    id: int
    kind: CoverageKind
    status: CoverageStatus
    source: CoverageSource

    # Notes-only
    body: str | None
    partner_credit: str | None

    # Citations-only
    outlet_id: int | None
    external_url: str | None
    headline: str | None
    reporter_byline: str | None
    excerpt: str | None
    article_published_at: date | None

    # Authoring & audit
    author_id: int
    byline: str | None  # snapshot-on-publish
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    featured_until: datetime | None

    # Hydrated by the reader (not raw columns):
    author_display_name: str | None = None
    author_username: str | None = None
    outlet_slug: str | None = None
    outlet_name: str | None = None
    subjects: tuple[CoverageSubjectLink, ...] = ()

    def display_byline(self) -> str:
        """Snapshotted byline if set; else author's live display_name or username."""
        if self.byline:
            return self.byline
        return self.author_display_name or self.author_username or 'docket.pub editorial'
