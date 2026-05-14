"""Editorial coverage writer service.

All multi-step writes are wrapped in a single transaction via db_cursor().
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from docket.db import db_cursor


SubjectSpec = tuple[str, int | None, str | None]
# (subject_type, subject_id, subject_slug). Exactly one of subject_id/subject_slug
# is non-None per row, gated by subject_type.


def _validate_subjects(subjects: Iterable[SubjectSpec]) -> list[SubjectSpec]:
    subs = list(subjects)
    if not subs:
        raise ValueError("Coverage entry must attach to at least one subject")
    for st, sid, sslug in subs:
        if st == 'badge':
            if not sslug or sid is not None:
                raise ValueError(f"Badge subject requires slug only: {(st, sid, sslug)}")
        elif st in ('agenda_item', 'meeting', 'council_member'):
            if sid is None or sslug is not None:
                raise ValueError(f"{st} subject requires int id only: {(st, sid, sslug)}")
        else:
            raise ValueError(f"Unknown subject_type: {st!r}")
    return subs


def _insert_subjects(cur, coverage_id: int, subjects: list[SubjectSpec]) -> None:
    for st, sid, sslug in subjects:
        cur.execute(
            """INSERT INTO coverage_subject_links
               (coverage_id, subject_type, subject_id, subject_slug)
               VALUES (%s, %s, %s, %s)""",
            (coverage_id, st, sid, sslug),
        )


def create_note(
    *,
    author_id: int,
    body: str,
    partner_credit: str | None,
    subjects: Iterable[SubjectSpec],
    status: str = 'draft',
    featured_until: datetime | None = None,
) -> int:
    """Create a note. Returns new coverage_entries.id.

    Transactional: entry + all subject_links inserted atomically.
    """
    subs = _validate_subjects(subjects)
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO coverage_entries
               (kind, status, body, partner_credit, author_id, featured_until)
               VALUES ('note', %s, %s, %s, %s, %s)
               RETURNING id""",
            (status, body, partner_credit, author_id, featured_until),
        )
        entry_id = cur.fetchone()['id']
        _insert_subjects(cur, entry_id, subs)
        if status == 'published':
            _set_publish_state(cur, entry_id, author_id)
        return entry_id


def create_citation(
    *,
    author_id: int,
    outlet_id: int,
    external_url: str,
    headline: str,
    reporter_byline: str | None,
    excerpt: str | None,
    article_published_at,
    subjects: Iterable[SubjectSpec],
    status: str = 'draft',
    featured_until: datetime | None = None,
) -> int:
    """Create a citation entry attached to ``subjects``. Atomic insert."""
    subs = _validate_subjects(subjects)
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO coverage_entries
               (kind, status, outlet_id, external_url, headline,
                reporter_byline, excerpt, article_published_at,
                author_id, featured_until)
               VALUES ('citation', %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (status, outlet_id, external_url, headline, reporter_byline,
             excerpt, article_published_at, author_id, featured_until),
        )
        entry_id = cur.fetchone()['id']
        _insert_subjects(cur, entry_id, subs)
        if status == 'published':
            _set_publish_state(cur, entry_id, author_id)
        return entry_id


def _set_publish_state(cur, coverage_id: int, author_id: int) -> None:
    """Populate published_at + byline snapshot for a newly-published entry.

    Idempotent: re-running on an entry that already has a byline keeps it.
    """
    cur.execute(
        """UPDATE coverage_entries
              SET published_at = COALESCE(published_at, NOW()),
                  byline = COALESCE(byline,
                                    (SELECT COALESCE(display_name, username)
                                       FROM admin_users WHERE id = %s))
            WHERE id = %s""",
        (author_id, coverage_id),
    )
