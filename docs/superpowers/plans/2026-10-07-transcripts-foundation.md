# Meeting Transcripts Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the schema, the desktop GPU producer, and the public transcript surfaces (transcript page, item excerpt, search, data debt) so Birmingham council meetings have searchable machine transcripts in production.

**Architecture:** A standalone `transcriber/` package runs faster-whisper plus pyannote inside Docker on the Lenovo Legion and uploads raw timestamped segments with anonymous speaker clusters straight into Railway Postgres through a narrow `transcriber` role. The Flask app reads those rows for a server-rendered transcript page, an item-page excerpt, and a Transcripts search result type. Migration 035 creates all seven tables from the spec so the follow-on plan (worker LLM stages, comparison, admin queue, public "Minutes vs. Video" block) needs no further schema work.

**Tech Stack:** Python 3.10 (Railway) and 3.11 (producer container), Flask + Jinja + HTMX 2, PostgreSQL 18 with pg_trgm, psycopg2, faster-whisper (CTranslate2, CUDA 12.8), pyannote.audio 3.1, ffmpeg, Docker Desktop with WSL2 GPU passthrough, pytest.

**Spec:** `docs/superpowers/specs/2026-10-05-meeting-transcripts-design.md`

**Plan 2 (not here):** Sections 3 and 4 of the spec, the admin queue, the public discrepancy block, the webhook alert, the Haiku A/B, and the ship gate. Written after this plan is reviewed.

## Global Constraints

- Birmingham only. Every claim query filters `mu.slug = 'birmingham'` and `m.external_id ~ '^[0-9]+$'`.
- The Railway image never installs torch, faster-whisper, or pyannote. `requirements.txt` at the repo root is not touched by this plan; the producer has its own `transcriber/requirements.txt`.
- The producer connects only as the `transcriber` role with `sslmode=require`. It never holds the app's `DATABASE_URL`.
- Migration tests and producer integration tests refuse to run when `DATABASE_URL` contains `railway.internal` or `railway.app` (existing pattern in `tests/integration/test_034_migration.py`).
- Word-level timestamps are never written to Postgres. They stay in the producer's JSON archive.
- The `low_speech` guard is an absolute floor: under 180 seconds of detected speech. Never a percentage.
- Whisper initial prompt budget: 224 tokens. The builder uses a conservative 600-character ceiling and refuses to build a longer prompt.
- Zombie claims are released after 6 hours, inside the claim query.
- The resolved speaker name is never part of `transcript_segments.search_vector`.
- Public transcript pages carry the label "Machine-generated transcript" naming the ASR model and linking to `/about/how-we-read-minutes/`.
- Clusters with `confidence < 0.6` or no resolved name display as "Speaker N" where N is the cluster's ordinal by first appearance over the whole meeting. The same cluster gets the same N on the transcript page, the item excerpt, and anywhere else.
- Transcript text is never marked `| safe` in a template. Search headlines are escaped in Python and the highlight markers swapped for `<mark>` afterwards.
- Commits in this repo use `git -c user.email=hello@docket.pub` (house rule) and end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Run tests with `pytest` from the repo root; integration tests need a local `DATABASE_URL` with migrations applied. Producer tests run with `pytest transcriber/tests`.

## Review Focus

Inputs the spec implies but no obvious task test covers, most likely to bite first. Each has a test pinned to the owning task below.

1. **A meeting whose video download returns HTTP 403 or truncates mid-stream.** Expected: the transcript row goes to `failed` with ffmpeg's stderr in `last_error`, attempts incremented, and the producer moves to the next meeting. Pinned to Task 6.
2. **A transcript segment whose text contains `%`, a backslash, a tab, or a newline.** Expected: COPY upload round-trips it byte-for-byte. Pinned to Task 7.
3. **A transcript page requested for a meeting with a `transcripts` row still in `claimed` or `failed`.** Expected: 404 for the transcript URL, and the meeting page shows no Transcript link. Pinned to Task 10.
4. **A search query that is only a `speaker:` token with no words.** Expected: returns that speaker's turns ordered newest first, no SQL error from an empty tsquery. Pinned to Task 12.
5. **An agenda item whose transcript span is empty because no `item_opened` event exists yet and index points did not cover it.** Expected: the item page renders with no "From the video" block, not an empty block. Pinned to Task 11.

## File Structure

**Repo root (Railway app):**
- `src/docket/migrations/035_transcripts.py` — seven tables, indexes, constraints (Task 1)
- `src/docket/migrations/runner.py` — register 035 (Task 1)
- `scripts/sql/create_transcriber_role.sql` — role and grants, run once by an operator (Task 2)
- `tests/fixtures/transcript_pilot/` — pilot transcript, minutes text, `expected.json`, README (Task 3)
- `src/docket/services/transcripts.py` — read-side helpers: `get_public_transcript`, `list_segments`, `speaker_ordinals`, `group_turns`, `excerpt_for_item`, `search_transcripts`, `parse_speaker_token`, `list_transcript_debt` (Tasks 10–13)
- `src/docket/web/public.py` — new route `meeting_transcript`; `item_detail` and `search` and `data_debt` gain context (Tasks 10–13)
- `src/docket/web/templates/transcript.html`, `partials/transcript_body.html`, `partials/transcript_excerpt.html`, `partials/search_transcript_hit.html` (Tasks 10–12)
- `src/docket/web/templates/meeting_detail.html`, `item_detail.html`, `search.html`, `data_debt.html` — small additions (Tasks 10–13)
- `scripts/transcript_scale_check.py` — synthetic fill + ANALYZE + EXPLAIN inside a rolled-back transaction (Task 14)
- `tests/integration/test_035_migration.py`, `tests/integration/test_transcriber_role.py`, `tests/integration/test_transcript_routes.py`, `tests/integration/test_transcript_search.py`, `tests/unit/test_transcript_turns.py`, `tests/unit/test_transcript_search_parse.py`

**`transcriber/` (desktop producer, its own dependency tree):**
- `transcriber/README.md` — Legion runbook (Task 9)
- `transcriber/Dockerfile`, `transcriber/docker-compose.yml`, `transcriber/.env.example`, `transcriber/requirements.txt` (Task 9)
- `transcriber/transcriber/__init__.py`
- `transcriber/transcriber/contract.py` — `Segment`, `Speaker`, `TranscriptOutput` dataclasses and JSON round-trip (Task 4)
- `transcriber/transcriber/prompt.py` — `build_initial_prompt(roster_names, vocabulary, max_chars=600)` (Task 5)
- `transcriber/transcriber/audio.py` — `download_url_for(external_id)`, `fetch_audio(video_url, out_path)`, `sha256_file` (Task 6)
- `transcriber/transcriber/db.py` — `claim_next`, `mark_status`, `heartbeat`, `upload`, `roster_for_meeting` (Task 7)
- `transcriber/transcriber/engine.py` — `Engine` protocol, `FasterWhisperEngine`, `postprocess(raw_segments, raw_words, diarization)`, `speech_seconds`, `insert_silence_markers` (Task 8)
- `transcriber/transcriber/cli.py` — argument parsing and the per-meeting loop (Task 9)
- `transcriber/tests/test_contract.py`, `test_prompt.py`, `test_audio.py`, `test_db.py`, `test_engine_postprocess.py`, `test_cli_loop.py`
- `transcriber/scripts/bringup.sh` — Blackwell acceptance check (Task 9)

---

### Task 1: Migration 035 — seven transcript tables

**Files:**
- Create: `src/docket/migrations/035_transcripts.py`
- Modify: `src/docket/migrations/runner.py` (append to `MIGRATIONS` list after `034_video_ocr_processing_status`)
- Test: `tests/integration/test_035_migration.py`

**Interfaces:**
- Consumes: `docket.migrations.runner.apply_migrations(conn)`, `rollback_migration(conn, version)`, existing tables `meetings`, `council_members`, `agenda_items`.
- Produces: tables `transcripts`, `transcript_speakers`, `transcript_segments`, `minutes_texts`, `meeting_events`, `minutes_discrepancies`, `producer_heartbeats` with the exact columns below. Every later task reads these names.

- [ ] **Step 1: Write the failing migration test**

```python
"""Verify migration 035 creates the seven transcript tables idempotently."""
import pytest
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner

pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Migration test must not run against Railway prod.",
)

TABLES = {
    "transcripts", "transcript_speakers", "transcript_segments",
    "minutes_texts", "meeting_events", "minutes_discrepancies",
    "producer_heartbeats",
}


@pytest.fixture
def fresh_035():
    with db() as conn:
        runner.rollback_migration(conn, 35)
    yield
    with db() as conn:
        runner.apply_migrations(conn)


def _existing_tables() -> set[str]:
    with db_cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
             WHERE table_schema = 'public' AND table_name = ANY(%s)
        """, [sorted(TABLES)])
        return {r["table_name"] for r in cur.fetchall()}


def test_apply_creates_tables(fresh_035):
    with db() as conn:
        runner.apply_migrations(conn)
    assert _existing_tables() == TABLES


def test_apply_is_idempotent(fresh_035):
    with db() as conn:
        runner.apply_migrations(conn)
        runner.apply_migrations(conn)
    with db_cursor() as cur:
        cur.execute("""
            SELECT indexname FROM pg_indexes
             WHERE tablename = 'transcript_segments'
        """)
        idx = {r["indexname"] for r in cur.fetchall()}
    assert {"idx_transcript_segments_search", "idx_transcript_segments_trgm",
            "idx_transcript_segments_item"} <= idx


def test_segments_search_vector_is_generated(fresh_035):
    with db() as conn:
        runner.apply_migrations(conn)
    with db_cursor() as cur:
        cur.execute("""
            SELECT is_generated FROM information_schema.columns
             WHERE table_name = 'transcript_segments' AND column_name = 'search_vector'
        """)
        assert cur.fetchone()["is_generated"] == "ALWAYS"


def test_discrepancy_requires_one_event(fresh_035):
    import psycopg2
    with db() as conn:
        runner.apply_migrations(conn)
    with db_cursor() as cur:
        cur.execute("SELECT id FROM meetings ORDER BY id LIMIT 1")
        meeting_id = cur.fetchone()["id"]
    with pytest.raises(psycopg2.errors.CheckViolation):
        with db_cursor() as cur:
            cur.execute("""
                INSERT INTO minutes_discrepancies
                    (meeting_id, category, severity, title, description, prompt_version)
                VALUES (%s, 'sequence', 'material', 't', 'd', 200)
            """, [meeting_id])


def test_rollback_removes_tables(fresh_035):
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 35)
    assert _existing_tables() == set()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/integration/test_035_migration.py -v`
Expected: FAIL. `rollback_migration(conn, 35)` raises or `apply_migrations` leaves `_existing_tables()` empty because module `035_transcripts` is not in `MIGRATIONS`.

- [ ] **Step 3: Write the migration**

```python
"""Migration 035 — meeting transcripts, event timelines, discrepancies.

Seven tables from docs/superpowers/specs/2026-10-05-meeting-transcripts-design.md
Section 1. `transcripts` is the per-meeting status machine; segments cascade
from it so a re-transcription is delete-and-replace. Speakers and
discrepancies key to `meeting_id`, not to segment ids, so manual work
survives a re-run. The resolved speaker name is deliberately not part of
`transcript_segments.search_vector` (speaker search is a join filter).
Word-level timestamps are not stored.
"""

from __future__ import annotations


SQL_UP = r"""
CREATE TABLE IF NOT EXISTS transcripts (
    id                     SERIAL PRIMARY KEY,
    meeting_id             INTEGER NOT NULL UNIQUE REFERENCES meetings(id) ON DELETE CASCADE,
    status                 TEXT NOT NULL CHECK (status IN (
                               'claimed', 'audio_fetched', 'transcribed', 'uploaded',
                               'speakers_resolved', 'events_extracted', 'compared',
                               'failed', 'needs_review', 'low_speech')),
    version                INTEGER NOT NULL DEFAULT 1,
    engine                 TEXT,
    asr_model              TEXT,
    diarization_model      TEXT,
    audio_duration_s       REAL,
    speech_ratio           REAL,
    word_count             INTEGER,
    producer_host          TEXT,
    claimed_at             TIMESTAMPTZ,
    uploaded_at            TIMESTAMPTZ,
    audio_sha256           TEXT,
    raw_output_path        TEXT,
    stage_attempts         INTEGER NOT NULL DEFAULT 0,
    last_error             TEXT,
    last_attempted_at      TIMESTAMPTZ,
    compare_skipped_reason TEXT,
    needs_review_reason    TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_transcripts_status ON transcripts (status);

CREATE TABLE IF NOT EXISTS transcript_speakers (
    id                    SERIAL PRIMARY KEY,
    meeting_id            INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    cluster_label         TEXT NOT NULL,
    council_member_id     INTEGER REFERENCES council_members(id) ON DELETE SET NULL,
    display_name          TEXT,
    role                  TEXT CHECK (role IN ('council', 'mayor', 'clerk', 'attorney',
                                               'staff', 'public', 'unknown')),
    confidence            REAL,
    method                TEXT CHECK (method IN ('roll_call', 'addressed_by_chair',
                                                 'llm_inference', 'manual')),
    is_manual             BOOLEAN NOT NULL DEFAULT FALSE,
    embedding             REAL[],
    remapped_from_version INTEGER,
    needs_review          BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (meeting_id, cluster_label)
);

CREATE INDEX IF NOT EXISTS idx_transcript_speakers_member
    ON transcript_speakers (council_member_id);

CREATE TABLE IF NOT EXISTS transcript_segments (
    id                BIGSERIAL PRIMARY KEY,
    transcript_id     INTEGER NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    seq               INTEGER NOT NULL,
    start_s           REAL NOT NULL,
    end_s             REAL NOT NULL,
    text              TEXT NOT NULL,
    cluster_label     TEXT,
    speaker_id        INTEGER REFERENCES transcript_speakers(id) ON DELETE SET NULL,
    agenda_item_id    INTEGER REFERENCES agenda_items(id) ON DELETE SET NULL,
    assignment_method TEXT CHECK (assignment_method IN ('index_point', 'event', 'manual')),
    avg_logprob       REAL,
    no_speech_prob    REAL,
    is_silence        BOOLEAN NOT NULL DEFAULT FALSE,
    search_vector     TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    UNIQUE (transcript_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_transcript_segments_search
    ON transcript_segments USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS idx_transcript_segments_trgm
    ON transcript_segments USING GIN (text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_transcript_segments_item
    ON transcript_segments (agenda_item_id);
CREATE INDEX IF NOT EXISTS idx_transcript_segments_speaker
    ON transcript_segments (speaker_id);

CREATE TABLE IF NOT EXISTS minutes_texts (
    id           SERIAL PRIMARY KEY,
    meeting_id   INTEGER NOT NULL UNIQUE REFERENCES meetings(id) ON DELETE CASCADE,
    source_url   TEXT,
    pdf_sha256   TEXT,
    text         TEXT NOT NULL,
    page_offsets JSONB NOT NULL DEFAULT '[]'::jsonb,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS meeting_events (
    id               BIGSERIAL PRIMARY KEY,
    meeting_id       INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    source           TEXT NOT NULL CHECK (source IN ('transcript', 'minutes')),
    seq              INTEGER NOT NULL,
    event_type       TEXT NOT NULL CHECK (event_type IN (
                         'item_opened', 'item_deferred', 'consent_amendment', 'motion',
                         'second', 'amendment', 'vote', 'executive_session_motion',
                         'recusal', 'procedural_ruling', 'roll_call', 'recess',
                         'reconvene', 'adjourn', 'public_comment', 'statement')),
    scope            TEXT NOT NULL DEFAULT 'item' CHECK (scope IN ('item', 'consent_block', 'meeting')),
    agenda_item_refs INTEGER[] NOT NULL DEFAULT '{}',
    actor_member_id  INTEGER REFERENCES council_members(id) ON DELETE SET NULL,
    actor_text       TEXT,
    summary          TEXT NOT NULL,
    detail           JSONB NOT NULL DEFAULT '{}'::jsonb,
    start_s          REAL,
    page             INTEGER,
    char_offset      INTEGER,
    segment_id       BIGINT REFERENCES transcript_segments(id) ON DELETE SET NULL,
    prompt_version   INTEGER NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_meeting_events_meeting
    ON meeting_events (meeting_id, source, seq);

CREATE TABLE IF NOT EXISTS minutes_discrepancies (
    id                    SERIAL PRIMARY KEY,
    meeting_id            INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    agenda_item_id        INTEGER REFERENCES agenda_items(id) ON DELETE SET NULL,
    category              TEXT NOT NULL CHECK (category IN (
                              'vote_outcome', 'omission', 'addition', 'wording',
                              'sequence', 'speaker')),
    severity              TEXT NOT NULL CHECK (severity IN ('material', 'minor')),
    title                 TEXT NOT NULL,
    description           TEXT NOT NULL,
    admin_title           TEXT,
    admin_description     TEXT,
    transcript_event_id   BIGINT REFERENCES meeting_events(id) ON DELETE SET NULL,
    minutes_event_id      BIGINT REFERENCES meeting_events(id) ON DELETE SET NULL,
    transcript_excerpt    TEXT,
    transcript_start_s    REAL,
    minutes_excerpt       TEXT,
    minutes_page          INTEGER,
    citation_match        TEXT NOT NULL DEFAULT 'missing'
                          CHECK (citation_match IN ('exact', 'fuzzy', 'missing')),
    confidence            REAL,
    origin                TEXT NOT NULL DEFAULT 'aligner'
                          CHECK (origin IN ('aligner', 'model_initiated')),
    review_state          TEXT NOT NULL DEFAULT 'proposed'
                          CHECK (review_state IN ('proposed', 'approved', 'rejected',
                                                  'dismissed_by_model', 'stale')),
    previous_review_state TEXT,
    reject_reason         TEXT,
    reviewed_at           TIMESTAMPTZ,
    reviewed_by           TEXT,
    review_note           TEXT,
    prompt_version        INTEGER NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT minutes_discrepancies_has_event
        CHECK (transcript_event_id IS NOT NULL OR minutes_event_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_minutes_discrepancies_review
    ON minutes_discrepancies (review_state, severity, meeting_id);

CREATE TABLE IF NOT EXISTS producer_heartbeats (
    host             TEXT PRIMARY KEY,
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_status      TEXT,
    last_meeting_id  INTEGER,
    producer_version TEXT
);
"""

SQL_DOWN = r"""
DROP TABLE IF EXISTS producer_heartbeats;
DROP TABLE IF EXISTS minutes_discrepancies;
DROP TABLE IF EXISTS meeting_events;
DROP TABLE IF EXISTS minutes_texts;
DROP TABLE IF EXISTS transcript_segments;
DROP TABLE IF EXISTS transcript_speakers;
DROP TABLE IF EXISTS transcripts;
"""
```

- [ ] **Step 4: Register the migration**

In `src/docket/migrations/runner.py`, append to the `MIGRATIONS` list after the `034` line:

