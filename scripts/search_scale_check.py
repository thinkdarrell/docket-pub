#!/usr/bin/env python
"""Synthetic-scale check for the ranked agenda-item search (plan
search-finds-what-was-said, M6; house rule `explain_at_scale`).

Everything happens inside one transaction that is rolled back: a synthetic
Birmingham meeting, N agenda items, ANALYZE, then the statement
`docket.services.query.build_search_sql` returns, timed for four queries
on the same connection. The rows are uncommitted, so `search_agenda_items`
itself, which opens its own connection, would not see them; that is why the
statement is built by a function of its own.

A row's search vector must be of a production row's order of size, because
the ranked query reads the vector of every candidate row and a vector that
large is stored outside the row. So each row has a title of 8 to 30 words
and a description of 40 to 400 words (`--desc-words`) drawn with a fixed
seed from 3,000 generated words, and the line reports the stored size of
the vectors it timed. Five common council words are each added to the
title of half the rows, independently, and one rare word to a handful.

    DATABASE_URL=$(tools/test-db) venv/bin/python scripts/search_scale_check.py --rows 60000; tools/test-db --drop

prints one line:

    scale: 60000 rows; vector median 3.1 kB, p95 5.4 kB; rare-word 12 ms; three-word 85 ms; common-words 640 ms; excluded-words 700 ms

Each timing is the slowest of three runs of the statement, in wall-clock
milliseconds from sending it to reading its last row. `--explain` prints
each query's EXPLAIN (ANALYZE, BUFFERS) after the line.

Run it on a disposable database. It refuses a Railway database: the fill is
tens of thousands of row writes and index entries, rolled back or not.
"""
from __future__ import annotations

import argparse
import io
import random
import sys
import time

from docket.config import DATABASE_URL
from docket.db import db
from docket.services.query import build_search_sql
from docket.services.search_query import MAX_EXCLUDED, STOP_WORDS, or_tsquery_sql, parse_query

MEETING_TITLE = "SYNTH search scale"
MEETING_EXTERNAL_ID = "999997"
TITLE_PREFIX = "SYNTH"
CITY = "birmingham"
SEED = 42
VOCABULARY_SIZE = 3000
TITLE_WORDS = (8, 30)
DEFAULT_DESC_WORDS = (40, 400)
# Each is added to the title of half the rows, chosen independently per word.
COMMON_WORDS = ("ordinance", "resolution", "city", "contract", "night")
# Added to the title of one row in RARE_EVERY.
RARE_WORD = "zeppelin"
RARE_EVERY = 5000
# label -> typed query. The third is the worst case: nearly every row is a
# candidate. The fourth is the third with as many excluded words as a query
# keeps, none of them in any row, so every candidate is tested against all.
_WORST_CASE = "city ordinance resolution contract"
QUERIES = (
    ("rare-word", RARE_WORD),
    ("three-word", "late night ordinance"),
    ("common-words", _WORST_CASE),
    ("excluded-words", _WORST_CASE + "".join(f" -zq{chr(97 + n)}" for n in range(MAX_EXCLUDED))),
)
RUNS = 3
PAGE = 20
COPY_CHUNK = 5000
RAILWAY_HOSTS = ("railway.internal", "railway.app", "rlwy.net")


def vocabulary(size: int = VOCABULARY_SIZE, seed: int = SEED) -> list[str]:
    """`size` distinct generated words of two to four consonant-vowel syllables.

    No generated word is a stop word or one of the words the queries search
    for or exclude (no generated word holds a q, and every excluded word
    does), and none contains the letter c, so none stems to "citi" as "city"
    does. The rows a query matches are therefore the rows the fill
    put its words in, and no others.
    """
    rng = random.Random(seed)
    consonants, vowels = "bdfghjklmnprstvwz", "aeiou"
    taken = set(STOP_WORDS) | set(COMMON_WORDS) | {RARE_WORD}
    for _, text in QUERIES:
        taken |= set(text.split())
    words: list[str] = []
    while len(words) < size:
        word = "".join(rng.choice(consonants) + rng.choice(vowels) for _ in range(rng.randint(2, 4)))
        if word not in taken:
            taken.add(word)
            words.append(word)
    return words


