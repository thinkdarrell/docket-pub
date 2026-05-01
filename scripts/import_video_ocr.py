"""Import video OCR votes from al-municipal-meetings SQLite into docket PostgreSQL.

Imports votes and member_votes for meetings after 2025-12-30 that don't
already have votes in docket_db. Maps clip_id -> external_id to match meetings.
"""

import sqlite3
import psycopg2

SQLITE_PATH = "/Users/darrellnance/projects/al-municipal-meetings/data/meetings.db"
PG_DSN = "postgresql://docket@localhost:5432/docket_db"


def main():
    sq = sqlite3.connect(SQLITE_PATH)
    sq.row_factory = sqlite3.Row
    pg = psycopg2.connect(PG_DSN)
    pgc = pg.cursor()

    # Get video OCR votes for post-12/30 meetings from SQLite
    rows = sq.execute("""
        SELECT m.clip_id, m.meeting_date, v.id as sq_vote_id,
               v.vote_result, v.yeas, v.nays, v.abstentions,
               v.video_timestamp_seconds, v.raw_text, v.confidence,
               v.flagged, v.flag_reason
        FROM votes v
        JOIN meetings m ON v.meeting_id = m.id
        WHERE v.extraction_method = 'video_ocr'
          AND m.meeting_date > '2025-12-30'
        ORDER BY m.meeting_date, v.id
    """).fetchall()

    # Build clip_id -> docket meeting_id mapping
    clip_ids = list({str(r["clip_id"]) for r in rows})
    pgc.execute(
        "SELECT id, external_id FROM meetings WHERE external_id = ANY(%s)",
        (clip_ids,),
    )
    clip_to_meeting = {ext: mid for mid, ext in pgc.fetchall()}

    # Check which docket meetings already have video_ocr votes
    pgc.execute(
        "SELECT DISTINCT meeting_id FROM votes WHERE source = 'video_ocr'"
    )
    already_has_ocr = {r[0] for r in pgc.fetchall()}

    # Get member names from SQLite
    members = {
        r["id"]: r["name"]
        for r in sq.execute("SELECT id, name FROM council_members").fetchall()
    }

    # Map result values
    result_map = {"passed": "passed", "failed": "failed", "tabled": "tabled"}

    imported_votes = 0
    imported_mv = 0
    skipped_meetings = set()

    for row in rows:
        clip_id = str(row["clip_id"])
        meeting_id = clip_to_meeting.get(clip_id)
        if not meeting_id:
            print(f"  SKIP: no docket meeting for clip_id={clip_id}")
            continue
        if meeting_id in already_has_ocr:
            if meeting_id not in skipped_meetings:
                skipped_meetings.add(meeting_id)
            continue

        result = result_map.get(row["vote_result"], row["vote_result"])
        needs_review = bool(row["flagged"])
        confidence = "high" if (row["confidence"] or 0) >= 0.8 else "medium" if (row["confidence"] or 0) >= 0.5 else "low"

        pgc.execute(
            """INSERT INTO votes
               (meeting_id, external_id, result, yeas, nays, abstentions,
                source, confidence, needs_review, review_reason,
                video_timestamp, raw_text)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                meeting_id,
                f"{clip_id}-ocr-{row['sq_vote_id']}",
                result,
                row["yeas"],
                row["nays"],
                row["abstentions"],
                "video_ocr",
                confidence,
                needs_review,
                row["flag_reason"],
                row["video_timestamp_seconds"],
                row["raw_text"],
            ),
        )
        pg_vote_id = pgc.fetchone()[0]
        imported_votes += 1

        # Import member votes for this vote
        mvs = sq.execute(
            "SELECT member_id, position FROM member_votes WHERE vote_id = ?",
            (row["sq_vote_id"],),
        ).fetchall()
        for mv in mvs:
            member_name = members.get(mv["member_id"], f"Unknown-{mv['member_id']}")
            pgc.execute(
                """INSERT INTO member_votes (vote_id, member_name, position)
                   VALUES (%s, %s, %s)""",
                (pg_vote_id, member_name, mv["position"]),
            )
            imported_mv += 1

    pg.commit()
    pg.close()
    sq.close()

    print(f"\nImported {imported_votes} votes, {imported_mv} member votes")
    if skipped_meetings:
        print(f"Skipped {len(skipped_meetings)} meetings (already have video_ocr)")


if __name__ == "__main__":
    main()
