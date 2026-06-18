"""Import Better Birmingham weekly Substack summaries as meeting-level coverage.

Each post is one `coverage_entries` row (kind=citation, source=manual,
status=published) linked to the BHM council meeting(s) that week.

Idempotent: re-running skips entries whose (outlet_id, external_url) already
exists. Dry-run by default; pass --commit to persist.

Usage:
    venv/bin/python scripts/import_better_bham_coverage.py            # dry run
    venv/bin/python scripts/import_better_bham_coverage.py --commit   # persist
"""

import argparse
import sys
from datetime import date

import psycopg2

from docket.config import DATABASE_URL

OUTLET = {
    "slug": "better-birmingham",
    "name": "Better Birmingham",
    "homepage": "https://betterbham.substack.com",
}

BYLINE = "Better Birmingham"

CURATOR_USERNAME = "darrell"

# (post_url, published_at, headline, [meeting_id, ...])
POSTS = [
    (
        "https://betterbham.substack.com/p/summary-of-birmingham-city-council-812",
        date(2026, 5, 17),
        "Summary of Birmingham City Council for the Week of 5/18/26",
        [2232],
    ),
    (
        "https://betterbham.substack.com/p/summary-of-birmingham-city-council-ac4",
        date(2026, 5, 11),
        "Summary of Birmingham City Council for the Week of 5/11/26",
        [2231],
    ),
    (
        "https://betterbham.substack.com/p/summary-of-birmingham-city-council-c25",
        date(2026, 5, 4),
        "Summary of Birmingham City Council for the Week of 5/4/26",
        [2222, 2224],
    ),
    (
        "https://betterbham.substack.com/p/summary-of-birmingham-city-council-89d",
        date(2026, 4, 27),
        "Summary of Birmingham City Council for the Week of 4/27/26",
        [1],
    ),
    (
        "https://betterbham.substack.com/p/summary-of-birmingham-city-council-a0f",
        date(2026, 4, 20),
        "Summary of Birmingham City Council for the Week of 4/20/26",
        [3, 2],
    ),
    (
        "https://betterbham.substack.com/p/copy-summary-of-birmingham-city-council",
        date(2026, 4, 13),
        "Summary of Birmingham City Council for the Week of 4/13/26",
        [5, 4],
    ),
    (
        "https://betterbham.substack.com/p/summary-of-birmingham-city-council-8be",
        date(2026, 4, 6),
        "Summary of Birmingham City Council for the Week of 4/6/26",
        [7, 6],
    ),
    (
        "https://betterbham.substack.com/p/summary-of-birmingham-city-council-7ef",
        date(2026, 3, 30),
        "Summary of Birmingham City Council for the Week of 3/30/26",
        [9, 8],
    ),
    (
        "https://betterbham.substack.com/p/summary-of-birmingham-city-council-101",
        date(2026, 3, 22),
        "Summary of Birmingham City Council for the Week of 3/23/26",
        [10],
    ),
    (
        "https://betterbham.substack.com/p/summary-of-birmingham-city-council-2dc",
        date(2026, 3, 8),
        "Summary of Birmingham City Council for the Week of 3/9/26",
        [12],
    ),
]


def upsert_outlet(cur) -> int:
    cur.execute(
        """
        INSERT INTO outlets (slug, name, homepage, is_active)
        VALUES (%(slug)s, %(name)s, %(homepage)s, TRUE)
        ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, homepage = EXCLUDED.homepage
        RETURNING id
        """,
        OUTLET,
    )
    return cur.fetchone()[0]


def existing_coverage_id(cur, outlet_id: int, external_url: str) -> int | None:
    cur.execute(
        "SELECT id FROM coverage_entries WHERE outlet_id = %s AND external_url = %s",
        (outlet_id, external_url),
    )
    row = cur.fetchone()
    return row[0] if row else None


def insert_coverage(
    cur, outlet_id: int, author_id: int, external_url: str, published_at: date, headline: str
) -> int:
    cur.execute(
        """
        INSERT INTO coverage_entries (
            kind, status, source, outlet_id, author_id, external_url, headline,
            byline, article_published_at, published_at
        )
        VALUES ('citation', 'published', 'manual', %s, %s, %s, %s, %s, %s, now())
        RETURNING id
        """,
        (outlet_id, author_id, external_url, headline, BYLINE, published_at),
    )
    return cur.fetchone()[0]


def link_exists(cur, coverage_id: int, meeting_id: int) -> bool:
    cur.execute(
        """
        SELECT 1 FROM coverage_subject_links
        WHERE coverage_id = %s AND subject_type = 'meeting' AND subject_id = %s
        """,
        (coverage_id, meeting_id),
    )
    return cur.fetchone() is not None


def insert_link(cur, coverage_id: int, meeting_id: int) -> None:
    cur.execute(
        """
        INSERT INTO coverage_subject_links (coverage_id, subject_type, subject_id)
        VALUES (%s, 'meeting', %s)
        """,
        (coverage_id, meeting_id),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true", help="persist changes (default: dry run)")
    args = parser.parse_args()

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Verify all referenced meeting IDs exist + belong to Birmingham
    referenced = sorted({mid for _, _, _, mids in POSTS for mid in mids})
    cur.execute(
        """
        SELECT m.id, m.meeting_date, mu.name
        FROM meetings m JOIN municipalities mu ON m.municipality_id = mu.id
        WHERE m.id = ANY(%s)
        """,
        (referenced,),
    )
    found = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    missing = [m for m in referenced if m not in found]
    non_bhm = [m for m, (_, name) in found.items() if name.lower() != "birmingham"]
    if missing or non_bhm:
        print(f"ERROR: missing meeting ids: {missing}", file=sys.stderr)
        print(f"ERROR: non-BHM meeting ids: {non_bhm}", file=sys.stderr)
        return 1

    cur.execute("SELECT id FROM admin_users WHERE username = %s", (CURATOR_USERNAME,))
    row = cur.fetchone()
    if not row:
        print(f"ERROR: admin user {CURATOR_USERNAME!r} not found", file=sys.stderr)
        return 1
    author_id = row[0]

    outlet_id = upsert_outlet(cur)
    print(f"outlet {OUTLET['slug']}: id={outlet_id}")
    print(f"curator {CURATOR_USERNAME!r}: author_id={author_id}")

    created_entries = 0
    skipped_entries = 0
    created_links = 0
    skipped_links = 0

    for external_url, published_at, headline, meeting_ids in POSTS:
        existing = existing_coverage_id(cur, outlet_id, external_url)
        if existing is not None:
            cov_id = existing
            skipped_entries += 1
            print(f"  [skip entry] id={cov_id} {published_at} {headline}")
        else:
            cov_id = insert_coverage(cur, outlet_id, author_id, external_url, published_at, headline)
            created_entries += 1
            print(f"  [+entry]    id={cov_id} {published_at} {headline}")

        for mid in meeting_ids:
            mdate, _ = found[mid]
            if link_exists(cur, cov_id, mid):
                skipped_links += 1
                print(f"      [skip link] meeting={mid} ({mdate})")
            else:
                insert_link(cur, cov_id, mid)
                created_links += 1
                print(f"      [+link]    meeting={mid} ({mdate})")

    print()
    print(f"entries: +{created_entries} created, {skipped_entries} already present")
    print(f"links:   +{created_links} created, {skipped_links} already present")

    if args.commit:
        conn.commit()
        print("COMMITTED.")
    else:
        conn.rollback()
        print("DRY RUN — rolled back. Re-run with --commit to persist.")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
