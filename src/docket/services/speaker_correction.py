# src/docket/services/speaker_correction.py
"""Admin speaker correction: the manual shield for transcript_speakers (spec Section 5)."""
from __future__ import annotations

import logging

from docket.ai.transcripts.speakers import roster_for_meeting
from docket.db import db_cursor
from docket.services.transcripts import speaker_ordinals

log = logging.getLogger(__name__)
ROLES = ("council", "mayor", "clerk", "attorney", "staff", "public", "unknown")


def roster_options(meeting_id: int) -> list[dict]:
    return [{"id": m.id, "name": m.name} for m in roster_for_meeting(meeting_id)]


def list_clusters(meeting_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM transcripts WHERE meeting_id = %s", [meeting_id])
        t = cur.fetchone()
        if not t:
            return []
        tid = t["id"]
        cur.execute(
            r"""WITH utt AS (
                   SELECT s.cluster_label, s.seq, s.start_s, s.text, s.end_s - s.start_s AS dur,
                          row_number() OVER (PARTITION BY s.cluster_label ORDER BY s.seq) AS rn,
                          count(*) OVER (PARTITION BY s.cluster_label) AS n
                     FROM transcript_segments s
                    WHERE s.transcript_id = %s AND s.is_silence = FALSE AND s.text <> ''
               )
               SELECT sp.cluster_label, sp.council_member_id, cm.name AS member_name, sp.display_name, sp.role, sp.confidence,
                      sp.method, sp.is_manual, sp.needs_review,
                      COALESCE((SELECT sum(dur) FROM utt WHERE utt.cluster_label = sp.cluster_label), 0) AS speaking_s,
                      COALESCE((SELECT max(n) FROM utt WHERE utt.cluster_label = sp.cluster_label), 0) AS utterances,
                      COALESCE((SELECT json_agg(json_build_object('seq', u.seq, 'start_s', u.start_s, 'text', u.text) ORDER BY u.seq)
                                  FROM utt u WHERE u.cluster_label = sp.cluster_label
                                   AND array_length(regexp_split_to_array(u.text, '\s+'), 1) >= 6
                                   AND u.rn IN (1, (u.n + 1) / 2, u.n)), '[]'::json) AS samples
                 FROM transcript_speakers sp
                 LEFT JOIN council_members cm ON cm.id = sp.council_member_id
                WHERE sp.meeting_id = %s""",
            [tid, meeting_id],
        )
        rows = [dict(r) for r in cur.fetchall()]
    ords = speaker_ordinals(tid)
    for r in rows:
        r["ordinal"] = ords.get(r["cluster_label"], 0)
        r["samples"] = list(r["samples"] or [])[:3]
    rows.sort(key=lambda r: (r["ordinal"] == 0, r["ordinal"], r["cluster_label"]))
    return rows


def reassign(meeting_id: int, cluster_label: str, *, council_member_id: int | None, display_name: str | None,
             role: str, actor: str) -> None:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    name = (display_name or "").strip() or None
    if council_member_id is not None:
        match = next((m for m in roster_for_meeting(meeting_id) if m.id == council_member_id), None)
        if match is None:
            raise ValueError("council member is not on this meeting's roster")
        name, role = match.name, "council"
    elif not name:
        raise ValueError("a council member or a display name is required")
    with db_cursor() as cur:
        cur.execute("""UPDATE transcript_speakers
                          SET council_member_id = %s, display_name = %s, role = %s, confidence = 1.0, method = 'manual',
                              is_manual = TRUE, needs_review = FALSE
                        WHERE meeting_id = %s AND cluster_label = %s""",
                    [council_member_id, name, role, meeting_id, cluster_label])
        if cur.rowcount == 0:
            raise LookupError(cluster_label)
    log.info("speaker correction: meeting %s cluster %s -> %s (%s) by %s", meeting_id, cluster_label, name, role, actor)


def release(meeting_id: int, cluster_label: str) -> None:
    with db_cursor() as cur:
        cur.execute("""UPDATE transcript_speakers SET is_manual = FALSE, needs_review = TRUE
                        WHERE meeting_id = %s AND cluster_label = %s""", [meeting_id, cluster_label])
        if cur.rowcount == 0:
            raise LookupError(cluster_label)