```python
    "docket.migrations.035_transcripts",
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/integration/test_035_migration.py -v`
Expected: 5 PASS.

- [ ] **Step 6: Run the whole integration suite to be sure nothing else broke**

Run: `pytest tests/integration -q`
Expected: all PASS (the 035 fixture teardown re-applies migrations, so later tests see the tables).

- [ ] **Step 7: Commit**

```bash
git add src/docket/migrations/035_transcripts.py src/docket/migrations/runner.py tests/integration/test_035_migration.py
git -c user.email=hello@docket.pub commit -m "feat(db): migration 035 transcript, event, and discrepancy tables

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: The `transcriber` Postgres role

**Files:**
- Create: `scripts/sql/create_transcriber_role.sql`
- Test: `tests/integration/test_transcriber_role.py`

**Interfaces:**
- Consumes: the seven tables from Task 1.
- Produces: role `transcriber` with the grants below. Task 7's producer connects as this role. The operator runs the script once against Railway with the app connection (`railway ssh` or `psql $PGURL -v password='...'`).

- [ ] **Step 1: Write the failing test**

```python
"""The transcriber role can write transcript tables and nothing else."""
import pytest
import psycopg2
from docket.config import DATABASE_URL
from docket.db import db

pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Role test must not run against Railway prod.",
)

ROLE_SQL = open("scripts/sql/create_transcriber_role.sql").read()


@pytest.fixture
def transcriber_role():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP ROLE IF EXISTS transcriber")
            cur.execute(ROLE_SQL.replace(":'password'", "'test-pass'"))
    yield
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("REASSIGN OWNED BY transcriber TO CURRENT_USER")
            cur.execute("DROP OWNED BY transcriber")
            cur.execute("DROP ROLE IF EXISTS transcriber")


def _priv(table: str, priv: str) -> bool:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT has_table_privilege('transcriber', %s, %s)", [table, priv])
            return cur.fetchone()[0]


def test_can_write_transcript_tables(transcriber_role):
    for t in ("transcripts", "transcript_segments", "transcript_speakers", "producer_heartbeats"):
        assert _priv(t, "INSERT"), t
        assert _priv(t, "UPDATE"), t
        assert _priv(t, "DELETE"), t


def test_can_read_reference_tables(transcriber_role):
    for t in ("meetings", "municipalities", "council_members", "agenda_items"):
        assert _priv(t, "SELECT"), t
        assert not _priv(t, "UPDATE"), t


def test_cannot_touch_everything_else(transcriber_role):
    for t in ("votes", "ai_runs", "minutes_discrepancies", "meeting_events", "admin_users"):
        assert not _priv(t, "SELECT"), t
        assert not _priv(t, "INSERT"), t
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/integration/test_transcriber_role.py -v`
Expected: FAIL with `FileNotFoundError` for the SQL script.

- [ ] **Step 3: Write the role script**

```sql
-- scripts/sql/create_transcriber_role.sql
-- Run once per database as the app owner:
--   psql "$PGURL" -v password="$(openssl rand -hex 32)" -f scripts/sql/create_transcriber_role.sql
-- Then put the URL in transcriber/.env as
--   TRANSCRIBER_DATABASE_URL=postgresql://transcriber:<password>@<host>:<port>/railway?sslmode=require
-- The role writes only the producer's tables and reads the reference
-- tables the claim query joins. It never sees votes, AI tables, or
-- the review tables.

CREATE ROLE transcriber LOGIN PASSWORD :'password';

GRANT CONNECT ON DATABASE CURRENT_DATABASE TO transcriber;
GRANT USAGE ON SCHEMA public TO transcriber;

GRANT SELECT ON meetings, municipalities, council_members, agenda_items TO transcriber;

GRANT SELECT, INSERT, UPDATE, DELETE
    ON transcripts, transcript_segments, transcript_speakers, producer_heartbeats
    TO transcriber;

GRANT USAGE, SELECT
    ON SEQUENCE transcripts_id_seq, transcript_segments_id_seq, transcript_speakers_id_seq
    TO transcriber;
```

`GRANT CONNECT ON DATABASE CURRENT_DATABASE` is not valid SQL. Replace that line with a `DO` block so the script works on any database name:

```sql
DO $$
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO transcriber', current_database());
END $$;
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/integration/test_transcriber_role.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Document the one-time operator step**

Append to `CLAUDE.md` under the Railway/DB operations section:

```markdown
**Transcriber role (desktop producer):** created once with
`scripts/sql/create_transcriber_role.sql`. It can write only
`transcripts`, `transcript_segments`, `transcript_speakers`, and
`producer_heartbeats`. Rotate by `ALTER ROLE transcriber PASSWORD '...'`
and updating `transcriber/.env` on the Legion.
```

- [ ] **Step 6: Commit**

