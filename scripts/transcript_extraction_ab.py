#!/usr/bin/env python
# scripts/transcript_extraction_ab.py
"""Run the Haiku vs Sonnet extraction A/B over the N newest compared meetings and write the report.

    ANTHROPIC_API_KEY=... DATABASE_URL=... venv/bin/python scripts/transcript_extraction_ab.py --meetings 10

Cost: about $0.25 per meeting (one Sonnet + one Haiku extraction). Writes
docs/superpowers/experiments/<date>-haiku-extraction-ab.md by default.
"""
from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

from docket.ai.transcripts.ab import render_report, run_ab
from docket.ai.transcripts.client import StructuredClient
from docket.db import db_cursor

logging.basicConfig(level=logging.INFO)
ap = argparse.ArgumentParser()
ap.add_argument("--meetings", type=int, default=10)
ap.add_argument("--out", type=Path, default=Path(f"docs/superpowers/experiments/{date.today().isoformat()}-haiku-extraction-ab.md"))
a = ap.parse_args()
with db_cursor() as cur:
    cur.execute("""SELECT t.meeting_id FROM transcripts t JOIN meetings m ON m.id = t.meeting_id
                    WHERE t.status = 'compared' AND m.is_hidden = FALSE ORDER BY m.meeting_date DESC LIMIT %s""", [a.meetings])
    ids = [r["meeting_id"] for r in cur.fetchall()]
results = run_ab(ids, client=StructuredClient())
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(render_report(results))
print(f"wrote {a.out}")