def _fill(cur, rows: int, desc_words: tuple[int, int]) -> int:
    """Insert the synthetic meeting and `rows` agenda items; return the meeting id."""
    cur.execute("SELECT id FROM municipalities WHERE slug = %s", [CITY])
    muni = cur.fetchone()[0]
    cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, external_id, video_url)
                   VALUES (%s, %s, '2026-01-01', %s, 'https://x/v') RETURNING id""",
                [muni, MEETING_TITLE, MEETING_EXTERNAL_ID])
    meeting_id = cur.fetchone()[0]
    rng = random.Random(SEED)
    vocab = vocabulary()
    for first in range(0, rows, COPY_CHUNK):
        buf = io.StringIO()
        for i in range(first, min(first + COPY_CHUNK, rows)):
            title = [TITLE_PREFIX, *rng.choices(vocab, k=rng.randint(*TITLE_WORDS))]
            title.extend(word for word in COMMON_WORDS if rng.random() < 0.5)
            if i % RARE_EVERY == 0:
                title.append(RARE_WORD)
            description = " ".join(rng.choices(vocab, k=rng.randint(*desc_words)))
            buf.write(f"{meeting_id}\t{i + 1}\t{' '.join(title)}\t{description}\n")
        buf.seek(0)
        cur.copy_expert("""COPY agenda_items (meeting_id, item_number, title, description)
                           FROM STDIN WITH (FORMAT text)""", buf)
    return meeting_id


def _time_statement(cur, sql: str, params: dict) -> tuple[float, int]:
    """The slowest of RUNS wall-clock runs in milliseconds, and the rows the statement returned."""
    slowest, returned = 0.0, 0
    for _ in range(RUNS):
        started = time.perf_counter()
        cur.execute(sql, params)
        returned = len(cur.fetchall())
        slowest = max(slowest, (time.perf_counter() - started) * 1000.0)
    return slowest, returned


def run_scale_check(conn, rows: int, desc_words: tuple[int, int] = DEFAULT_DESC_WORDS) -> dict:
    """Fill, measure, and roll back on `conn`. Returns what `format_line` prints, and more.

    Keys: `rows`; `vector_median_bytes` and `vector_p95_bytes`, the stored
    size of the synthetic rows' search vectors; and, keyed by the four
    query labels in order, `timings_ms`, `returned` (rows on the page),
    `candidates` (synthetic rows the query's any-word match selects), and
    `plans` (EXPLAIN ANALYZE text); `log` is what happened, line by line.
    """
    log: list[str] = []
    out: dict = {"rows": rows, "timings_ms": {}, "returned": {}, "candidates": {}, "plans": {}}
    try:
        with conn.cursor() as cur:
            started = time.time()
            meeting_id = _fill(cur, rows, desc_words)
            log.append(f"filled {rows} rows in {time.time() - started:.1f}s")
            # On production autovacuum moves the index's pending entries into
            # the index proper; here nothing has, and a query would read
            # them one by one.
            cur.execute("SELECT gin_clean_pending_list('idx_agenda_items_search'::regclass)")
            # ANALYZE is transactional: its statistics roll back with the
            # synthetic rows. Without it the planner would see the table as
            # it was before the fill and the check would prove nothing.
            cur.execute("ANALYZE agenda_items")
            cur.execute("ANALYZE meetings")
            log.append("pending index entries flushed; ANALYZE done")
            cur.execute("""SELECT percentile_cont(0.5)  WITHIN GROUP (ORDER BY pg_column_size(search_vector)),
                                  percentile_cont(0.95) WITHIN GROUP (ORDER BY pg_column_size(search_vector))
                             FROM agenda_items WHERE meeting_id = %s""", [meeting_id])
            median, p95 = cur.fetchone()
            out["vector_median_bytes"], out["vector_p95_bytes"] = float(median), float(p95)
            cur.execute("SELECT pg_size_pretty(pg_total_relation_size('agenda_items'))")
            log.append(f"agenda_items total size (table, toast, indexes): {cur.fetchone()[0]}")
            for label, text in QUERIES:
                sq = parse_query(text)
                sql, params = build_search_sql(sq, CITY, PAGE, 0)
                out["timings_ms"][label], out["returned"][label] = _time_statement(cur, sql, params)
                any_unit, unit_params = or_tsquery_sql(sq.units, "u")
                cur.execute(f"""SELECT count(*) FROM agenda_items ai
                                 WHERE ai.meeting_id = %(meeting_id)s AND ai.search_vector @@ {any_unit}""",
                            {**unit_params, "meeting_id": meeting_id})
                out["candidates"][label] = cur.fetchone()[0]
                cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + sql, params)
                out["plans"][label] = "\n".join(r[0] for r in cur.fetchall())
                log.append(f"{label} ({text!r}): {out['candidates'][label]} candidate rows, "
                           f"{out['returned'][label]} returned, slowest of {RUNS} runs "
                           f"{out['timings_ms'][label]:.1f} ms")
    finally:
        conn.rollback()
    out["log"] = "\n".join(log)
    return out


def format_line(out: dict) -> str:
    timings = "; ".join(f"{label} {ms:.0f} ms" for label, ms in out["timings_ms"].items())
    return (f"scale: {out['rows']} rows; vector median {out['vector_median_bytes'] / 1024:.1f} kB, "
            f"p95 {out['vector_p95_bytes'] / 1024:.1f} kB; {timings}")


def _desc_words(value: str) -> tuple[int, int]:
    low, sep, high = value.partition("-")
    if not sep or not low.isdigit() or not high.isdigit() or not 1 <= int(low) <= int(high):
        raise argparse.ArgumentTypeError("--desc-words is LOW-HIGH, two whole numbers with 1 <= LOW <= HIGH")
    return int(low), int(high)


def _rows(value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError("--rows is a whole number of at least 1")
    return int(value)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Time the ranked agenda-item search on synthetic rows, then roll back.")
    ap.add_argument("--rows", type=_rows, default=60_000, help="synthetic agenda items to insert (default 60000)")
    ap.add_argument("--desc-words", type=_desc_words, default=DEFAULT_DESC_WORDS, metavar="LOW-HIGH",
                    help="words in a row's description (default 40-400)")
    ap.add_argument("--explain", action="store_true", help="also print the log and each query's EXPLAIN ANALYZE")
    args = ap.parse_args(argv)
    if any(host in DATABASE_URL for host in RAILWAY_HOSTS):
        print("scale: refusing to run against a Railway database; use a disposable one "
              "(DATABASE_URL=$(tools/test-db)). Nothing was written.", file=sys.stderr)
        return 2
    with db() as conn:
        out = run_scale_check(conn, args.rows, args.desc_words)
    print(format_line(out))
    if args.explain:
        print(out["log"])
        for label, plan in out["plans"].items():
            print(f"\n== {label}\n{plan}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