```bash
git add scripts/sql/create_transcriber_role.sql tests/integration/test_transcriber_role.py CLAUDE.md
git -c user.email=hello@docket.pub commit -m "feat(db): narrow transcriber role for the desktop producer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Pilot fixtures into the repo

**Files:**
- Move: `data/transcript_pilot/*` → `tests/fixtures/transcript_pilot/`
- Create: `tests/fixtures/transcript_pilot/expected.json`, `tests/fixtures/transcript_pilot/README.md`
- Test: `tests/unit/test_pilot_fixture.py`

**Interfaces:**
- Produces: `tests/fixtures/transcript_pilot/2026-02-17_clip1950_item15_small-en.srt`, `.txt`, `2026-02-17_clip1950_minutes.txt`, `expected.json`. Plan 2's live pipeline test and Task 8's post-processing test read these.

- [ ] **Step 1: Write the failing test**

```python
"""The pilot fixture is present, parseable, and names the two expected discrepancies."""
import json
from pathlib import Path

FIX = Path("tests/fixtures/transcript_pilot")


def test_fixture_files_present():
    for name in (
        "2026-02-17_clip1950_item15_small-en.srt",
        "2026-02-17_clip1950_item15_small-en.txt",
        "2026-02-17_clip1950_minutes.txt",
        "expected.json",
        "README.md",
    ):
        assert (FIX / name).exists(), name


def test_expected_names_two_material_discrepancies():
    exp = json.loads((FIX / "expected.json").read_text())
    assert exp["meeting_id"] == 15
    assert exp["granicus_clip_id"] == 1950
    cats = sorted(d["category"] for d in exp["discrepancies"])
    assert cats == ["sequence", "wording"]
    assert all(d["severity"] == "material" for d in exp["discrepancies"])
    wording = next(d for d in exp["discrepancies"] if d["category"] == "wording")
    assert "36-25A-7(a)(4)" in wording["transcript_must_contain"]
    assert "pending litigation" in wording["minutes_must_contain"]


def test_minutes_text_contains_exec_session_passage():
    text = (FIX / "2026-02-17_clip1950_minutes.txt").read_text()
    assert "go into Executive Session" in text
    assert "pending litigation" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_pilot_fixture.py -v`
Expected: FAIL, files not found under `tests/fixtures/transcript_pilot/`.

- [ ] **Step 3: Move the files and write the two new ones**

```bash
mkdir -p tests/fixtures/transcript_pilot
git mv -k data/transcript_pilot/*.srt data/transcript_pilot/*.txt tests/fixtures/transcript_pilot/ 2>/dev/null || mv data/transcript_pilot/*.srt data/transcript_pilot/*.txt tests/fixtures/transcript_pilot/
rm -rf data/transcript_pilot
```

`tests/fixtures/transcript_pilot/expected.json`:

```json
{
  "meeting_id": 15,
  "granicus_clip_id": 1950,
  "meeting_date": "2026-02-17",
  "agenda_item_number": "15",
  "index_points_s": {"item_open": 3309, "motion": 3393, "vote": 3847},
  "clip_offset_note": "The pilot clip starts at roughly 3290 s of the full video; clip timestamps are relative to the clip.",
  "discrepancies": [
    {
      "category": "sequence",
      "severity": "material",
      "summary": "Executive session occurs before the vote on video; minutes record it after the ordinance was adopted.",
      "transcript_must_contain": "we will go into executive session",
      "minutes_must_contain": "said ordinance adopted"
    },
    {
      "category": "wording",
      "severity": "material",
      "summary": "City attorney cites 36-25A-7(a)(4) security plans on video; minutes cite the pending-litigation ground.",
      "transcript_must_contain": "36-25A-7(a)(4)",
      "minutes_must_contain": "pending litigation"
    }
  ],
  "statement_events_expected": [
    "agreement is not in the packet",
    "license plate reader cameras give access to the Alabama criminal justice information system"
  ],
  "known_asr_errors": {"aliyah": "ALEA", "Vassa": "Vasa"}
}
```

`tests/fixtures/transcript_pilot/README.md`:

```markdown
# Transcript pilot fixture — Birmingham City Council, 2026-02-17, Item 15

Source clip: user's Premiere export of the Item 15 window (530.6 s) from
Granicus clip 1950 (docket meeting id 15). Transcribed 2026-10-04 with
whisper.cpp `ggml-small.en` on an M1 Pro (27 s wall-clock). The minutes
text is `pdftotext` of the Granicus MinutesViewer PDF for the same clip.

`expected.json` records the two hand-verified discrepancies the pipeline
must reproduce (spec, "Pilot evidence"). The transcript file still
contains the small model's errors ("aliyah" for ALEA, "Vassa" for Vasa);
that is intentional, it is what name resolution has to fix.

Note the "36-25A-7(a)(4)" string in `expected.json` is the normalized
form; the small model rendered it as "36, 25, a seven a four". The
citation guard's normalizer (Plan 2) is what makes these match.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit/test_pilot_fixture.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/transcript_pilot tests/unit/test_pilot_fixture.py
git -c user.email=hello@docket.pub commit -m "test: commit the 2026-02-17 Item 15 transcript pilot as a fixture

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Producer package scaffold and the JSON contract

**Files:**
- Create: `transcriber/transcriber/__init__.py`, `transcriber/transcriber/contract.py`, `transcriber/requirements.txt`, `transcriber/requirements-dev.txt`, `transcriber/pytest.ini`
- Test: `transcriber/tests/__init__.py`, `transcriber/tests/test_contract.py`

**Interfaces:**
- Produces:
  - `Segment(seq: int, start_s: float, end_s: float, text: str, cluster_label: str | None, avg_logprob: float | None, no_speech_prob: float | None, is_silence: bool = False)`
  - `Speaker(cluster_label: str, embedding: list[float] | None)`
  - `TranscriptOutput(meeting_id: int, version: int, engine: str, asr_model: str, diarization_model: str | None, audio_duration_s: float, speech_seconds: float, audio_sha256: str, segments: list[Segment], speakers: list[Speaker], words_path: str | None)` with `to_json() -> str`, `from_json(s) -> TranscriptOutput`, `word_count -> int`, `speech_ratio -> float`, `validate() -> None` (raises `ContractError`).
  - `CONTRACT_VERSION = 1`.

- [ ] **Step 1: Write the failing tests**

```python
# transcriber/tests/test_contract.py
import json
import pytest
from transcriber.contract import (
    CONTRACT_VERSION, ContractError, Segment, Speaker, TranscriptOutput,
)


def _out(**kw) -> TranscriptOutput:
    base = dict(
        meeting_id=15, version=1, engine="faster-whisper", asr_model="large-v3",
        diarization_model="pyannote/speaker-diarization-3.1",
        audio_duration_s=530.6, speech_seconds=400.0, audio_sha256="ab" * 32,
        segments=[
            Segment(seq=0, start_s=0.0, end_s=4.2, text="Council is my recommendation",
                    cluster_label="SPEAKER_00", avg_logprob=-0.2, no_speech_prob=0.01),
            Segment(seq=1, start_s=4.2, end_s=70.0, text="", cluster_label=None,
                    avg_logprob=None, no_speech_prob=None, is_silence=True),
        ],
        speakers=[Speaker(cluster_label="SPEAKER_00", embedding=[0.1, 0.2])],
        words_path=None,
    )
    base.update(kw)
    return TranscriptOutput(**base)


def test_round_trip_json():
    out = _out()
    again = TranscriptOutput.from_json(out.to_json())
    assert again == out
    assert json.loads(out.to_json())["contract_version"] == CONTRACT_VERSION


def test_word_count_ignores_silence():
    assert _out().word_count == 4


def test_speech_ratio():
    assert _out().speech_ratio == pytest.approx(400.0 / 530.6)


def test_validate_rejects_non_contiguous_seq():
    out = _out()
    out.segments[1].seq = 5
    with pytest.raises(ContractError, match="seq"):
        out.validate()


def test_validate_rejects_end_before_start():
    out = _out()
    out.segments[0].end_s = -1.0
    with pytest.raises(ContractError, match="end_s"):
        out.validate()


def test_validate_rejects_unknown_cluster():
    out = _out()
    out.segments[0].cluster_label = "SPEAKER_99"
    with pytest.raises(ContractError, match="cluster"):
        out.validate()


def test_validate_rejects_bad_sha():
    with pytest.raises(ContractError, match="sha256"):
        _out(audio_sha256="nope").validate()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd transcriber && pytest tests/test_contract.py -v`
Expected: FAIL with `ModuleNotFoundError: transcriber`.

- [ ] **Step 3: Write the scaffold files**

`transcriber/requirements.txt`:

```
faster-whisper>=1.1
pyannote.audio>=3.1
torch>=2.6
torchaudio>=2.6
psycopg2-binary>=2.9
python-dotenv>=1.0
```

WhisperX is deliberately absent. The WhisperX fallback engine is a follow-up task, and `whisperx` pins its own torch, ctranslate2, and faster-whisper versions, which would fight the CUDA 12.8 torch index in the Dockerfile and roughly double the image. Add it in the task that writes the fallback engine, not before.

`transcriber/requirements-dev.txt`:

```
pytest>=7.0
psycopg2-binary>=2.9
python-dotenv>=1.0
```

`transcriber/pytest.ini`:

```ini
[pytest]
testpaths = tests
pythonpath = .
```

`transcriber/transcriber/__init__.py`:

```python
"""docket.pub desktop transcript producer. GPU work only; no LLM calls."""
__version__ = "0.1.0"
```

`transcriber/transcriber/contract.py`:

```python
"""The upload contract between the desktop producer and the Railway side.

One JSON file per meeting. This is the only thing the two sides share.
Word-level timestamps are NOT in this file's segments; they are written to
a sibling file named in ``words_path`` and never uploaded.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

CONTRACT_VERSION = 1
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """The output does not satisfy the contract."""


@dataclass
class Segment:
    seq: int
    start_s: float
    end_s: float
    text: str
    cluster_label: str | None
    avg_logprob: float | None
    no_speech_prob: float | None
    is_silence: bool = False


@dataclass
class Speaker:
    cluster_label: str
    embedding: list[float] | None


@dataclass
class TranscriptOutput:
    meeting_id: int
    version: int
    engine: str
    asr_model: str
    diarization_model: str | None
    audio_duration_s: float
    speech_seconds: float
    audio_sha256: str
    segments: list[Segment] = field(default_factory=list)
    speakers: list[Speaker] = field(default_factory=list)
    words_path: str | None = None

    @property
    def word_count(self) -> int:
        return sum(len(s.text.split()) for s in self.segments if not s.is_silence)

    @property
    def speech_ratio(self) -> float:
        if self.audio_duration_s <= 0:
            return 0.0
        return self.speech_seconds / self.audio_duration_s

    def validate(self) -> None:
        if not _SHA_RE.match(self.audio_sha256):
            raise ContractError("audio_sha256 must be 64 lowercase hex chars")
        labels = {sp.cluster_label for sp in self.speakers}
        for i, s in enumerate(self.segments):
            if s.seq != i:
                raise ContractError(f"segment seq must be contiguous from 0; got {s.seq} at {i}")
            if s.end_s < s.start_s or s.start_s < 0:
                raise ContractError(f"segment {i}: end_s {s.end_s} before start_s {s.start_s}")
            if s.cluster_label is not None and s.cluster_label not in labels:
                raise ContractError(f"segment {i}: unknown cluster {s.cluster_label}")

    def to_json(self) -> str:
        d = asdict(self)
        d["contract_version"] = CONTRACT_VERSION
        return json.dumps(d, ensure_ascii=False, indent=1)

    @classmethod
    def from_json(cls, s: str) -> "TranscriptOutput":
        d = json.loads(s)
        if d.pop("contract_version", CONTRACT_VERSION) != CONTRACT_VERSION:
            raise ContractError("unsupported contract_version")
        d["segments"] = [Segment(**x) for x in d["segments"]]
        d["speakers"] = [Speaker(**x) for x in d["speakers"]]
        return cls(**d)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd transcriber && pip install -r requirements-dev.txt && pytest tests/test_contract.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add transcriber/
git -c user.email=hello@docket.pub commit -m "feat(transcriber): package scaffold and JSON upload contract

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Whisper initial-prompt builder with a hard budget

**Files:**
- Create: `transcriber/transcriber/prompt.py`
- Test: `transcriber/tests/test_prompt.py`

**Interfaces:**
- Produces: `build_initial_prompt(roster_names: list[str], vocabulary: list[str] = LOCAL_VOCABULARY, max_chars: int = 600) -> str` and `PromptBudgetError`. `LOCAL_VOCABULARY` is a module constant. Task 8 calls this with the roster from Task 7.

- [ ] **Step 1: Write the failing tests**

```python
# transcriber/tests/test_prompt.py
import pytest
from transcriber.prompt import LOCAL_VOCABULARY, PromptBudgetError, build_initial_prompt

ROSTER = ["Darrell O'Quinn", "Valerie Abbott", "Hunter Williams", "Carol Clarke",
          "LaTonya Tate", "Crystal Smitherman", "Wardine Alexander", "Clinton Woods",
          "J.T. Smith"]


def test_roster_names_come_first_then_vocabulary():
    p = build_initial_prompt(ROSTER)
    assert p.startswith("Birmingham City Council. Councilors: Darrell O'Quinn, Valerie Abbott")
    assert "ALEA" in p and "Woodlawn" in p
    assert p.index("O'Quinn") < p.index("ALEA")


def test_within_budget():
    assert len(build_initial_prompt(ROSTER)) <= 600


def test_vocabulary_is_trimmed_before_roster():
    long_roster = [f"Councilor Namenumber{i:02d} Surnamelong" for i in range(14)]
    p = build_initial_prompt(long_roster, max_chars=600)
    assert len(p) <= 600
    assert all(n in p for n in long_roster)


def test_refuses_when_roster_alone_overflows():
    huge = [f"Councilor Averyveryverylongname{i:03d} Surname" for i in range(40)]
    with pytest.raises(PromptBudgetError):
        build_initial_prompt(huge, max_chars=600)


def test_vocabulary_has_no_duplicates():
    assert len(LOCAL_VOCABULARY) == len(set(LOCAL_VOCABULARY))
```

- [ ] **Step 2: Run to verify failure**

Run: `cd transcriber && pytest tests/test_prompt.py -v`
Expected: FAIL, `ModuleNotFoundError: transcriber.prompt`.

- [ ] **Step 3: Write the builder**

```python
"""Build Whisper's initial prompt from the meeting roster plus local vocabulary.

Whisper keeps only the LAST 224 tokens of the initial prompt, so an
overflow silently drops the start. We size by characters with a
conservative ceiling (600 chars is comfortably under 224 BPE tokens for
English names) and refuse to build a prompt that would overflow rather
than let truncation happen quietly. Roster names matter more than the
fixed vocabulary, so vocabulary is trimmed first.
"""
from __future__ import annotations

LOCAL_VOCABULARY: tuple[str, ...] = (
    "ALEA", "CJI", "APC", "Alabama Power", "BJCC", "Woodlawn", "Ensley",
    "Avondale", "Pratt City", "Norwood", "Smithfield", "Titusville", "ADECA",
    "ALDOT", "BJCTA", "Granicus", "Birmingham-Jefferson", "Railroad Park",
    "Red Mountain", "Protective Stadium", "Legion Field", "Crossplex",
    "Flock Safety", "license plate reader", "Mayor Woodfin", "City Attorney",
    "Pro Tem", "ordinance", "resolution", "consent agenda", "executive session",
)

_LEAD = "Birmingham City Council. Councilors: "
_VOCAB_LEAD = " Terms: "


class PromptBudgetError(ValueError):
    """The roster alone does not fit the prompt budget."""


def build_initial_prompt(
    roster_names: list[str],
    vocabulary: tuple[str, ...] | list[str] = LOCAL_VOCABULARY,
    max_chars: int = 600,
) -> str:
    head = _LEAD + ", ".join(roster_names) + "."
    if len(head) > max_chars:
        raise PromptBudgetError(
            f"roster alone is {len(head)} chars; budget is {max_chars}"
        )
    vocab = list(vocabulary)
    while vocab:
        candidate = head + _VOCAB_LEAD + ", ".join(vocab) + "."
        if len(candidate) <= max_chars:
            return candidate
        vocab.pop()
    return head
```

- [ ] **Step 4: Run to verify pass**

Run: `cd transcriber && pytest tests/test_prompt.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add transcriber/transcriber/prompt.py transcriber/tests/test_prompt.py
git -c user.email=hello@docket.pub commit -m "feat(transcriber): roster-first initial prompt with hard budget

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Audio fetch via ffmpeg with the browser user agent

**Files:**
- Create: `transcriber/transcriber/audio.py`
- Test: `transcriber/tests/test_audio.py`

**Interfaces:**
- Produces:
  - `download_url_for(external_id: str) -> str` → `https://bhamal.granicus.com/DownloadFile.php?view_id=2&clip_id=<id>` (same endpoint the OCR pipeline uses in `src/docket/services/video_ocr.py`).
  - `fetch_audio(source: str, out_wav: Path, *, attempts: int = 3, delay_s: float = 5.0, timeout_s: int = 3600, runner=subprocess.run) -> Path` → 16 kHz mono PCM WAV; raises `AudioFetchError(str)` carrying ffmpeg's stderr after the last attempt.
  - `probe_duration(source: str, runner=subprocess.run) -> float`.
  - `sha256_file(path: Path) -> str`.
  - `BROWSER_USER_AGENT` constant identical to `src/docket/analysis/ocr/frame_io.py`.

- [ ] **Step 1: Write the failing tests**

```python
# transcriber/tests/test_audio.py
import hashlib
import subprocess
from pathlib import Path
import pytest
from transcriber.audio import (
    AudioFetchError, BROWSER_USER_AGENT, download_url_for, fetch_audio,
    probe_duration, sha256_file,
)


def test_download_url():
    assert download_url_for("1950") == (
        "https://bhamal.granicus.com/DownloadFile.php?view_id=2&clip_id=1950"
    )


class _FakeRun:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        rc, err = self.results.pop(0)
        if rc == 0 and "-i" in cmd and cmd[-1].endswith(".wav"):
            Path(cmd[-1]).write_bytes(b"RIFF" + b"\0" * 44)
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr=err)


def test_fetch_audio_uses_browser_ua_and_pcm_flags(tmp_path):
    run = _FakeRun([(0, "")])
    out = fetch_audio("https://x/video.mp4", tmp_path / "a.wav", runner=run)
    cmd = run.calls[0]
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-user_agent") + 1] == BROWSER_USER_AGENT
    for flag, val in (("-vn", None), ("-ac", "1"), ("-ar", "16000"), ("-c:a", "pcm_s16le")):
        assert flag in cmd
        if val:
            assert cmd[cmd.index(flag) + 1] == val
    assert out.exists()


def test_fetch_audio_retries_then_raises_with_stderr(tmp_path):
    run = _FakeRun([(1, "HTTP error 403 Forbidden")] * 3)
    with pytest.raises(AudioFetchError, match="403 Forbidden"):
        fetch_audio("https://x/video.mp4", tmp_path / "a.wav", runner=run, delay_s=0)
    assert len(run.calls) == 3


def test_fetch_audio_no_ua_for_local_file(tmp_path):
    run = _FakeRun([(0, "")])
    fetch_audio("/clips/local.mp4", tmp_path / "a.wav", runner=run)
    assert "-user_agent" not in run.calls[0]


def test_probe_duration_parses_ffprobe(tmp_path):
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout="530.600000\n", stderr="")
    assert probe_duration("https://x/video.mp4", runner=run) == pytest.approx(530.6)


def test_sha256_file(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    assert sha256_file(p) == hashlib.sha256(b"hello").hexdigest()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd transcriber && pytest tests/test_audio.py -v`
Expected: FAIL, `ModuleNotFoundError: transcriber.audio`.

- [ ] **Step 3: Write the module**

```python
"""Pull 16 kHz mono audio from a Granicus clip (or a local file) with ffmpeg.

Granicus serves archive video through CloudFront, which answers 403 to
non-browser user agents. Same constant and same download endpoint as the
OCR pipeline in the main repo (src/docket/analysis/ocr/frame_io.py and
src/docket/services/video_ocr.py). Audio only: we never keep video.
"""
from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path

GRANICUS_DOWNLOAD_URL = "https://bhamal.granicus.com/DownloadFile.php?view_id=2"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class AudioFetchError(RuntimeError):
    """ffmpeg could not produce audio; message carries ffmpeg's stderr."""


def download_url_for(external_id: str) -> str:
    return f"{GRANICUS_DOWNLOAD_URL}&clip_id={external_id}"


def _is_http(src: str) -> bool:
    return src.lower().startswith(("http://", "https://"))


def _ua_args(src: str) -> list[str]:
    return ["-user_agent", BROWSER_USER_AGENT] if _is_http(src) else []


def probe_duration(source: str, runner=subprocess.run, timeout_s: int = 120) -> float:
    cmd = ["ffprobe", *_ua_args(source), "-v", "error", "-show_entries",
           "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", source]
    proc = runner(cmd, capture_output=True, text=True, timeout=timeout_s)
    if proc.returncode != 0:
        raise AudioFetchError(f"ffprobe failed: {proc.stderr.strip() or 'no output'}")
    try:
        return float(proc.stdout.strip().splitlines()[0])
    except (IndexError, ValueError):
        raise AudioFetchError(f"ffprobe gave no duration: {proc.stdout!r}") from None


def fetch_audio(
    source: str,
    out_wav: Path,
    *,
    attempts: int = 3,
    delay_s: float = 5.0,
    timeout_s: int = 3600,
    runner=subprocess.run,
) -> Path:
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *_ua_args(source),
           "-i", source, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
           str(out_wav)]
    last_err = ""
    for i in range(attempts):
        proc = runner(cmd, capture_output=True, text=True, timeout=timeout_s)
        if proc.returncode == 0 and out_wav.exists() and out_wav.stat().st_size > 44:
            return out_wav
        last_err = proc.stderr.strip() or f"exit {proc.returncode}"
        if i < attempts - 1:
            time.sleep(delay_s)
    raise AudioFetchError(f"ffmpeg could not read {source}: {last_err}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd transcriber && pytest tests/test_audio.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add transcriber/transcriber/audio.py transcriber/tests/test_audio.py
git -c user.email=hello@docket.pub commit -m "feat(transcriber): ffmpeg audio fetch with browser UA and retries

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Producer database layer — claim, heartbeat, status, upload

**Files:**
- Create: `transcriber/transcriber/db.py`
- Test: `transcriber/tests/test_db.py` (integration; needs `TRANSCRIBER_TEST_DATABASE_URL` or falls back to `DATABASE_URL`; skipped when neither is set or when the URL is Railway)

**Interfaces:**
- Consumes: Task 1 tables; Task 4 `TranscriptOutput`.
- Produces:
  - `connect(url: str) -> psycopg2 connection` (autocommit off).
  - `Claim(transcript_id: int, meeting_id: int, external_id: str, title: str, meeting_date: date, status: str)`.
  - `claim_next(conn, *, since: date, host: str, stale_after_hours: int = 6) -> Claim | None` — serialized with `pg_advisory_xact_lock(hashtext('transcriber_claim'))`; picks newest eligible Birmingham meeting; a row in `transcribed` is returned with that status so the CLI skips to upload.
  - `mark_status(conn, transcript_id: int, status: str, *, error: str | None = None, **fields) -> None` — sets `status`, `updated_at`, optional `last_error`, and any of `audio_sha256`, `audio_duration_s`, `raw_output_path`, `speech_ratio`, `word_count`, `engine`, `asr_model`, `diarization_model`; increments `stage_attempts` when `status == 'failed'`.
  - `heartbeat(conn, host: str, status: str, meeting_id: int | None, version: str) -> None`.
  - `roster_for_meeting(conn, meeting_id: int) -> list[str]` — `council_members` active on `meeting_date` (`term_start <= date AND (term_end IS NULL OR term_end >= date)`), plus the municipality's mayor if present in `council_members`.
  - `upload(conn, out: TranscriptOutput) -> int` — one transaction: delete segments for the transcript, upsert speakers, COPY segments, set `uploaded`; returns segment count. Idempotent on replay.

- [ ] **Step 1: Write the failing tests**

```python
# transcriber/tests/test_db.py
"""Integration tests for the producer's claim/upload layer against a local Postgres
with docket migrations applied (run `python -m docket.migrations.runner` in the main
repo first)."""
import os
from datetime import date
import pytest
import psycopg2

from transcriber.contract import Segment, Speaker, TranscriptOutput
from transcriber import db as tdb

URL = os.environ.get("TRANSCRIBER_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not URL or "railway" in URL, reason="needs a local docket Postgres"
)


@pytest.fixture
def conn():
    c = tdb.connect(URL)
    yield c
    c.rollback()
    c.close()


@pytest.fixture
def bham_meeting(conn):
    """Insert one Birmingham meeting with a numeric external_id; clean up after."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'")
        muni = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO meetings (municipality_id, title, meeting_date, external_id,
                                     video_url, is_hidden)
               VALUES (%s, 'TDB test', %s, '999901',
                       'https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=999901', FALSE)
               RETURNING id""",
            [muni, date(2026, 9, 1)],
        )
        mid = cur.fetchone()[0]
    conn.commit()
    yield mid
    with conn.cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id = %s", [mid])
    conn.commit()


def _output(meeting_id: int) -> TranscriptOutput:
    return TranscriptOutput(
        meeting_id=meeting_id, version=1, engine="faster-whisper", asr_model="large-v3",
        diarization_model="pyannote/speaker-diarization-3.1", audio_duration_s=100.0,
        speech_seconds=80.0, audio_sha256="ab" * 32,
        segments=[
            Segment(0, 0.0, 3.0, "Item 15 passes.", "SPEAKER_00", -0.1, 0.01),
            Segment(1, 3.0, 6.0, "100% sure\\ttab\\there\nnewline % percent \\\\ backslash",
                    "SPEAKER_01", -0.3, 0.02),
            Segment(2, 6.0, 70.0, "", None, None, None, is_silence=True),
        ],
        speakers=[Speaker("SPEAKER_00", [0.1, 0.2]), Speaker("SPEAKER_01", None)],
    )


def test_claim_creates_row_and_returns_newest(conn, bham_meeting):
    c = tdb.claim_next(conn, since=date(2026, 1, 1), host="legion")
    conn.commit()
    assert c is not None and c.meeting_id == bham_meeting
    assert c.external_id == "999901" and c.status == "claimed"
    # Second claim must not return the same meeting (it is now claimed and fresh).
    assert tdb.claim_next(conn, since=date(2026, 1, 1), host="legion") is None
    conn.commit()


def test_claim_respects_since(conn, bham_meeting):
    assert tdb.claim_next(conn, since=date(2026, 10, 1), host="legion") is None


def test_stale_claim_is_reclaimable(conn, bham_meeting):
    c = tdb.claim_next(conn, since=date(2026, 1, 1), host="legion")
    with conn.cursor() as cur:
        cur.execute("UPDATE transcripts SET claimed_at = now() - interval '7 hours' WHERE id=%s",
                    [c.transcript_id])
    conn.commit()
    c2 = tdb.claim_next(conn, since=date(2026, 1, 1), host="legion-2")
    conn.commit()
    assert c2 is not None and c2.transcript_id == c.transcript_id


def test_transcribed_row_claims_straight_to_upload(conn, bham_meeting):
    c = tdb.claim_next(conn, since=date(2026, 1, 1), host="legion")
    tdb.mark_status(conn, c.transcript_id, "transcribed", raw_output_path="/archive/x.json")
    conn.commit()
    c2 = tdb.claim_next(conn, since=date(2026, 1, 1), host="legion")
    conn.commit()
    assert c2.transcript_id == c.transcript_id and c2.status == "transcribed"


def test_mark_failed_increments_attempts_and_keeps_error(conn, bham_meeting):
    c = tdb.claim_next(conn, since=date(2026, 1, 1), host="legion")
    tdb.mark_status(conn, c.transcript_id, "failed", error="ffmpeg could not read: 403 Forbidden")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT status, stage_attempts, last_error FROM transcripts WHERE id=%s",
                    [c.transcript_id])
        status, attempts, err = cur.fetchone()
    assert status == "failed" and attempts == 1 and "403" in err


def test_upload_round_trips_awkward_text_and_is_idempotent(conn, bham_meeting):
    c = tdb.claim_next(conn, since=date(2026, 1, 1), host="legion")
    out = _output(bham_meeting)
    n1 = tdb.upload(conn, out)
    n2 = tdb.upload(conn, out)
    conn.commit()
    assert n1 == n2 == 3
    with conn.cursor() as cur:
        cur.execute("""SELECT s.seq, s.text, s.is_silence, sp.cluster_label
                         FROM transcript_segments s
                         LEFT JOIN transcript_speakers sp ON sp.id = s.speaker_id
                        WHERE s.transcript_id=%s ORDER BY s.seq""", [c.transcript_id])
        rows = cur.fetchall()
        cur.execute("SELECT status, word_count, uploaded_at FROM transcripts WHERE id=%s",
                    [c.transcript_id])
        status, wc, up = cur.fetchone()
        cur.execute("SELECT count(*) FROM transcript_speakers WHERE meeting_id=%s", [bham_meeting])
        n_speakers = cur.fetchone()[0]
    assert len(rows) == 3
    assert rows[1][1] == out.segments[1].text
    assert rows[2][2] is True and rows[2][3] is None
    assert rows[0][3] == "SPEAKER_00"
    assert status == "uploaded" and wc == out.word_count and up is not None
    assert n_speakers == 2


def test_heartbeat_upserts(conn):
    tdb.heartbeat(conn, "legion-test", "idle", None, "0.1.0")
    tdb.heartbeat(conn, "legion-test", "transcribing", 15, "0.1.0")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT last_status, last_meeting_id FROM producer_heartbeats WHERE host='legion-test'")
        assert cur.fetchone() == ("transcribing", 15)
        cur.execute("DELETE FROM producer_heartbeats WHERE host='legion-test'")
    conn.commit()


def test_roster_for_meeting_returns_names(conn, bham_meeting):
    names = tdb.roster_for_meeting(conn, bham_meeting)
    assert isinstance(names, list) and all(isinstance(n, str) for n in names)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd transcriber && DATABASE_URL=postgresql://localhost/docket pytest tests/test_db.py -v`
Expected: FAIL, `ModuleNotFoundError: transcriber.db`.

- [ ] **Step 3: Write the module**

```python
"""Producer-side Postgres access. Connects ONLY as the `transcriber` role.

Claiming is serialized with a transaction-scoped advisory lock instead of
SELECT ... FOR UPDATE, because FOR UPDATE on `meetings` would need UPDATE
privilege the role does not have. Two producers can run at once; the lock
makes the "find newest eligible" + "insert claim" pair atomic.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date

import psycopg2
import psycopg2.extras

from .contract import TranscriptOutput

_UPDATABLE = {"audio_sha256", "audio_duration_s", "raw_output_path", "speech_ratio",
              "word_count", "engine", "asr_model", "diarization_model"}


@dataclass(frozen=True)
class Claim:
    transcript_id: int
    meeting_id: int
    external_id: str
    title: str
    meeting_date: date
    status: str


def connect(url: str):
    return psycopg2.connect(url)


_CANDIDATE_SQL = """
    SELECT m.id AS meeting_id, m.external_id, m.title, m.meeting_date,
           t.id AS transcript_id, t.status
      FROM meetings m
      JOIN municipalities mu ON mu.id = m.municipality_id
      LEFT JOIN transcripts t ON t.meeting_id = m.id
     WHERE mu.slug = 'birmingham'
       AND m.video_url IS NOT NULL
       AND m.is_hidden = FALSE
       AND m.external_id ~ '^[0-9]+$'
       AND m.meeting_date >= %(since)s
       AND (
            t.id IS NULL
         OR t.status = 'transcribed'
         OR (t.status IN ('claimed', 'audio_fetched')
             AND t.claimed_at < now() - make_interval(hours => %(stale)s))
       )
     ORDER BY m.meeting_date DESC, m.id DESC
     LIMIT 1
"""


def claim_next(conn, *, since: date, host: str, stale_after_hours: int = 6) -> Claim | None:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('transcriber_claim'))")
        cur.execute(_CANDIDATE_SQL, {"since": since, "stale": stale_after_hours})
        row = cur.fetchone()
        if row is None:
            return None
        if row["transcript_id"] is None:
            cur.execute(
                """INSERT INTO transcripts (meeting_id, status, producer_host, claimed_at)
                   VALUES (%s, 'claimed', %s, now()) RETURNING id, status""",
                [row["meeting_id"], host],
            )
        else:
            new_status = "transcribed" if row["status"] == "transcribed" else "claimed"
            cur.execute(
                """UPDATE transcripts
                      SET status = %s, producer_host = %s, claimed_at = now(), updated_at = now()
                    WHERE id = %s RETURNING id, status""",
                [new_status, host, row["transcript_id"]],
            )
        t = cur.fetchone()
    return Claim(t["id"], row["meeting_id"], row["external_id"], row["title"],
                 row["meeting_date"], t["status"])


def mark_status(conn, transcript_id: int, status: str, *, error: str | None = None, **fields) -> None:
    bad = set(fields) - _UPDATABLE
    if bad:
        raise ValueError(f"not updatable: {sorted(bad)}")
    sets = ["status = %s", "updated_at = now()", "last_attempted_at = now()"]
    params: list = [status]
    if error is not None:
        sets.append("last_error = %s")
        params.append(error[:4000])
    if status == "failed":
        sets.append("stage_attempts = stage_attempts + 1")
    for k, v in fields.items():
        sets.append(f"{k} = %s")
        params.append(v)
    params.append(transcript_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE transcripts SET {', '.join(sets)} WHERE id = %s", params)


def heartbeat(conn, host: str, status: str, meeting_id: int | None, version: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO producer_heartbeats (host, last_seen_at, last_status, last_meeting_id, producer_version)
               VALUES (%s, now(), %s, %s, %s)
               ON CONFLICT (host) DO UPDATE
                 SET last_seen_at = now(), last_status = EXCLUDED.last_status,
                     last_meeting_id = EXCLUDED.last_meeting_id,
                     producer_version = EXCLUDED.producer_version""",
            [host, status, meeting_id, version],
        )


def roster_for_meeting(conn, meeting_id: int) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT cm.name
                 FROM council_members cm
                 JOIN meetings m ON m.municipality_id = cm.municipality_id
                WHERE m.id = %s
                  AND (cm.term_start IS NULL OR cm.term_start <= m.meeting_date)
                  AND (cm.term_end   IS NULL OR cm.term_end   >= m.meeting_date)
                ORDER BY cm.name""",
            [meeting_id],
        )
        return [r[0] for r in cur.fetchall()]


def _copy_escape(s: str) -> str:
    return (s.replace("\\", "\\\\").replace("\t", "\\t")
             .replace("\n", "\\n").replace("\r", "\\r"))


def upload(conn, out: TranscriptOutput) -> int:
    out.validate()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM transcripts WHERE meeting_id = %s", [out.meeting_id])
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"no transcripts row for meeting {out.meeting_id}; claim first")
        transcript_id = row[0]

        cur.execute("DELETE FROM transcript_segments WHERE transcript_id = %s", [transcript_id])

        speaker_ids: dict[str, int] = {}
        for sp in out.speakers:
            cur.execute(
                """INSERT INTO transcript_speakers (meeting_id, cluster_label, embedding)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (meeting_id, cluster_label) DO UPDATE
                     SET embedding = COALESCE(EXCLUDED.embedding, transcript_speakers.embedding)
                   RETURNING id""",
                [out.meeting_id, sp.cluster_label, sp.embedding],
            )
            speaker_ids[sp.cluster_label] = cur.fetchone()[0]

        buf = io.StringIO()
        for s in out.segments:
            sid = speaker_ids.get(s.cluster_label) if s.cluster_label else None
            buf.write("\t".join([
                str(transcript_id), str(s.seq), repr(float(s.start_s)), repr(float(s.end_s)),
                _copy_escape(s.text),
                s.cluster_label if s.cluster_label else "\\N",
                str(sid) if sid is not None else "\\N",
                repr(float(s.avg_logprob)) if s.avg_logprob is not None else "\\N",
                repr(float(s.no_speech_prob)) if s.no_speech_prob is not None else "\\N",
                "t" if s.is_silence else "f",
            ]) + "\n")
        buf.seek(0)
        cur.copy_expert(
            """COPY transcript_segments
                 (transcript_id, seq, start_s, end_s, text, cluster_label, speaker_id,
                  avg_logprob, no_speech_prob, is_silence)
               FROM STDIN WITH (FORMAT text)""",
            buf,
        )

        cur.execute(
            """UPDATE transcripts
                  SET status = 'uploaded', uploaded_at = now(), updated_at = now(),
                      version = %s, engine = %s, asr_model = %s, diarization_model = %s,
                      audio_duration_s = %s, speech_ratio = %s, word_count = %s,
                      audio_sha256 = %s, last_error = NULL
                WHERE id = %s""",
            [out.version, out.engine, out.asr_model, out.diarization_model,
             out.audio_duration_s, out.speech_ratio, out.word_count, out.audio_sha256,
             transcript_id],
        )
    return len(out.segments)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd transcriber && DATABASE_URL=postgresql://localhost/docket pytest tests/test_db.py -v`
Expected: 8 PASS. (Review Focus item 2 is `test_upload_round_trips_awkward_text_and_is_idempotent`.)

- [ ] **Step 5: Commit**

```bash
git add transcriber/transcriber/db.py transcriber/tests/test_db.py
git -c user.email=hello@docket.pub commit -m "feat(transcriber): claim, heartbeat, status, and COPY upload

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Engine wrapper and deterministic post-processing

**Files:**
- Create: `transcriber/transcriber/engine.py`
- Test: `transcriber/tests/test_engine_postprocess.py`

**Interfaces:**
- Consumes: `build_initial_prompt` (Task 5), `Segment`, `Speaker` (Task 4).
- Produces:
  - `RawSegment(start_s, end_s, text, avg_logprob, no_speech_prob)`; `DiarTurn(start_s, end_s, label)`.
  - `assign_clusters(raw: list[RawSegment], turns: list[DiarTurn]) -> list[str | None]` — majority-overlap label per segment, `None` when no overlap.
  - `insert_silence_markers(segments: list[Segment], audio_duration_s: float, min_gap_s: float = 60.0) -> list[Segment]` — adds `is_silence` rows for gaps ≥ `min_gap_s`, renumbers `seq`.
  - `speech_seconds(raw: list[RawSegment]) -> float`.
  - `LOW_SPEECH_FLOOR_S = 180.0` and `is_low_speech(speech_s: float) -> bool`.
  - `Engine` protocol: `transcribe(wav: Path, initial_prompt: str) -> list[RawSegment]`, `diarize(wav: Path) -> tuple[list[DiarTurn], dict[str, list[float]]]`, properties `name`, `asr_model`, `diarization_model`.
  - `FasterWhisperEngine(model_size="large-v3", device="cuda", compute_type="float16", hf_token=None)` — real implementation; imports torch/faster_whisper/pyannote lazily inside `__init__` so unit tests never import them. Catches `torch.cuda.OutOfMemoryError` on either step, unloads the other model, retries once, and counts `oom_fallbacks`.
  - `build_output(meeting_id, version, engine: Engine, raw, turns, embeddings, audio_duration_s, audio_sha256, words_path) -> TranscriptOutput`.

- [ ] **Step 1: Write the failing tests**

```python
# transcriber/tests/test_engine_postprocess.py
import pytest
from transcriber.contract import Segment
from transcriber.engine import (
    LOW_SPEECH_FLOOR_S, DiarTurn, RawSegment, assign_clusters, insert_silence_markers,
    is_low_speech, speech_seconds,
)


def test_assign_clusters_majority_overlap():
    raw = [RawSegment(0.0, 10.0, "a", -0.1, 0.0), RawSegment(10.0, 12.0, "b", -0.1, 0.0),
           RawSegment(500.0, 501.0, "c", -0.1, 0.0)]
    turns = [DiarTurn(0.0, 4.0, "SPEAKER_00"), DiarTurn(4.0, 12.0, "SPEAKER_01")]
    assert assign_clusters(raw, turns) == ["SPEAKER_01", "SPEAKER_01", None]


def test_insert_silence_markers_adds_rows_for_long_gaps_only():
    segs = [Segment(0, 0.0, 5.0, "x", "S0", None, None),
            Segment(1, 5.0, 8.0, "y", "S0", None, None),
            Segment(2, 100.0, 103.0, "z", "S1", None, None)]
    out = insert_silence_markers(segs, audio_duration_s=200.0, min_gap_s=60.0)
    assert [s.seq for s in out] == [0, 1, 2, 3, 4]
    assert out[2].is_silence and out[2].start_s == 8.0 and out[2].end_s == 100.0
    assert out[4].is_silence and out[4].start_s == 103.0 and out[4].end_s == 200.0
    assert not out[1].is_silence  # 5.0 -> 5.0 gap of zero


def test_speech_seconds_sums_segments():
    raw = [RawSegment(0.0, 10.0, "a", None, None), RawSegment(20.0, 25.5, "b", None, None)]
    assert speech_seconds(raw) == pytest.approx(15.5)


def test_low_speech_is_absolute_floor():
    assert LOW_SPEECH_FLOOR_S == 180.0
    assert is_low_speech(120.0)          # 2 min of business in a 10 min meeting is NOT low...
    assert not is_low_speech(180.0)      # ...unless under 3 minutes total speech
    assert not is_low_speech(10_000.0)
```

Correct the misleading comment in the fourth test before running: `is_low_speech(120.0)` is True because 120 s is under the 180 s floor; a short meeting with at least three minutes of speech uploads. Write the test as:

```python
def test_low_speech_is_absolute_floor():
    assert LOW_SPEECH_FLOOR_S == 180.0
    assert is_low_speech(120.0)       # under three minutes of speech: dead or near-empty stream
    assert not is_low_speech(180.0)   # a 10-minute emergency session with 3 min of business uploads
    assert not is_low_speech(10_000.0)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd transcriber && pytest tests/test_engine_postprocess.py -v`
Expected: FAIL, `ModuleNotFoundError: transcriber.engine`.

- [ ] **Step 3: Write the module**

```python
"""ASR + diarization engine and the pure post-processing around it.

Everything that touches torch is inside FasterWhisperEngine and imported
lazily, so unit tests run on a laptop with no GPU libraries installed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .contract import Segment, Speaker, TranscriptOutput

log = logging.getLogger(__name__)

LOW_SPEECH_FLOOR_S = 180.0


@dataclass
class RawSegment:
    start_s: float
    end_s: float
    text: str
    avg_logprob: float | None
    no_speech_prob: float | None


@dataclass
class DiarTurn:
    start_s: float
    end_s: float
    label: str


class Engine(Protocol):
    name: str
    asr_model: str
    diarization_model: str | None

    def transcribe(self, wav: Path, initial_prompt: str) -> list[RawSegment]: ...
    def diarize(self, wav: Path) -> tuple[list[DiarTurn], dict[str, list[float]]]: ...


def speech_seconds(raw: list[RawSegment]) -> float:
    return float(sum(max(0.0, r.end_s - r.start_s) for r in raw))


def is_low_speech(speech_s: float) -> bool:
    return speech_s < LOW_SPEECH_FLOOR_S


def assign_clusters(raw: list[RawSegment], turns: list[DiarTurn]) -> list[str | None]:
    out: list[str | None] = []
    for r in raw:
        overlap: dict[str, float] = {}
        for t in turns:
            o = min(r.end_s, t.end_s) - max(r.start_s, t.start_s)
            if o > 0:
                overlap[t.label] = overlap.get(t.label, 0.0) + o
        out.append(max(overlap, key=overlap.get) if overlap else None)
    return out


def insert_silence_markers(segments: list[Segment], audio_duration_s: float,
                           min_gap_s: float = 60.0) -> list[Segment]:
    result: list[Segment] = []
    cursor = 0.0
    for s in sorted(segments, key=lambda x: x.start_s):
        if s.start_s - cursor >= min_gap_s:
            result.append(Segment(0, cursor, s.start_s, "", None, None, None, is_silence=True))
        result.append(s)
        cursor = max(cursor, s.end_s)
    if audio_duration_s - cursor >= min_gap_s:
        result.append(Segment(0, cursor, audio_duration_s, "", None, None, None, is_silence=True))
    for i, s in enumerate(result):
        s.seq = i
    return result


def build_output(meeting_id: int, version: int, engine: Engine, raw: list[RawSegment],
                 turns: list[DiarTurn], embeddings: dict[str, list[float]],
                 audio_duration_s: float, audio_sha256: str,
                 words_path: str | None) -> TranscriptOutput:
    labels = assign_clusters(raw, turns)
    segs = [Segment(i, r.start_s, r.end_s, r.text.strip(), lab, r.avg_logprob, r.no_speech_prob)
            for i, (r, lab) in enumerate(zip(raw, labels))]
    segs = insert_silence_markers(segs, audio_duration_s)
    used = {s.cluster_label for s in segs if s.cluster_label}
    speakers = [Speaker(lab, embeddings.get(lab)) for lab in sorted(used)]
    out = TranscriptOutput(
        meeting_id=meeting_id, version=version, engine=engine.name, asr_model=engine.asr_model,
        diarization_model=engine.diarization_model, audio_duration_s=audio_duration_s,
        speech_seconds=speech_seconds(raw), audio_sha256=audio_sha256,
        segments=segs, speakers=speakers, words_path=words_path,
    )
    out.validate()
    return out


class FasterWhisperEngine:
    """faster-whisper for ASR, pyannote 3.1 for diarization. Both stay resident."""

    name = "faster-whisper"

    def __init__(self, model_size: str = "large-v3", device: str = "cuda",
                 compute_type: str = "float16", hf_token: str | None = None,
                 batch_size: int = 16):
        import torch  # noqa: F401  (lazy; proves CUDA stack is importable)
        from faster_whisper import BatchedInferencePipeline, WhisperModel

        self.asr_model = model_size
        self.device = device
        self.batch_size = batch_size
        self._whisper = WhisperModel(model_size, device=device, compute_type=compute_type)
        self._batched = BatchedInferencePipeline(model=self._whisper)
        self.diarization_model: str | None = None
        self._pipeline = None
        if hf_token:
            from pyannote.audio import Pipeline
            self.diarization_model = "pyannote/speaker-diarization-3.1"
            self._pipeline = Pipeline.from_pretrained(self.diarization_model, use_auth_token=hf_token)
            import torch
            self._pipeline.to(torch.device(device))
        self.oom_fallbacks = 0
        self.last_words: list[dict] = []

    def _is_oom(self, exc: BaseException) -> bool:
        return "out of memory" in str(exc).lower()

    def transcribe(self, wav: Path, initial_prompt: str) -> list[RawSegment]:
        try:
            return self._transcribe(wav, initial_prompt)
        except RuntimeError as e:
            if not self._is_oom(e):
                raise
            self.oom_fallbacks += 1
            log.warning("CUDA OOM in ASR; unloading diarizer and retrying once")
            self._unload_diarizer()
            return self._transcribe(wav, initial_prompt)

    def _transcribe(self, wav: Path, initial_prompt: str) -> list[RawSegment]:
        segments, _info = self._batched.transcribe(
            str(wav), batch_size=self.batch_size, word_timestamps=True,
            vad_filter=True, initial_prompt=initial_prompt, language="en",
        )
        raw: list[RawSegment] = []
        words: list[dict] = []
        for s in segments:
            raw.append(RawSegment(float(s.start), float(s.end), s.text,
                                  getattr(s, "avg_logprob", None), getattr(s, "no_speech_prob", None)))
            for w in (s.words or []):
                words.append({"s": float(w.start), "e": float(w.end), "w": w.word, "p": float(w.probability)})
        self.last_words = words
        return raw

    def diarize(self, wav: Path) -> tuple[list[DiarTurn], dict[str, list[float]]]:
        if self._pipeline is None:
            self._reload_diarizer()
        if self._pipeline is None:
            return [], {}
        try:
            return self._diarize(wav)
        except RuntimeError as e:
            if not self._is_oom(e):
                raise
            self.oom_fallbacks += 1
            log.warning("CUDA OOM in diarization; unloading ASR and retrying once")
            import gc, torch
            self._batched = None
            self._whisper = None
            gc.collect(); torch.cuda.empty_cache()
            result = self._diarize(wav)
            self._reload_asr()
            return result

    def _diarize(self, wav: Path):
        # pyannote.audio 3.1.x: SpeakerDiarization.apply(file, ..., return_embeddings=False)
        # returns (Annotation, ndarray[n_speakers, dim]) when True, and Pipeline.__call__
        # forwards **kwargs to apply(). Verified against tags 3.1.0 and 3.1.1. The
        # embeddings row order matches diar.labels().
        diar, embeddings = self._pipeline(str(wav), return_embeddings=True)
        turns = [DiarTurn(float(seg.start), float(seg.end), label)
                 for seg, _, label in diar.itertracks(yield_label=True)]
        labels = diar.labels()
        emb = {lab: [float(x) for x in embeddings[i]] for i, lab in enumerate(labels)}
        return turns, emb

    def _unload_diarizer(self):
        import gc, torch
        self._pipeline = None
        gc.collect(); torch.cuda.empty_cache()

    def _reload_diarizer(self):
        pass  # left None when no HF token; reloaded lazily by __init__ semantics on next run

    def _reload_asr(self):
        from faster_whisper import BatchedInferencePipeline, WhisperModel
        self._whisper = WhisperModel(self.asr_model, device=self.device, compute_type="float16")
        self._batched = BatchedInferencePipeline(model=self._whisper)
```

`_reload_diarizer` is intentionally a no-op: the pipeline is only unloaded during an ASR OOM, after which the same meeting's diarization runs with the ASR still resident; the next meeting's `transcribe` succeeds and `diarize` finds `_pipeline is None` and returns no turns. That is wrong. Replace `_reload_diarizer` with a real reload so the next meeting still gets speakers:

```python
    def _reload_diarizer(self):
        if not self._hf_token:
            return
        from pyannote.audio import Pipeline
        import torch
        self._pipeline = Pipeline.from_pretrained(self.diarization_model, use_auth_token=self._hf_token)
        self._pipeline.to(torch.device(self.device))
```

and store `self._hf_token = hf_token` in `__init__` before the `if hf_token:` block.

- [ ] **Step 4: Run to verify pass**

Run: `cd transcriber && pytest tests/test_engine_postprocess.py -v`
Expected: 4 PASS. The `FasterWhisperEngine` class is not exercised by unit tests; Task 9's bring-up script is its acceptance check.

- [ ] **Step 5: Commit**

```bash
git add transcriber/transcriber/engine.py transcriber/tests/test_engine_postprocess.py
git -c user.email=hello@docket.pub commit -m "feat(transcriber): faster-whisper + pyannote engine with OOM fallback and silence markers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: CLI loop, Docker image, runbook, and Blackwell bring-up

**Files:**
- Create: `transcriber/transcriber/cli.py`, `transcriber/Dockerfile`, `transcriber/docker-compose.yml`, `transcriber/.env.example`, `transcriber/README.md`, `transcriber/scripts/bringup.sh`, `transcriber/scripts/wslconfig.example`
- Test: `transcriber/tests/test_cli_loop.py`

**Interfaces:**
- Consumes: everything from Tasks 4–8.
- Produces: `python -m transcriber.cli [--since YYYY-MM-DD] [--limit N] [--max-hours H] [--dry-run FILE] [--model SIZE] [--device cuda|cpu] [--compute-type float16|int8]`; `run_loop(conn, engine, cfg: Config, *, clock=time.monotonic, stop_flag=None) -> dict` returning counts; `process_claim(conn, engine, claim, cfg) -> str` returning final status.

- [ ] **Step 1: Write the failing test (loop logic with fakes, no GPU, no DB)**

```python
# transcriber/tests/test_cli_loop.py
from datetime import date
from pathlib import Path
import pytest

from transcriber import cli
from transcriber.contract import TranscriptOutput
from transcriber.db import Claim
from transcriber.engine import DiarTurn, RawSegment


class FakeEngine:
    name = "fake"; asr_model = "tiny"; diarization_model = None
    last_words: list = []
    def transcribe(self, wav, initial_prompt):
        return [RawSegment(0.0, 200.0, "Item 15 passes.", -0.1, 0.0)]
    def diarize(self, wav):
        return [DiarTurn(0.0, 200.0, "SPEAKER_00")], {"SPEAKER_00": [0.1]}


class FakeDB:
    """Stands in for transcriber.db functions via monkeypatch."""
    def __init__(self, claims):
        self.claims = list(claims); self.status = []; self.uploaded = []; self.beats = []
    def claim_next(self, conn, **kw):
        return self.claims.pop(0) if self.claims else None
    def mark_status(self, conn, tid, status, **kw):
        self.status.append((tid, status, kw.get("error")))
    def heartbeat(self, conn, host, status, mid, ver):
        self.beats.append(status)
    def roster_for_meeting(self, conn, mid):
        return ["Darrell O'Quinn"]
    def upload(self, conn, out: TranscriptOutput):
        self.uploaded.append(out.meeting_id); return len(out.segments)


@pytest.fixture
def cfg(tmp_path):
    return cli.Config(since=date(2025, 10, 28), limit=10, max_hours=None, host="test",
                      work_dir=tmp_path / "work", archive_dir=tmp_path / "archive",
                      dry_run_file=None, version="0.1.0")


def _wire(monkeypatch, fakedb, *, fetch_ok=True):
    for name in ("claim_next", "mark_status", "heartbeat", "roster_for_meeting", "upload"):
        monkeypatch.setattr(cli.tdb, name, getattr(fakedb, name))
    def fake_fetch(source, out_wav, **kw):
        if not fetch_ok:
            from transcriber.audio import AudioFetchError
            raise AudioFetchError("ffmpeg could not read: HTTP 403 Forbidden")
        Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
        Path(out_wav).write_bytes(b"RIFF" + b"\0" * 100); return Path(out_wav)
    monkeypatch.setattr(cli, "fetch_audio", fake_fetch)
    monkeypatch.setattr(cli, "probe_duration", lambda *a, **k: 200.0)
    monkeypatch.setattr(cli, "sha256_file", lambda p: "ab" * 32)


def _claim(i, status="claimed"):
    return Claim(i, 100 + i, str(1950 + i), f"M{i}", date(2026, 2, 17), status)


def test_happy_path_uploads_and_archives_json(monkeypatch, cfg):
    fdb = FakeDB([_claim(1)]); _wire(monkeypatch, fdb)
    counts = cli.run_loop(object(), FakeEngine(), cfg)
    assert counts == {"uploaded": 1, "failed": 0, "low_speech": 0}
    assert fdb.uploaded == [101]
    assert any(p.suffix == ".json" for p in cfg.archive_dir.rglob("*"))
    assert not list(cfg.work_dir.rglob("*.wav"))          # audio deleted after upload
    assert [s for _, s, _ in fdb.status][:2] == ["audio_fetched", "transcribed"]


def test_fetch_failure_marks_failed_with_stderr_and_continues(monkeypatch, cfg):
    fdb = FakeDB([_claim(1), _claim(2)]); _wire(monkeypatch, fdb, fetch_ok=False)
    counts = cli.run_loop(object(), FakeEngine(), cfg)
    assert counts["failed"] == 2
    assert all(s == "failed" and "403" in (e or "") for _, s, e in fdb.status)


def test_transcribed_claim_skips_gpu_and_uploads(monkeypatch, cfg, tmp_path):
    out = TranscriptOutput(meeting_id=101, version=1, engine="fake", asr_model="tiny",
                           diarization_model=None, audio_duration_s=200.0, speech_seconds=200.0,
                           audio_sha256="ab" * 32, segments=[], speakers=[])
    path = cfg.archive_dir / "101" / "transcript.json"
    path.parent.mkdir(parents=True); path.write_text(out.to_json())
    fdb = FakeDB([_claim(1, status="transcribed")]); _wire(monkeypatch, fdb)
    class Boom(FakeEngine):
        def transcribe(self, *a, **k): raise AssertionError("GPU must not run")
    counts = cli.run_loop(object(), Boom(), cfg)
    assert counts["uploaded"] == 1 and fdb.uploaded == [101]


def test_low_speech_is_not_uploaded(monkeypatch, cfg):
    class Quiet(FakeEngine):
        def transcribe(self, wav, p): return [RawSegment(0.0, 30.0, "quorum?", None, None)]
    fdb = FakeDB([_claim(1)]); _wire(monkeypatch, fdb)
    counts = cli.run_loop(object(), Quiet(), cfg)
    assert counts["low_speech"] == 1 and fdb.uploaded == []
    assert fdb.status[-1][1] == "low_speech"


def test_max_hours_stops_between_meetings(monkeypatch, cfg):
    cfg.max_hours = 1.0
    fdb = FakeDB([_claim(1), _claim(2)]); _wire(monkeypatch, fdb)
    t = iter([0.0, 0.0, 3601.0, 3601.0, 3601.0])
    counts = cli.run_loop(object(), FakeEngine(), cfg, clock=lambda: next(t))
    assert counts["uploaded"] == 1 and len(fdb.claims) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `cd transcriber && pytest tests/test_cli_loop.py -v`
Expected: FAIL, `ModuleNotFoundError: transcriber.cli`.

- [ ] **Step 3: Write the CLI**

```python
"""Desktop producer entry point.

    python -m transcriber.cli --since 2025-10-28 --limit 5 --max-hours 3
    python -m transcriber.cli --dry-run /archive/clips/item15.mp4   # no DB, CPU ok

Per meeting: claim -> fetch audio -> transcribe -> diarize -> write JSON
(status transcribed) -> upload (status uploaded) -> delete audio. Ctrl-C
finishes the current meeting and exits.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from . import __version__
from . import db as tdb
from .audio import AudioFetchError, download_url_for, fetch_audio, probe_duration, sha256_file
from .contract import TranscriptOutput
from .engine import Engine, build_output, is_low_speech, speech_seconds
from .prompt import PromptBudgetError, build_initial_prompt

log = logging.getLogger("transcriber")


@dataclass
class Config:
    since: date
    limit: int
    max_hours: float | None
    host: str
    work_dir: Path
    archive_dir: Path
    dry_run_file: str | None
    version: str


class _Stop:
    def __init__(self):
        self.requested = False
        signal.signal(signal.SIGINT, self._on)
        signal.signal(signal.SIGTERM, self._on)

    def _on(self, *_):
        log.warning("stop requested; finishing current meeting")
        self.requested = True


def _archive_path(cfg: Config, meeting_id: int) -> Path:
    return cfg.archive_dir / str(meeting_id) / "transcript.json"


def process_claim(conn, engine: Engine, claim: tdb.Claim, cfg: Config) -> str:
    json_path = _archive_path(cfg, claim.meeting_id)
    if claim.status == "transcribed" and json_path.exists():
        out = TranscriptOutput.from_json(json_path.read_text())
        tdb.upload(conn, out)
        conn.commit()
        return "uploaded"

    wav = cfg.work_dir / f"{claim.meeting_id}.wav"
    source = download_url_for(claim.external_id)
    try:
        fetch_audio(source, wav)
        duration = probe_duration(str(wav))
        sha = sha256_file(wav)
        tdb.mark_status(conn, claim.transcript_id, "audio_fetched",
                        audio_sha256=sha, audio_duration_s=duration)
        conn.commit()
    except AudioFetchError as e:
        tdb.mark_status(conn, claim.transcript_id, "failed", error=str(e))
        conn.commit()
        wav.unlink(missing_ok=True)
        return "failed"

    try:
        roster = tdb.roster_for_meeting(conn, claim.meeting_id)
        try:
            prompt = build_initial_prompt(roster)
        except PromptBudgetError as e:
            log.warning("prompt budget: %s; using vocabulary only", e)
            prompt = build_initial_prompt([])
        raw = engine.transcribe(wav, prompt)
        sp_s = speech_seconds(raw)
        if is_low_speech(sp_s):
            tdb.mark_status(conn, claim.transcript_id, "low_speech",
                            error=f"{sp_s:.0f}s of speech detected", speech_ratio=sp_s / max(duration, 1))
            conn.commit()
            return "low_speech"
        turns, emb = engine.diarize(wav)
        words_path = None
        if getattr(engine, "last_words", None):
            import json
            wp = json_path.with_name("words.json")
            wp.parent.mkdir(parents=True, exist_ok=True)
            wp.write_text(json.dumps(engine.last_words))
            words_path = str(wp)
        out = build_output(claim.meeting_id, 1, engine, raw, turns, emb, duration, sha, words_path)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(out.to_json())
        tdb.mark_status(conn, claim.transcript_id, "transcribed", raw_output_path=str(json_path),
                        speech_ratio=out.speech_ratio, word_count=out.word_count,
                        engine=engine.name, asr_model=engine.asr_model,
                        diarization_model=engine.diarization_model)
        conn.commit()
    except Exception as e:  # noqa: BLE001 — any GPU/model failure is a per-meeting failure
        log.exception("meeting %s failed", claim.meeting_id)
        tdb.mark_status(conn, claim.transcript_id, "failed", error=f"{type(e).__name__}: {e}")
        conn.commit()
        return "failed"
    finally:
        wav.unlink(missing_ok=True)

    tdb.upload(conn, out)
    conn.commit()
    return "uploaded"


def run_loop(conn, engine: Engine, cfg: Config, *, clock=time.monotonic, stop_flag=None) -> dict:
    counts = {"uploaded": 0, "failed": 0, "low_speech": 0}
    started = clock()
    stop = stop_flag or _Stop()
    tdb.heartbeat(conn, cfg.host, "started", None, cfg.version)
    conn.commit()
    for _ in range(cfg.limit):
        if stop.requested:
            break
        if cfg.max_hours is not None and (clock() - started) > cfg.max_hours * 3600:
            log.info("max-hours reached; stopping")
            break
        claim = tdb.claim_next(conn, since=cfg.since, host=cfg.host)
        conn.commit()
        if claim is None:
            log.info("nothing to claim")
            break
        tdb.heartbeat(conn, cfg.host, "processing", claim.meeting_id, cfg.version)
        conn.commit()
        log.info("meeting %s (%s) %s", claim.meeting_id, claim.meeting_date, claim.title)
        status = process_claim(conn, engine, claim, cfg)
        counts[status] += 1
        tdb.heartbeat(conn, cfg.host, status, claim.meeting_id, cfg.version)
        conn.commit()
    tdb.heartbeat(conn, cfg.host, "exited", None, cfg.version)
    conn.commit()
    return counts


def dry_run(engine: Engine, source: str, cfg: Config) -> Path:
    """Transcribe one local file or URL to JSON without touching the database."""
    wav = cfg.work_dir / "dry_run.wav"
    fetch_audio(source, wav)
    duration = probe_duration(str(wav))
    raw = engine.transcribe(wav, build_initial_prompt([]))
    turns, emb = engine.diarize(wav)
    out = build_output(0, 1, engine, raw, turns, emb, duration, sha256_file(wav), None)
    path = cfg.archive_dir / "dry_run" / (Path(source).stem + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out.to_json())
    wav.unlink(missing_ok=True)
    return path


def main(argv=None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description="docket.pub transcript producer")
    ap.add_argument("--since", default=os.environ.get("TRANSCRIBER_SINCE", "2025-10-28"))
    ap.add_argument("--limit", type=int, default=int(os.environ.get("TRANSCRIBER_LIMIT", "100")))
    ap.add_argument("--max-hours", type=float, default=None)
    ap.add_argument("--dry-run", metavar="FILE_OR_URL", default=None)
    ap.add_argument("--model", default=os.environ.get("TRANSCRIBER_MODEL", "large-v3"))
    ap.add_argument("--device", default=os.environ.get("TRANSCRIBER_DEVICE", "cuda"))
    ap.add_argument("--compute-type", default=os.environ.get("TRANSCRIBER_COMPUTE", "float16"))
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config(
        since=date.fromisoformat(args.since), limit=args.limit, max_hours=args.max_hours,
        host=os.environ.get("TRANSCRIBER_HOST", socket.gethostname()),
        work_dir=Path(os.environ.get("TRANSCRIBER_WORK_DIR", "/archive/work")),
        archive_dir=Path(os.environ.get("TRANSCRIBER_ARCHIVE_DIR", "/archive/transcripts")),
        dry_run_file=args.dry_run, version=__version__,
    )
    cfg.work_dir.mkdir(parents=True, exist_ok=True)

    from .engine import FasterWhisperEngine
    engine = FasterWhisperEngine(model_size=args.model, device=args.device,
                                 compute_type=args.compute_type,
                                 hf_token=os.environ.get("HF_TOKEN"))

    if args.dry_run:
        print(dry_run(engine, args.dry_run, cfg))
        return 0

    url = os.environ.get("TRANSCRIBER_DATABASE_URL")
    if not url:
        ap.error("TRANSCRIBER_DATABASE_URL is not set")
    if "sslmode=require" not in url:
        ap.error("TRANSCRIBER_DATABASE_URL must include sslmode=require")
    conn = tdb.connect(url)
    try:
        counts = run_loop(conn, engine, cfg)
    finally:
        conn.close()
    log.info("done %s oom_fallbacks=%s", counts, getattr(engine, "oom_fallbacks", 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify pass**

Run: `cd transcriber && pytest tests/test_cli_loop.py -v`
Expected: 5 PASS. (Review Focus item 1 is `test_fetch_failure_marks_failed_with_stderr_and_continues`.)

- [ ] **Step 5: Write the container files**

`transcriber/Dockerfile`:

```dockerfile
FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 \
    HF_HOME=/models/hf XDG_CACHE_HOME=/models/cache

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3-pip ffmpeg git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.11 /usr/bin/python

WORKDIR /app
COPY requirements.txt .
# Blackwell (sm_120) needs the CUDA 12.8 torch wheels.
RUN python -m pip install --no-cache-dir --upgrade pip \
 && python -m pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cu128 \
 && python -m pip install --no-cache-dir -r requirements.txt

COPY transcriber ./transcriber
COPY scripts ./scripts
ENTRYPOINT ["python", "-m", "transcriber.cli"]
```

`transcriber/docker-compose.yml`:

```yaml
services:
  transcriber:
    build: .
    env_file: .env
    gpus: all
    volumes:
      - models:/models                       # named volume: model cache, downloaded once
      - ${ARCHIVE_HOST_DIR:-C:/docket-archive}:/archive   # host bind mount: work + JSON archive
    shm_size: "2gb"
volumes:
  models:
```

`transcriber/.env.example`:

```
TRANSCRIBER_DATABASE_URL=postgresql://transcriber:CHANGE_ME@HOST:PORT/railway?sslmode=require
HF_TOKEN=hf_CHANGE_ME
TRANSCRIBER_SINCE=2025-10-28
TRANSCRIBER_LIMIT=100
TRANSCRIBER_HOST=legion
ARCHIVE_HOST_DIR=C:/docket-archive
```

`transcriber/scripts/wslconfig.example` (copied to `%UserProfile%\.wslconfig`):

```ini
[wsl2]
memory=16GB
processors=8
[experimental]
autoMemoryReclaim=gradual
sparseVhd=true
```

`transcriber/scripts/bringup.sh` (the Blackwell acceptance check):

```bash
#!/usr/bin/env bash
# Run inside the container: docker compose run --rm --entrypoint bash transcriber scripts/bringup.sh /archive/clips/pilot.mp4
set -euo pipefail
CLIP="${1:?path to a 30s+ clip under /archive}"
python - <<'EOF'
import torch, ctranslate2
print("torch", torch.__version__, "cuda", torch.version.cuda, "available", torch.cuda.is_available())
print("device", torch.cuda.get_device_name(0), "capability", torch.cuda.get_device_capability(0))
print("ctranslate2", ctranslate2.__version__, "cuda devices", ctranslate2.get_cuda_device_count())
assert torch.cuda.is_available(), "CUDA not visible inside the container"
assert ctranslate2.get_cuda_device_count() > 0, "CTranslate2 cannot see the GPU: use the WhisperX fallback engine"
EOF
time python -m transcriber.cli --dry-run "$CLIP" --model large-v3 --device cuda
echo "BRING-UP OK"
```

- [ ] **Step 6: Write the runbook**

`transcriber/README.md`:

```markdown
# docket.pub transcript producer (Lenovo Legion)

GPU-only. Fetches Birmingham council audio from Granicus, runs faster-whisper
large-v3 and pyannote diarization, and uploads raw segments to Railway Postgres
as the narrow `transcriber` role. All thinking (names, events, comparison)
happens on the Railway worker.

## One-time setup on Windows

1. Install Docker Desktop; enable the WSL2 backend and GPU support
   (Settings → Resources → WSL integration). Install the NVIDIA Windows driver
   (Blackwell needs 570+). Nothing else is installed on Windows.
2. Copy `scripts/wslconfig.example` to `%UserProfile%\.wslconfig`, then run
   `wsl --shutdown` once. This caps WSL2 at 16 GB and reclaims memory.
3. Power plan: Settings → System → Power → "Never" sleep when plugged in;
   allow wake timers. A sleeping desktop is the most likely cause of a quiet week.
4. Create `C:\docket-archive` (the host bind mount). Audio is written and
   deleted there, so the WSL2 virtual disk never grows.
5. `copy .env.example .env` and fill in the transcriber DB URL (from the
   operator who ran `scripts/sql/create_transcriber_role.sql`) and a Hugging
   Face token that has accepted the pyannote 3.1 model terms.
6. `docker compose build` (10 minutes; downloads CUDA 12.8 torch wheels).
7. Bring-up: put a short clip at `C:\docket-archive\clips\pilot.mp4` and run
   `docker compose run --rm --entrypoint bash transcriber scripts/bringup.sh /archive/clips/pilot.mp4`
   Expect `BRING-UP OK` and a JSON file under `C:\docket-archive\transcripts\dry_run\`.
   If the CTranslate2 assertion fails, Blackwell kernels are missing from the
   wheel: set `TRANSCRIBER_DEVICE=cuda` with `--compute-type int8_float16`
   first; if that also fails, open an issue to swap `FasterWhisperEngine` for
   the WhisperX PyTorch path (one class, same `Engine` protocol).

## Running

    docker compose run --rm transcriber --since 2025-10-28 --limit 10 --max-hours 3

Ctrl-C finishes the current meeting and exits. Re-running is always safe: a
meeting left in `transcribed` uploads without touching the GPU; a claim older
than six hours is reclaimed.

Task Scheduler (optional): a basic task "At log on" running
`docker compose -f C:\path\to\transcriber\docker-compose.yml run --rm transcriber --max-hours 4`.

## Where things land

- `C:\docket-archive\transcripts\<meeting_id>\transcript.json` — the upload contract (kept)
- `C:\docket-archive\transcripts\<meeting_id>\words.json` — word timestamps (kept, never uploaded)
- `C:\docket-archive\work\*.wav` — audio, deleted after each meeting

## Local development (laptop, no GPU)

    pip install -r requirements-dev.txt && pytest
    TRANSCRIBER_DEVICE=cpu python -m transcriber.cli --dry-run ../tests/fixtures/transcript_pilot/clip.mp4 --model small.en
```

- [ ] **Step 7: Commit**

```bash
git add transcriber/
git -c user.email=hello@docket.pub commit -m "feat(transcriber): CLI loop, CUDA 12.8 image, Legion runbook, bring-up check

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

- [ ] **Step 8: Bring-up on the Legion (operator step, blocks Task 9's acceptance)**

Follow README steps 1–7 on the desktop. Record the `bringup.sh` output (device name, capability, CTranslate2 device count, wall-clock for the clip) in `transcriber/README.md` under a new "Bring-up log" heading, and commit. If the CTranslate2 assertion fails, stop here and report; the WhisperX fallback engine is a follow-up task, not part of this plan.

---

### Task 10: Public transcript page and the meeting-page link

**Files:**
- Create: `src/docket/services/transcripts.py`, `src/docket/web/templates/transcript.html`, `src/docket/web/templates/partials/transcript_body.html`
- Modify: `src/docket/web/public.py` (new route after `meeting_detail`), `src/docket/web/templates/meeting_detail.html` (rail link block near line 387 and a new section after Votes)
- Test: `tests/unit/test_transcript_turns.py`, `tests/integration/test_transcript_routes.py`

**Interfaces:**
- Produces in `docket.services.transcripts`:
  - `Transcript` dataclass: `id, meeting_id, status, version, asr_model, diarization_model, audio_duration_s, word_count, uploaded_at`.
  - `get_public_transcript(meeting_id: int) -> Transcript | None` — only statuses in `PUBLIC_STATUSES = ('uploaded', 'speakers_resolved', 'events_extracted', 'compared')`.
  - `list_segments(transcript_id: int) -> list[dict]` with keys `seq, start_s, end_s, text, cluster_label, is_silence, agenda_item_id, speaker_name, speaker_confidence, speaker_member_id`.
  - `Turn` dataclass: `anchor: str ("t-<first seq>"), start_s, end_s, speaker_label, speaker_member_id, cluster_label, texts: list[str], agenda_item_id, is_silence`.
  - `speaker_ordinals(transcript_id: int) -> dict[str, int]` — `cluster_label → N`, 1-based, by first appearance over every non-silence segment of the meeting. One GROUP BY query.
  - `group_turns(segments: list[dict], confidence_floor: float = 0.6, ordinals: dict[str, int] | None = None) -> list[Turn]` — pure; consecutive segments with the same `cluster_label` merge; a silence row is its own turn; `speaker_label` is the resolved name when `speaker_confidence >= floor` else `"Speaker N"`. N comes from `ordinals` when given (the excerpt passes `speaker_ordinals(...)`), otherwise from first appearance within `segments` (the full page, where both agree). Clusters missing from a supplied map are appended after it.
  - `item_anchor_map(turns, agenda_items) -> dict[int, str]` — first turn anchor per `agenda_item_id`, so the page can emit `id="item-N"` at the right turn.
- Route: `GET /al/<slug>/meetings/<int:meeting_id>/transcript/` → 404 unless `get_public_transcript` returns a row. Returns `partials/transcript_body.html` alone when the request carries the `HX-Request` header, otherwise the full `transcript.html`.

- [ ] **Step 1: Write the failing unit tests for turn grouping**

```python
# tests/unit/test_transcript_turns.py
from docket.services.transcripts import Turn, group_turns, item_anchor_map


def _seg(seq, start, end, text, cluster, name=None, conf=None, item=None, silence=False):
    return dict(seq=seq, start_s=start, end_s=end, text=text, cluster_label=cluster,
                is_silence=silence, agenda_item_id=item, speaker_name=name,
                speaker_confidence=conf, speaker_member_id=None)


def test_consecutive_same_cluster_merge_into_one_turn():
    segs = [_seg(0, 0, 2, "Council,", "S0", "Darrell O'Quinn", 0.9),
            _seg(1, 2, 5, "I have a question.", "S0", "Darrell O'Quinn", 0.9),
            _seg(2, 5, 9, "Sure.", "S1", None, None)]
    turns = group_turns(segs)
    assert [t.anchor for t in turns] == ["t-0", "t-2"]
    assert turns[0].texts == ["Council,", "I have a question."]
    assert turns[0].speaker_label == "Darrell O'Quinn"
    assert turns[1].speaker_label == "Speaker 2"


def test_low_confidence_name_falls_back_to_speaker_n():
    segs = [_seg(0, 0, 2, "x", "S0", "Guess Name", 0.4)]
    assert group_turns(segs)[0].speaker_label == "Speaker 1"


def test_silence_is_its_own_turn_and_does_not_merge():
    segs = [_seg(0, 0, 2, "x", "S0", "A", 0.9), _seg(1, 2, 80, "", None, silence=True),
            _seg(2, 80, 82, "y", "S0", "A", 0.9)]
    turns = group_turns(segs)
    assert [t.is_silence for t in turns] == [False, True, False]
    assert [t.anchor for t in turns] == ["t-0", "t-1", "t-2"]


def test_item_anchor_map_takes_first_turn_per_item():
    segs = [_seg(0, 0, 2, "a", "S0", item=7), _seg(1, 2, 4, "b", "S1", item=7),
            _seg(2, 4, 6, "c", "S1", item=9)]
    turns = group_turns(segs)
    assert item_anchor_map(turns) == {7: "t-0", 9: "t-2"}


def test_seeded_ordinals_keep_whole_meeting_numbering():
    # An excerpt sees only a slice; with the meeting-wide map S2 stays "Speaker 3".
    slice_ = [_seg(40, 100, 102, "x", "S2"), _seg(41, 102, 104, "y", "S0")]
    turns = group_turns(slice_, ordinals={"S0": 1, "S1": 2, "S2": 3})
    assert [t.speaker_label for t in turns] == ["Speaker 3", "Speaker 1"]
    # A cluster the map does not know is appended, never renumbered over an existing one.
    turns = group_turns([_seg(50, 110, 112, "z", "S9")], ordinals={"S0": 1})
    assert turns[0].speaker_label == "Speaker 2"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_transcript_turns.py -v`
Expected: FAIL, `ModuleNotFoundError: docket.services.transcripts`.

- [ ] **Step 3: Write the service module (read side only)**

```python
"""Read-side helpers for public transcript surfaces.

Rows come from the tables in migration 035. Nothing here writes. Speaker
names are joined in from transcript_speakers; the search vector never
includes them (spec Section 1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from docket.db import db_cursor

PUBLIC_STATUSES = ("uploaded", "speakers_resolved", "events_extracted", "compared")
SPEAKER_CONFIDENCE_FLOOR = 0.6


@dataclass(frozen=True)
class Transcript:
    id: int
    meeting_id: int
    status: str
    version: int
    asr_model: str | None
    diarization_model: str | None
    audio_duration_s: float | None
    word_count: int | None
    uploaded_at: datetime | None


@dataclass
class Turn:
    anchor: str
    start_s: float
    end_s: float
    speaker_label: str
    speaker_member_id: int | None
    cluster_label: str | None
    texts: list[str] = field(default_factory=list)
    agenda_item_id: int | None = None
    is_silence: bool = False

    @property
    def text(self) -> str:
        return " ".join(self.texts)


def get_public_transcript(meeting_id: int) -> Transcript | None:
    with db_cursor() as cur:
        cur.execute(
            """SELECT id, meeting_id, status, version, asr_model, diarization_model,
                      audio_duration_s, word_count, uploaded_at
                 FROM transcripts
                WHERE meeting_id = %s AND status = ANY(%s)""",
            [meeting_id, list(PUBLIC_STATUSES)],
        )
        row = cur.fetchone()
        return Transcript(**row) if row else None


def list_segments(transcript_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            """SELECT s.seq, s.start_s, s.end_s, s.text, s.cluster_label, s.is_silence,
                      s.agenda_item_id,
                      COALESCE(cm.name, sp.display_name) AS speaker_name,
                      sp.confidence AS speaker_confidence,
                      sp.council_member_id AS speaker_member_id
                 FROM transcript_segments s
                 LEFT JOIN transcript_speakers sp ON sp.id = s.speaker_id
                 LEFT JOIN council_members cm ON cm.id = sp.council_member_id
                WHERE s.transcript_id = %s
                ORDER BY s.seq""",
            [transcript_id],
        )
        return [dict(r) for r in cur.fetchall()]


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


def _label(seg: dict, ordinals: dict[str, int], floor: float) -> tuple[str, int | None]:
    """Resolved name when confident (or manual), else "Speaker N".

    N is the cluster's ordinal by first appearance among ALL clusters, resolved
    or not, so the number is stable when a correction later resolves a cluster.
    A cluster not yet in `ordinals` is appended with the next number.
    """
    cl = seg.get("cluster_label")
    if cl is not None and cl not in ordinals:
        ordinals[cl] = len(ordinals) + 1
    name, conf = seg.get("speaker_name"), seg.get("speaker_confidence")
    if name and (conf is None or conf >= floor):
        return name, seg.get("speaker_member_id")
    if cl is None:
        return "Unknown speaker", None
    return f"Speaker {ordinals[cl]}", None


def group_turns(segments: list[dict], confidence_floor: float = SPEAKER_CONFIDENCE_FLOOR,
                ordinals: dict[str, int] | None = None) -> list[Turn]:
    turns: list[Turn] = []
    ordinals = dict(ordinals) if ordinals else {}
    for seg in segments:
        if seg.get("is_silence"):
            turns.append(Turn(f"t-{seg['seq']}", seg["start_s"], seg["end_s"], "", None, None,
                              [], seg.get("agenda_item_id"), True))
            continue
        label, member_id = _label(seg, ordinals, confidence_floor)
        last = turns[-1] if turns else None
        if (last is not None and not last.is_silence and last.cluster_label is not None
                and last.cluster_label == seg.get("cluster_label")):
            last.texts.append(seg["text"])
            last.end_s = seg["end_s"]
            if last.agenda_item_id is None:
                last.agenda_item_id = seg.get("agenda_item_id")
            continue
        turns.append(Turn(f"t-{seg['seq']}", seg["start_s"], seg["end_s"], label, member_id,
                          seg.get("cluster_label"), [seg["text"]], seg.get("agenda_item_id")))
    return turns


def item_anchor_map(turns: list[Turn]) -> dict[int, str]:
    out: dict[int, str] = {}
    for t in turns:
        if t.agenda_item_id is not None and t.agenda_item_id not in out:
            out[t.agenda_item_id] = t.anchor
    return out
```

Note: `_label` numbers every cluster by first appearance, so in the route test the resolved O'Quinn cluster is ordinal 1 and the unresolved cluster renders as "Speaker 2". `_label` also treats a `speaker_confidence` of `None` with a name present as confident. That is the manual-assignment case (admin set `display_name` with `is_manual`, no model confidence). Keep that behavior and add this test to `tests/unit/test_transcript_turns.py`:

```python
def test_manual_name_without_confidence_is_shown():
    segs = [_seg(0, 0, 2, "x", "S0", "LaTonya Tate", None)]
    assert group_turns(segs)[0].speaker_label == "LaTonya Tate"
```

- [ ] **Step 4: Run unit tests to verify pass**

Run: `pytest tests/unit/test_transcript_turns.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Write the failing route tests**

```python
# tests/integration/test_transcript_routes.py
"""Transcript page: 404 until uploaded, full page vs HTMX partial, anchors, label."""
import pytest
from datetime import date
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.web import create_app

pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run against Railway DB.",
)


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def meeting_with_transcript():
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, external_id, video_url)
                       VALUES (%s, 'TR test', %s, '999902',
                               'https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=999902')
                       RETURNING id""", [muni, date(2026, 9, 2)])
        mid = cur.fetchone()["id"]
        cur.execute("INSERT INTO processing_status (meeting_id) VALUES (%s)", [mid])
        cur.execute("""INSERT INTO agenda_items (meeting_id, item_number, title, external_id)
                       VALUES (%s, '15', 'ALEA agreement', '77001') RETURNING id""", [mid])
        item = cur.fetchone()["id"]
        cur.execute("""INSERT INTO transcripts (meeting_id, status, version, asr_model, word_count)
                       VALUES (%s, 'claimed', 1, 'large-v3', 0) RETURNING id""", [mid])
        tid = cur.fetchone()["id"]
        cur.execute("""INSERT INTO transcript_speakers (meeting_id, cluster_label, display_name, confidence)
                       VALUES (%s, 'S0', 'Darrell O''Quinn', 0.9) RETURNING id""", [mid])
        sid = cur.fetchone()["id"]
        cur.execute("""INSERT INTO transcript_segments
                         (transcript_id, seq, start_s, end_s, text, cluster_label, speaker_id, agenda_item_id)
                       VALUES (%s, 0, 3309.0, 3312.0, 'Item fifteen.', 'S0', %s, %s),
                              (%s, 1, 3312.0, 3320.0, 'I would like a summary.', 'S0', %s, %s),
                              (%s, 2, 3320.0, 3325.0, 'Sure.', 'S1', NULL, %s)""",
                    [tid, sid, item, tid, sid, item, tid, item])
    yield {"meeting_id": mid, "transcript_id": tid, "item_id": item}
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id = %s", [mid])


def _publish(tid):
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status='uploaded', uploaded_at=now() WHERE id=%s", [tid])


def test_404_while_not_public(client, meeting_with_transcript):
    mid = meeting_with_transcript["meeting_id"]
    assert client.get(f"/al/birmingham/meetings/{mid}/transcript/").status_code == 404
    page = client.get(f"/al/birmingham/meetings/{mid}/").get_data(as_text=True)
    assert "/transcript/" not in page


def test_full_page_renders_label_turns_and_anchors(client, meeting_with_transcript):
    fx = meeting_with_transcript; _publish(fx["transcript_id"])
    r = client.get(f"/al/birmingham/meetings/{fx['meeting_id']}/transcript/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Machine-generated transcript" in html and "large-v3" in html
    assert 'id="t-0"' in html and 'id="t-2"' in html and 'id="t-1"' not in html
    assert "Darrell O'Quinn" in html and "Speaker 2" in html
    assert f'id="item-{fx["item_id"]}"' in html
    assert "55:09" in html                      # 3309 s formatted by format_timestamp
    assert "/about/how-we-read-minutes/" in html
    assert "<html" in html


def test_htmx_request_returns_partial_only(client, meeting_with_transcript):
    fx = meeting_with_transcript; _publish(fx["transcript_id"])
    r = client.get(f"/al/birmingham/meetings/{fx['meeting_id']}/transcript/",
                   headers={"HX-Request": "true"})
    html = r.get_data(as_text=True)
    assert "<html" not in html and 'id="t-0"' in html


def test_meeting_page_links_to_transcript_with_hx_attrs(client, meeting_with_transcript):
    fx = meeting_with_transcript; _publish(fx["transcript_id"])
    html = client.get(f"/al/birmingham/meetings/{fx['meeting_id']}/").get_data(as_text=True)
    assert f'href="/al/birmingham/meetings/{fx["meeting_id"]}/transcript/"' in html
    assert 'hx-get="/al/birmingham/meetings/' in html and 'hx-push-url="true"' in html
```

- [ ] **Step 6: Run to verify failure**

Run: `pytest tests/integration/test_transcript_routes.py -v`
Expected: first test PASS (404 is the default), others FAIL with 404.

- [ ] **Step 7: Add the route**

In `src/docket/web/public.py`, after `meeting_detail`:

```python
@bp.route("/al/<slug>/meetings/<int:meeting_id>/transcript/")
def meeting_transcript(slug, meeting_id):
    """Server-rendered machine transcript. HTMX requests get the body partial only."""
    from docket.services import transcripts as tsvc

    municipality = query.get_municipality(slug)
    if not municipality:
        abort(404)
    meeting = query.get_meeting(meeting_id)
    if not meeting or meeting.municipality_id != municipality["id"]:
        abort(404)
    if meeting.is_hidden and not session.get("admin_user"):
        abort(404)
    transcript = tsvc.get_public_transcript(meeting_id)
    if transcript is None:
        abort(404)

    turns = tsvc.group_turns(tsvc.list_segments(transcript.id))
    anchors = tsvc.item_anchor_map(turns)
    agenda_items = query.list_agenda_items(meeting_id)
    items_by_id = {it.id: it for it in agenda_items}
    ctx = dict(municipality=municipality, meeting=meeting, transcript=transcript,
               turns=turns, item_anchors=anchors, items_by_id=items_by_id)
    template = "partials/transcript_body.html" if request.headers.get("HX-Request") else "transcript.html"
    return render_template(template, **ctx)
```

Also pass `has_transcript` into `meeting_detail`: add before its `render_template` call

```python
    from docket.services import transcripts as tsvc
    has_transcript = tsvc.get_public_transcript(meeting_id) is not None
```

and add `has_transcript=has_transcript` to the `render_template(...)` kwargs.

- [ ] **Step 8: Write the templates**

`src/docket/web/templates/partials/transcript_body.html`:

```html
{# Transcript body — shared by the full page and the HTMX tab load.
   Each turn has a stable anchor (t-<seq of first segment>) and the first
   turn of each agenda item also carries id="item-N" so agenda links and
   transcript links cross-reference. #}
<div class="transcript" id="transcript-body">
  <div class="callout callout-info is-tight transcript-label">
    <div class="callout-title t-mono">Machine-generated transcript</div>
    <div class="callout-body">
      Produced by speech recognition ({{ transcript.asr_model }}){% if transcript.diarization_model %} with automatic speaker separation{% endif %}.
      Names are assigned by software and may be wrong; low-confidence speakers are shown as "Speaker N".
      Verify against the <a class="link" href="{{ meeting.video_url }}" target="_blank" rel="noreferrer">original video</a>.
      <a class="link" href="/about/how-we-read-minutes/">How we read meetings</a>.
    </div>
  </div>

  {% set anchor_to_item = {} %}
  {% for item_id, anchor in item_anchors.items() %}{% set _ = anchor_to_item.update({anchor: item_id}) %}{% endfor %}

  <ol class="transcript-turns">
  {% for turn in turns %}
    {% if turn.is_silence %}
    <li id="{{ turn.anchor }}" class="transcript-turn transcript-turn--silence">
      <span class="t-mono t-meta">{{ turn.start_s | format_timestamp }} – {{ turn.end_s | format_timestamp }}</span>
      <span class="t-meta">No speech detected (recess or dead air)</span>
    </li>
    {% else %}
    {% set item_id = anchor_to_item.get(turn.anchor) %}
    {% if item_id %}
    <li id="item-{{ item_id }}" class="transcript-item-marker">
      <span class="t-eyebrow">Item {{ items_by_id[item_id].item_number if item_id in items_by_id else '' }}</span>
      {% if item_id in items_by_id %}<a class="link" href="/al/{{ municipality.slug }}/items/{{ item_id }}/">{{ items_by_id[item_id].title }}</a>{% endif %}
    </li>
    {% endif %}
    <li id="{{ turn.anchor }}" class="transcript-turn">
      <div class="transcript-turn-head">
        <a class="transcript-time t-mono" href="#{{ turn.anchor }}">{{ turn.start_s | format_timestamp }}</a>
        <span class="transcript-speaker{% if turn.speaker_member_id %} is-resolved{% endif %}">
          {% if turn.speaker_member_id %}<a class="link" href="/al/{{ municipality.slug }}/council/{{ turn.speaker_member_id }}/">{{ turn.speaker_label }}</a>{% else %}{{ turn.speaker_label }}{% endif %}
        </span>
        {% if item_id and items_by_id.get(item_id) and items_by_id[item_id].external_id %}
        <a class="t-meta link" href="{{ chapter_url(meeting.video_url, items_by_id[item_id].external_id) }}" target="_blank" rel="noreferrer">video chapter ↗</a>
        {% endif %}
      </div>
      <p class="transcript-text">{{ turn.text }}</p>
    </li>
    {% endif %}
  {% endfor %}
  </ol>
</div>
<style>
  .transcript-turn:target { background: var(--color-highlight, #fff6d5); }
  .transcript-turns { list-style: none; padding: 0; margin: 0; }
  .transcript-turn { padding: 10px 0; border-bottom: 1px solid var(--color-rule, #e5e5e5); }
  .transcript-turn-head { display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; }
  .transcript-item-marker { padding: 18px 0 6px; }
  .transcript-turn--silence { color: var(--color-muted, #777); font-style: italic; }
</style>
```

`src/docket/web/templates/transcript.html`:

```html
{% extends "base.html" %}
{% block title %}Transcript — {{ meeting.title }} — docket.pub{% endblock %}
{% block content %}
<section class="hero hero--detail">
  <div class="t-eyebrow">Transcript · {{ meeting.meeting_date | format_date }}</div>
  <h1 class="hero-title t-display">{{ meeting.title }}</h1>
  <p class="t-meta">
    <a class="link" href="/al/{{ municipality.slug }}/meetings/{{ meeting.id }}/">← Back to the meeting</a>
    · {{ transcript.word_count | default(0) }} words
    {% if transcript.audio_duration_s %}· {{ transcript.audio_duration_s | format_timestamp }} of audio{% endif %}
  </p>
</section>
<section class="feed">
  {% include "partials/transcript_body.html" %}
</section>
{% endblock %}
```

In `src/docket/web/templates/meeting_detail.html`, inside the rail-links block right after the "Watch video" link (line ~392), add:

```html
        {% if has_transcript %}
        <a class="rail-link" href="/al/{{ municipality.slug }}/meetings/{{ meeting.id }}/transcript/"
           hx-get="/al/{{ municipality.slug }}/meetings/{{ meeting.id }}/transcript/"
           hx-target="#transcript-tab" hx-swap="innerHTML" hx-push-url="true"
           style="flex: 1; min-width: 180px;">
            <div><div class="rail-link-label">Transcript</div><div class="t-meta">machine-generated</div></div>
            <span class="t-mono">→</span>
        </a>
        {% endif %}
```

and after the Votes section (after its closing `</section>`), add the target container:

```html
{# ── Transcript (loaded on demand via HTMX; full page at /transcript/) ── #}
{% if has_transcript %}
<section class="feed" id="transcript-tab" style="padding-bottom: 32px;"></section>
{% endif %}
```

- [ ] **Step 9: Run the route tests to verify pass**

Run: `pytest tests/integration/test_transcript_routes.py -v`
Expected: 4 PASS. (Review Focus item 3 is `test_404_while_not_public`.)

- [ ] **Step 10: Commit**

```bash
git add src/docket/services/transcripts.py src/docket/web/public.py src/docket/web/templates/transcript.html src/docket/web/templates/partials/transcript_body.html src/docket/web/templates/meeting_detail.html tests/unit/test_transcript_turns.py tests/integration/test_transcript_routes.py
git -c user.email=hello@docket.pub commit -m "feat(web): public machine transcript page with turn anchors and HTMX tab

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: "From the video" excerpt on item pages

**Files:**
- Modify: `src/docket/services/transcripts.py` (add `excerpt_for_item`), `src/docket/web/public.py` (`item_detail`), `src/docket/web/templates/item_detail.html`
- Create: `src/docket/web/templates/partials/transcript_excerpt.html`
- Test: `tests/integration/test_transcript_routes.py` (add three tests)

**Interfaces:**
- Produces: `excerpt_for_item(item_id: int, max_turns: int = 4) -> dict | None` returning `{"meeting_id", "transcript_id", "turns": list[Turn], "anchor": str, "truncated": bool}` or `None` when the meeting has no public transcript or no segment carries this `agenda_item_id`.

- [ ] **Step 1: Write the failing tests (append to `tests/integration/test_transcript_routes.py`)**

```python
def test_item_page_shows_excerpt_with_read_more(client, meeting_with_transcript):
    fx = meeting_with_transcript; _publish(fx["transcript_id"])
    html = client.get(f"/al/birmingham/items/{fx['item_id']}/").get_data(as_text=True)
    assert "From the video" in html
    assert "Item fifteen. I would like a summary." in html
    assert f"/al/birmingham/meetings/{fx['meeting_id']}/transcript/#t-0" in html


def test_item_page_without_segments_has_no_excerpt_block(client, meeting_with_transcript):
    fx = meeting_with_transcript; _publish(fx["transcript_id"])
    with db_cursor() as cur:
        cur.execute("""INSERT INTO agenda_items (meeting_id, item_number, title)
                       VALUES (%s, '16', 'Nothing said') RETURNING id""", [fx["meeting_id"]])
        other = cur.fetchone()["id"]
    html = client.get(f"/al/birmingham/items/{other}/").get_data(as_text=True)
    assert "From the video" not in html


def test_item_page_no_excerpt_when_transcript_not_public(client, meeting_with_transcript):
    fx = meeting_with_transcript
    html = client.get(f"/al/birmingham/items/{fx['item_id']}/").get_data(as_text=True)
    assert "From the video" not in html


def test_item_excerpt_speaker_numbers_match_full_page(client, meeting_with_transcript):
    # S0 (O'Quinn) is cluster 1 and S1 is cluster 2 in the fixture; a later item
    # whose only voice is a new cluster S2 must read "Speaker 3", not "Speaker 1".
    fx = meeting_with_transcript; _publish(fx["transcript_id"])
    with db_cursor() as cur:
        cur.execute("""INSERT INTO agenda_items (meeting_id, item_number, title)
                       VALUES (%s, '17', 'Later item') RETURNING id""", [fx["meeting_id"]])
        later = cur.fetchone()["id"]
        cur.execute("""INSERT INTO transcript_segments
                         (transcript_id, seq, start_s, end_s, text, cluster_label, agenda_item_id)
                       VALUES (%s, 3, 4000.0, 4004.0, 'Point of order.', 'S2', %s)""",
                    [fx["transcript_id"], later])
    item_html = client.get(f"/al/birmingham/items/{later}/").get_data(as_text=True)
    page_html = client.get(f"/al/birmingham/meetings/{fx['meeting_id']}/transcript/").get_data(as_text=True)
    assert "Speaker 3" in item_html and "Speaker 1" not in item_html
    assert "Speaker 3" in page_html
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/integration/test_transcript_routes.py -k item_page -v`
Expected: first and fourth FAIL ("From the video" missing; "Speaker 3" missing); the middle two PASS trivially.

- [ ] **Step 3: Add the service function**

Append to `src/docket/services/transcripts.py`:

```python
def excerpt_for_item(item_id: int, max_turns: int = 4) -> dict | None:
    """First few transcript turns tagged with this agenda item, or None."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT t.id AS transcript_id, t.meeting_id
                 FROM agenda_items ai
                 JOIN transcripts t ON t.meeting_id = ai.meeting_id
                WHERE ai.id = %s AND t.status = ANY(%s)""",
            [item_id, list(PUBLIC_STATUSES)],
        )
        head = cur.fetchone()
        if head is None:
            return None
        cur.execute(
            """SELECT s.seq, s.start_s, s.end_s, s.text, s.cluster_label, s.is_silence,
                      s.agenda_item_id,
                      COALESCE(cm.name, sp.display_name) AS speaker_name,
                      sp.confidence AS speaker_confidence,
                      sp.council_member_id AS speaker_member_id
                 FROM transcript_segments s
                 LEFT JOIN transcript_speakers sp ON sp.id = s.speaker_id
                 LEFT JOIN council_members cm ON cm.id = sp.council_member_id
                WHERE s.transcript_id = %s AND s.agenda_item_id = %s AND s.is_silence = FALSE
                ORDER BY s.seq""",
            [head["transcript_id"], item_id],
        )
        segs = [dict(r) for r in cur.fetchall()]
    if not segs:
        return None
    turns = group_turns(segs, ordinals=speaker_ordinals(head["transcript_id"]))
    return {
        "meeting_id": head["meeting_id"],
        "transcript_id": head["transcript_id"],
        "turns": turns[:max_turns],
        "anchor": turns[0].anchor,
        "truncated": len(turns) > max_turns,
    }
```

The excerpt passes `speaker_ordinals(transcript_id)` so an unresolved voice carries the same "Speaker N" here as on the full transcript page. Without the map, `group_turns` would number from the slice and the item page could say "Speaker 1" where the transcript says "Speaker 3".

- [ ] **Step 4: Wire the route and template**

In `item_detail` (`src/docket/web/public.py`), before `render_template`:

```python
    from docket.services import transcripts as tsvc
    transcript_excerpt = tsvc.excerpt_for_item(item_id)
```

and pass `transcript_excerpt=transcript_excerpt`.

`src/docket/web/templates/partials/transcript_excerpt.html`:

```html
{% if transcript_excerpt %}
<section class="item-body transcript-excerpt">
  <div class="t-eyebrow">From the video</div>
  {% for turn in transcript_excerpt.turns %}
  <p class="transcript-excerpt-turn">
    <span class="t-mono t-meta">{{ turn.start_s | format_timestamp }}</span>
    <strong>{{ turn.speaker_label }}:</strong> {{ turn.text }}
  </p>
  {% endfor %}
  <p class="t-meta">
    <a class="link" href="/al/{{ municipality.slug }}/meetings/{{ transcript_excerpt.meeting_id }}/transcript/#{{ transcript_excerpt.anchor }}">
      {% if transcript_excerpt.truncated %}Read the full discussion →{% else %}Open in the transcript →{% endif %}
    </a>
    · machine-generated transcript
  </p>
</section>
{% endif %}
```

In `item_detail.html`, directly after the `item-body` section ends (before the editorial coverage block at line ~111), add:

```html
{% include "partials/transcript_excerpt.html" %}
```

- [ ] **Step 5: Run to verify pass**

Run: `pytest tests/integration/test_transcript_routes.py -v`
Expected: 8 PASS. (Review Focus item 5 is `test_item_page_without_segments_has_no_excerpt_block`.)

- [ ] **Step 6: Commit**

```bash
git add src/docket/services/transcripts.py src/docket/web/public.py src/docket/web/templates/item_detail.html src/docket/web/templates/partials/transcript_excerpt.html tests/integration/test_transcript_routes.py
git -c user.email=hello@docket.pub commit -m "feat(web): 'From the video' transcript excerpt on item pages

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: Transcript search with a `speaker:` filter

**Files:**
- Modify: `src/docket/services/transcripts.py` (add `parse_speaker_token`, `search_transcripts`), `src/docket/web/public.py` (`search`), `src/docket/web/templates/search.html`
- Create: `src/docket/web/templates/partials/search_transcript_hit.html`
- Test: `tests/unit/test_transcript_search_parse.py`, `tests/integration/test_transcript_search.py`

**Interfaces:**
- Produces:
  - `parse_speaker_token(q: str) -> tuple[str, str | None]` — strips one `speaker:<name>` or `speaker:"Two Words"` token; returns the remaining query and the speaker text.
  - `search_transcripts(q: str, *, municipality_slug: str | None, speaker: str | None, limit: int = 10, offset: int = 0) -> list[dict]` with keys `meeting_id, municipality_slug, meeting_title, meeting_date, seq, start_s, speaker_name, headline, anchor_url`. Uses `websearch_to_tsquery('english', q)` when `q` is non-empty; speaker filter is `COALESCE(cm.name, sp.display_name) % speaker OR ILIKE '%speaker%'` via the pg_trgm `%` operator; ordered by `ts_rank` then `meeting_date DESC, seq`; with no text query ordered by `meeting_date DESC, seq`.

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/unit/test_transcript_search_parse.py
from docket.services.transcripts import parse_speaker_token


def test_no_token():
    assert parse_speaker_token("license plate reader") == ("license plate reader", None)


def test_single_word_token_anywhere():
    assert parse_speaker_token("executive session speaker:oquinn") == ("executive session", "oquinn")
    assert parse_speaker_token("speaker:Tate recess") == ("recess", "Tate")


def test_quoted_token():
    assert parse_speaker_token('speaker:"Darrell O\'Quinn" packet') == ("packet", "Darrell O'Quinn")


def test_token_only():
    assert parse_speaker_token("speaker:smith") == ("", "smith")
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_transcript_search_parse.py -v`
Expected: FAIL, `ImportError: parse_speaker_token`.

- [ ] **Step 3: Add the parser and the search query**

Append to `src/docket/services/transcripts.py` (and add `from markupsafe import Markup, escape` to the imports at the top of the module; markupsafe ships with Flask):

```python
import re as _re

_SPEAKER_RE = _re.compile(r'\bspeaker:(?:"([^"]+)"|(\S+))', _re.IGNORECASE)


def parse_speaker_token(q: str) -> tuple[str, str | None]:
    m = _SPEAKER_RE.search(q)
    if not m:
        return q.strip(), None
    speaker = m.group(1) or m.group(2)
    rest = (q[:m.start()] + q[m.end():]).strip()
    return _re.sub(r"\s{2,}", " ", rest), speaker


def search_transcripts(q: str, *, municipality_slug: str | None, speaker: str | None,
                       limit: int = 10, offset: int = 0) -> list[dict]:
    where = ["mu.active = TRUE", "m.is_hidden = FALSE", "t.status = ANY(%s)", "s.is_silence = FALSE"]
    params: list = [list(PUBLIC_STATUSES)]
    if municipality_slug:
        where.append("mu.slug = %s"); params.append(municipality_slug)
    if speaker:
        where.append("(COALESCE(cm.name, sp.display_name) %% %s OR COALESCE(cm.name, sp.display_name) ILIKE %s)")
        params.extend([speaker, f"%{speaker}%"])
    if q:
        where.append("s.search_vector @@ websearch_to_tsquery('english', %s)"); params.append(q)
        select_rank = "ts_rank(s.search_vector, websearch_to_tsquery('english', %s)) AS rank,"
        headline = "ts_headline('english', s.text, websearch_to_tsquery('english', %s), 'MaxWords=40, MinWords=20, StartSel=[[HL]], StopSel=[[/HL]]') AS headline"
        head_params = [q, q]
        order = "ORDER BY rank DESC, m.meeting_date DESC, s.seq"
    else:
        select_rank = "0::float AS rank,"
        headline = "left(s.text, 240) AS headline"
        head_params = []
        order = "ORDER BY m.meeting_date DESC, s.seq"
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT m.id AS meeting_id, mu.slug AS municipality_slug, m.title AS meeting_title,
                       m.meeting_date, s.seq, s.start_s,
                       COALESCE(cm.name, sp.display_name) AS speaker_name,
                       {select_rank}
                       {headline}
                  FROM transcript_segments s
                  JOIN transcripts t ON t.id = s.transcript_id
                  JOIN meetings m ON m.id = t.meeting_id
                  JOIN municipalities mu ON mu.id = m.municipality_id
                  LEFT JOIN transcript_speakers sp ON sp.id = s.speaker_id
                  LEFT JOIN council_members cm ON cm.id = sp.council_member_id
                 WHERE {' AND '.join(where)}
                 {order}
                 LIMIT %s OFFSET %s""",
            [*head_params, *params, limit, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["headline"] = _safe_headline(r["headline"] or "")
        r["anchor_url"] = f"/al/{r['municipality_slug']}/meetings/{r['meeting_id']}/transcript/#t-{r['seq']}"
    return rows


_HL_OPEN, _HL_CLOSE = "[[HL]]", "[[/HL]]"


def _safe_headline(raw: str) -> Markup:
    """Escape transcript text, then turn the ts_headline markers into <mark>.

    ts_headline does not HTML-escape the document (the Postgres docs say so),
    and the no-text-query path is a plain left(text, 240). Both go through here,
    so a transcript containing '<' or '&' can never inject markup. Returns a
    Markup object: Jinja renders it as-is, the template needs no `| safe`.
    """
    escaped = str(escape(raw))
    return Markup(escaped.replace(_HL_OPEN, "<mark>").replace(_HL_CLOSE, "</mark>"))
```

Parameter order matters: the `SELECT` list's placeholders (`head_params`) come before the `WHERE` placeholders (`params`). The `%%` in the speaker clause is the psycopg2 escape for the trgm `%` operator.

- [ ] **Step 4: Run unit tests to verify pass**

Run: `pytest tests/unit/test_transcript_search_parse.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Write the failing integration tests**

```python
# tests/integration/test_transcript_search.py
import pytest
from datetime import date
from docket.config import DATABASE_URL
from docket.db import db_cursor
from docket.services import transcripts as tsvc
from docket.web import create_app

pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run against Railway DB.",
)


@pytest.fixture(scope="module")
def client():
    app = create_app(); app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def searchable():
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, external_id, video_url)
                       VALUES (%s, 'TS test', %s, '999903', 'https://x/v') RETURNING id""",
                    [muni, date(2026, 9, 3)])
        mid = cur.fetchone()["id"]
        cur.execute("INSERT INTO processing_status (meeting_id) VALUES (%s)", [mid])
        cur.execute("""INSERT INTO transcripts (meeting_id, status, uploaded_at) VALUES (%s, 'uploaded', now())
                       RETURNING id""", [mid])
        tid = cur.fetchone()["id"]
        cur.execute("""INSERT INTO transcript_speakers (meeting_id, cluster_label, display_name, confidence)
                       VALUES (%s, 'S0', 'Darrell O''Quinn', 0.95) RETURNING id""", [mid])
        sid = cur.fetchone()["id"]
        cur.execute("""INSERT INTO transcript_segments (transcript_id, seq, start_s, end_s, text, cluster_label, speaker_id)
                       VALUES (%s, 0, 10, 14, 'the agreement is not in the packet', 'S0', %s),
                              (%s, 1, 14, 20, 'license plate reader cameras give access', 'S1', NULL),
                              (%s, 2, 20, 90, '', NULL, NULL)""", [tid, sid, tid, tid])
        cur.execute("UPDATE transcript_segments SET is_silence = TRUE WHERE transcript_id=%s AND seq=2", [tid])
    yield {"meeting_id": mid}
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id = %s", [mid])


def test_text_search_returns_headline_and_anchor(searchable):
    rows = tsvc.search_transcripts("license plate", municipality_slug="birmingham", speaker=None)
    hit = next(r for r in rows if r["meeting_id"] == searchable["meeting_id"])
    assert "<mark>license</mark>" in hit["headline"]
    assert hit["anchor_url"].endswith(f"/meetings/{searchable['meeting_id']}/transcript/#t-1")


def test_speaker_filter_with_text(searchable):
    rows = tsvc.search_transcripts("packet", municipality_slug="birmingham", speaker="oquinn")
    assert [r["seq"] for r in rows if r["meeting_id"] == searchable["meeting_id"]] == [0]


def test_speaker_only_query_has_no_sql_error_and_returns_turns(searchable):
    rows = tsvc.search_transcripts("", municipality_slug="birmingham", speaker="O'Quinn")
    assert any(r["meeting_id"] == searchable["meeting_id"] and r["seq"] == 0 for r in rows)


def test_headline_escapes_html_in_transcript_text(searchable):
    with db_cursor() as cur:
        cur.execute("SELECT id FROM transcripts WHERE meeting_id=%s", [searchable["meeting_id"]])
        tid = cur.fetchone()["id"]
        cur.execute("""INSERT INTO transcript_segments (transcript_id, seq, start_s, end_s, text, cluster_label)
                       VALUES (%s, 3, 95, 99, 'fee is <b>less</b> than 5 & <script>x</script> per license', 'S1')""",
                    [tid])
    # ts_headline path
    rows = tsvc.search_transcripts("license", municipality_slug="birmingham", speaker=None)
    hit = next(r for r in rows if r["meeting_id"] == searchable["meeting_id"] and r["seq"] == 3)
    assert "<script>" not in hit["headline"] and "&lt;script&gt;" in hit["headline"]
    assert "&amp;" in hit["headline"] and "<mark>license</mark>" in hit["headline"]
    # left(text, 240) fallback path
    rows = tsvc.search_transcripts("", municipality_slug="birmingham", speaker=None)
    hit = next(r for r in rows if r["meeting_id"] == searchable["meeting_id"] and r["seq"] == 3)
    assert "<script>" not in hit["headline"] and "&lt;b&gt;less&lt;/b&gt;" in hit["headline"]


def test_search_page_renders_transcript_section(client, searchable):
    html = client.get("/search?q=license+plate&city=birmingham").get_data(as_text=True)
    assert "From transcripts" in html
    assert f"/meetings/{searchable['meeting_id']}/transcript/#t-1" in html
```

- [ ] **Step 6: Run to verify failure**

Run: `pytest tests/integration/test_transcript_search.py -v`
Expected: first four PASS (service exists and escapes), the page test FAILS ("From transcripts" missing).

- [ ] **Step 7: Wire the search route and template**

In `search()` (`src/docket/web/public.py`), after `results = ...` block:

```python
    from docket.services import transcripts as tsvc
    transcript_hits: list[dict] = []
    if q:
        clean_q, speaker = tsvc.parse_speaker_token(q)
        if clean_q or speaker:
            transcript_hits = tsvc.search_transcripts(
                clean_q, municipality_slug=city, speaker=speaker, limit=10, offset=offset // 2,
            )
```

and pass `transcript_hits=transcript_hits` to `render_template`. Note the existing agenda-item search still receives the raw `q`; a `speaker:` token simply matches nothing there, which is fine.

`src/docket/web/templates/partials/search_transcript_hit.html`:

```html
<li class="search-transcript-hit">
  <a class="link" href="{{ hit.anchor_url }}">
    <span class="t-mono t-meta">{{ hit.start_s | format_timestamp }}</span>
    {% if hit.speaker_name %}<strong>{{ hit.speaker_name }}:</strong>{% endif %}
    {{ hit.headline }}
  </a>
  <div class="t-meta">{{ hit.meeting_title }} · {{ hit.meeting_date | format_date }} · machine transcript</div>
</li>
```

In `search.html`, immediately before the `{% if results %}` at line ~57, add:

```html
    {% if transcript_hits %}
    <section class="feed">
        <div class="feed-head"><div>
            <div class="t-eyebrow">From transcripts</div>
            <h2 class="feed-title t-display" style="font-size: 24px;">What was said</h2>
            <div class="t-meta">Tip: add <code>speaker:name</code> to filter by who said it.</div>
        </div></div>
        <ul class="search-transcript-hits" style="list-style:none; padding:0;">
        {% for hit in transcript_hits %}{% include 'partials/search_transcript_hit.html' %}{% endfor %}
        </ul>
    </section>
    {% endif %}
```

Also change the "No results" condition at line ~87 so it only fires when both `results` and `transcript_hits` are empty.

- [ ] **Step 8: Run to verify pass**

Run: `pytest tests/integration/test_transcript_search.py tests/unit/test_transcript_search_parse.py -v`
Expected: 9 PASS. (Review Focus item 4 is `test_speaker_only_query_has_no_sql_error_and_returns_turns`.)

- [ ] **Step 9: Commit**

```bash
git add src/docket/services/transcripts.py src/docket/web/public.py src/docket/web/templates/search.html src/docket/web/templates/partials/search_transcript_hit.html tests/unit/test_transcript_search_parse.py tests/integration/test_transcript_search.py
git -c user.email=hello@docket.pub commit -m "feat(search): transcript hits with headline snippets and speaker: filter

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 13: Transcript failures on the data debt page

**Files:**
- Modify: `src/docket/services/transcripts.py` (add `list_transcript_debt`), `src/docket/web/public.py` (`data_debt`), `src/docket/web/templates/data_debt.html`
- Test: `tests/integration/test_transcript_routes.py` (add two tests)

**Interfaces:**
- Produces: `list_transcript_debt(municipality_id: int, limit: int = 50) -> list[dict]` with keys `meeting_id, meeting_title, meeting_date, status, last_error, stage_attempts, friendly_label`. Includes meetings with a video URL and either no `transcripts` row older than 14 days past the meeting date, a row in `failed` or `needs_review`, or a `low_speech` row whose recording is at least `SHORT_MEETING_S = 600.0` seconds long. A `low_speech` row on a recording under ten minutes is a short session (roll call, adjourn), not a failure, and never shows as debt. Friendly labels: `failed → "Transcription failed"`, `low_speech → "No usable audio"`, `needs_review → "Transcript held for review"`, missing → "Not yet transcribed".

- [ ] **Step 1: Write the failing tests (append to `tests/integration/test_transcript_routes.py`)**

```python
def test_data_debt_lists_failed_transcript(client, meeting_with_transcript):
    fx = meeting_with_transcript
    with db_cursor() as cur:
        cur.execute("""UPDATE transcripts SET status='failed', stage_attempts=3,
                              last_error='ffmpeg could not read: 403 Forbidden' WHERE id=%s""",
                    [fx["transcript_id"]])
    html = client.get("/al/birmingham/data-debt").get_data(as_text=True)
    assert "Transcription failed" in html and "TR test" in html


def test_data_debt_omits_uploaded_transcript(client, meeting_with_transcript):
    fx = meeting_with_transcript; _publish(fx["transcript_id"])
    html = client.get("/al/birmingham/data-debt").get_data(as_text=True)
    assert "TR test" not in html


def test_data_debt_low_speech_only_counts_on_long_recordings(client, meeting_with_transcript):
    fx = meeting_with_transcript
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status='low_speech', audio_duration_s=140 WHERE id=%s",
                    [fx["transcript_id"]])
    html = client.get("/al/birmingham/data-debt").get_data(as_text=True)
    assert "TR test" not in html                      # a 2-minute recording is a short session
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET audio_duration_s=5400 WHERE id=%s", [fx["transcript_id"]])
    html = client.get("/al/birmingham/data-debt").get_data(as_text=True)
    assert "No usable audio" in html and "TR test" in html   # 90 minutes of video, no speech: debt
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/integration/test_transcript_routes.py -k data_debt -v`
Expected: first and third FAIL, second PASS trivially.

- [ ] **Step 3: Add the query**

Append to `src/docket/services/transcripts.py`:

```python
TRANSCRIPT_DEBT_LABELS = {
    "failed": "Transcription failed",
    "low_speech": "No usable audio",
    "needs_review": "Transcript held for review",
    None: "Not yet transcribed",
}

# A low_speech result on a recording shorter than this is a short session
# (roll call and adjourn), not a problem to fix. Longer recordings with under
# three minutes of speech are a dead or near-empty stream and stay on the list.
SHORT_MEETING_S = 600.0


def list_transcript_debt(municipality_id: int, limit: int = 50) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            """SELECT m.id AS meeting_id, m.title AS meeting_title, m.meeting_date,
                      t.status, t.last_error, t.stage_attempts
                 FROM meetings m
                 LEFT JOIN transcripts t ON t.meeting_id = m.id
                WHERE m.municipality_id = %s
                  AND m.is_hidden = FALSE
                  AND m.video_url IS NOT NULL
                  AND m.external_id ~ '^[0-9]+$'
                  AND (
                        t.status IN ('failed', 'needs_review')
                     OR (t.status = 'low_speech' AND COALESCE(t.audio_duration_s, 0) >= %s)
                     OR (t.id IS NULL AND m.meeting_date < CURRENT_DATE - 14
                         AND m.meeting_date >= DATE '2025-10-28')
                  )
                ORDER BY m.meeting_date DESC
                LIMIT %s""",
            [municipality_id, SHORT_MEETING_S, limit],
        )
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["friendly_label"] = TRANSCRIPT_DEBT_LABELS.get(r["status"], "Transcript problem")
    return rows
```

The `2025-10-28` floor is the current-council backfill cutoff from the spec; older meetings without a transcript are not debt until a later backfill is approved. Move this constant to `docket/config.py` as `TRANSCRIPT_BACKFILL_SINCE = os.environ.get("TRANSCRIPT_BACKFILL_SINCE", "2025-10-28")` and pass it as a parameter rather than hard-coding the date in SQL. `audio_duration_s` is set by the producer at the `audio_fetched` step (Task 9 `process_claim`), before any `low_speech` decision, so it is populated for every `low_speech` row; the `COALESCE` only guards hand-inserted rows. An admin control to dismiss an individual debt row belongs with the admin surfaces in Plan 2.

- [ ] **Step 4: Wire route and template**

In `data_debt()` before `render_template`:

```python
    from docket.services import transcripts as tsvc
    transcript_debt = tsvc.list_transcript_debt(municipality["id"])
```

pass `transcript_debt=transcript_debt`. In `data_debt.html`, after the existing item lists and before the closing of the main content, add:

```html
{% if transcript_debt %}
<section class="feed">
  <div class="feed-head"><div>
    <div class="t-eyebrow">Video transcripts</div>
    <h2 class="feed-title t-display" style="font-size: 24px;">Meetings with video but no usable transcript</h2>
  </div></div>
  <ul style="list-style:none; padding:0;">
  {% for row in transcript_debt %}
    <li style="padding: 8px 0; border-bottom: 1px solid var(--color-rule, #e5e5e5);">
      <a class="link" href="/al/{{ municipality.slug }}/meetings/{{ row.meeting_id }}/">{{ row.meeting_title }}</a>
      <span class="t-meta">· {{ row.meeting_date | format_date }} · {{ row.friendly_label }}</span>
      {% if row.last_error %}<div class="t-mono t-meta">{{ row.last_error | truncate(140) }}</div>{% endif %}
    </li>
  {% endfor %}
  </ul>
</section>
{% endif %}
```

- [ ] **Step 5: Run to verify pass**

Run: `pytest tests/integration/test_transcript_routes.py -v`
Expected: 11 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/docket/services/transcripts.py src/docket/config.py src/docket/web/public.py src/docket/web/templates/data_debt.html tests/integration/test_transcript_routes.py
git -c user.email=hello@docket.pub commit -m "feat(web): surface transcript failures on the data debt page

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 14: Scale check before any backfill

**Files:**
- Create: `scripts/transcript_scale_check.py`
- Test: `tests/integration/test_transcript_scale_check.py`

**Interfaces:**
- Produces: `python scripts/transcript_scale_check.py --rows 1000000 [--sample-query search|page|both]` which, inside one transaction, inserts synthetic segments, runs `ANALYZE`, prints `EXPLAIN (ANALYZE, BUFFERS)` for the transcript page query and the search query, then `ROLLBACK`s. Exposes `run_scale_check(conn, rows: int) -> dict` returning `{"page_ms": float, "search_ms": float, "page_plan": str, "search_plan": str}`.

- [ ] **Step 1: Write the failing test (small row count, proves the rollback)**

```python
# tests/integration/test_transcript_scale_check.py
import importlib.util, pathlib
import pytest
from docket.config import DATABASE_URL
from docket.db import db, db_cursor

pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Never run the synthetic fill against Railway.",
)

spec = importlib.util.spec_from_file_location(
    "scale_check", pathlib.Path("scripts/transcript_scale_check.py"))
scale_check = importlib.util.module_from_spec(spec); spec.loader.exec_module(scale_check)


def _count():
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM transcript_segments WHERE text LIKE 'SYNTH %'")
        return cur.fetchone()["n"]


def test_scale_check_runs_and_leaves_nothing_behind():
    before = _count()
    with db() as conn:
        result = scale_check.run_scale_check(conn, rows=5000)
    assert result["page_ms"] >= 0 and result["search_ms"] >= 0
    assert "Execution Time" in result["search_plan"] and "Execution Time" in result["page_plan"]
    assert "ANALYZE" in result["log"]
    # Index usage is asserted by eye on the 1M-row run (Step 5); at 5,000 rows a
    # sequential scan is a legitimate planner choice.
    assert _count() == before
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/integration/test_transcript_scale_check.py -v`
Expected: FAIL, script file not found.

- [ ] **Step 3: Write the script**

```python
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
```

`run_scale_check` calls `conn.rollback()` itself, and `docket.db.db()` commits on exit; after a rollback that commit is a no-op, so nothing persists.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/integration/test_transcript_scale_check.py -v`
Expected: 1 PASS.

- [ ] **Step 5: Run the real check locally and record the numbers**

Run: `python scripts/transcript_scale_check.py --rows 1000000`
Expected: both plans use the GIN index (search) and the `(transcript_id, seq)` unique index (page); record `page_ms` and `search_ms` and the final table and index sizes (`SELECT pg_size_pretty(pg_total_relation_size('transcript_segments'))` before the rollback, add that line to the script output) in the spec's Section 1 storage paragraph, replacing the estimate.

- [ ] **Step 6: Commit**

```bash
git add scripts/transcript_scale_check.py tests/integration/test_transcript_scale_check.py docs/superpowers/specs/2026-10-05-meeting-transcripts-design.md
git -c user.email=hello@docket.pub commit -m "chore: synthetic-scale EXPLAIN check for transcript queries

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Operator steps after the code tasks

1. Deploy: `scripts/deploy.sh --service docket-web` then `--service worker`; migrations run at container start.
2. Create the role on Railway: `psql "$PGURL" -v password="$(openssl rand -hex 32)" -f scripts/sql/create_transcriber_role.sql` and put the URL in `transcriber/.env` on the Legion.
3. Legion bring-up (Task 9 Step 8). Then `docker compose run --rm transcriber --since 2025-10-28 --limit 3` and confirm three meetings reach `uploaded` and their transcript pages render on docket.pub.
4. Run `python scripts/transcript_scale_check.py` once against a local database and record the numbers (Task 14 Step 5).
5. Full current-council batch: `--limit 100 --max-hours 6`. About 69 meetings have video in that window as of 2026-10-06.
6. Hand off to Plan 2 (worker stages and comparison).

## Self-review notes

- **Spec coverage, this plan:** Section 1 → Task 1; dedicated role → Task 2; pilot fixtures → Task 3; Section 2 producer (contract, prompt budget, audio, claim with zombie release, `transcribed` resume, COPY upload, heartbeat, OOM fallback, silence markers, `low_speech` floor, bind-mount work dir, `.wslconfig`, power plan, bring-up) → Tasks 4–9; Section 5 transcript page, item excerpt, search with `speaker:`, data debt → Tasks 10–13; Section 6 scale check with ANALYZE → Task 14. Deferred to Plan 2 by design: Sections 3 and 4, admin queue, speaker correction UI, public discrepancy block, webhook alert (including the heartbeat staleness alert, which needs the worker task), Haiku A/B, ship gate, live tests.
- **Type consistency:** `Claim.status` values `claimed|transcribed` match `claim_next`; `TranscriptOutput` field names match `upload()`'s UPDATE; `Turn.anchor` format `t-<seq>` matches the template ids, the excerpt link, and `search_transcripts.anchor_url`; `PUBLIC_STATUSES` is the single list used by the page, excerpt, and search.
- **Speaker numbering:** `speaker_ordinals` is the single source of "Speaker N" across the page and the excerpt (Tasks 10–11). The earlier "accepted rough edge" of per-slice numbering is gone.
- **Plan review dispositions (2026-10-07), accepted:** search headline XSS, fixed by escaping in Python and swapping `[[HL]]` markers for `<mark>` (Task 12); `low_speech` on short recordings is not debt below 600 s of audio (Task 13); `whisperx` dropped from `transcriber/requirements.txt` until the fallback engine task (Task 9); item excerpt numbering unified via `speaker_ordinals` (Tasks 10–11).
- **Plan review dispositions, rejected with evidence (do not re-raise):** "ANALYZE cannot run inside a transaction block" is false; that restriction is VACUUM's. Confirmed on the production PostgreSQL 18 with `BEGIN; ANALYZE meetings; ROLLBACK;` succeeding and `BEGIN; VACUUM meetings;` failing with "VACUUM cannot run inside a transaction block". "pyannote 3.1 does not accept `return_embeddings=True`" is false; `SpeakerDiarization.apply` declares `return_embeddings: bool = False` and `Pipeline.__call__` forwards `**kwargs` in tags 3.1.0 and 3.1.1. Storing the ordinal as a column on `transcript_speakers` was declined in favor of the GROUP BY query: no producer coupling, no schema change, and it stays correct if an admin remap merges clusters.
