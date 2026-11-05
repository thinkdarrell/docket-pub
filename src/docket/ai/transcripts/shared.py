# src/docket/ai/transcripts/shared.py
"""The two speaker helpers the transcript stages and the read-side service share.

They live in the AI layer because the stages need them and `src/docket/ai/`
may not import `src/docket/services/` (`ARCHITECTURE.md`, dependency rules).
`docket.services.transcripts` imports both names from here and re-exports
them, so the transcript page, the item excerpt, and a stage's prompt all
number unresolved speakers from the same map and apply the same floor.
"""
from __future__ import annotations

from docket.db import db_cursor

SPEAKER_CONFIDENCE_FLOOR = 0.6


def speaker_ordinals(transcript_id: int) -> dict[str, int]:
    """cluster_label -> 1-based ordinal by first appearance over the whole meeting.

    The transcript page and the item excerpt both number unresolved speakers
    from this map, so "Speaker 3" means the same voice on every surface.
    """
    with db_cursor() as cur:
        cur.execute(
            """SELECT cluster_label, MIN(seq) AS first_seq
                 FROM transcript_segments
                WHERE transcript_id = %s AND is_silence = FALSE AND cluster_label IS NOT NULL
                GROUP BY cluster_label
                ORDER BY first_seq""",
            [transcript_id],
        )
        return {r["cluster_label"]: i + 1 for i, r in enumerate(cur.fetchall())}
