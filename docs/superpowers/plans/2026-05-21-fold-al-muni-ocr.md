# Fold al-muni video OCR into docket.pub — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the video-OCR vote-extraction pipeline from `al-municipal-meetings` into `docket-pub` so the worker can OCR new Birmingham council meetings without operator intervention or SQLite bouncing.

**Architecture:** New `docket.analysis.ocr` subpackage holds the ported pure-OCR modules (frame IO, classifier, header reader, layout detector, count OCR, sequence grouping, pipeline orchestrator). A new `docket.services.video_ocr` service owns claim/scan/persist orchestration using the Claim pattern (atomic UPDATE-RETURNING with `FOR UPDATE SKIP LOCKED` in a CTE; long scan runs unlocked; fresh transaction at finalize). A new cron task at 06:30 CT slots between `ingest_all` and `ai_items` in the existing worker scheduler. Roster comes from `council_members` at runtime (no hardcoded name lists). An admin force-rescan route handles OCR-bugfix correction cycles.

**Tech Stack:** Python 3.10+, PostgreSQL 18 (Railway), psycopg2, OpenCV (opencv-python-headless), pytesseract, ffmpeg, APScheduler, Flask (admin route).

**Spec:** `docs/superpowers/specs/2026-05-21-fold-al-muni-ocr-design.md`

## Plan review history

| Round | Catch | Resolution | Section |
|---|---|---|---|
| R1 | Migration as `apply()`/`rollback()` functions | Actual runner reads `SQL_UP` / `SQL_DOWN` string constants; tests use `runner.apply_migrations(conn)` + `runner.rollback_migration(conn, N)` | Task 1 |
| R1 | Wrong filename `033_hide_non_real_meetings.py` | Actual `033_meetings_is_hidden.py` | Task 1 |
| R1 | Wrong `DetectedVote` / `MemberVote` field names | Use actual fields: `timestamp`, `vote_result`, `member_votes: list[MemberVote]` | Tasks 12+ |
| R1 | `member_votes` INSERT missed the `member_name` column | Added — captures OCR'd name even when council_member_id is NULL | Task 12 |
| R1 | Admin auth gate wrong (`current_user.is_authenticated`) | Use `session.get('admin_user')` (docket's actual session-based pattern) | Task 16 template |
| R2 | Missing port of `muni/models/vote.py` — pipeline.py imports DetectedVote/MemberVote from there; without porting it Tasks 10+ ImportError | New steps 10.0a–10.0c port to `docket.analysis.ocr._models` (NOT `docket.models` — collides with N:M shape); pipeline.py re-exports for convenience | Task 10 |
| R2 | `@login_required` decorator on rescan route doesn't match docket pattern (admin.py uses `@bp.before_request` instead) | Drop the decorator; rely on blueprint-level gate | Task 16 |
| R2 | INSERT omits `confidence` (NOT NULL DEFAULT 'high'); needs_review=True silently gets 'high' badge | Map `needs_review`→'medium'/'high' explicitly + add test | Task 12 |
| R2 | Conftest fixtures incomplete (10 of 12 referenced fixtures were placeholder) | All 12 fixtures inlined with `_insert_meeting` helper | Task 11 step 11.1b |

---

## File structure

### New files

| Path | Responsibility |
|---|---|
| `src/docket/migrations/034_video_ocr_processing_status.py` | Adds 4 columns + 2 indexes; idempotent ALTER + CREATE INDEX |
| `src/docket/analysis/ocr/__init__.py` | Package marker; exports public API surface |
| `src/docket/analysis/ocr/frame_io.py` | ffmpeg/ffprobe wrappers — verbatim port |
| `src/docket/analysis/ocr/classifier.py` | `is_vote_frame()` 4-signal histogram check — verbatim port |
| `src/docket/analysis/ocr/header.py` | `read_header()` + `HeaderState` enum — verbatim port |
| `src/docket/analysis/ocr/layout.py` | `detect_member_rows()` spatial name↔dot — verbatim port |
| `src/docket/analysis/ocr/ocr.py` | `extract_counts()` + `extract_vote_text()` — verbatim port |
| `src/docket/analysis/ocr/sequence.py` | `VoteSequence` + grouping helpers — verbatim port |
| `src/docket/analysis/ocr/pipeline.py` | `scan_meeting_for_votes()` orchestrator — verbatim port |
| `src/docket/analysis/ocr/_models.py` | `DetectedVote` + `MemberVote` dataclasses — ported from `muni/models/vote.py` (MatchedVote dropped) |
| `src/docket/analysis/ocr/rosters.py` | NEW — `OCRRoster`, `CouncilLayout`, `build_roster_for_meeting()` |
| `src/docket/services/video_ocr.py` | NEW — claim/scan/persist orchestration + `persist_detected_votes` |
| `src/docket/web/templates/admin/_rescan_ocr_button.html` | NEW — partial: form posting to rescan endpoint |
| `tests/unit/ocr/__init__.py` | Test package marker |
| `tests/unit/ocr/test_classifier.py` | Ported tests |
| `tests/unit/ocr/test_header.py` | Ported tests |
| `tests/unit/ocr/test_layout.py` | Ported tests |
| `tests/unit/ocr/test_ocr.py` | Ported tests |
| `tests/unit/ocr/test_sequence.py` | Ported tests |
| `tests/unit/ocr/test_rosters.py` | NEW — boundary, surname-tie, ordering |
| `tests/integration/test_video_ocr_claim.py` | NEW — claim pattern, concurrency, backoff |
| `tests/integration/test_video_ocr_persistence.py` | NEW — DetectedVote → Postgres + ON CONFLICT |
| `tests/integration/test_video_ocr_rescan.py` | NEW — admin force-rescan deletes prior OCR rows |
| `tests/fixtures/vote_frames/*.png` | Fixture frames copied from al-muni |

### Modified files

| Path | Change |
|---|---|
| `Dockerfile` | Add `apt-get install ffmpeg tesseract-ocr` layer |
| `requirements.txt` | Add `opencv-python-headless` + `pytesseract` |
| `src/docket/migrations/runner.py` | Register migration 034 in `MIGRATIONS` list |
| `src/docket/worker/tasks.py` | Add `_do_video_ocr` + `task_video_ocr` + entry in `TASKS` dict |
| `src/docket/worker/scheduler.py` | Add `add_job` for `video_ocr` at 06:30 CT |
| `src/docket/web/admin.py` | Add `POST /admin/meetings/<id>/rescan-ocr` route |
| `src/docket/web/templates/meeting_detail.html` | Add admin-only rescan button include |
| `CLAUDE.md` | Update status table with "Video OCR (folded into worker)" row |

---

## Pre-flight

- [ ] **Step 0a: Confirm clean working tree**

Run: `cd ~/docket-pub && git status`
Expected: `nothing to commit, working tree clean` on `main` (or current feature branch is the intended base).

- [ ] **Step 0b: Pull latest**

Run: `cd ~/docket-pub && git pull --ff-only`
Expected: `Already up to date.` or fast-forward.

- [ ] **Step 0c: Create feature branch**

Run: `cd ~/docket-pub && git checkout -b feat/fold-al-muni-ocr`
Expected: `Switched to a new branch 'feat/fold-al-muni-ocr'`.

- [ ] **Step 0d: Verify venv works + tests baseline green**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/unit -x -q 2>&1 | tail -10`
Expected: all unit tests pass (no new failures). Note the count for comparison.

---

## Task 1: Migration 034 — video OCR columns + indexes

**Files:**
- Create: `src/docket/migrations/034_video_ocr_processing_status.py`
- Modify: `src/docket/migrations/runner.py`
- Test: `tests/integration/test_migration_034.py`

- [ ] **Step 1.1: Read an existing migration for style reference**

Run: `cd ~/docket-pub && cat src/docket/migrations/033_hide_non_real_meetings.py | head -40`
This sets the pattern: `SQL_UP`, `SQL_DOWN` string constants, idempotent guards via `IF NOT EXISTS`/`IF EXISTS`.

- [ ] **Step 1.2: Write the migration file**

Create `src/docket/migrations/034_video_ocr_processing_status.py`:

```python
"""Migration 034 — video OCR scan state on processing_status.

Adds four columns tracking whether a meeting has been OCR-scanned, how
many attempts, when last attempted, and last error text. Two indexes:
one partial index supporting the claim CTE's selection ordering, one
unique partial index enforcing OCR idempotency in `votes`.
"""

SQL_UP = \"\"\"
ALTER TABLE processing_status
    ADD COLUMN IF NOT EXISTS video_ocr_scanned          BOOLEAN     NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS video_ocr_attempts         INTEGER     NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS video_ocr_last_attempted_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS video_ocr_last_error       TEXT        NULL;

CREATE INDEX IF NOT EXISTS idx_processing_status_ocr_pending
    ON processing_status (video_ocr_last_attempted_at NULLS FIRST)
 WHERE video_ocr_scanned = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_votes_ocr_unique
    ON votes (meeting_id, video_timestamp, source)
 WHERE source = 'video_ocr';
\"\"\"

SQL_DOWN = \"\"\"
DROP INDEX IF EXISTS idx_votes_ocr_unique;
DROP INDEX IF EXISTS idx_processing_status_ocr_pending;
ALTER TABLE processing_status
    DROP COLUMN IF EXISTS video_ocr_last_error,
    DROP COLUMN IF EXISTS video_ocr_last_attempted_at,
    DROP COLUMN IF EXISTS video_ocr_attempts,
    DROP COLUMN IF EXISTS video_ocr_scanned;
\"\"\"
```

- [ ] **Step 1.3: Register the migration in the runner**

Modify `src/docket/migrations/runner.py` — find the `MIGRATIONS` list and append the module path string:

```python
    "docket.migrations.033_meetings_is_hidden",
    "docket.migrations.034_video_ocr_processing_status",
]
```

- [ ] **Step 1.4: Write integration test for the migration**

Create `tests/integration/test_migration_034.py`:

```python
"""Verify migration 034 adds the four columns and two indexes idempotently."""
import pytest
from docket.db import db, db_cursor
from docket.migrations import runner


@pytest.fixture
def fresh_ps_columns():
    """Roll the migration back before each test, apply fresh."""
    with db() as conn:
        runner.rollback_migration(conn, 34)
    yield
    with db() as conn:
        runner.rollback_migration(conn, 34)


