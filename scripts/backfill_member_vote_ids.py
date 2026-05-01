"""Backfill member_votes.council_member_id by fuzzy-matching member_name
against the council_members roster, scoped by meeting date + term dates.

No hardcoded name maps — uses the roster as the source of truth.
Handles OCR variants: "C. Woods", "Woods", "OQuinn" → match against
council_members.name using last-name + first-initial matching.
"""

import re
import psycopg2

from docket.config import DATABASE_URL


def build_name_index(cur):
    """Build a lookup from name variants → council_member_id with term ranges."""
    cur.execute("""
        SELECT id, name, term_start, term_end, municipality_id
        FROM council_members
        ORDER BY id
    """)
    entries = []
    for row in cur.fetchall():
        mid, full_name, term_start, term_end, muni_id = row
        parts = full_name.split()
        last_name = parts[-1]
        first_initial = parts[0][0] if parts else ""

        # Generate all name variants this member could appear as
        variants = set()
        variants.add(last_name)                          # "Woods"
        variants.add(f"{first_initial}. {last_name}")    # "C. Woods"
        # Handle apostrophes/hyphens: O'Quinn → OQuinn, Quinn
        stripped = last_name.replace("'", "").replace("\u2019", "").replace("-", "")
        if stripped != last_name:
            variants.add(stripped)                        # "OQuinn"
            variants.add(f"{first_initial}. {stripped}")  # "D. OQuinn"
            # Base after prefix: O'Quinn → Quinn
            for prefix in ("O'", "O\u2019", "Mc", "Mac", "O"):
                if last_name.startswith(prefix) and len(last_name) > len(prefix):
                    base = last_name[len(prefix):]
                    variants.add(base)                    # "Quinn"

        for variant in variants:
            entries.append({
                "variant": variant,
                "member_id": mid,
                "term_start": term_start,
                "term_end": term_end,
                "muni_id": muni_id,
                "specificity": len(variant),  # longer = more specific
            })

    return entries


def find_member(name_index, member_name, meeting_date, muni_id):
    """Find the best council_member_id for a given name + meeting date."""
    candidates = []
    for entry in name_index:
        if entry["variant"].lower() != member_name.lower():
            continue
        if entry["muni_id"] != muni_id:
            continue
        # Check term overlap
        if entry["term_start"] and meeting_date and meeting_date < entry["term_start"]:
            continue
        if entry["term_end"] and meeting_date and meeting_date > entry["term_end"]:
            continue
        candidates.append(entry)

    if not candidates:
        return None
    # Prefer most specific match (longest variant name)
    candidates.sort(key=lambda e: e["specificity"], reverse=True)
    return candidates[0]["member_id"]


def is_garbage_name(name):
    """Detect non-person names from minutes parser noise."""
    if len(name) < 3 or len(name) > 20:
        return True
    # Must start with uppercase letter
    if not re.match(r'^[A-Z]', name):
        return True
    # Known patterns that are never names
    garbage_words = {
        'None', 'City', 'Birmingham', 'Department', 'Georgia', 'Friday',
        'Tuesday', 'Thursday', 'Wednesday', 'Saturday', 'Zoning', 'Public',
        'Section', 'Conservation', 'State', 'Incorporated', 'Jefferson',
        'DEC', 'MEDIUM', 'ORDAINED', 'RESIDENTIAL', 'Council', 'Board',
        'County', 'Alabama', 'Official', 'Ordinance', 'Committee',
        'Division', 'Housing', 'Property', 'Code', 'Chapter', 'Article',
        'Notice', 'Officer', 'Development', 'Design', 'Engineering',
        'Enforcement', 'Facilities', 'Facility', 'Floor', 'Guidelines',
        'Health', 'Impact', 'Living', 'Maintenance', 'Map', 'Mental',
        'Residential', 'Structure', 'Subdivision', 'Title', 'Avenue',
        'Hall', 'Club', 'Case', 'Chambers', 'Clerk', 'Country',
        'Density', 'Detached', 'Accessory', 'Adjustment', 'April',
        'October', 'November', 'Coperate', 'Communal', 'Due',
        'Councilmember', 'Presiding', 'Medium', 'Non', 'Low',
        'Peggy', 'Alicia', 'Walters', 'For', 'Any', 'That', 'The',
        'This', 'Third',
    }
    if name in garbage_words:
        return True
    # All caps = not a name
    if name.isupper() and len(name) > 2:
        return True
    return False


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    name_index = build_name_index(cur)
    print(f"Built name index: {len(name_index)} variants from council_members\n")

    # Get all distinct member_name values with their meeting context
    cur.execute("""
        SELECT DISTINCT mv.member_name
        FROM member_votes mv
        WHERE mv.council_member_id IS NULL
    """)
    unresolved_names = [r[0] for r in cur.fetchall()]
    print(f"{len(unresolved_names)} unresolved member_name values\n")

    # Process each name
    resolved = 0
    deleted = 0
    unmatched = []

    for name in unresolved_names:
        if is_garbage_name(name):
            cur.execute("DELETE FROM member_votes WHERE member_name = %s AND council_member_id IS NULL", (name,))
            deleted += cur.rowcount
            continue

        # Get meeting dates for this name to resolve against terms
        cur.execute("""
            SELECT DISTINCT m.meeting_date, m.municipality_id
            FROM member_votes mv
            JOIN votes v ON mv.vote_id = v.id
            JOIN meetings m ON v.meeting_id = m.id
            WHERE mv.member_name = %s AND mv.council_member_id IS NULL
            LIMIT 1
        """, (name,))
        row = cur.fetchone()
        if not row:
            continue

        meeting_date, muni_id = row
        member_id = find_member(name_index, name, meeting_date, muni_id)

        if member_id:
            cur.execute(
                "UPDATE member_votes SET council_member_id = %s WHERE member_name = %s AND council_member_id IS NULL",
                (member_id, name),
            )
            print(f"  {name:>15} → member {member_id:>2} ({cur.rowcount} rows)")
            resolved += cur.rowcount
        else:
            cur.execute("SELECT count(*) FROM member_votes WHERE member_name = %s", (name,))
            cnt = cur.fetchone()[0]
            unmatched.append((name, cnt))

    conn.commit()

    # Summary
    cur.execute("SELECT count(*) FROM member_votes WHERE council_member_id IS NULL")
    still_null = cur.fetchone()[0]
    conn.close()

    print(f"\nResolved: {resolved} rows")
    print(f"Deleted garbage: {deleted} rows")
    print(f"Still unmapped: {still_null}")
    if unmatched:
        print("\nUnmatched names:")
        for name, cnt in sorted(unmatched, key=lambda x: -x[1]):
            print(f"  {name}: {cnt} rows")


if __name__ == "__main__":
    main()
