#!/usr/bin/env python
# scripts/transcript_recompare.py
"""Force a re-comparison for one meeting (corrected minutes, prompt tuning, a bad run).

    venv/bin/python scripts/transcript_recompare.py --meeting-id 2543          # queue for the next cron tick
    venv/bin/python scripts/transcript_recompare.py --meeting-id 2543 --now    # run the stages now (needs ANTHROPIC_API_KEY)

Approved rows are set stale and re-proposed in place when the same discrepancy
comes back (compare.reconcile), so nothing approved is silently lost.
"""
from __future__ import annotations

import argparse
import logging

from docket.db import db_cursor
from docket.ai.transcripts.pipeline import run_for_meeting

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

ap = argparse.ArgumentParser()
ap.add_argument("--meeting-id", type=int, required=True)
ap.add_argument("--now", action="store_true")
a = ap.parse_args()
with db_cursor() as cur:
    cur.execute("""UPDATE transcripts SET status = 'events_extracted', compare_skipped_reason = 'minutes_changed',
                          stage_attempts = 0, last_attempted_at = NULL WHERE meeting_id = %s
                      AND status IN ('events_extracted', 'compared', 'needs_review', 'failed')
                      AND EXISTS (SELECT 1 FROM meeting_events e WHERE e.meeting_id = transcripts.meeting_id AND e.source = 'transcript')
                    RETURNING id""", [a.meeting_id])
    if cur.fetchone() is None:
        raise SystemExit(f"meeting {a.meeting_id}: nothing to re-compare. It needs a transcript past event extraction "
                         "(events_extracted, compared, needs_review, or failed) that has transcript-side events; a transcript "
                         "held before event extraction must be retried from the admin queue instead.")
print("queued" if not a.now else run_for_meeting(a.meeting_id, notes="cli_recompare"))
