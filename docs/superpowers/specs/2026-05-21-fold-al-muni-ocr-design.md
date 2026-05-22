# Fold al-muni video OCR into docket.pub

**Status:** Design — awaiting user review
**Filed:** 2026-05-21
**Surface:** New `docket.analysis.ocr` subpackage + new worker task + migration 034 + Dockerfile/requirements
**Severity:** Medium — removes the two-repo, SQLite-bounce dependency for Birmingham vote OCR; lets the docket.pub worker fetch + OCR + persist votes for new BHM meetings without operator intervention.

---

## TL;DR

The video-OCR pipeline that extracts council vote counts from Birmingham's Granicus video frames currently lives in [`thinkdarrell/al-municipal-meetings`](https://github.com/thinkdarrell/al-municipal-meetings). To get votes onto a new meeting in docket.pub today, an operator runs the al-muni pipeline locally (writes to al-muni's SQLite), then runs `scripts/import_video_ocr.py` to push into docket Postgres, then triggers `vote_matching`. This is the "minimal-fold" path: port the OCR detection modules into docket, run them from a new worker task, write straight to Postgres, retire the SQLite intermediate.

This is **path A** in the brainstorming conversation: port the OCR core only. al-muni stays alive as a research sandbox for now; full repo absorption (archiving al-muni) is a future decision.

---

## Goals