def test_apply_adds_columns(fresh_ps_columns):
    with db() as conn:
        runner.apply_migrations(conn)
    with db_cursor() as cur:
        cur.execute(\"\"\"
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'processing_status'
               AND column_name LIKE 'video_ocr%'
        \"\"\")
        cols = {r['column_name'] for r in cur.fetchall()}
    assert cols == {
        'video_ocr_scanned',
        'video_ocr_attempts',
        'video_ocr_last_attempted_at',
        'video_ocr_last_error',
    }


def test_apply_is_idempotent(fresh_ps_columns):
    with db() as conn:
        runner.apply_migrations(conn)
        runner.apply_migrations(conn)   # second apply must not raise
    with db_cursor() as cur:
        cur.execute(\"\"\"
            SELECT indexname FROM pg_indexes
             WHERE tablename IN ('processing_status', 'votes')
               AND indexname IN ('idx_processing_status_ocr_pending', 'idx_votes_ocr_unique')
        \"\"\")
        idx = {r['indexname'] for r in cur.fetchall()}
    assert idx == {'idx_processing_status_ocr_pending', 'idx_votes_ocr_unique'}


def test_rollback_removes_columns_and_indexes(fresh_ps_columns):
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 34)
    with db_cursor() as cur:
        cur.execute(\"\"\"
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'processing_status'
               AND column_name LIKE 'video_ocr%'
        \"\"\")
        cols = [r['column_name'] for r in cur.fetchall()]
    assert cols == []
```

- [ ] **Step 1.5: Run the test — verify it fails before apply**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/integration/test_migration_034.py -v`
Expected: tests fail with "module not found" — migration file isn't importable yet from the test's perspective if the runner registration is wrong, OR tests pass if step 1.2 completed.

- [ ] **Step 1.6: Run the migration runner manually against local DB**

Run: `cd ~/docket-pub && venv/bin/python -m docket.migrations.runner --status 2>&1 | tail -5`
Expected: `034_video_ocr_processing_status [pending]`

Run: `cd ~/docket-pub && venv/bin/python -m docket.migrations.runner 2>&1 | tail -5`
Expected: `034_video_ocr_processing_status [applied]`

- [ ] **Step 1.7: Run the test suite — confirm all green**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/integration/test_migration_034.py -v`
Expected: 3 passed.

- [ ] **Step 1.8: Commit**

```bash
cd ~/docket-pub
git add src/docket/migrations/034_video_ocr_processing_status.py \
        src/docket/migrations/runner.py \
        tests/integration/test_migration_034.py
git commit -m "feat(migrations): 034 — video OCR processing_status columns

Adds video_ocr_scanned, video_ocr_attempts, video_ocr_last_attempted_at,
video_ocr_last_error to processing_status. Adds idx_processing_status_ocr_pending
(partial, drives the claim CTE) and idx_votes_ocr_unique (partial unique,
enforces OCR idempotency via ON CONFLICT).

Spec: docs/superpowers/specs/2026-05-21-fold-al-muni-ocr-design.md §3"
```

---

## Task 2: Dockerfile + requirements — OCR system deps

**Files:**
- Modify: `Dockerfile`
- Modify: `requirements.txt`

- [ ] **Step 2.1: Read current Dockerfile**

Run: `cd ~/docket-pub && cat Dockerfile`
Note the base image and existing `apt-get` layers (if any).

- [ ] **Step 2.2: Add OCR system deps to Dockerfile**

Edit `Dockerfile`. Insert this layer **after** the base image / before the Python install layer:

```dockerfile
# OCR runtime: ffmpeg for frame extraction, tesseract for text OCR.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*
```

(If the Dockerfile already has an `apt-get install` layer, append `ffmpeg tesseract-ocr` to its list rather than adding a second `RUN apt-get update`.)

- [ ] **Step 2.3: Add Python deps to requirements.txt**

Append to `requirements.txt`:

```
opencv-python-headless==4.10.0.84
pytesseract==0.3.13
```

(numpy is already pulled in transitively; confirm with `cd ~/docket-pub && venv/bin/pip show numpy 2>&1 | head -1`. If absent, add `numpy>=1.26,<2`.)

- [ ] **Step 2.4: Install locally**

Run: `cd ~/docket-pub && venv/bin/pip install -r requirements.txt 2>&1 | tail -5`
Expected: `Successfully installed opencv-python-headless-... pytesseract-...`.

- [ ] **Step 2.5: Verify system binaries available locally**

Run: `which ffmpeg && which tesseract`
Expected: both resolved (on macOS dev host they come via Homebrew). On Linux/Railway they'll come from the Dockerfile layer; we'll verify post-deploy.

- [ ] **Step 2.6: Smoke import test**

Run: `cd ~/docket-pub && venv/bin/python -c "import cv2, pytesseract, numpy; print('cv2', cv2.__version__); print('pytesseract', pytesseract.__version__); print('numpy', numpy.__version__)"`
Expected: three version lines, no ImportError.

- [ ] **Step 2.7: Commit**

```bash
cd ~/docket-pub
git add Dockerfile requirements.txt
git commit -m "deps: add ffmpeg + tesseract + opencv-python-headless + pytesseract

Required by the upcoming docket.analysis.ocr subpackage (folded from
al-municipal-meetings). Single shared image; both docket-web and worker
services pick this up on next deploy.

Spec: docs/superpowers/specs/2026-05-21-fold-al-muni-ocr-design.md §8"
```

---

## Task 3: Copy fixture frames + create test package

**Files:**
- Create: `tests/fixtures/vote_frames/*.png` (copied)
- Create: `tests/unit/ocr/__init__.py`

- [ ] **Step 3.1: List source fixtures**

Run: `ls ~/projects/al-municipal-meetings/tests/fixtures/vote_frames/`
Note the file names — there should be ~10 PNG files (vote-passes, vote-fails, vote-tabled, voting-in-progress, non-vote frames, etc.).

- [ ] **Step 3.2: Copy fixtures**

Run:
```bash
mkdir -p ~/docket-pub/tests/fixtures/vote_frames
cp ~/projects/al-municipal-meetings/tests/fixtures/vote_frames/*.png \
   ~/docket-pub/tests/fixtures/vote_frames/
```

- [ ] **Step 3.3: Verify**

Run: `ls ~/docket-pub/tests/fixtures/vote_frames/ | wc -l`
Expected: same count as step 3.1.

- [ ] **Step 3.4: Create test package marker**

Run: `cd ~/docket-pub && touch tests/unit/ocr/__init__.py`

- [ ] **Step 3.5: Commit**

```bash
cd ~/docket-pub
git add tests/fixtures/vote_frames/ tests/unit/ocr/__init__.py
git commit -m "test: import OCR fixture frames from al-muni

Ported verbatim. These PNGs drive the unit tests for classifier, header,
layout, OCR, and sequence in upcoming tasks."
```

---

## Task 4: Port `frame_io.py` + tests

**Files:**
- Create: `src/docket/analysis/ocr/__init__.py`
- Create: `src/docket/analysis/ocr/frame_io.py`

(No tests in al-muni for frame_io — it's tested indirectly through pipeline integration tests.)

- [ ] **Step 4.1: Create package marker**

Run: `cd ~/docket-pub && mkdir -p src/docket/analysis/ocr && touch src/docket/analysis/ocr/__init__.py`

- [ ] **Step 4.2: Copy source verbatim**

Run: `cp ~/projects/al-municipal-meetings/src/muni/analysis/frame_io.py ~/docket-pub/src/docket/analysis/ocr/frame_io.py`

- [ ] **Step 4.3: Verify no muni-namespace imports**

Run: `cd ~/docket-pub && grep -n "from muni\|import muni" src/docket/analysis/ocr/frame_io.py`
Expected: no output (no muni imports in this module — confirmed during survey).

- [ ] **Step 4.4: Smoke import**

Run: `cd ~/docket-pub && venv/bin/python -c "from docket.analysis.ocr.frame_io import probe_duration, scan_full, scan_window; print('ok')"`
Expected: `ok`

- [ ] **Step 4.5: Commit**

```bash
cd ~/docket-pub
git add src/docket/analysis/ocr/__init__.py src/docket/analysis/ocr/frame_io.py
git commit -m "feat(ocr): port frame_io from al-muni — ffmpeg/ffprobe wrappers

Verbatim port. Module is pure (no DB/network deps beyond ffmpeg+ffprobe
subprocess calls). Public API: probe_duration, scan_full, scan_window,
download_video_to_tempfile, IncompleteVideoScanError."
```

---

## Task 5: Port `classifier.py` + tests

**Files:**
- Create: `src/docket/analysis/ocr/classifier.py`
- Create: `tests/unit/ocr/test_classifier.py`

- [ ] **Step 5.1: Copy source**

Run: `cp ~/projects/al-municipal-meetings/src/muni/analysis/vote_classifier.py ~/docket-pub/src/docket/analysis/ocr/classifier.py`

- [ ] **Step 5.2: Confirm no internal imports to rewrite**

Run: `cd ~/docket-pub && grep -n "from muni\|import muni" src/docket/analysis/ocr/classifier.py`
Expected: no output (classifier only imports cv2, numpy).

- [ ] **Step 5.3: Copy test file**

Run: `cp ~/projects/al-municipal-meetings/tests/unit/test_classifier.py ~/docket-pub/tests/unit/ocr/test_classifier.py`

- [ ] **Step 5.4: Rewrite imports in test file**

Edit `tests/unit/ocr/test_classifier.py`. Replace all `from muni.analysis.vote_classifier` with `from docket.analysis.ocr.classifier`. Replace fixture path constants — search for any `Path("tests/fixtures/vote_frames")` or similar and confirm they resolve correctly from the new test location (they should, since the repo root is the same).

Specifically rewrite (use Edit tool's `replace_all` mode on the file):
- `from muni.analysis.vote_classifier` → `from docket.analysis.ocr.classifier`
- `from muni.` → `from docket.analysis.ocr.` (for any other muni imports — there shouldn't be any in this test file, but verify)

- [ ] **Step 5.5: Run the test**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/unit/ocr/test_classifier.py -v`
Expected: all tests pass. If a fixture-path test fails, the resolution is to make paths relative to the test file using `Path(__file__).parent.parent.parent / "fixtures" / "vote_frames"`.

- [ ] **Step 5.6: Commit**

```bash
cd ~/docket-pub
git add src/docket/analysis/ocr/classifier.py tests/unit/ocr/test_classifier.py
git commit -m "feat(ocr): port classifier + tests from al-muni

Verbatim port of is_vote_frame() — the 4-signal histogram check that
gates downstream OCR. Pure module (cv2 + numpy only). All ported tests
pass against the copied fixture frames."
```

---

## Task 6: Port `header.py` + tests

**Files:**
- Create: `src/docket/analysis/ocr/header.py`
- Create: `tests/unit/ocr/test_header.py`

- [ ] **Step 6.1: Copy source**

Run: `cp ~/projects/al-municipal-meetings/src/muni/analysis/vote_header.py ~/docket-pub/src/docket/analysis/ocr/header.py`

- [ ] **Step 6.2: Verify no internal imports**

Run: `cd ~/docket-pub && grep -n "from muni\|import muni" src/docket/analysis/ocr/header.py`
Expected: no output.

- [ ] **Step 6.3: Copy and rewrite test**

```bash
cp ~/projects/al-municipal-meetings/tests/unit/test_header.py ~/docket-pub/tests/unit/ocr/test_header.py
```

Edit `tests/unit/ocr/test_header.py`:
- `from muni.analysis.vote_header` → `from docket.analysis.ocr.header`

- [ ] **Step 6.4: Run the test**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/unit/ocr/test_header.py -v`
Expected: all tests pass.

- [ ] **Step 6.5: Commit**

```bash
cd ~/docket-pub
git add src/docket/analysis/ocr/header.py tests/unit/ocr/test_header.py
git commit -m "feat(ocr): port header reader + tests from al-muni

Verbatim port of read_header() + HeaderState enum. Crops top ~22% of
the frame, runs Tesseract PSM 7, fuzzy-matches keywords to {voting_in_progress,
passed, failed, tabled, unknown}."
```

---

## Task 7: Port `layout.py` + tests

**Files:**
- Create: `src/docket/analysis/ocr/layout.py`
- Create: `tests/unit/ocr/test_layout.py`

- [ ] **Step 7.1: Copy source**

Run: `cp ~/projects/al-municipal-meetings/src/muni/analysis/vote_layout.py ~/docket-pub/src/docket/analysis/ocr/layout.py`

- [ ] **Step 7.2: Inspect for internal muni imports**

Run: `cd ~/docket-pub && grep -n "from muni\|import muni" src/docket/analysis/ocr/layout.py`

If output shows imports like `from muni.analysis.rosters.birmingham import CouncilLayout`, those need to point at the new rosters module — but the new module doesn't exist until Task 11. So for now, replace with a local import:

If there's a `CouncilLayout` import from al-muni rosters, change it to:
```python
# Forward reference — defined in docket.analysis.ocr.rosters (Task 11)
# Until then, expect callers to pass CouncilLayout instances built by the caller.
```

Actually, simpler: move the `CouncilLayout` dataclass definition itself into `layout.py` if it doesn't have other deps, or temporarily inline it. Confirm by reading al-muni's rosters/birmingham.py — it likely has CouncilLayout as a small dataclass.

Run: `grep -n "class CouncilLayout\|@dataclass" ~/projects/al-municipal-meetings/src/muni/analysis/rosters/birmingham.py`

If `CouncilLayout` is a simple dataclass with no deps, copy that class definition to the top of `src/docket/analysis/ocr/layout.py` with a comment `# Will be re-exported from docket.analysis.ocr.rosters in Task 11`. Then change the broken import to a local one.

- [ ] **Step 7.3: Copy and rewrite test**

```bash
cp ~/projects/al-municipal-meetings/tests/unit/test_layout.py ~/docket-pub/tests/unit/ocr/test_layout.py
```

Edit `tests/unit/ocr/test_layout.py`:
- `from muni.analysis.vote_layout` → `from docket.analysis.ocr.layout`
- `from muni.analysis.rosters` → `from docket.analysis.ocr.layout` (for `CouncilLayout` until Task 11 moves it)

- [ ] **Step 7.4: Run the test**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/unit/ocr/test_layout.py -v`
Expected: all tests pass.

- [ ] **Step 7.5: Commit**

```bash
cd ~/docket-pub
git add src/docket/analysis/ocr/layout.py tests/unit/ocr/test_layout.py
git commit -m "feat(ocr): port layout + tests from al-muni

Verbatim port of detect_member_rows() — the spatial name↔dot association
that survives name reflow when council members are absent. CouncilLayout
dataclass temporarily lives here; Task 11 promotes it to rosters.py."
```

---

## Task 8: Port `ocr.py` + tests

**Files:**
- Create: `src/docket/analysis/ocr/ocr.py`
- Create: `tests/unit/ocr/test_ocr.py`

- [ ] **Step 8.1: Copy source**

Run: `cp ~/projects/al-municipal-meetings/src/muni/analysis/vote_ocr.py ~/docket-pub/src/docket/analysis/ocr/ocr.py`

- [ ] **Step 8.2: Verify no internal imports**

Run: `cd ~/docket-pub && grep -n "from muni\|import muni" src/docket/analysis/ocr/ocr.py`
Expected: no output.

- [ ] **Step 8.3: Copy and rewrite test**

```bash
cp ~/projects/al-municipal-meetings/tests/unit/test_ocr.py ~/docket-pub/tests/unit/ocr/test_ocr.py
```

Edit `tests/unit/ocr/test_ocr.py`:
- `from muni.analysis.vote_ocr` → `from docket.analysis.ocr.ocr`

- [ ] **Step 8.4: Run the test**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/unit/ocr/test_ocr.py -v`
Expected: all tests pass.

- [ ] **Step 8.5: Commit**

```bash
cd ~/docket-pub
git add src/docket/analysis/ocr/ocr.py tests/unit/ocr/test_ocr.py
git commit -m "feat(ocr): port count OCR + tests from al-muni

Verbatim port of extract_counts() (per-box digit OCR with proportional
inner padding) + extract_vote_text() (debug-only full-frame dump)."
```

---

## Task 9: Port `sequence.py` + tests

**Files:**
- Create: `src/docket/analysis/ocr/sequence.py`
- Create: `tests/unit/ocr/test_sequence.py`

- [ ] **Step 9.1: Copy source**

Run: `cp ~/projects/al-municipal-meetings/src/muni/analysis/vote_sequence.py ~/docket-pub/src/docket/analysis/ocr/sequence.py`

- [ ] **Step 9.2: Rewrite internal imports**

Run: `cd ~/docket-pub && grep -n "from muni\|import muni" src/docket/analysis/ocr/sequence.py`

For any matches (likely `from muni.analysis.vote_classifier`, `from muni.analysis.frame_io`), rewrite:
- `from muni.analysis.vote_classifier` → `from docket.analysis.ocr.classifier`
- `from muni.analysis.frame_io` → `from docket.analysis.ocr.frame_io`
- `from muni.analysis.vote_sequence` → `from docket.analysis.ocr.sequence`

- [ ] **Step 9.3: Copy and rewrite test**

```bash
cp ~/projects/al-municipal-meetings/tests/unit/test_sequence.py ~/docket-pub/tests/unit/ocr/test_sequence.py
```

Edit `tests/unit/ocr/test_sequence.py` with the same import rewrites.

- [ ] **Step 9.4: Run the test**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/unit/ocr/test_sequence.py -v`
Expected: all tests pass.

- [ ] **Step 9.5: Commit**

```bash
cd ~/docket-pub
git add src/docket/analysis/ocr/sequence.py tests/unit/ocr/test_sequence.py
git commit -m "feat(ocr): port sequence grouping + tests from al-muni

Verbatim port of VoteSequence + group_hits + sequences_from_frames +
find_vote_sequences. Coarse-hit grouping bridges frame_io (ffmpeg) and
the higher-level pipeline orchestrator."
```

---

## Task 10: Port `pipeline.py` (orchestrator) + models module + adapt for new roster shape

**Files:**
- Create: `src/docket/analysis/ocr/_models.py` (NEW — DetectedVote + MemberVote dataclasses)
- Create: `src/docket/analysis/ocr/pipeline.py`

(No new test in this task — the pipeline is exercised end-to-end in Task 14's integration test against a stubbed scanner.)

**Why the `_models` port is its own step:** al-muni's `vote_pipeline.py` does `from muni.models import DetectedVote, MemberVote` — those dataclasses live in `src/muni/models/vote.py`. Without porting that module, the pipeline import chain breaks at first run. We put them at `docket.analysis.ocr._models` (NOT `docket.models.vote`) because docket already has unrelated `Vote`/`MemberVote` dataclasses in `src/docket/models/vote.py` (the N:M shape) — putting OCR's classes there would shadow or collide.

- [ ] **Step 10.0a: Port the DetectedVote/MemberVote dataclasses**

Run: `cp ~/projects/al-municipal-meetings/src/muni/models/vote.py ~/docket-pub/src/docket/analysis/ocr/_models.py`

- [ ] **Step 10.0b: Strip the MatchedVote class from the port**

`muni.models.vote` also defines `MatchedVote` (a DetectedVote enriched with `agenda_item_id` + `confidence` + `matched_item_desc`). docket does NOT use MatchedVote — vote↔item matching goes through `docket.analysis.vote_matcher` and the N:M `vote_agenda_items` join table. Drop MatchedVote and the `replace`-re-export from the copy.

Edit `src/docket/analysis/ocr/_models.py`:

Keep only `MemberVote`, `DetectedVote`, and their imports. The leading `__all__` becomes:

```python
__all__ = ["DetectedVote", "MemberVote"]
```

Delete the `@dataclass MatchedVote(DetectedVote)` block and the `replace` import + re-export.

- [ ] **Step 10.0c: Smoke import**

Run: `cd ~/docket-pub && venv/bin/python -c "from docket.analysis.ocr._models import DetectedVote, MemberVote; v = DetectedVote(timestamp=1.0, vote_result='passed', yeas=8, nays=0, abstentions=0, raw_text='ok'); print('ok', v.timestamp, v.vote_result)"`
Expected: `ok 1.0 passed`

- [ ] **Step 10.1: Copy source**

Run: `cp ~/projects/al-municipal-meetings/src/muni/analysis/vote_pipeline.py ~/docket-pub/src/docket/analysis/ocr/pipeline.py`

- [ ] **Step 10.2: Rewrite internal imports (including the models module)**

Run: `cd ~/docket-pub && grep -n "from muni\|import muni" src/docket/analysis/ocr/pipeline.py`

Rewrite all imports per the renaming table:

| muni name | docket name |
|---|---|
| `muni.analysis.vote_classifier` | `docket.analysis.ocr.classifier` |
| `muni.analysis.vote_header` | `docket.analysis.ocr.header` |
| `muni.analysis.vote_layout` | `docket.analysis.ocr.layout` |
| `muni.analysis.vote_ocr` | `docket.analysis.ocr.ocr` |
| `muni.analysis.vote_sequence` | `docket.analysis.ocr.sequence` |
| `muni.analysis.frame_io` | `docket.analysis.ocr.frame_io` |
| `muni.analysis.rosters.birmingham` | `docket.analysis.ocr.layout` (temp) |
| `muni.models` | `docket.analysis.ocr._models` |

Then add a re-export so callers can import the dataclasses from the pipeline module (matches al-muni's "from muni.analysis.vote_pipeline import DetectedVote" convenience, prevents Task 12/13/14 tests from needing to know about `_models`):

Append to the bottom of `pipeline.py`:

```python
from docket.analysis.ocr._models import DetectedVote, MemberVote  # noqa: F401,E402  re-export

__all__ = list(__all__) if "__all__" in dir() else []
__all__ += ["DetectedVote", "MemberVote", "scan_meeting_for_votes"]
```

(If the file already defines `__all__`, append `"DetectedVote", "MemberVote"` to it instead.)

- [ ] **Step 10.3: Verify `scan_meeting_for_votes` accepts a `layout=` kwarg**

Run: `cd ~/docket-pub && grep -n "def scan_meeting_for_votes" src/docket/analysis/ocr/pipeline.py`

Read the signature. In al-muni it likely defaults to `get_birmingham_layout(None)`. For docket, the caller (Task 14) will pass `roster.layout` explicitly. If the current signature has `get_birmingham_layout` as a default, change the default to `None` and add:

```python
if layout is None:
    raise ValueError(
        "scan_meeting_for_votes requires a CouncilLayout; "
        "callers should build one via docket.analysis.ocr.rosters.build_roster_for_meeting()"
    )
```

This makes the no-roster case fail loudly rather than silently using a stale hardcoded list.

- [ ] **Step 10.4: Smoke import**

Run: `cd ~/docket-pub && venv/bin/python -c "from docket.analysis.ocr.pipeline import scan_meeting_for_votes; print('ok')"`
Expected: `ok`

- [ ] **Step 10.5: Run the full unit suite to ensure no regression**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/unit/ocr -v`
Expected: all OCR unit tests pass.

- [ ] **Step 10.6: Commit**

```bash
cd ~/docket-pub
git add src/docket/analysis/ocr/_models.py src/docket/analysis/ocr/pipeline.py
git commit -m "feat(ocr): port pipeline orchestrator + DetectedVote models from al-muni

Verbatim port of scan_meeting_for_votes() — the Stages A-E orchestrator
(coarse scan → sequence bounding → terminal frame identification → full
terminal OCR → cross-verification). Now requires an explicit
CouncilLayout argument; raises ValueError if None (forces callers to
build one from the live roster, no stale hardcoded fallback).

Also ports DetectedVote + MemberVote dataclasses to
docket.analysis.ocr._models (NOT docket.models — would collide with
docket's existing N:M Vote/MemberVote shape). MatchedVote dropped:
vote↔item matching goes through docket.analysis.vote_matcher and the
vote_agenda_items join table, not a single-FK shape."
```

---

## Task 11: New `rosters.py` — `OCRRoster` + `build_roster_for_meeting`

**Files:**
- Create: `src/docket/analysis/ocr/rosters.py`
- Modify: `src/docket/analysis/ocr/layout.py` (remove temp `CouncilLayout`; re-import from rosters)
- Create: `tests/unit/ocr/test_rosters.py`

- [ ] **Step 11.1: Write the test first (TDD)**

Create `tests/unit/ocr/test_rosters.py`:

```python
"""Unit tests for the runtime roster builder.

Covers boundary cases the spec called out:
- transition-date inclusivity (half-open range)
- duplicate surnames (deterministic ordering)
- empty council (no rows)
"""
from datetime import date

import pytest

from docket.analysis.ocr.rosters import (
    OCRRoster,
    CouncilLayout,
    build_roster_for_meeting,
    _to_initial_lastname,
)


def test_to_initial_lastname_simple():
    assert _to_initial_lastname("Carole Smitherman") == "C. Smitherman"


def test_to_initial_lastname_middle_name():
    assert _to_initial_lastname("Jonathan Q Public") == "J. Public"


def test_to_initial_lastname_single_token_passthrough():
    # Defensive: never crash, return as-is so the fuzzy matcher can still try.
    assert _to_initial_lastname("Madonna") == "Madonna"


def test_build_roster_meeting_before_transition(seeded_bham_meeting_2024):
    """Meeting on 2024-06-01 yields the pre-transition council."""
    roster = build_roster_for_meeting(seeded_bham_meeting_2024.id)
    assert isinstance(roster, OCRRoster)
    assert isinstance(roster.layout, CouncilLayout)
    assert len(roster.layout.name_list) >= 7   # BHM had a 7-member council pre-transition
    # member_map keys must match name_list exactly
    assert set(roster.member_map.keys()) == set(roster.layout.name_list)


def test_build_roster_meeting_after_transition(seeded_bham_meeting_2026):
    """Meeting on 2026-05-19 yields the post-2025-10-28 council."""
    roster = build_roster_for_meeting(seeded_bham_meeting_2026.id)
    # Pick a known post-transition member to assert presence
    # (caller's seed fixture controls these names — update if seed changes)
    assert any("Hilliard" in n for n in roster.layout.name_list)


def test_boundary_term_end_exclusive(seeded_term_end_boundary):
    """A member whose term_end falls exactly on the meeting date must NOT
    appear (the half-open `< term_end + 1day` predicate must exclude them
    if their successor's term_start is the same date)."""
    outgoing_id, incoming_id, meeting_id = seeded_term_end_boundary
    roster = build_roster_for_meeting(meeting_id)
    assert incoming_id in roster.member_map.values()
    assert outgoing_id not in roster.member_map.values()


def test_deterministic_ordering_duplicate_surname(seeded_duplicate_surname):
    """Two members with the same surname must both appear, ordered by
    name → district_id → id."""
    roster = build_roster_for_meeting(seeded_duplicate_surname.meeting_id)
    name_list = roster.layout.name_list
    # Both Smithermans should be present
    smithermans = [n for n in name_list if n.endswith("Smitherman")]
    assert len(smithermans) == 2


def test_empty_council_returns_empty_layout(seeded_empty_meeting):
    """Meeting where no council members are active returns empty layout (no crash)."""
    roster = build_roster_for_meeting(seeded_empty_meeting.id)
    assert roster.layout.name_list == []
    assert roster.member_map == {}
```

Fixtures (`seeded_bham_meeting_2024`, etc.) should be added to `tests/integration/conftest.py` — they need DB writes. Move this test to `tests/integration/test_rosters.py` if simpler, or use the existing integration fixture pattern (see `tests/integration/conftest.py` for the `temp_db`-style fixtures).

**Decision: move to `tests/integration/test_rosters.py`** because `build_roster_for_meeting` touches the DB. Re-create the file at that path; delete the unit one.

```bash
mv ~/docket-pub/tests/unit/ocr/test_rosters.py ~/docket-pub/tests/integration/test_rosters.py
```

And add fixtures to `tests/integration/conftest.py` (read the existing conftest first for the seed-helper pattern; the BHM seed is already in migration 005 / 007 — the new fixtures can build on those by inserting one extra meeting with a known date).

- [ ] **Step 11.1b: Create the full fixture set in `conftest.py`**

Read `tests/integration/conftest.py` first to see the existing seeding convention (`db_cursor()`, transaction rollback per test, etc.). Then append the block below. All Task 11 / 12 / 13 / 16 fixtures live here in one place so the engineer doesn't have to invent the surrounding plumbing.

Append to `tests/integration/conftest.py`:

```python
import pytest
from datetime import date, timedelta
from docket.db import db_cursor
from docket.analysis.ocr.rosters import build_roster_for_meeting


# ---------------------------------------------------------------------------
# Municipality + meeting seeds
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded_birmingham():
    """Birmingham is already seeded by migration 002. Return its id."""
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
        row = cur.fetchone()
        if row is None:
            pytest.fail("Birmingham municipality not seeded — run migrations first.")
        return row["id"]


def _insert_meeting(muni_id: int, *, meeting_date, external_id: str = "9999",
                    title: str = "Test Meeting", is_hidden: bool = False) -> int:
    """Insert one meeting + processing_status row, return meeting id."""
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, title, meeting_date,
                                     external_id, is_hidden)
                 VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            [muni_id, title, meeting_date, external_id, is_hidden],
        )
        meeting_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO processing_status (meeting_id) VALUES (%s)",
            [meeting_id],
        )
        return meeting_id


@pytest.fixture
def seeded_bham_meeting_2024(seeded_birmingham):
    """A BHM meeting on 2024-06-01 (pre-transition council)."""
    return _insert_meeting(seeded_birmingham, meeting_date="2024-06-01",
                           external_id="1500")


@pytest.fixture
def seeded_bham_meeting_2026(seeded_birmingham):
    """A BHM meeting on 2026-05-19 (post-transition council)."""
    return _insert_meeting(seeded_birmingham, meeting_date="2026-05-19",
                           external_id="1982")


# ---------------------------------------------------------------------------
# Roster boundary fixtures (Task 11)
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded_term_end_boundary(seeded_birmingham):
    """One member whose term_end is exactly the meeting date; one whose
    term_start is the same date. The half-open predicate must include
    only the incoming member.

    Returns (outgoing_id, incoming_id, meeting_id).
    """
    boundary = date(2025, 10, 28)
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO council_members (municipality_id, name, term_start, term_end, active)
                 VALUES (%s, 'Outgoing Test', '2020-01-01', %s, FALSE) RETURNING id""",
            [seeded_birmingham, boundary],
        )
        outgoing_id = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO council_members (municipality_id, name, term_start, term_end, active)
                 VALUES (%s, 'Incoming Test', %s, NULL, TRUE) RETURNING id""",
            [seeded_birmingham, boundary],
        )
        incoming_id = cur.fetchone()["id"]
    meeting_id = _insert_meeting(seeded_birmingham, meeting_date=boundary,
                                  external_id="1888")
    return outgoing_id, incoming_id, meeting_id


@pytest.fixture
def seeded_duplicate_surname(seeded_birmingham):
    """Two active council members sharing the surname 'Smitherman'.
    Returns a namespace with .meeting_id."""
    md = date(2024, 6, 1)
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO council_members (municipality_id, name, term_start, active)
                 VALUES (%s, 'Carole Smitherman', '2020-01-01', TRUE),
                        (%s, 'Charles Smitherman', '2020-01-01', TRUE)""",
            [seeded_birmingham, seeded_birmingham],
        )
    meeting_id = _insert_meeting(seeded_birmingham, meeting_date=md, external_id="1501")

    class _NS:
        pass
    ns = _NS()
    ns.meeting_id = meeting_id
    return ns


@pytest.fixture
def seeded_empty_meeting(seeded_birmingham):
    """Insert a meeting in a year where no council_members rows are active."""
    return _insert_meeting(seeded_birmingham, meeting_date="1990-01-01",
                            external_id="1")


@pytest.fixture
def bham_roster_2026(seeded_bham_meeting_2026):
    """Pre-built OCRRoster for the 2026 meeting — saves re-querying in tests."""
    return build_roster_for_meeting(seeded_bham_meeting_2026)


# ---------------------------------------------------------------------------
# OCR claim fixtures (Task 13)
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded_one_ocr_pending(seeded_birmingham):
    """Single BHM meeting, processing_status video_ocr_scanned=FALSE,
    attempts=0, never attempted."""
    return _insert_meeting(seeded_birmingham,
                           meeting_date=date.today() - timedelta(days=2),
                           external_id="1983")


@pytest.fixture
def seeded_two_ocr_pending(seeded_birmingham):
    """Two pending meetings — used for the concurrent-claim test."""
    m1 = _insert_meeting(seeded_birmingham,
                          meeting_date=date.today() - timedelta(days=3),
                          external_id="1984")
    m2 = _insert_meeting(seeded_birmingham,
                          meeting_date=date.today() - timedelta(days=2),
                          external_id="1985")
    return m1, m2


@pytest.fixture
def seeded_one_ocr_pending_hidden(seeded_birmingham):
    """Pending OCR but is_hidden=TRUE — must be filtered out of the claim CTE."""
    return _insert_meeting(seeded_birmingham,
                           meeting_date=date.today() - timedelta(days=1),
                           external_id="1986",
                           is_hidden=True)


@pytest.fixture
def seeded_one_ocr_pending_old(seeded_birmingham):
    """61 days old — past the 60-day window."""
    return _insert_meeting(seeded_birmingham,
                           meeting_date=date.today() - timedelta(days=61),
                           external_id="1987")


@pytest.fixture
def seeded_one_ocr_pending_event_id(seeded_birmingham):
    """external_id = 'event-12345' — must be filtered by the regex."""
    return _insert_meeting(seeded_birmingham,
                           meeting_date=date.today() - timedelta(days=1),
                           external_id="event-12345")


# ---------------------------------------------------------------------------
# Admin rescan fixtures (Task 16)
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded_meeting_with_mixed_votes(seeded_bham_meeting_2026):
    """A meeting carrying one video_ocr vote (+ member_votes row) and one
    minutes_text vote. Used to verify rescan deletes only the OCR row."""
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO votes
                 (meeting_id, video_timestamp, result, yeas, nays, abstentions,
                  raw_text, confidence, source)
                 VALUES (%s, 100.0, 'passed', 8, 0, 0, 'OCR vote', 'high', 'video_ocr')
                 RETURNING id""",
            [seeded_bham_meeting_2026],
        )
        ocr_vote_id = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO member_votes (vote_id, council_member_id, member_name, position)
                 VALUES (%s, NULL, 'C. Smitherman', 'yes')""",
            [ocr_vote_id],
        )
        cur.execute(
            """INSERT INTO votes
                 (meeting_id, result, yeas, nays, abstentions, raw_text, confidence, source)
                 VALUES (%s, 'passed', 8, 0, 0, 'Minutes vote', 'high', 'minutes_text')""",
            [seeded_bham_meeting_2026],
        )
    return seeded_bham_meeting_2026


@pytest.fixture
def authed_admin_client(client):
    """Flask test client with the admin_user session key set.

    Matches the existing PR #81 admin-test pattern. If conftest already
    exposes an authed-admin client, prefer that and delete this fixture.
    """
    with client.session_transaction() as sess:
        sess["admin_user"] = "test-admin"
    return client
```

**Verification:** before writing test code, run `pytest --collect-only tests/integration/test_rosters.py tests/integration/test_video_ocr_claim.py tests/integration/test_video_ocr_persistence.py tests/integration/test_video_ocr_rescan.py 2>&1 | tail -20` and confirm no `fixture not found` errors. If `client` fixture is missing, look in the project root `conftest.py` for the existing Flask test-app pattern and add a forwarding fixture here.

- [ ] **Step 11.2: Run test — verify it fails**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/integration/test_rosters.py -v`
Expected: ImportError on `from docket.analysis.ocr.rosters import ...`.

- [ ] **Step 11.3: Implement `rosters.py`**

Create `src/docket/analysis/ocr/rosters.py`:

```python
"""Runtime roster builder for the OCR pipeline.

al-muni stored Birmingham's roster in hardcoded `LAYOUT_2021` / `LAYOUT_2025`
constants. docket builds the roster on demand from `council_members`, scoped
by `meeting_date` against `term_start` / `term_end`. The result is an
`OCRRoster` carrying both the `CouncilLayout` (name list for the spatial
matcher) and a `member_map` (OCR string → council_member_id) so the
persistence layer in `docket.services.video_ocr` can resolve members
without re-querying or fuzzy-matching surnames.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from docket.db import db_cursor


@dataclass(frozen=True)
class CouncilLayout:
    """The OCR matcher's view of the active council on a given meeting date."""
    name_list: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OCRRoster:
    """Pair of (layout, member_map). Layout drives the OCR spatial matcher;
    member_map lets the persistence layer resolve OCR names to DB IDs."""
    layout: CouncilLayout
    member_map: dict[str, int]


def _to_initial_lastname(full_name: str) -> str:
    """\"Carole Smitherman\" -> \"C. Smitherman\". Defensive on single-token names."""
    tokens = full_name.split()
    if len(tokens) < 2:
        return full_name
    return f"{tokens[0][0]}. {tokens[-1]}"


def build_roster_for_meeting(meeting_id: int) -> OCRRoster:
    """Construct the OCR roster for a meeting from `council_members`.

    Returns the active Birmingham council on the meeting date with a
    map linking OCR name strings to DB member IDs. The date predicate
    is half-open (`>= term_start AND < term_end + 1 day`) to avoid the
    BETWEEN-inclusivity foot-gun on transition days where one member's
    `term_end` and the successor's `term_start` are the same date.

    Ordering is deterministic by `name`, `district_id`, `id` so tests
    that assert on list contents are stable across runs.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT cm.id, cm.name, cm.district_id
              FROM council_members cm
              JOIN meetings m ON m.municipality_id = cm.municipality_id
             WHERE m.id = %s
               AND m.meeting_date >= cm.term_start
               AND m.meeting_date < COALESCE(cm.term_end, m.meeting_date + INTERVAL '1 day')
             ORDER BY cm.name, cm.district_id, cm.id
            """,
            [meeting_id],
        )
        rows = cur.fetchall()

    member_map: dict[str, int] = {}
    for r in rows:
        ocr_name = _to_initial_lastname(r["name"])
        # If two members produce the same OCR key (rare; same initial + same surname),
        # keep the first by ordering — the matcher works against name_list only,
        # and member_map ties to whichever lookup matched.
        member_map.setdefault(ocr_name, r["id"])

    layout = CouncilLayout(name_list=list(member_map.keys()))
    return OCRRoster(layout=layout, member_map=member_map)
```

- [ ] **Step 11.4: Update `layout.py` to re-import `CouncilLayout`**

Edit `src/docket/analysis/ocr/layout.py`:

Remove the temporary local `CouncilLayout` dataclass added in Task 7. Replace with:

```python
from docket.analysis.ocr.rosters import CouncilLayout  # re-export for back-compat
```

Verify no other code in `layout.py` defines a *different* `CouncilLayout` and that callers' usage is unchanged.

- [ ] **Step 11.5: Run rosters test**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/integration/test_rosters.py -v`
Expected: all rosters tests pass.

- [ ] **Step 11.6: Run full OCR test suite to confirm no regression**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/unit/ocr tests/integration/test_rosters.py -v`
Expected: all green.

- [ ] **Step 11.7: Commit**

```bash
cd ~/docket-pub
git add src/docket/analysis/ocr/rosters.py \
        src/docket/analysis/ocr/layout.py \
        tests/integration/test_rosters.py \
        tests/integration/conftest.py
git commit -m "feat(ocr): runtime roster builder from council_members

OCRRoster carries both CouncilLayout (name list for the OCR matcher)
and member_map (OCR name → council_member_id) so persistence avoids a
second DB round-trip and a class of surname-collision bugs.

Half-open date range (>= term_start AND < term_end + 1day) avoids the
BETWEEN-inclusivity foot-gun on transition days.

Spec: docs/superpowers/specs/2026-05-21-fold-al-muni-ocr-design.md §2"
```

---

## Task 12: Persistence — `persist_detected_votes`

**Files:**
- Create: `src/docket/services/video_ocr.py` (initial — just `persist_detected_votes` + helpers)
- Create: `tests/integration/test_video_ocr_persistence.py`

- [ ] **Step 12.1: Write the test first**

Create `tests/integration/test_video_ocr_persistence.py`:

```python
"""Integration tests for persist_detected_votes — DetectedVote → Postgres."""
from datetime import datetime

import pytest

from docket.analysis.ocr.pipeline import DetectedVote, MemberVote
from docket.db import db_cursor
from docket.services.video_ocr import persist_detected_votes


def _mkvote(
    *,
    timestamp: float,
    result: str = "passed",
    yeas: int = 8, nays: int = 0, abstentions: int = 0,
    member_positions: dict[str, str] | None = None,
) -> DetectedVote:
    """Build a DetectedVote for tests. Field names mirror DetectedVote in pipeline.py."""
    mvs = []
    if member_positions:
        for name, pos in member_positions.items():
            mvs.append(MemberVote(member_name=name, position=pos))
    return DetectedVote(
        timestamp=timestamp,
        vote_result=result,
        yeas=yeas, nays=nays, abstentions=abstentions,
        header_result=result,
        needs_review=False,
        review_reason=None,
        raw_text=f"Motion {result.capitalize()}",
        member_votes=mvs,
    )


def test_persist_single_vote_no_members(seeded_bham_meeting_2026):
    detected = [_mkvote(timestamp=100.0)]
    n = persist_detected_votes(seeded_bham_meeting_2026.id, detected, member_map={})
    assert n == 1
    with db_cursor() as cur:
        cur.execute(
            "SELECT result, yeas, source FROM votes WHERE meeting_id = %s",
            [seeded_bham_meeting_2026.id],
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["source"] == "video_ocr"
    assert rows[0]["yeas"] == 8


def test_persist_member_votes_via_member_map(seeded_bham_meeting_2026, bham_roster_2026):
    """Member-level rows resolve council_member_id via the passed member_map."""
    name = next(iter(bham_roster_2026.member_map.keys()))
    detected = [_mkvote(timestamp=200.0, member_positions={name: "yes"})]
    persist_detected_votes(
        seeded_bham_meeting_2026.id,
        detected,
        member_map=bham_roster_2026.member_map,
    )
    with db_cursor() as cur:
        cur.execute(
            """SELECT mv.council_member_id, mv.position
                 FROM member_votes mv JOIN votes v ON v.id = mv.vote_id
                WHERE v.meeting_id = %s""",
            [seeded_bham_meeting_2026.id],
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["council_member_id"] == bham_roster_2026.member_map[name]
    assert rows[0]["position"] == "yes"


def test_persist_idempotent_on_conflict(seeded_bham_meeting_2026):
    """Re-running with the same (meeting_id, timestamp, source='video_ocr') does NOT duplicate."""
    detected = [_mkvote(timestamp=300.0)]
    persist_detected_votes(seeded_bham_meeting_2026.id, detected, member_map={})
    persist_detected_votes(seeded_bham_meeting_2026.id, detected, member_map={})
    with db_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM votes WHERE meeting_id = %s AND video_timestamp = 300.0",
            [seeded_bham_meeting_2026.id],
        )
        assert cur.fetchone()["n"] == 1


def test_persist_unmatched_member_logs_warning(seeded_bham_meeting_2026, bham_roster_2026, caplog):
    """A member name not in the map is logged and inserted with council_member_id=NULL."""
    detected = [_mkvote(timestamp=400.0, member_positions={"X. Nonexistent": "yes"})]
    persist_detected_votes(
        seeded_bham_meeting_2026.id, detected, member_map=bham_roster_2026.member_map,
    )
    assert "Nonexistent" in caplog.text or "X. Nonexistent" in caplog.text
    with db_cursor() as cur:
        cur.execute(
            """SELECT council_member_id FROM member_votes mv
                 JOIN votes v ON v.id = mv.vote_id
                WHERE v.meeting_id = %s AND v.video_timestamp = 400.0""",
            [seeded_bham_meeting_2026.id],
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["council_member_id"] is None


def test_persist_needs_review_vote_marked_medium_confidence(seeded_bham_meeting_2026):
    """Cross-verification failure (needs_review=True) must NOT inherit the
    column default 'high' — that would silently misrepresent the vote on
    the citizen UI's confidence badges. Mapping: needs_review→'medium',
    clean scan→'high'."""
    clean = _mkvote(timestamp=500.0)
    flagged = _mkvote(timestamp=600.0)
    # Build a flagged DetectedVote manually since _mkvote defaults needs_review=False
    flagged_dv = DetectedVote(
        timestamp=600.0,
        vote_result="passed",
        yeas=8, nays=0, abstentions=0,
        raw_text="Motion Passes",
        member_votes=[],
        header_result="passed",
        needs_review=True,
        review_reason="counts_mismatch",
    )
    persist_detected_votes(seeded_bham_meeting_2026.id, [clean, flagged_dv], member_map={})
    with db_cursor() as cur:
        cur.execute(
            "SELECT video_timestamp, confidence, needs_review FROM votes WHERE meeting_id = %s ORDER BY video_timestamp",
            [seeded_bham_meeting_2026.id],
        )
        rows = cur.fetchall()
    assert len(rows) == 2
    assert rows[0]["video_timestamp"] == 500.0
    assert rows[0]["confidence"] == "high"
    assert rows[0]["needs_review"] is False
    assert rows[1]["video_timestamp"] == 600.0
    assert rows[1]["confidence"] == "medium"
    assert rows[1]["needs_review"] is True
```

Fixture `bham_roster_2026` builds an `OCRRoster` via `build_roster_for_meeting`. Add to `tests/integration/conftest.py`.

- [ ] **Step 12.2: Run test — confirm it fails**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/integration/test_video_ocr_persistence.py -v`
Expected: ImportError on `from docket.services.video_ocr import persist_detected_votes`.

- [ ] **Step 12.3: Implement `persist_detected_votes`**

Create `src/docket/services/video_ocr.py`:

```python
"""Video OCR orchestration service.

This module owns the worker-task seam:
- `persist_detected_votes` — DetectedVote(s) + member_map → votes + member_votes
- `_claim_next_ocr_meeting` (Task 13) — atomic claim of a meeting to OCR
- `_ocr_one_meeting` (Task 14) — full claim/scan/persist orchestration

OCR detection itself lives in `docket.analysis.ocr.pipeline`; this
module is the thin layer that ties it to Postgres.
"""

from __future__ import annotations

import logging
from typing import Iterable

from docket.analysis.ocr.pipeline import DetectedVote
from docket.db import db_cursor

log = logging.getLogger(__name__)


def persist_detected_votes(
    meeting_id: int,
    detected: Iterable[DetectedVote],
    *,
    member_map: dict[str, int],
) -> int:
    """Persist each DetectedVote as one votes row + N member_votes rows.

    Idempotent via the partial unique index
    `idx_votes_ocr_unique (meeting_id, video_timestamp, source='video_ocr')`:
    re-runs with the same timestamps skip via ON CONFLICT DO NOTHING.

    Returns the number of new votes rows inserted (NOT including rows
    skipped by the conflict).

    Member positions whose OCR-name keys are absent from `member_map`
    are logged at WARNING and inserted with `council_member_id = NULL`,
    so the row is still auditable in `member_votes` without an FK lookup.
    """
    inserted = 0
    with db_cursor() as cur:
        for vote in detected:
            # confidence column is `text NOT NULL DEFAULT 'high'`. Cross-verification
            # failures (needs_review=True) MUST drop to 'medium' so the citizen UI's
            # confidence badges don't silently claim the vote is clean. See spec §6.
            confidence = "medium" if vote.needs_review else "high"
            cur.execute(
                """
                INSERT INTO votes (
                    meeting_id, video_timestamp, result,
                    yeas, nays, abstentions,
                    header_result, needs_review, review_reason,
                    raw_text, confidence, source
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'video_ocr')
                ON CONFLICT (meeting_id, video_timestamp, source)
                WHERE source = 'video_ocr'
                DO NOTHING
                RETURNING id
                """,
                [
                    meeting_id,
                    vote.timestamp,
                    vote.vote_result,
                    vote.yeas, vote.nays, vote.abstentions,
                    vote.header_result,
                    vote.needs_review,
                    vote.review_reason,
                    vote.raw_text,
                    confidence,
                ],
            )
            row = cur.fetchone()
            if row is None:
                # Conflict — vote already persisted; skip member_votes too.
                continue
            vote_id = row["id"]
            inserted += 1

            for mv in vote.member_votes:
                ocr_name = mv.member_name
                position = mv.position
                member_id = member_map.get(ocr_name)
                if member_id is None:
                    log.warning(
                        "video_ocr: unmatched member name '%s' on meeting %s vote %s — inserting with NULL council_member_id",
                        ocr_name, meeting_id, vote_id,
                    )
                cur.execute(
                    """
                    INSERT INTO member_votes (vote_id, council_member_id, member_name, position)
                    VALUES (%s, %s, %s, %s)
                    """,
                    [vote_id, member_id, ocr_name, position],
                )
    return inserted
```

(If the actual `votes` schema has different columns than what's listed — confirmed in spec §6's mapping table — adjust the INSERT statement to match. Run `\d votes` against the local DB to verify column names before committing.)

- [ ] **Step 12.4: Verify the `ON CONFLICT` syntax against the partial index**

The unique index in migration 034 is partial (`WHERE source = 'video_ocr'`). PostgreSQL needs the same WHERE in the ON CONFLICT clause to match the index. The SQL above uses `ON CONFLICT (meeting_id, video_timestamp, source) WHERE source = 'video_ocr' DO NOTHING`. Confirm this is valid syntax against the local DB:

```bash
cd ~/docket-pub && venv/bin/python -c "
from docket.db import db_cursor
with db_cursor() as cur:
    cur.execute('''
        INSERT INTO votes (meeting_id, video_timestamp, result, yeas, nays, abstentions, source)
        VALUES (1, 9999.0, 'passed', 1, 0, 0, 'video_ocr')
        ON CONFLICT (meeting_id, video_timestamp, source)
        WHERE source = 'video_ocr'
        DO NOTHING
    ''')
    cur.execute('DELETE FROM votes WHERE video_timestamp = 9999.0 AND source = %s', ('video_ocr',))
print('ON CONFLICT syntax OK')
"
```

Expected: `ON CONFLICT syntax OK` (no exception).

If Postgres rejects the WHERE clause shape, the alternative is to use a unique constraint (not just index) — but partial unique constraints aren't supported in PG, so the index form is correct. The fix would be to make the conflict target an `ON CONSTRAINT idx_votes_ocr_unique` — try that next.

- [ ] **Step 12.5: Run the test**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/integration/test_video_ocr_persistence.py -v`
Expected: all 4 tests pass.

- [ ] **Step 12.6: Commit**

```bash
cd ~/docket-pub
git add src/docket/services/video_ocr.py \
        tests/integration/test_video_ocr_persistence.py \
        tests/integration/conftest.py
git commit -m "feat(ocr): persist_detected_votes — DetectedVote → Postgres

Single-vote and per-member-vote writes in one pass. ON CONFLICT DO NOTHING
on (meeting_id, video_timestamp, source='video_ocr') makes cron retries
idempotent. Unmatched member-name keys log WARNING + insert with NULL
council_member_id rather than dropping the row.

Spec: docs/superpowers/specs/2026-05-21-fold-al-muni-ocr-design.md §6"
```

---

## Task 13: Claim pattern — `_claim_next_ocr_meeting`

**Files:**
- Modify: `src/docket/services/video_ocr.py` (add `_claim_next_ocr_meeting`)
- Create: `tests/integration/test_video_ocr_claim.py`

- [ ] **Step 13.1: Write the test first — six scenarios from spec §10**

Create `tests/integration/test_video_ocr_claim.py`:

```python
"""Integration tests for the OCR claim pattern.

Six scenarios from spec §10:
1. Concurrent claims pick different meetings.
2. Counter bumps on claim (not on completion).
3. Scan failure path doesn't propagate.
4. Hidden meeting never claimed.
5. 60-day window enforced.
6. event-N external_id never claimed.
"""
from datetime import date, timedelta
from unittest.mock import patch

import psycopg2
import pytest

from docket.db import db_cursor, DATABASE_URL
from docket.services.video_ocr import (
    _claim_next_ocr_meeting,
    _ocr_one_meeting,
    _mark_ocr_failed,
)


def _set_meeting_ocr_state(meeting_id, **kwargs):
    """Test helper — set processing_status OCR fields for a meeting."""
    cols = ', '.join(f"{k} = %s" for k in kwargs)
    with db_cursor() as cur:
        cur.execute(
            f"UPDATE processing_status SET {cols} WHERE meeting_id = %s",
            list(kwargs.values()) + [meeting_id],
        )


def test_concurrent_claims_pick_different_meetings(seeded_two_ocr_pending):
    """Two open connections each call _claim_next_ocr_meeting; one
    gets a meeting, the other gets a DIFFERENT meeting (or None)."""
    m1_id, m2_id = seeded_two_ocr_pending
    claimed = []
    # Use two parallel connections to simulate two workers
    conn_a = psycopg2.connect(DATABASE_URL)
    conn_b = psycopg2.connect(DATABASE_URL)
    try:
        # Both start transactions and try to claim
        with conn_a.cursor() as ca, conn_b.cursor() as cb:
            from docket.services.video_ocr import _CLAIM_SQL
            ca.execute(_CLAIM_SQL)
            row_a = ca.fetchone()
            cb.execute(_CLAIM_SQL)
            row_b = cb.fetchone()
            conn_a.commit()
            conn_b.commit()
            if row_a:
                claimed.append(row_a[0])
            if row_b:
                claimed.append(row_b[0])
    finally:
        conn_a.close()
        conn_b.close()
    assert len(claimed) == 2
    assert claimed[0] != claimed[1]
    assert set(claimed) == {m1_id, m2_id}


def test_counter_bumps_on_claim_not_completion(seeded_one_ocr_pending):
    """Claim bumps attempts; not calling _mark_ocr_complete leaves the
    bumped attempts visible to the next selection."""
    m_id = seeded_one_ocr_pending
    claimed = _claim_next_ocr_meeting()
    assert claimed["id"] == m_id
    with db_cursor() as cur:
        cur.execute(
            "SELECT video_ocr_attempts, video_ocr_last_attempted_at, video_ocr_scanned FROM processing_status WHERE meeting_id = %s",
            [m_id],
        )
        row = cur.fetchone()
    assert row["video_ocr_attempts"] == 1
    assert row["video_ocr_last_attempted_at"] is not None
    assert row["video_ocr_scanned"] is False


def test_24h_backoff_after_failed_claim(seeded_one_ocr_pending):
    """Within 24h of a failed claim, the same meeting is NOT re-claimable."""
    m_id = seeded_one_ocr_pending
    _claim_next_ocr_meeting()  # bumps attempts to 1, last_attempted_at = now
    second_claim = _claim_next_ocr_meeting()
    assert second_claim is None


def test_scan_failure_records_error_does_not_propagate(seeded_one_ocr_pending):
    """When scan_meeting_for_votes raises, _ocr_one_meeting catches it,
    writes the error, and returns dict with 'error' key."""
    m_id = seeded_one_ocr_pending
    claimed = _claim_next_ocr_meeting()
    with patch(
        "docket.services.video_ocr.scan_meeting_for_votes",
        side_effect=RuntimeError("simulated ffmpeg crash"),
    ):
        result = _ocr_one_meeting(claimed)
    assert "error" in result
    assert "simulated ffmpeg crash" in result["error"]
    with db_cursor() as cur:
        cur.execute(
            "SELECT video_ocr_scanned, video_ocr_last_error FROM processing_status WHERE meeting_id = %s",
            [m_id],
        )
        row = cur.fetchone()
    assert row["video_ocr_scanned"] is False
    assert "simulated ffmpeg crash" in row["video_ocr_last_error"]


def test_hidden_meeting_never_claimed(seeded_one_ocr_pending_hidden):
    """A meeting with is_hidden=TRUE is filtered out of the claim CTE."""
    claimed = _claim_next_ocr_meeting()
    assert claimed is None


def test_60day_window_enforced(seeded_one_ocr_pending_old):
    """A meeting with meeting_date 61 days ago is not claimed."""
    claimed = _claim_next_ocr_meeting()
    assert claimed is None


def test_event_external_id_never_claimed(seeded_one_ocr_pending_event_id):
    """Meeting with external_id like 'event-12345' is filtered by the regex."""
    claimed = _claim_next_ocr_meeting()
    assert claimed is None
```

Fixtures `seeded_two_ocr_pending`, `seeded_one_ocr_pending`, etc. seed Birmingham meetings with the appropriate `processing_status` rows. Add to `tests/integration/conftest.py`.

- [ ] **Step 13.2: Run — verify it fails**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/integration/test_video_ocr_claim.py -v`
Expected: ImportError on `_CLAIM_SQL`, `_claim_next_ocr_meeting`.

- [ ] **Step 13.3: Implement `_claim_next_ocr_meeting`**

Append to `src/docket/services/video_ocr.py`:

```python
# Spec §4: claim pattern. Inner CTE locks rows passing the full filter
# set with FOR UPDATE SKIP LOCKED, so concurrent workers never deadlock
# or claim the same meeting. The outer UPDATE bumps attempts before any
# scan runs so a process crash mid-scan still consumes one attempt.
_CLAIM_SQL = """
    WITH candidate AS (
        SELECT ps.meeting_id
          FROM processing_status ps
          JOIN meetings m        ON m.id  = ps.meeting_id
          JOIN municipalities mu ON mu.id = m.municipality_id
         WHERE mu.slug = 'birmingham'
           AND m.external_id ~ '^[0-9]+$'
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
       SET video_ocr_attempts         = ps.video_ocr_attempts + 1,
           video_ocr_last_attempted_at = now()
      FROM candidate
      JOIN meetings m ON m.id = candidate.meeting_id
     WHERE ps.meeting_id = candidate.meeting_id
     RETURNING m.id, m.external_id, m.meeting_date
"""


def _claim_next_ocr_meeting() -> dict | None:
    """Atomically claim the next BHM meeting needing OCR.

    Returns a dict with keys (id, external_id, meeting_date), or None
    if no meeting is currently eligible. The claim itself commits;
    the long-running OCR scan that follows runs without holding any
    DB connection.
    """
    with db_cursor() as cur:
        cur.execute(_CLAIM_SQL)
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "external_id": row["external_id"],
        "meeting_date": row["meeting_date"],
    }


def _mark_ocr_complete(meeting_id: int) -> None:
    """Set video_ocr_scanned=TRUE and clear last error."""
    with db_cursor() as cur:
        cur.execute(
            """UPDATE processing_status
                  SET video_ocr_scanned = TRUE,
                      video_ocr_last_error = NULL
                WHERE meeting_id = %s""",
            [meeting_id],
        )


def _mark_ocr_failed(meeting_id: int, error: str) -> None:
    """Record error text on processing_status; leave video_ocr_scanned=FALSE
    so the 24h backoff applies and the meeting is eligible again on retry."""
    with db_cursor() as cur:
        cur.execute(
            """UPDATE processing_status
                  SET video_ocr_last_error = %s
                WHERE meeting_id = %s""",
            [error[:2000], meeting_id],  # cap stored error to 2000 chars
        )
```

- [ ] **Step 13.4: Run tests — partial pass expected**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/integration/test_video_ocr_claim.py -v -k "claim or counter or 24h or hidden or 60day or event"`
Expected: claim/counter/24h/hidden/60day/event tests pass; the scan_failure test will still fail since `_ocr_one_meeting` doesn't exist yet (Task 14).

- [ ] **Step 13.5: Commit**

```bash
cd ~/docket-pub
git add src/docket/services/video_ocr.py \
        tests/integration/test_video_ocr_claim.py \
        tests/integration/conftest.py
git commit -m "feat(ocr): claim pattern for atomic meeting selection

CTE-based UPDATE-RETURNING with FOR UPDATE SKIP LOCKED on rows passing
the full filter set (BHM + clip-id + not hidden + 60-day window +
attempts<3 + 24h backoff). Counter bumps at claim time so process crashes
mid-scan still consume an attempt and the backoff kicks in.

Spec: docs/superpowers/specs/2026-05-21-fold-al-muni-ocr-design.md §4"
```

---

## Task 14: `_ocr_one_meeting` orchestrator + completion of claim tests

**Files:**
- Modify: `src/docket/services/video_ocr.py` (add `_ocr_one_meeting`)

- [ ] **Step 14.1: Implement `_ocr_one_meeting`**

Append to `src/docket/services/video_ocr.py`:

```python
from docket.analysis.ocr.pipeline import scan_meeting_for_votes
from docket.analysis.ocr.rosters import build_roster_for_meeting

GRANICUS_DOWNLOAD_URL = "https://bhamal.granicus.com/DownloadFile.php?view_id=2"


def _ocr_one_meeting(meeting: dict) -> dict:
    """Build roster → scan video → persist → mark complete.

    All work after roster construction is inside a single try/except:
    scan failures must NOT propagate out and kill the outer for-loop in
    _do_video_ocr. On exception we record the error and return cleanly.
    """
    meeting_id = meeting["id"]
    roster = build_roster_for_meeting(meeting_id)
    video_url = f"{GRANICUS_DOWNLOAD_URL}&clip_id={meeting['external_id']}"

    try:
        detected = scan_meeting_for_votes(
            video_url,
            scan_interval=2,
            meeting_date=meeting["meeting_date"].isoformat() if meeting["meeting_date"] else None,
            layout=roster.layout,
        )
        persist_detected_votes(meeting_id, detected, member_map=roster.member_map)
        _mark_ocr_complete(meeting_id)
        return {"meeting_id": meeting_id, "votes": len(detected)}
    except Exception as e:
        _mark_ocr_failed(meeting_id, str(e))
        log.exception("OCR failed for meeting %s", meeting_id)
        return {"meeting_id": meeting_id, "votes": 0, "error": str(e)}
```

- [ ] **Step 14.2: Run the scan-failure test from Task 13**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/integration/test_video_ocr_claim.py::test_scan_failure_records_error_does_not_propagate -v`
Expected: PASS.

- [ ] **Step 14.3: Run full claim test suite**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/integration/test_video_ocr_claim.py -v`
Expected: all 7 pass.

- [ ] **Step 14.4: Commit**

```bash
cd ~/docket-pub
git add src/docket/services/video_ocr.py
git commit -m "feat(ocr): _ocr_one_meeting — build roster → scan → persist → mark

Try/except wraps the scan + persist sequence (not just persist) so
scan-time failures (ffmpeg crashes, stream truncation, OOM) record the
error and let the outer for-loop continue rather than aborting the run.

Spec: docs/superpowers/specs/2026-05-21-fold-al-muni-ocr-design.md §5"
```

---

## Task 15: Worker task wiring + scheduler registration

**Files:**
- Modify: `src/docket/worker/tasks.py`
- Modify: `src/docket/worker/scheduler.py`
- Create: `tests/unit/worker/test_task_video_ocr.py`

- [ ] **Step 15.1: Write the test first**

Create `tests/unit/worker/test_task_video_ocr.py`:

```python
"""Verify the cron-task wrapper around _do_video_ocr."""
from unittest.mock import patch

from docket.worker.tasks import TASKS, task_video_ocr


def test_video_ocr_in_tasks_dict():
    assert "video_ocr" in TASKS
    assert TASKS["video_ocr"] is task_video_ocr


def test_task_video_ocr_calls_safe_run():
    with patch("docket.worker.tasks._safe_run") as safe_run:
        task_video_ocr()
    safe_run.assert_called_once()
    name, fn = safe_run.call_args.args
    assert name == "video_ocr"


def test_do_video_ocr_processes_up_to_5_meetings():
    """The loop calls _claim_next_ocr_meeting() up to 5 times, exiting
    early if None is returned."""
    from docket.worker.tasks import _do_video_ocr
    calls = [{"id": 1, "external_id": "1", "meeting_date": None},
             {"id": 2, "external_id": "2", "meeting_date": None},
             None]
    with patch("docket.worker.tasks._claim_next_ocr_meeting", side_effect=calls) as claim, \
         patch("docket.worker.tasks._ocr_one_meeting", return_value={"meeting_id": 0, "votes": 0}) as ocr:
        _do_video_ocr()
    assert claim.call_count == 3   # 2 meetings + 1 None
    assert ocr.call_count == 2
```

- [ ] **Step 15.2: Run test — verify import failure**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/unit/worker/test_task_video_ocr.py -v`
Expected: ImportError on `task_video_ocr` from `docket.worker.tasks`.

- [ ] **Step 15.3: Wire the task into `tasks.py`**

Edit `src/docket/worker/tasks.py`. Read the file first; find the pattern used by existing `_do_*` + `task_*` + `TASKS` dict entries. Append:

```python
def _do_video_ocr() -> None:
    """Spec §5: process up to 5 BHM meetings needing OCR per cron tick."""
    from docket.services.video_ocr import _claim_next_ocr_meeting, _ocr_one_meeting

    processed = 0
    for _ in range(5):
        meeting = _claim_next_ocr_meeting()
        if meeting is None:
            break
        result = _ocr_one_meeting(meeting)
        log.info(
            "video_ocr meeting=%s votes=%s%s",
            result["meeting_id"], result.get("votes", 0),
            (" error=" + result["error"]) if "error" in result else "",
        )
        processed += 1
    log.info("video_ocr processed=%d", processed)


def task_video_ocr() -> None:
    _safe_run("video_ocr", _do_video_ocr)
```

And append to the `TASKS` dict (find it near the end of the file):

```python
    "video_ocr":                 task_video_ocr,
```

Re-export the helpers used by the test:

```python
# Re-exports for tests (do not call directly; cron only)
from docket.services.video_ocr import _claim_next_ocr_meeting, _ocr_one_meeting  # noqa: F401
```

- [ ] **Step 15.4: Register in scheduler**

Edit `src/docket/worker/scheduler.py`. Find the block that registers existing CronTrigger jobs (look for `add_job` calls with `CronTrigger`). Add:

```python
sched.add_job(
    TASKS["video_ocr"],
    CronTrigger(hour=6, minute=30, timezone=TZ),
    id="video_ocr",
)
```

(`TZ` is `America/Chicago` — copy the exact variable name used by neighboring `add_job` calls.)

- [ ] **Step 15.5: Run the tests**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/unit/worker/test_task_video_ocr.py -v`
Expected: 3 passed.

- [ ] **Step 15.6: Confirm `--run-once video_ocr` works locally (smoke)**

Run: `cd ~/docket-pub && venv/bin/python -m docket.worker.scheduler --run-once video_ocr 2>&1 | tail -10`
Expected: `video_ocr processed=0` (no eligible meetings on local DB — that's correct; we're just verifying no import/wiring errors).

- [ ] **Step 15.7: Commit**

```bash
cd ~/docket-pub
git add src/docket/worker/tasks.py \
        src/docket/worker/scheduler.py \
        tests/unit/worker/test_task_video_ocr.py
git commit -m "feat(worker): wire video_ocr task at 06:30 CT

Slots between ingest_all (06:00) and ai_items (07:00). Loops up to 5
claim attempts per tick; exits early when no meeting is eligible.
Healthchecks UUID env var is HEALTHCHECK_VIDEO_OCR_UUID (set in Railway
dashboard during deploy).

Spec: docs/superpowers/specs/2026-05-21-fold-al-muni-ocr-design.md §5+§9"
```

---

## Task 16: Admin force-rescan route + template

**Files:**
- Modify: `src/docket/web/admin.py`
- Modify: `src/docket/web/templates/meeting_detail.html`
- Create: `src/docket/web/templates/admin/_rescan_ocr_button.html`
- Create: `tests/integration/test_video_ocr_rescan.py`

- [ ] **Step 16.1: Write the test first**

Create `tests/integration/test_video_ocr_rescan.py`:

```python
"""Integration test for POST /admin/meetings/<id>/rescan-ocr.

Verifies prior OCR votes + member_votes are deleted and processing_status
flags are reset. Minutes-text votes are NOT touched.
"""
import pytest

from docket.db import db_cursor


def test_rescan_deletes_only_video_ocr_votes(authed_admin_client, seeded_meeting_with_mixed_votes):
    """Meeting has both video_ocr and minutes_text votes; rescan deletes
    only the video_ocr ones and resets processing_status flags."""
    meeting_id = seeded_meeting_with_mixed_votes
    resp = authed_admin_client.post(f"/admin/meetings/{meeting_id}/rescan-ocr",
                                     follow_redirects=False)
    assert resp.status_code == 302

    with db_cursor() as cur:
        cur.execute(
            "SELECT source FROM votes WHERE meeting_id = %s ORDER BY source",
            [meeting_id],
        )
        sources = [r["source"] for r in cur.fetchall()]
        cur.execute(
            """SELECT video_ocr_scanned, video_ocr_attempts,
                      video_ocr_last_attempted_at, video_ocr_last_error
                 FROM processing_status WHERE meeting_id = %s""",
            [meeting_id],
        )
        ps = cur.fetchone()
    assert sources == ["minutes_text"]   # video_ocr rows gone, minutes_text retained
    assert ps["video_ocr_scanned"] is False
    assert ps["video_ocr_attempts"] == 0
    assert ps["video_ocr_last_attempted_at"] is None
    assert ps["video_ocr_last_error"] is None


def test_rescan_requires_login(client, seeded_meeting_with_mixed_votes):
    """Unauthenticated POST returns 302 to login (or 403, depending on
    the existing admin auth pattern)."""
    resp = client.post(f"/admin/meetings/{seeded_meeting_with_mixed_votes}/rescan-ocr",
                       follow_redirects=False)
    assert resp.status_code in (302, 403)
```

Fixture `seeded_meeting_with_mixed_votes` seeds a BHM meeting with one `video_ocr` vote (+ member_votes) and one `minutes_text` vote. `authed_admin_client` is the existing pattern from PR #81's admin-route tests.

- [ ] **Step 16.2: Run test — confirm route 404**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/integration/test_video_ocr_rescan.py -v`
Expected: 404 from the test client (route not registered yet).

- [ ] **Step 16.3: Implement the route**

Edit `src/docket/web/admin.py`. Read the existing pattern around PR #81's `/admin/meetings/<id>/hide` endpoint and follow the same structure. Append:

```python
@bp.route("/meetings/<int:meeting_id>/rescan-ocr", methods=["POST"])
def rescan_meeting_ocr(meeting_id: int):
    """Force-rescan: delete prior video_ocr votes for this meeting and
    reset the processing_status flags so the next worker tick re-OCRs.

    Auth: gated by the blueprint-level ``@bp.before_request require_login``
    in src/docket/web/admin.py (line 28). No per-route decorator needed —
    no other admin route in this file uses one.

    Spec §7: necessary because the persistence ON CONFLICT is timestamp-stable;
    an OCR-algorithm bugfix that produces different terminal frames would
    otherwise stack new rows next to the bad ones.
    """
    with db_cursor() as cur:
        # Count what we're about to delete (for flash message)
        cur.execute(
            "SELECT COUNT(*) AS n FROM votes WHERE meeting_id = %s AND source = 'video_ocr'",
            [meeting_id],
        )
        deleted_count = cur.fetchone()["n"]

        cur.execute(
            """DELETE FROM member_votes
                WHERE vote_id IN (
                    SELECT id FROM votes
                     WHERE meeting_id = %s AND source = 'video_ocr'
                )""",
            [meeting_id],
        )
        cur.execute(
            "DELETE FROM votes WHERE meeting_id = %s AND source = 'video_ocr'",
            [meeting_id],
        )
        cur.execute(
            """UPDATE processing_status
                  SET video_ocr_scanned = FALSE,
                      video_ocr_attempts = 0,
                      video_ocr_last_attempted_at = NULL,
                      video_ocr_last_error = NULL
                WHERE meeting_id = %s""",
            [meeting_id],
        )

    flash(f"Cleared {deleted_count} video-OCR vote(s); meeting will be rescanned at the next cron tick.",
          "success")
    return redirect(url_for("public.meeting_detail", meeting_id=meeting_id))
```

(Confirm `flash`, `redirect`, `url_for`, `session` are already imported at the top of `admin.py` — they are, verified at line 9-19. Do NOT add `login_required`; this file uses the blueprint-level gate.)

- [ ] **Step 16.4: Create the rescan button partial**

Create `src/docket/web/templates/admin/_rescan_ocr_button.html`:

```html
{# Admin-only force-rescan button. Included by meeting_detail.html
   when session.get('admin_user') is truthy. Spec §7. #}
<form method="post" action="{{ url_for('admin.rescan_meeting_ocr', meeting_id=meeting.id) }}"
      class="admin-action-form"
      onsubmit="return confirm('Delete all video-OCR votes for this meeting and re-scan? Minutes-PDF votes will be untouched.');">
  {{ csrf_token() if csrf_token is defined }}
  <button type="submit" class="btn btn-warn btn-sm">Re-scan OCR</button>
  {% if processing_status and processing_status.video_ocr_last_error %}
    <span class="admin-ocr-error" title="{{ processing_status.video_ocr_last_error }}">
      Last error: {{ processing_status.video_ocr_last_error[:200] }}{% if processing_status.video_ocr_last_error|length > 200 %}…{% endif %}
    </span>
  {% endif %}
</form>
```

- [ ] **Step 16.5: Include the partial in `meeting_detail.html`**

Edit `src/docket/web/templates/meeting_detail.html`. Find a sensible location (near the admin hide/unhide button from PR #81). Add:

```html
{% if session.get('admin_user') %}
  {% include "admin/_rescan_ocr_button.html" %}
{% endif %}
```

- [ ] **Step 16.6: Run the tests**

Run: `cd ~/docket-pub && venv/bin/python -m pytest tests/integration/test_video_ocr_rescan.py -v`
Expected: both tests pass.

- [ ] **Step 16.7: Commit**

```bash
cd ~/docket-pub
git add src/docket/web/admin.py \
        src/docket/web/templates/admin/_rescan_ocr_button.html \
        src/docket/web/templates/meeting_detail.html \
        tests/integration/test_video_ocr_rescan.py
git commit -m "feat(admin): force-rescan OCR endpoint + button

POST /admin/meetings/<id>/rescan-ocr deletes prior video_ocr votes +
member_votes for the meeting and resets processing_status flags so the
next cron tick re-OCRs from scratch. Minutes-PDF votes are untouched.

Button appears on meeting_detail for authenticated admin users with the
last-error tooltip if a prior scan failed.

Spec: docs/superpowers/specs/2026-05-21-fold-al-muni-ocr-design.md §7"
```

---

## Task 17: Full unit + integration sweep before deploy

- [ ] **Step 17.1: Run the entire test suite**

Run: `cd ~/docket-pub && venv/bin/python -m pytest -x -q 2>&1 | tail -20`
Expected: all green. Note the count increase vs the pre-flight baseline (step 0d).

- [ ] **Step 17.2: Run ruff + format check (whichever the repo uses)**

Run: `cd ~/docket-pub && venv/bin/ruff check src/docket/analysis/ocr src/docket/services/video_ocr.py src/docket/web/admin.py 2>&1 | tail -10`
Expected: no errors.

Run: `cd ~/docket-pub && venv/bin/ruff format --check src/docket/analysis/ocr src/docket/services/video_ocr.py 2>&1 | tail -10`
Expected: `X files already formatted` (or run `ruff format` to fix).

- [ ] **Step 17.3: Confirm the branch is in shape**

Run: `cd ~/docket-pub && git log --oneline main..HEAD`
Expected: ~14 commits matching the Task numbers, each with a clean conventional message.

---

## Task 18: Deploy to Railway + verify

- [ ] **Step 18.1: Confirm Railway healthchecks UUID exists**

Open Healthchecks.io and create a new check named `video_ocr` if missing. Copy its UUID.

- [ ] **Step 18.2: Add `HEALTHCHECK_VIDEO_OCR_UUID` to Railway `worker` service env**

Via Railway dashboard: `worker` service → Variables → New Variable:
- Key: `HEALTHCHECK_VIDEO_OCR_UUID`
- Value: `<the UUID from step 18.1>`

- [ ] **Step 18.3: Push and open PR**

```bash
cd ~/docket-pub
git push -u origin feat/fold-al-muni-ocr
gh pr create --title "feat: fold al-muni video OCR into docket worker" \
             --body "$(cat <<'EOF'
## Summary
- Ports the video-OCR vote-extraction pipeline from `thinkdarrell/al-municipal-meetings` into `docket.analysis.ocr`.
- New worker task `video_ocr` at 06:30 CT scans new BHM meetings using the Claim pattern (atomic UPDATE-RETURNING, no long-held locks).
- Admin force-rescan endpoint at `/admin/meetings/<id>/rescan-ocr` for OCR-bugfix correction cycles.
- Migration 034 adds `video_ocr_*` columns to `processing_status` and a partial unique index on `votes` for ON CONFLICT idempotency.

## Test plan
- [ ] CI passes (unit + integration)
- [ ] On Railway deploy, verify `docker logs` shows `ffmpeg` + `tesseract` available
- [ ] `railway ssh --service worker "python -m docket.worker.scheduler --run-once video_ocr"` returns `video_ocr processed=N` cleanly
- [ ] Confirm migration 034 applied
- [ ] Smoke test: admin rescan on meeting 2232 → cron re-OCRs → 5 votes re-appear with `source='video_ocr'`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 18.4: After PR merges to main, deploy**

```bash
cd ~/docket-pub
git checkout main && git pull
railway up --service docket-web --detach
railway up --service worker --detach
```

- [ ] **Step 18.5: Verify migration applied**

Run: `cd ~/docket-pub && railway ssh --service worker "python -m docket.migrations.runner --status" 2>&1 | tail -5`
Expected: `034_video_ocr_processing_status [applied]`.

- [ ] **Step 18.6: Verify ffmpeg + tesseract in container**

Run: `cd ~/docket-pub && railway ssh --service worker "which ffmpeg && which tesseract && tesseract --version 2>&1 | head -1"`
Expected: both paths resolve, tesseract version line printed.

---

## Task 19: Smoke test against meeting 2232 + update CLAUDE.md

- [ ] **Step 19.1: Admin force-rescan on meeting 2232 (via web)**

Open the production site, log in to admin, navigate to meeting 2232 (BHM 5/19), click "Re-scan OCR". Confirm the flash message says "Cleared 5 video-OCR vote(s)".

- [ ] **Step 19.2: Trigger the worker task once to pick it up**

Run: `cd ~/docket-pub && railway ssh --service worker "python -m docket.worker.scheduler --run-once video_ocr" 2>&1 | tail -15`
Expected: `video_ocr meeting=2232 votes=5 ... video_ocr processed=1`.

- [ ] **Step 19.3: Verify parity with the manual import path**

Run: `cd ~/docket-pub && DATABASE_URL=$(railway variables --service docket-web --kv 2>/dev/null | grep '^DATABASE_PUBLIC_URL=' | cut -d= -f2-) venv/bin/python -c "
from docket.db import db_cursor
with db_cursor() as cur:
    cur.execute('''
        SELECT v.id, v.result, v.yeas, v.nays, v.video_timestamp, v.source, v.needs_review,
               (SELECT COUNT(*) FROM member_votes mv WHERE mv.vote_id = v.id) AS mvs
        FROM votes v WHERE v.meeting_id = 2232 ORDER BY v.video_timestamp
    ''')
    for r in cur.fetchall():
        print(r)
"`

Expected: 5 votes, same timestamps (1888, 2294, 2461, 2485, 2655 — recorded from this evening's al-muni run), each with member_votes attached.

- [ ] **Step 19.4: Update CLAUDE.md status table**

Edit `~/docket-pub/CLAUDE.md`. Add a new row to the status table:

```markdown
| Video OCR (folded into worker) | Done | `src/docket/analysis/ocr/` subpackage ported from al-muni 2026-05-21. New `video_ocr` cron at 06:30 CT scans new BHM meetings via the Claim pattern (no SQLite bounce, no operator). Admin force-rescan at `/admin/meetings/<id>/rescan-ocr` for OCR-bugfix correction cycles. Migration 034 adds processing_status columns + partial unique index on votes. `scripts/import_video_ocr.py` is deprecated (kept for one cycle as schema-mapping reference). |
```

Also append a "Key decisions" bullet:

```markdown
- **Video OCR pipeline:** ported from al-municipal-meetings into `docket.analysis.ocr` on 2026-05-21. al-muni stays alive as a research sandbox; full repo absorption is a future decision. OCR roster is built at runtime from `council_members` (no hardcoded layouts). Claim pattern (UPDATE-RETURNING + CTE with `FOR UPDATE SKIP LOCKED`) avoids holding row locks during multi-minute scans. Idempotency via `idx_votes_ocr_unique` partial unique index (`meeting_id, video_timestamp, source='video_ocr'`). Force-rescan deletes prior video_ocr votes before reset — necessary because ON CONFLICT is timestamp-stable and an algorithm bugfix could produce different terminal frames.
```

- [ ] **Step 19.5: Commit CLAUDE.md update**

```bash
cd ~/docket-pub
git checkout -b chore/claude-md-ocr-fold
git add CLAUDE.md
git commit -m "docs(CLAUDE): add video OCR fold to status table + decisions

Folded 2026-05-21. Now self-sufficient on docket worker; al-muni stays
as research sandbox. Documents the Claim pattern, idempotency contract,
and force-rescan rationale for future agents."
git push -u origin chore/claude-md-ocr-fold
gh pr create --title "docs: CLAUDE.md — record video OCR fold" --body "Updates status table + key-decisions section after 2026-05-21 OCR fold." --base main
```

---

## Plan complete

After Task 19 merges, the worker is self-sufficient on Birmingham vote OCR. Next steps (out of scope for this plan):

- **Task #3** in the broader work list — the OCR URL/link failure-mode fix, now landable directly in docket with TDD against fixtures.
- **Path B decision** — whether to archive al-muni (it stays as research sandbox until decided otherwise).
- **`scripts/import_video_ocr.py` removal** — keep one full cycle to confirm parity, then delete in a tiny follow-up PR.
