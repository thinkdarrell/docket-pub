#!/usr/bin/env python
"""Synthetic-scale check for transcript queries (spec Section 6, house rule
`explain_at_scale`). Everything happens inside one transaction that is
rolled back: a synthetic meeting + transcript, N segments, ANALYZE, then
EXPLAIN ANALYZE of the two hot queries. Without the ANALYZE the planner
would see an empty table and the check would prove nothing.

    python scripts/transcript_scale_check.py --rows 1000000
"""
from __future__ import annotations

import argparse
import io
import random
import time

from docket.db import db

WORDS = ("council", "motion", "ordinance", "agreement", "camera", "license", "plate",
         "reader", "budget", "district", "resolution", "amend", "second", "aye", "nay",
         "executive", "session", "recess", "item", "approve", "contract", "police", "mayor")


def _fill(cur, rows: int) -> tuple[int, int]:
    cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'")
    muni = cur.fetchone()[0]
    cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, external_id, video_url)
                   VALUES (%s, 'SYNTH scale', '2026-01-01', '999999', 'https://x/v') RETURNING id""", [muni])
    mid = cur.fetchone()[0]
    cur.execute("INSERT INTO transcripts (meeting_id, status) VALUES (%s, 'uploaded') RETURNING id", [mid])
    tid = cur.fetchone()[0]
    rng = random.Random(42)
    buf = io.StringIO()
    t = 0.0
    for i in range(rows):
        n = rng.randint(6, 30)
        text = "SYNTH " + " ".join(rng.choice(WORDS) for _ in range(n))
        dur = n * 0.4
        buf.write(f"{tid}\t{i}\t{t:.2f}\t{t + dur:.2f}\t{text}\tSPEAKER_0{rng.randint(0, 9)}\tf\n")
        t += dur
    buf.seek(0)
    cur.copy_expert("""COPY transcript_segments (transcript_id, seq, start_s, end_s, text, cluster_label, is_silence)
                       FROM STDIN WITH (FORMAT text)""", buf)
    return mid, tid


def _explain(cur, sql: str, params) -> tuple[float, str]:
    cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + sql, params)
    plan = "\n".join(r[0] for r in cur.fetchall())
    ms = 0.0
    for line in plan.splitlines():
        if line.strip().startswith("Execution Time:"):
            ms = float(line.split(":")[1].strip().split()[0])
    return ms, plan


def run_scale_check(conn, rows: int) -> dict:
    log: list[str] = []
    with conn.cursor() as cur:
        t0 = time.time()
        mid, tid = _fill(cur, rows)
        log.append(f"filled {rows} rows in {time.time() - t0:.1f}s")
        # ANALYZE is transactional: its pg_statistic rows roll back with the
        # synthetic data. VACUUM is the command that cannot run inside a
        # transaction block. Verified on PostgreSQL 18 (BEGIN; ANALYZE; ROLLBACK).
        cur.execute("ANALYZE transcript_segments")
        cur.execute("ANALYZE transcripts")
        log.append("ANALYZE done")
        cur.execute("SELECT pg_size_pretty(pg_total_relation_size('transcript_segments'))")
        log.append(f"transcript_segments total size (table + indexes): {cur.fetchone()[0]}")
        page_ms, page_plan = _explain(
            cur,
            """SELECT s.seq, s.start_s, s.end_s, s.text, s.cluster_label, s.is_silence, s.agenda_item_id
                 FROM transcript_segments s WHERE s.transcript_id = %s ORDER BY s.seq""",
            [tid],
        )
        search_ms, search_plan = _explain(
            cur,
            """SELECT s.seq, ts_rank(s.search_vector, websearch_to_tsquery('english', %s)) AS rank
                 FROM transcript_segments s
                WHERE s.search_vector @@ websearch_to_tsquery('english', %s)
                ORDER BY rank DESC LIMIT 10""",
            ["license plate", "license plate"],
        )
        conn.rollback()
    return {"page_ms": page_ms, "search_ms": search_ms, "page_plan": page_plan,
            "search_plan": search_plan, "log": "\n".join(log)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=1_000_000)
    args = ap.parse_args()
    with db() as conn:
        r = run_scale_check(conn, args.rows)
    print(r["log"])
    print(f"\n== transcript page query: {r['page_ms']:.1f} ms\n{r['page_plan']}")
    print(f"\n== search query: {r['search_ms']:.1f} ms\n{r['search_plan']}")


if __name__ == "__main__":
    main()