1. The docket.pub worker can OCR new Birmingham meeting videos on its own — no operator commands, no al-muni dependency in the production path.
2. New BHM votes land in docket Postgres within hours of the meeting being recorded and posted to Granicus.
3. `scripts/import_video_ocr.py` becomes obsolete and can be removed in a follow-up.
4. The OCR modules in docket are testable in isolation with the same fixture frames that exercise them in al-muni today.
5. Roster maintenance happens in one place (docket's `council_members` table) — no duplicated name lists in code.

## Non-goals

- **Retire al-muni.** Out of scope; the repo stays as-is. Future "path B" decision.
- **Multi-city OCR.** Only Birmingham today (the only Granicus video source we index where vote counts appear as an on-screen overlay). Other cities continue to depend on minutes-PDF parsing for votes.
- **The known URL/link failure mode.** User flagged: OCR sometimes fails when URLs/links fail despite votes actually being present. Tracked separately (task #3); the retry semantic in this spec creates room for that fix to land.
- **Backfill of historical meetings.** Existing OCR votes from January–April 2026 were already imported via `scripts/import_video_ocr.py`; we don't re-scan them. Only go-forward meetings flow through the new worker task.
- **Replacing the minutes parser.** OCR and minutes are independent vote sources; both continue.

---

## Decisions reached in brainstorming

| ID | Decision |
|---|---|
| A | Minimal fold — port the OCR detection modules only; leave al-muni's orchestration and SQLite alone |
| A3 | Meeting selection uses a `processing_status.video_ocr_scanned` flag, not a separate queue table |
| B1 | OCR deps (ffmpeg, tesseract, opencv, pytesseract) added to the single existing docket image; both web and worker services share it |
| C2 | OCR roster derived at runtime from `council_members`, scoped by half-open `>= term_start AND < term_end + 1d`; no hardcoded roster module |
| D1 | Cron slot at 06:30 America/Chicago, between `ingest_all` (06:00) and `ai_items` (07:00) |
| D-retry-C | Bounded retry: up to 3 attempts over 7 days; after that, mark `video_ocr_scanned=TRUE` regardless of vote count |

### Reviewer feedback round 1 (2026-05-21) — applied inline

| Catch | Resolution | Section |
|---|---|---|
| Roster schema mismatch (`first_name/last_name/term_start_date/term_end_date` don't exist) | Use actual columns `name`, `term_start`, `term_end`; split to `[Initial]. [Lastname]` in Python via `_to_initial_lastname` helper | §2 |
| `BETWEEN` inclusivity foot-gun on `term_end` | Half-open range with 1-day pad on NULL `term_end` | §2 + §10 boundary test |
| Multi-worker race in selection | `FOR UPDATE OF ps SKIP LOCKED` (AI-worker pattern) | §4 |
| Idempotent persist would skip rescan corrections | Force-rescan explicitly `DELETE`s prior `source='video_ocr'` rows before resetting flags | §7 |
| Roster determinism on duplicate surnames | `ORDER BY name, district_id, id`; test case added | §2 + §10 |
| Resource constraints (Tesseract + OpenCV) | Concrete empirical footprint + fallback options (tier bump / `LIMIT 1` / B2 split) | §8 |
| Long stack traces in `video_ocr_last_error` | Admin UI truncates to 200 chars with full-view toggle | §7 |
| **Round 2 (2026-05-21)** | | |
| Unique constraint for idempotency | Add `idx_votes_ocr_unique` on `(meeting_id, video_timestamp, source)` | §3 |
| Transactional lock bloat | Switch to "Claim" pattern: atomic claim → scan (unlocked) → finalize | §4 + §5 |
| Member ID resolution | Pass `member_id` map from roster builder to persistence; avoid surname "guessing" | §2 + §6 |
| **Round 3 (2026-05-21)** — review of round 2 | | |
| Bug A — claim SQL inner subquery missed filters; locked rows that outer WHERE rejected | Rewrite as CTE; full filter set inside `FOR UPDATE SKIP LOCKED` | §4 |
| Bug B — `is_hidden`, 60-day window, ORDER BY silently dropped from claim | Restored inside CTE | §4 |
| Bug C — scan failure escapes try/except and kills outer loop | Wrap scan + persist together in single try | §5 |
| Bug D — §3 narrative still claimed partial index covers selection | Clarified + `EXPLAIN` verification note | §3 |
| Timestamp-drift idempotency contract | Documented: cron stable, force-rescan handles algorithm change | §3 |
| §7 markdown formatting (broken code fence) | Fixed | §7 |
| Claim-pattern test coverage missing | Six new integration tests added | §10 |

---

## Design

### 1. New subpackage layout

```
src/docket/analysis/
    ocr/
        __init__.py
        classifier.py    # ← al-muni vote_classifier.py
        header.py        # ← al-muni vote_header.py
        layout.py        # ← al-muni vote_layout.py
        ocr.py           # ← al-muni vote_ocr.py
        sequence.py      # ← al-muni vote_sequence.py
        pipeline.py      # ← al-muni vote_pipeline.py
        frame_io.py      # ← al-muni frame_io.py
        rosters.py       # NEW — runtime roster builder from council_members
```

Module names lose the redundant `vote_` prefix once they're under `ocr/`. The internal API (`scan_meeting_for_votes`, `is_vote_frame`, `read_header`, etc.) keeps the same shape so the port is mostly imports + adapter glue.

Tests live alongside in `tests/unit/ocr/`, with the al-muni fixture frames copied to `tests/fixtures/vote_frames/` (~10 PNG files, ~5 MB total).

### 2. Roster runtime construction

al-muni's `rosters/birmingham.py` exposes two pieces:

- `CouncilLayout` dataclass (`name_list: list[str]`, helpers).
- `LAYOUT_2021` / `LAYOUT_2025` constants — hardcoded name lists keyed by transition date.

In docket, `CouncilLayout` ports verbatim. The hardcoded constants are replaced by:

```python
# src/docket/analysis/ocr/rosters.py

@dataclass(frozen=True)
class OCRRoster:
    layout: CouncilLayout
    member_map: dict[str, int]  # "[Initial]. [Lastname]" -> council_member_id

def build_roster_for_meeting(meeting_id: int) -> OCRRoster:
    """Construct the OCR roster for a meeting from council_members.

    Returns the active Birmingham council on the meeting date, with a map
    linking OCR name strings to DB member IDs.
    """
    with db_cursor() as cur:
        cur.execute("""
            SELECT cm.id, cm.name, cm.district_id
              FROM council_members cm
              JOIN meetings m ON m.municipality_id = cm.municipality_id
             WHERE m.id = %s
               AND m.meeting_date >= cm.term_start
               AND m.meeting_date <  COALESCE(cm.term_end, m.meeting_date + INTERVAL '1 day')
             ORDER BY cm.name, cm.district_id, cm.id
        """, [meeting_id])
        rows = cur.fetchall()
    
    member_map = {}
    for r in rows:
        ocr_name = _to_initial_lastname(r['name'])
        member_map[ocr_name] = r['id']
        
    layout = CouncilLayout(name_list=list(member_map.keys()))
    return OCRRoster(layout=layout, member_map=member_map)
```

The `member_map` ensures that the persistence layer (§6) doesn't have to re-parse names to find member IDs; it uses the exact IDs that were active on the meeting date.

### 3. Data model — migration 034

```sql
ALTER TABLE processing_status
    ADD COLUMN video_ocr_scanned         BOOLEAN     NOT NULL DEFAULT FALSE,
    ADD COLUMN video_ocr_attempts        INTEGER     NOT NULL DEFAULT 0,
    ADD COLUMN video_ocr_last_attempted_at  TIMESTAMPTZ NULL,
    ADD COLUMN video_ocr_last_error      TEXT        NULL;

CREATE INDEX idx_processing_status_ocr_pending
    ON processing_status (video_ocr_last_attempted_at NULLS FIRST)
 WHERE video_ocr_scanned = FALSE;

-- Round 2: Unique constraint for OCR idempotency
CREATE UNIQUE INDEX idx_votes_ocr_unique
    ON votes (meeting_id, video_timestamp, source)
 WHERE source = 'video_ocr';
```

`idx_processing_status_ocr_pending` accelerates the inner subquery of §4's claim CTE (filter on `video_ocr_scanned = FALSE`, order by `video_ocr_last_attempted_at NULLS FIRST`). The implementation should `EXPLAIN` the claim SQL on a representative dataset to confirm planner picks it; if it doesn't, the index predicate may need to widen.

`idx_votes_ocr_unique` enables safe `INSERT ... ON CONFLICT (meeting_id, video_timestamp, source) DO NOTHING` during persistence.

**Idempotency contract (timestamp-drift caveat):** the unique key is *timestamp-stable* — it deduplicates the cron path (where rescans of the same meeting hit identical terminal frames) but does NOT deduplicate across OCR algorithm changes. A future OCR improvement that picks a slightly different terminal frame for the same vote sequence (say, 1888.0s today, 1890.0s after a fix) would INSERT as a new row, not collapse. That's intentional: cron rescans are idempotent by construction; force-rescan (§7) handles algorithm-change cases by explicitly deleting prior `source='video_ocr'` rows before re-running.

### 4. Selection query — Claiming meetings

To avoid holding database locks for minutes while ffmpeg runs, we adopt the **Claim pattern**: an atomic `UPDATE ... RETURNING` bumps the attempts counter and timestamp at claim time, then the long OCR scan runs *without* holding any DB lock, then a fresh transaction at the end persists results.

The claim itself is a CTE so the inner `FOR UPDATE SKIP LOCKED` only locks rows that pass the *full* filter set (not just `video_ocr_scanned=FALSE`):

```sql
WITH candidate AS (
    SELECT ps.meeting_id
      FROM processing_status ps
      JOIN meetings m        ON m.id  = ps.meeting_id
      JOIN municipalities mu ON mu.id = m.municipality_id
     WHERE mu.slug = 'birmingham'
       AND m.external_id ~ '^[0-9]+$'            -- clip-id only, not 'event-N'
       AND m.is_hidden = FALSE
       AND m.meeting_date >= now() - interval '60 days'
       AND ps.video_ocr_scanned = FALSE
       AND ps.video_ocr_attempts < 3
       AND (
            ps.video_ocr_last_attempted_at IS NULL
            OR ps.video_ocr_last_attempted_at < now() - interval '24 hours'
       )
     ORDER BY ps.video_ocr_last_attempted_at NULLS FIRST, m.meeting_date DESC
     LIMIT 1
     FOR UPDATE OF ps SKIP LOCKED
)
UPDATE processing_status ps
   SET video_ocr_attempts        = ps.video_ocr_attempts + 1,
       video_ocr_last_attempted_at = now()
  FROM candidate
  JOIN meetings m ON m.id = candidate.meeting_id
 WHERE ps.meeting_id = candidate.meeting_id
 RETURNING m.id, m.external_id, m.meeting_date;
```

Two properties that matter:

- **Filter parity.** The full filter set (Birmingham + clip-id + not hidden + 60-day window + attempts + backoff) is inside the CTE's `FOR UPDATE SKIP LOCKED`, so other workers skip past a row that we've claimed *and* we don't accidentally lock rows that wouldn't pass the outer WHERE anyway.
- **Counter-bump on claim.** Attempts is incremented at claim time, *before* the scan runs. If the worker process dies mid-scan, the next tick sees `attempts=N+1` and the 24h backoff prevents an immediate re-claim of the same broken meeting. Without that, a deterministically-crashing meeting would burn unbounded retries.

The `_claim_next_ocr_meeting()` Python wrapper executes this statement, commits its own transaction immediately, and returns the meeting dict (or `None` if no rows). The OCR scan then runs in process memory with no DB connection held.

Bounded to 5 meetings per cron run via the loop in §5 (not via SQL `LIMIT > 1`) — a typical run will process 0–1 (the previous day's recording, or zero on non-meeting weekdays).

### 5. The worker task

```python
src/docket/worker/tasks.py
    task_video_ocr() -> _safe_run("video_ocr", _do_video_ocr)
    _do_video_ocr():
        # Process up to 5 meetings, one at a time
        for _ in range(5):
            meeting = _claim_next_ocr_meeting()
            if not meeting:
                break
            _ocr_one_meeting(meeting)

src/docket/services/video_ocr.py
    _ocr_one_meeting(meeting) -> dict:
        # 1. Build roster (includes member_id map) — fast, in own txn
        roster = rosters.build_roster_for_meeting(meeting["id"])
        video_url = GRANICUS_DOWNLOAD_URL + meeting["external_id"]

        # 2 + 3 are inside the same try/except: scan failures must record
        # the error, not propagate out and kill the outer for-loop.
        try:
            # Slow part — no DB lock held
            detected = scan_meeting_for_votes(video_url, roster.layout)
            # Finalize in a fresh transaction
            persist_detected_votes(meeting["id"], detected, roster.member_map)
            _mark_ocr_complete(meeting["id"])
            return {"meeting_id": meeting["id"], "votes": len(detected)}
        except Exception as e:
            _mark_ocr_failed(meeting["id"], str(e))
            log.exception("OCR failed for meeting %s", meeting["id"])
            return {"meeting_id": meeting["id"], "votes": 0, "error": str(e)}
```

The try/except wraps the **entire** scan-persist sequence (not just persist). A scan-time failure (ffmpeg truncation, stream timeout, Tesseract crash, OOM in OpenCV) writes `video_ocr_last_error` and exits cleanly so the next meeting in the for-loop still runs. Only the persist step is in a "fresh transaction" sense — the scan itself holds no DB connection.

`_mark_ocr_complete` sets `video_ocr_scanned=TRUE` *and* clears `video_ocr_last_error`. `_mark_ocr_failed` leaves `video_ocr_scanned=FALSE` (so the 24h backoff applies and the meeting becomes eligible again for the next claim) and writes the error string.

### 6. Persistence — DetectedVote → Postgres

```python
def persist_detected_votes(meeting_id: int, detected: list[DetectedVote], member_map: dict[str, int]) -> int:
    """Insert each detected vote into `votes` + per-member rows into `member_votes`.

    Uses the member_map to resolve names to IDs. Unmatched names (not in the map)
    are logged as WARNINGs and inserted with council_member_id=NULL.
    
    Idempotent via ON CONFLICT (meeting_id, video_timestamp, source) DO NOTHING.
    """
```

### 7. Admin force-rescan

A small admin route lets an operator re-queue a meeting after the 3-attempt cap:

```
POST /admin/meetings/<int:meeting_id>/rescan-ocr
    1. DELETE from member_votes WHERE vote_id IN
       (SELECT id FROM votes WHERE meeting_id=:id AND source='video_ocr')
    2. DELETE from votes WHERE meeting_id=:id AND source='video_ocr'
       (CASCADE deactivates any vote_agenda_items links via FK)
    3. UPDATE processing_status SET
         video_ocr_scanned=FALSE,
         video_ocr_attempts=0,
         video_ocr_last_attempted_at=NULL,
         video_ocr_last_error=NULL
       WHERE meeting_id=:id
```

Redirects to meeting detail with a flash message naming the deleted vote count.

**Explicit DELETE before rescan (reviewer catch):** the persistence layer in §6 is idempotent on `(meeting_id, video_timestamp, source='video_ocr')` to make daily cron retries safe — but that same idempotency means a re-scan after an OCR bugfix would skip existing rows and the bad data would remain. Force-rescan therefore explicitly clears prior OCR votes for that meeting before resetting the flags. Minutes-parser votes (`source='minutes_text'`) are untouched.

The admin UI shows `video_ocr_last_error` truncated to ~200 chars in the meeting list, with a "View full" toggle on the meeting detail page (the column itself is `TEXT` so we don't lose anything).

Follows the same `@login_required` + CSRF-token pattern as the existing admin hide/unhide endpoint from PR #81 (the codebase-wide CSRF cleanup tracked in issue #83 will cover this route too once it lands).

This is the operator escape hatch for the URL/link failure mode (task #3) — once that fix lands, the operator can re-trigger affected meetings without waiting on the 60-day age-out.

### 8. Container deps — Dockerfile + requirements

**Dockerfile** (additions):

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*
```

**requirements.txt** (additions):

```
opencv-python-headless==4.10.0.84
pytesseract==0.3.13
# numpy already present (pulled by psycopg2 / others)
```

`opencv-python-headless` (not `opencv-python`) — the headless variant skips GUI bindings, ~40 MB smaller, and we have no display.

Both `docket-web` and `worker` services use the same image (per CLAUDE.md). Web doesn't import the OCR modules at all, so the deps are dead weight there but harmless. Promote to a separate worker image only if image size becomes painful (deferred decision).

**Resource ceiling check (reviewer catch):** Tesseract + OpenCV + ffmpeg are noticeably more CPU- and RAM-intensive than docket's current workload. al-muni's empirical footprint on a Birmingham council meeting (~3-hour video, scan_interval=2): peak ~600 MB RSS for the Python process plus an ffmpeg subprocess at ~150 MB. Combined with the worker daemon's idle ~954 MB (per memory `reference_railway_run_once_oom.md`), an active OCR task pushes the service to ~1.7 GB during the scan. Before deploy, verify the Railway `worker` service tier headroom (currently presumed 2 GB; check via dashboard). If close to the ceiling, options are: bump the tier, drop `LIMIT 5` to `LIMIT 1` (process one meeting per cron tick — six 30-minute ticks would still drain a normal week), or pull the OCR out into its own service per decision B2.

### 9. Schedule registration

```
src/docket/worker/scheduler.py
    sched.add_job(TASKS["video_ocr"], CronTrigger(hour=6, minute=30), id="video_ocr")
```

Slots between `ingest_all` (06:00, creates new meeting rows) and `ai_items` (07:00, doesn't read `votes`). `vote_matching` at 09:00 picks up freshly OCR'd votes the same morning, ~2.5 hours later.

Healthchecks env var: `HEALTHCHECK_VIDEO_OCR_UUID`. Add to the `worker` service via Railway dashboard after the UUID is created on Healthchecks.io.

### 10. Test strategy

- **Unit tests ported verbatim** from al-muni's `tests/unit/`:
  - `test_classifier.py` — histogram-based vote-frame detection
  - `test_header.py` — header OCR + HeaderState transitions
  - `test_layout.py` — spatial name↔dot association
  - `test_ocr.py` — count-box digit extraction
  - `test_sequence.py` — coarse-hit grouping
  - The PNG fixtures in `tests/fixtures/vote_frames/`

- **New unit test** for `rosters.build_layout_for_meeting`:
  - Meeting before 2025-10-28 → 2021 council roster
  - Meeting after 2025-10-28 → 2025 council roster
  - Meeting where a member's term spans the transition → that member included in both ranges
  - **Boundary case** — meeting on the exact `term_end` date of an outgoing member: the half-open `>= term_start AND < term_end + 1day` predicate must NOT include that member if their term has already rolled to the successor on the same date (this catches the BETWEEN-inclusivity foot-gun the reviewer flagged)
  - Empty council (impossible case) → returns layout with empty name_list
  - Two members with the same surname → both appear, ordered deterministically by `name, district_id, id`

- **New integration test** for `ocr_one_meeting`:
  - Stubs `scan_meeting_for_votes` to return 2 DetectedVote objects
  - Asserts 2 rows land in `votes`, N rows in `member_votes`, `video_ocr_scanned=TRUE`
  - Re-running the function is idempotent — no duplicate votes (relies on `idx_votes_ocr_unique` + ON CONFLICT)

- **New integration tests for the claim pattern** (`tests/integration/test_video_ocr_claim.py`):
  - **Concurrent claims pick different meetings.** Two open connections each call `_claim_next_ocr_meeting()` — one gets a meeting, the other gets `None` (or a different meeting if ≥2 are pending). Verifies `FOR UPDATE SKIP LOCKED` in the CTE.
  - **Counter bumps on claim, not on completion.** Claim a meeting, then simulate process crash by *not* calling `_mark_ocr_complete`. Verify `video_ocr_attempts = 1` and `video_ocr_last_attempted_at` is set. A second claim within 24h returns `None` (backoff); after 24h the same meeting is re-claimable with `attempts = 2`.
  - **Scan failure path.** Stub `scan_meeting_for_votes` to raise. Verify `_ocr_one_meeting` returns `{error: ...}` (not propagating), `video_ocr_last_error` is populated, `video_ocr_scanned=FALSE`, and the next meeting in the for-loop still runs.
  - **Hidden meeting is never claimed.** Set `meetings.is_hidden=TRUE` on a candidate; verify the CTE skips it.
  - **60-day window enforced.** A meeting with `meeting_date = now() - 61 days` and `scanned=FALSE` is not claimed.
  - **`event-N` external_id is never claimed.** A meeting upserted from the upcoming-meeting path (external_id like `'event-12345'`) is filtered by the regex.

- **No live OCR test in CI.** The OCR pipeline takes minutes to run against a real video and depends on Granicus availability; gated to manual smoke (`pytest -m live_ocr`) and the al-muni repo's existing integration tests already cover end-to-end against fixture frames.

### 11. Code that goes away

After this lands:

- `scripts/import_video_ocr.py` — no longer needed; deprecate in a follow-up PR (don't delete in this one — we want a clean before/after diff and the script is currently the only documentation of the al-muni → docket schema mapping).
- The al-muni → SQLite → import dance for new BHM meetings.

al-muni itself keeps its OCR pipeline (no deletion there) — the research sandbox stays useful for tuning the URL/link failure fix (task #3) before re-porting changes back to docket.

---

## Out of scope (re-stated for clarity)

- Archiving the al-muni repo — future decision.
- The OCR URL/link failure-mode fix — task #3, separate effort.
- Backfilling historical meetings — already imported.
- Multi-city OCR — Birmingham only.
- Replacing the minutes-PDF parser — independent vote source, unchanged.

---

## Open questions for the user

1. **Daily run cap.** Spec says LIMIT 5 per run. A typical week has 1 BHM regular meeting + maybe a special/budget session — so 5 is generous. Comfortable, or want to cap tighter?
2. **60-day window.** Hard ceiling for the selection query. Anything older that never got OCR'd just stays unmatched. Reasonable, or want to extend?
3. **Admin force-rescan UI placement.** I have it on the meeting detail page (`POST /admin/meetings/<id>/rescan-ocr`). Anywhere else useful — e.g., a small "OCR stuck" panel on the admin landing?

---

## Implementation phasing

The implementation plan (next step via writing-plans skill) will likely break this into:

1. Migration 034 + Dockerfile + requirements (infrastructure layer; deployable on its own)
2. Port OCR modules + tests; verify against fixtures locally
3. Roster runtime builder + tests
4. Persistence layer (DetectedVote → Postgres)
5. Worker task + scheduler registration
6. Admin force-rescan route + template
7. Smoke test against meeting 2232 (already OCR'd this evening via al-muni; rerun under docket native path to confirm parity)

Phases 1–4 are independent of each other and can ship in any order; 5–7 are sequential.
