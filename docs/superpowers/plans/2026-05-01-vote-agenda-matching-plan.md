# Vote ↔ Agenda Item Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the singular `votes.agenda_item_id` FK with an N:M join table, fix the parser context window, classify votes as substantive vs. consent-block, and add an adoption-aware lifecycle that flips provisional consent links to official after council adopts the minutes.

**Architecture:** New `vote_agenda_items` join table holds per-link metadata (confidence, method, association type, provisional flag, manual shield, active flag). Parser captures 1500-char pre-vote window plus full raw vote block. Matcher classifies each vote and dispatches to substantive (1:1) or consent-block (1:N, named-callout + default-fill) handlers via a single `_upsert_link()` writer that respects the `is_manual` shield at both app and DB level. New `services/minutes_adoption.py` runs a stateless sweep after each ingest; a strict re-parse triggered from both the sweep and the matcher promotes provisional consent links to official.

**Tech Stack:** Python 3.10+, PostgreSQL 16 (psycopg2), Flask + Jinja2 + HTMX, pytest. Migrations are pure SQL strings (`SQL_UP` / `SQL_DOWN`) executed by `docket.migrations.runner`.

**Spec:** `docs/superpowers/specs/2026-05-01-vote-agenda-matching-design.md`

**Out of scope (PR 2 — separate plan):** dropping the singular columns (`votes.agenda_item_id`, `votes.match_method`, `votes.match_confidence`).

---

## File Structure

### Files to create

| Path | Responsibility |
|---|---|
| `src/docket/migrations/009_vote_agenda_items.py` | Schema migration: create `vote_agenda_items` table + `meetings.minutes_adopted_at` column |
| `src/docket/migrations/010_backfill_vote_agenda_items.py` | Data migration: copy existing 110 explicit matches into the join table |
| `src/docket/services/minutes_adoption.py` | Adoption-pattern detection, sweep service, multi-match logging |
| `tests/unit/test_vote_dataclass.py` | `AgendaItemLink` + `Vote` convenience properties |
| `tests/unit/test_minutes_parser.py` | Parser context window + `is_likely_consent` flag |
| `tests/unit/test_vote_matcher.py` | Classify, substantive/consent matchers, upsert manual-shield, strict re-parse |
| `tests/unit/test_minutes_adoption.py` | Adoption-pattern regex, validity/window/multi-match branches |

### Files to modify

| Path | Change |
|---|---|
| `src/docket/migrations/runner.py` | Register migrations 009 and 010 in `MIGRATIONS` list |
| `src/docket/models/vote.py` | Add `AgendaItemLink`; refactor `Vote` (drop singular FK fields, add `agenda_links`, add convenience properties) |
| `src/docket/analysis/minutes_parser.py` | Widen `PRE_VOTE_WINDOW` to 1500; add `raw_text` field to `ParsedVote`; add `is_likely_consent`; populate both context windows |
| `src/docket/services/ingest.py` | Persist `raw_text` to `votes.raw_text`; call `sweep_adoptions()` at end of pipeline |
| `src/docket/analysis/vote_matcher.py` | Refactor: `_classify_vote`, `_match_substantive`, `_match_consent_block`, `_upsert_link`, `strict_reparse_meeting`; matcher-side strict re-parse trigger |
| `src/docket/services/query.py` | Rewrite `list_votes()` to 3-query pattern using join table; add `include_excerpts` param |
| `src/docket/web/templates/meeting.html` | Render N:M (consent-block collapse + per-link badges + provisional/adopted pills) |
| `scripts/backfill_vote_context.py` | Use new parser; cache parse output to `data/minutes_cache/<meeting_id>.json` for re-runs |

### Files unchanged (verify by inspection)

- `src/docket/db.py`, `src/docket/models/meeting.py`, `src/docket/models/agenda.py` — untouched
- `scripts/run_vote_matching.py` — same entry point, picks up updated matcher logic automatically
- All other unit test files — existing tests must remain green

---

## Conventions referenced throughout

- All Python uses absolute imports rooted at `docket.*`
- DB access via `from docket.db import db, db_cursor` (RealDictCursor by default in `db_cursor()`)
- Tests live in `tests/unit/`, run with `pytest tests/unit/<file> -v`
- Migrations export `SQL_UP` and `SQL_DOWN` string constants
- Commits use conventional prefix (`feat:`, `fix:`, `refactor:`, `test:`, `chore:`)
- Run `ruff check src/` before committing — codebase is ruff-clean

---

# Phase 1 — Schema + Dataclasses

Goal: ship the new shape end-to-end so subsequent phases have somewhere to land their work. After Phase 1 completes, the codebase compiles and tests pass; the join table exists with the original 110 matches inside.

## Task 1.1: Create migration 009 (schema)

**Files:**
- Create: `src/docket/migrations/009_vote_agenda_items.py`

- [ ] **Step 1: Write the migration file**

```python
"""Add vote_agenda_items join table and meetings.minutes_adopted_at."""

SQL_UP = """
CREATE TABLE IF NOT EXISTS vote_agenda_items (
    id                 SERIAL PRIMARY KEY,
    vote_id            INT NOT NULL REFERENCES votes(id) ON DELETE CASCADE,
    agenda_item_id     INT NOT NULL REFERENCES agenda_items(id) ON DELETE CASCADE,
    association_type   TEXT NOT NULL CHECK (association_type IN
                         ('explicit', 'consent_named', 'consent_implicit', 'positional')),
    match_method       TEXT,
    match_confidence   REAL NOT NULL CHECK (match_confidence BETWEEN 0 AND 1),
    excerpt_context    TEXT,
    provisional        BOOLEAN NOT NULL DEFAULT TRUE,
    is_manual          BOOLEAN NOT NULL DEFAULT FALSE,
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (vote_id, agenda_item_id)
);

CREATE INDEX IF NOT EXISTS idx_vai_vote ON vote_agenda_items(vote_id);
CREATE INDEX IF NOT EXISTS idx_vai_agenda_item ON vote_agenda_items(agenda_item_id);
CREATE INDEX IF NOT EXISTS idx_vai_provisional ON vote_agenda_items(provisional) WHERE provisional;
CREATE INDEX IF NOT EXISTS idx_vai_active ON vote_agenda_items(is_active) WHERE is_active;

ALTER TABLE meetings ADD COLUMN IF NOT EXISTS minutes_adopted_at TIMESTAMPTZ NULL;
"""

SQL_DOWN = """
ALTER TABLE meetings DROP COLUMN IF EXISTS minutes_adopted_at;
DROP INDEX IF EXISTS idx_vai_active;
DROP INDEX IF EXISTS idx_vai_provisional;
DROP INDEX IF EXISTS idx_vai_agenda_item;
DROP INDEX IF EXISTS idx_vai_vote;
DROP TABLE IF EXISTS vote_agenda_items;
"""
```

- [ ] **Step 2: Commit**

```bash
git add src/docket/migrations/009_vote_agenda_items.py
git commit -m "feat: migration 009 — vote_agenda_items table and minutes_adopted_at column"
```

---

## Task 1.2: Create migration 010 (data backfill)

**Files:**
- Create: `src/docket/migrations/010_backfill_vote_agenda_items.py`

- [ ] **Step 1: Write the migration file**

```python
"""Copy existing votes.agenda_item_id matches into vote_agenda_items.

Pre-N:M matches are unambiguous, so they land as provisional=FALSE.
Idempotent via ON CONFLICT.
"""

SQL_UP = """
INSERT INTO vote_agenda_items
    (vote_id, agenda_item_id, association_type, match_method,
     match_confidence, provisional, is_manual, is_active)
SELECT v.id,
       v.agenda_item_id,
       'explicit',
       v.match_method,
       COALESCE(v.match_confidence, 0.5),
       FALSE,
       FALSE,
       TRUE
FROM votes v
WHERE v.agenda_item_id IS NOT NULL
ON CONFLICT (vote_id, agenda_item_id) DO NOTHING;
"""

SQL_DOWN = """
-- Reverse: remove the migrated rows. We identify them by association_type='explicit'
-- AND match_method matching the original simple matcher methods, AND provisional=FALSE.
-- This is approximate; if you've inserted other 'explicit' rows, this will catch them too.
-- For full safety, take a backup before running --down.
DELETE FROM vote_agenda_items
WHERE association_type = 'explicit'
  AND provisional = FALSE
  AND is_manual = FALSE
  AND match_method IN ('resolution_number', 'item_number', 'text_similarity');
"""
```

- [ ] **Step 2: Commit**

```bash
git add src/docket/migrations/010_backfill_vote_agenda_items.py
git commit -m "feat: migration 010 — backfill existing matches into vote_agenda_items"
```

---

## Task 1.3: Register migrations in the runner

**Files:**
- Modify: `src/docket/migrations/runner.py:16-25`

- [ ] **Step 1: Add the two new migrations to the list**

Replace the `MIGRATIONS` list:

```python
MIGRATIONS = [
    "docket.migrations.001_initial",
    "docket.migrations.002_seed_cities",
    "docket.migrations.003_add_topic",
    "docket.migrations.004_expand_meeting_types",
    "docket.migrations.005_seed_council_rosters",
    "docket.migrations.006_admin_users",
    "docket.migrations.007_council_terms_and_backfill",
    "docket.migrations.008_vote_matching_support",
    "docket.migrations.009_vote_agenda_items",
    "docket.migrations.010_backfill_vote_agenda_items",
]
```

- [ ] **Step 2: Run the migrations against local DB**

```bash
venv/bin/python -m docket.migrations.runner
```

Expected output: two new "Applying migration ..." lines, ending with "All migrations applied."

- [ ] **Step 3: Verify schema**

```bash
psql -U docket -d docket_db -c "\d vote_agenda_items"
psql -U docket -d docket_db -c "SELECT COUNT(*) FROM vote_agenda_items;"
```

Expected: table description shows all columns and indexes; COUNT returns the number of pre-existing matches (~110 per memory).

- [ ] **Step 4: Commit**

```bash
git add src/docket/migrations/runner.py
git commit -m "chore: register migrations 009 and 010 in the runner"
```

---

## Task 1.4: Add `AgendaItemLink` dataclass + tests

**Files:**
- Modify: `src/docket/models/vote.py`
- Create: `tests/unit/test_vote_dataclass.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_vote_dataclass.py
"""Tests for AgendaItemLink and Vote dataclass shape."""

from docket.models.vote import AgendaItemLink


def test_agenda_item_link_required_fields():
    link = AgendaItemLink(
        id=1,
        agenda_item_id=42,
        item_number="12",
        title="A Resolution authorizing X",
        is_consent=True,
        association_type="consent_named",
        match_method="consent_block_named",
        match_confidence=1.0,
        excerpt_context="...the resolution body text...",
        provisional=True,
        is_manual=False,
        is_active=True,
    )
    assert link.id == 1
    assert link.agenda_item_id == 42
    assert link.is_consent is True
    assert link.match_confidence == 1.0


def test_agenda_item_link_is_frozen():
    link = AgendaItemLink(
        id=1, agenda_item_id=42, item_number=None, title="X",
        is_consent=False, association_type="explicit", match_method=None,
        match_confidence=0.9, excerpt_context=None, provisional=False,
        is_manual=False, is_active=True,
    )
    import dataclasses
    try:
        link.match_confidence = 0.5
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("AgendaItemLink should be frozen")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
venv/bin/pytest tests/unit/test_vote_dataclass.py -v
```

Expected: ImportError or NameError — `AgendaItemLink` doesn't exist yet.

- [ ] **Step 3: Add the dataclass**

In `src/docket/models/vote.py`, add at top after the existing imports:

```python
@dataclass(frozen=True)
class AgendaItemLink:
    """A single link between a vote and an agenda item, with link-level metadata.

    Stored in the vote_agenda_items join table. One vote can have many links
    (consent block) or one (substantive). is_active=False marks a "ghost"
    link kept for audit only — items pulled from a consent agenda before
    the vote.
    """

    id: int
    agenda_item_id: int
    item_number: str | None
    title: str
    is_consent: bool
    association_type: str  # 'explicit' | 'consent_named' | 'consent_implicit' | 'positional'
    match_method: str | None
    match_confidence: float
    excerpt_context: str | None
    provisional: bool
    is_manual: bool
    is_active: bool
```

(Place this immediately after the `MemberVote` dataclass and before the `Vote` dataclass.)

- [ ] **Step 4: Run the test to verify it passes**

```bash
venv/bin/pytest tests/unit/test_vote_dataclass.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/docket/models/vote.py tests/unit/test_vote_dataclass.py
git commit -m "feat: add AgendaItemLink dataclass for vote↔agenda-item join rows"
```

---

## Task 1.5: Refactor `Vote` dataclass to N:M shape

**Files:**
- Modify: `src/docket/models/vote.py`
- Modify: `tests/unit/test_vote_dataclass.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_vote_dataclass.py`:

```python
from docket.models.vote import Vote, MemberVote


def _make_link(**overrides):
    defaults = dict(
        id=1, agenda_item_id=42, item_number="12", title="X",
        is_consent=False, association_type="explicit", match_method="resolution_number",
        match_confidence=0.9, excerpt_context=None, provisional=False,
        is_manual=False, is_active=True,
    )
    defaults.update(overrides)
    return AgendaItemLink(**defaults)


def _make_vote(agenda_links=None, **overrides):
    defaults = dict(
        id=1, meeting_id=1, external_id=None, result="passed",
        yeas=5, nays=0, abstentions=0, source="minutes_text",
        confidence="high", header_result=None, needs_review=False,
        review_reason=None, resolution_number=None,
        agenda_links=agenda_links or [], member_votes=[],
    )
    defaults.update(overrides)
    return Vote(**defaults)


def test_vote_has_no_singular_agenda_item_id():
    """The new Vote shape removes singular FK fields."""
    vote = _make_vote()
    assert not hasattr(vote, "agenda_item_id"), \
        "Vote.agenda_item_id should be removed in the N:M refactor"
    assert not hasattr(vote, "match_confidence"), \
        "Vote.match_confidence (per-vote) is now per-link on AgendaItemLink"
    assert not hasattr(vote, "match_method"), \
        "Vote.match_method (per-vote) is now per-link on AgendaItemLink"


def test_vote_active_links_filters_inactive():
    active = _make_link(id=1, is_active=True)
    ghost = _make_link(id=2, is_active=False)
    vote = _make_vote(agenda_links=[active, ghost])
    assert vote.active_links == [active]


def test_vote_is_consent_block_true_when_any_active_link_is_consent():
    explicit = _make_link(id=1, association_type="explicit")
    consent = _make_link(id=2, association_type="consent_implicit")
    vote = _make_vote(agenda_links=[explicit, consent])
    assert vote.is_consent_block is True


def test_vote_is_consent_block_false_for_only_explicit():
    explicit = _make_link(id=1, association_type="explicit")
    vote = _make_vote(agenda_links=[explicit])
    assert vote.is_consent_block is False


def test_vote_has_provisional_links_ignores_inactive():
    """Ghost links keep provisional=True; they should NOT trigger UI warning."""
    ghost = _make_link(id=1, provisional=True, is_active=False)
    active = _make_link(id=2, provisional=False, is_active=True)
    vote = _make_vote(agenda_links=[ghost, active])
    assert vote.has_provisional_links is False


def test_vote_primary_link_only_for_single_active_link():
    one = _make_link(id=1, is_active=True)
    vote_single = _make_vote(agenda_links=[one])
    assert vote_single.primary_link is one

    two = _make_link(id=2, is_active=True)
    vote_multi = _make_vote(agenda_links=[one, two])
    assert vote_multi.primary_link is None

    vote_empty = _make_vote(agenda_links=[])
    assert vote_empty.primary_link is None


def test_vote_excluded_links_returns_only_inactive():
    active = _make_link(id=1, is_active=True)
    ghost = _make_link(id=2, is_active=False)
    vote = _make_vote(agenda_links=[active, ghost])
    assert vote.excluded_links == [ghost]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
venv/bin/pytest tests/unit/test_vote_dataclass.py -v
```

Expected: most new tests fail (Vote still has the old shape).

- [ ] **Step 3: Replace the `Vote` dataclass and `from_row`**

In `src/docket/models/vote.py`, replace the `Vote` class with:

```python
@dataclass(frozen=True)
class Vote:
    """A persisted vote row, with N:M agenda-item links attached."""

    id: int
    meeting_id: int
    external_id: str | None
    result: str  # 'passed' | 'failed' | 'tabled'
    yeas: int | None
    nays: int | None
    abstentions: int | None
    source: str  # 'video_ocr' | 'minutes_text' | 'api' | 'manual'
    confidence: str  # 'high' | 'medium' | 'low'
    header_result: str | None
    needs_review: bool
    review_reason: str | None
    resolution_number: str | None = None
    video_timestamp: float | None = None
    agenda_links: list[AgendaItemLink] = field(default_factory=list)
    member_votes: list[MemberVote] = field(default_factory=list)

    @property
    def active_links(self) -> list[AgendaItemLink]:
        return [l for l in self.agenda_links if l.is_active]

    @property
    def is_consent_block(self) -> bool:
        return any(l.association_type.startswith("consent_") for l in self.active_links)

    @property
    def has_provisional_links(self) -> bool:
        return any(l.provisional for l in self.active_links)

    @property
    def primary_link(self) -> AgendaItemLink | None:
        active = self.active_links
        return active[0] if len(active) == 1 else None

    @property
    def excluded_links(self) -> list[AgendaItemLink]:
        return [l for l in self.agenda_links if not l.is_active]
```

**Delete** the existing `Vote.from_row` classmethod entirely — the new reader (Phase 3) builds votes from joined data and won't use it.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
venv/bin/pytest tests/unit/test_vote_dataclass.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Verify nothing else imports the deleted fields**

```bash
venv/bin/grep -rn "agenda_item_id\|match_confidence\|match_method\|from_row" src/docket/ --include="*.py"
```

Expect references in `services/query.py` (will be rewritten in Phase 3) and in `analysis/vote_matcher.py` (will be rewritten in Phase 2). No other unexpected references.

- [ ] **Step 6: Commit**

```bash
git add src/docket/models/vote.py tests/unit/test_vote_dataclass.py
git commit -m "refactor: Vote dataclass to N:M shape with agenda_links and convenience properties"
```

---

## Task 1.6: Phase 1 verification — run full test suite

- [ ] **Step 1: Run all tests**

```bash
venv/bin/pytest -v
```

Expected: pre-existing tests will fail because `services/query.py:list_votes()` and `analysis/vote_matcher.py` reference removed Vote fields. This is expected at this checkpoint — Phase 2 and Phase 3 will fix them.

Specifically: tests that fail are the integration paths through `query.list_votes` and through `vote_matcher.match_*` functions. Pure unit tests (dollars, sponsors, topics, civicclerk, generic_cms, helpers, auth, vote_dataclass) MUST pass.

- [ ] **Step 2: Verify only the expected tests fail**

```bash
venv/bin/pytest tests/unit/test_vote_dataclass.py tests/unit/test_dollars.py tests/unit/test_sponsors.py tests/unit/test_topics.py tests/unit/test_civicclerk.py tests/unit/test_generic_cms.py tests/unit/test_helpers.py tests/unit/test_auth.py -v
```

Expected: ALL pass.

- [ ] **Step 3: Run ruff**

```bash
venv/bin/ruff check src/
```

Expected: clean.

- [ ] **Step 4: Tag the Phase 1 checkpoint**

```bash
git tag phase-1-complete
```

---

# Phase 2 — Parser + Matcher Core

Goal: parser captures rich context; matcher classifies and routes; substantive and consent-block matchers populate the join table; strict re-parse exists and is wired into the matcher-side trigger.

## Task 2.1: Widen parser context window + add `is_likely_consent` flag

**Files:**
- Modify: `src/docket/analysis/minutes_parser.py`
- Create: `tests/unit/test_minutes_parser.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_minutes_parser.py
"""Tests for minutes parser context capture and consent-phrase detection."""

from docket.analysis.minutes_parser import parse_minutes, ParsedVote, _contains_consent_phrase


CONSENT_BLOCK_TEXT = """
Some preceding text describing item 12 about a contract for paving services
authorized by ordinance 1854-25 with HCL Contracting at $2.3M.

The resolutions and ordinances introduced as consent agenda matters were read by the
City Clerk, all public hearings having been announced, and unanimous consent having been
previously granted, Councilmember Alexander moved their adoption which motion was
seconded by Councilmember Smitherman, and upon the roll being called, the vote was as
follows:
Ayes: Alexander, Smitherman, Williams, O'Quinn
Nays: None
"""

SUBSTANTIVE_VOTE_TEXT = """
A Resolution authorizing the Mayor to execute an agreement with HCL Contracting Inc.
in the amount of two million three hundred thousand dollars ($2,300,000) for paving
services on 9th Avenue North, said work being more particularly described in the
attached Exhibit A.

The resolution was read by the City Clerk, whereupon Councilmember Smitherman moved
its adoption which motion was seconded by Councilmember Williams, and upon the roll
being called, the vote was as follows:
Ayes: Alexander, Smitherman, Williams, O'Quinn
Nays: None
"""


def test_parser_captures_1500_char_window():
    """The parser must capture pre-vote context up to 1500 chars (was effectively 200)."""
    long_preamble = "X " * 800  # ~1600 chars of filler
    text = long_preamble + SUBSTANTIVE_VOTE_TEXT
    result = parse_minutes(text)
    assert len(result.votes) == 1
    vote = result.votes[0]
    # context should include text from the resolution body, not just the trailing boilerplate
    assert "HCL Contracting" in vote.context, \
        "Parser must capture far enough back to include the resolution body"


def test_parser_persists_raw_text_with_pre_and_post_window():
    text = SUBSTANTIVE_VOTE_TEXT
    result = parse_minutes(text)
    vote = result.votes[0]
    assert vote.raw_text, "raw_text must be populated"
    assert "HCL Contracting" in vote.raw_text
    assert "Ayes:" in vote.raw_text


def test_parser_flags_likely_consent_block():
    """is_likely_consent must be True when consent phrase is present in the captured window."""
    result = parse_minutes(CONSENT_BLOCK_TEXT)
    assert len(result.votes) == 1
    assert result.votes[0].is_likely_consent is True


def test_parser_flags_substantive_vote_as_not_consent():
    result = parse_minutes(SUBSTANTIVE_VOTE_TEXT)
    assert len(result.votes) == 1
    assert result.votes[0].is_likely_consent is False


def test_contains_consent_phrase_detects_each_canonical_phrase():
    assert _contains_consent_phrase("the resolutions and ordinances introduced as consent agenda matters were read")
    assert _contains_consent_phrase("...consent agenda matters were read by the city clerk...")
    assert _contains_consent_phrase("X all items on the consent agenda Y")
    assert _contains_consent_phrase("items on consent")
    assert not _contains_consent_phrase("this is just a regular resolution being voted on")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
venv/bin/pytest tests/unit/test_minutes_parser.py -v
```

Expected: failures — `is_likely_consent`, `raw_text`, and the wider context don't exist yet.

- [ ] **Step 3: Update the parser**

In `src/docket/analysis/minutes_parser.py`:

(a) Add at module scope, near the top:

```python
PRE_VOTE_WINDOW = 1500
POST_VOTE_WINDOW = 200

CONSENT_BLOCK_PHRASES = (
    "the resolutions and ordinances introduced as consent agenda matters",
    "consent agenda matters were read by the city clerk",
    "all items on the consent agenda",
    "items on consent",
)


def _contains_consent_phrase(text: str) -> bool:
    """True if the text contains any canonical consent-block phrase."""
    lowered = text.lower()
    return any(phrase in lowered for phrase in CONSENT_BLOCK_PHRASES)
```

(b) Modify `ParsedVote` to add the new fields:

```python
@dataclass
class ParsedVote:
    """A single vote extracted from minutes text."""

    ayes: list[str]
    nays: list[str]
    abstentions: list[str]
    result: str
    resolution_number: str | None = None
    context: str = ""        # full pre-vote window (was: trailing 200 chars)
    raw_text: str = ""       # full pre + vote block + post window
    is_likely_consent: bool = False
```

(c) Replace the body of `_build_vote()`:

```python
def _build_vote(text: str, match: re.Match) -> ParsedVote | None:
    ayes_raw = match.group(1).strip().rstrip(",")
    nays_raw = match.group(2).strip().rstrip(",")
    abstain_raw = (match.group(3) or "").strip().rstrip(",")

    ayes = _parse_vote_names(ayes_raw)
    nays = _parse_vote_names(nays_raw)
    abstentions = _parse_vote_names(abstain_raw)

    if not ayes and not nays:
        return None

    if len(ayes) > len(nays):
        result = "passed"
    elif len(nays) > len(ayes):
        result = "failed"
    else:
        result = "passed"

    pre_start = max(0, match.start() - PRE_VOTE_WINDOW)
    post_end = min(len(text), match.end() + POST_VOTE_WINDOW)
    context = text[pre_start:match.start()].strip()
    raw_text = text[pre_start:post_end].strip()

    res_matches = _RESOLUTION_RE.findall(context)
    resolution_number = res_matches[-1] if res_matches else None

    return ParsedVote(
        ayes=ayes,
        nays=nays,
        abstentions=abstentions,
        result=result,
        resolution_number=resolution_number,
        context=context,
        raw_text=raw_text,
        is_likely_consent=_contains_consent_phrase(raw_text),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
venv/bin/pytest tests/unit/test_minutes_parser.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Run ruff**

```bash
venv/bin/ruff check src/docket/analysis/minutes_parser.py
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/docket/analysis/minutes_parser.py tests/unit/test_minutes_parser.py
git commit -m "feat(parser): widen pre-vote window to 1500 chars, persist raw_text, flag consent blocks"
```

---

## Task 2.2: Persist `raw_text` through the ingest pipeline

**Files:**
- Modify: `src/docket/services/ingest.py`

- [ ] **Step 1: Locate the vote insert in ingest.py**

```bash
venv/bin/grep -n "INSERT INTO votes" src/docket/services/ingest.py
```

You're looking for the place where minutes-parsed votes are inserted, typically also writing `match_context` from `ParsedVote.context`.

- [ ] **Step 2: Add raw_text to the INSERT**

For each vote-insert site, ensure both `match_context` and `raw_text` are populated from the `ParsedVote`:

```python
cur.execute(
    """INSERT INTO votes
        (meeting_id, source, result, yeas, nays, abstentions,
         confidence, needs_review, review_reason,
         resolution_number, match_context, raw_text, header_result)
       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
       RETURNING id""",
    (
        meeting_id, "minutes_text", parsed_vote.result,
        len(parsed_vote.ayes), len(parsed_vote.nays), len(parsed_vote.abstentions),
        "high", False, None,
        parsed_vote.resolution_number,
        parsed_vote.context,
        parsed_vote.raw_text,
        None,
    ),
)
```

(The exact column list and parameter order should match what's already in your file. Just add `raw_text` alongside `match_context`.)

- [ ] **Step 3: Verify ingest still imports cleanly**

```bash
venv/bin/python -c "from docket.services import ingest"
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/docket/services/ingest.py
git commit -m "feat(ingest): persist raw_text from ParsedVote into votes.raw_text"
```

---

## Task 2.3: Implement `_upsert_link()` with manual shield + tests

**Files:**
- Modify: `src/docket/analysis/vote_matcher.py`
- Create: `tests/unit/test_vote_matcher.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_vote_matcher.py
"""Tests for the new vote matcher pipeline."""

import pytest
import psycopg2.extras

from docket.db import db, db_cursor
from docket.analysis.vote_matcher import _upsert_link


@pytest.fixture
def sample_vote_and_item():
    """Create a vote and agenda item, yield their IDs, clean up after."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   SELECT id, 'TEST_FIXTURE', '2099-01-01', 'council'
                   FROM municipalities ORDER BY id LIMIT 1
                   RETURNING id""",
            )
            mid = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO agenda_items (meeting_id, title, item_number, is_consent)
                   VALUES (%s, 'Test Resolution', '1', FALSE) RETURNING id""",
                (mid,),
            )
            aid = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                       confidence, needs_review)
                   VALUES (%s, 'minutes_text', 'passed', 5, 0, 0, 'high', FALSE)
                   RETURNING id""",
                (mid,),
            )
            vid = cur.fetchone()["id"]
        conn.commit()

    yield {"vote_id": vid, "agenda_item_id": aid, "meeting_id": mid}

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vote_agenda_items WHERE vote_id = %s", (vid,))
            cur.execute("DELETE FROM member_votes WHERE vote_id = %s", (vid,))
            cur.execute("DELETE FROM votes WHERE id = %s", (vid,))
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (aid,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mid,))
        conn.commit()


def test_upsert_link_inserts_when_absent(sample_vote_and_item):
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _upsert_link(
                cur,
                vote_id=sample_vote_and_item["vote_id"],
                agenda_item_id=sample_vote_and_item["agenda_item_id"],
                association_type="explicit",
                match_method="resolution_number",
                match_confidence=0.9,
                excerpt_context="snippet",
                provisional=False,
            )
            cur.execute(
                "SELECT * FROM vote_agenda_items WHERE vote_id = %s",
                (sample_vote_and_item["vote_id"],),
            )
            row = cur.fetchone()
        conn.commit()
    assert row["association_type"] == "explicit"
    assert row["match_method"] == "resolution_number"
    assert row["match_confidence"] == pytest.approx(0.9)
    assert row["provisional"] is False


def test_upsert_link_updates_on_conflict(sample_vote_and_item):
    """Re-running with different values updates the existing row, doesn't insert a duplicate."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _upsert_link(cur, vote_id=sample_vote_and_item["vote_id"],
                         agenda_item_id=sample_vote_and_item["agenda_item_id"],
                         association_type="explicit", match_method="resolution_number",
                         match_confidence=0.9, excerpt_context="A", provisional=False)
            _upsert_link(cur, vote_id=sample_vote_and_item["vote_id"],
                         agenda_item_id=sample_vote_and_item["agenda_item_id"],
                         association_type="explicit", match_method="text_similarity",
                         match_confidence=0.6, excerpt_context="B", provisional=False)
            cur.execute(
                "SELECT match_method, match_confidence, excerpt_context FROM vote_agenda_items WHERE vote_id = %s",
                (sample_vote_and_item["vote_id"],),
            )
            row = cur.fetchone()
            cur.execute(
                "SELECT COUNT(*) AS c FROM vote_agenda_items WHERE vote_id = %s",
                (sample_vote_and_item["vote_id"],),
            )
            count = cur.fetchone()["c"]
        conn.commit()
    assert count == 1
    assert row["match_method"] == "text_similarity"
    assert row["match_confidence"] == pytest.approx(0.6)


def test_upsert_link_respects_manual_shield(sample_vote_and_item):
    """If is_manual=True, the upsert must not modify the row."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO vote_agenda_items
                    (vote_id, agenda_item_id, association_type, match_method,
                     match_confidence, provisional, is_manual, is_active)
                   VALUES (%s, %s, 'explicit', 'manual_correction', 1.0, FALSE, TRUE, TRUE)""",
                (sample_vote_and_item["vote_id"], sample_vote_and_item["agenda_item_id"]),
            )
            _upsert_link(cur, vote_id=sample_vote_and_item["vote_id"],
                         agenda_item_id=sample_vote_and_item["agenda_item_id"],
                         association_type="consent_implicit", match_method="consent_block_default",
                         match_confidence=0.8, excerpt_context=None, provisional=True)
            cur.execute(
                "SELECT match_method, match_confidence, is_manual FROM vote_agenda_items WHERE vote_id = %s",
                (sample_vote_and_item["vote_id"],),
            )
            row = cur.fetchone()
        conn.commit()
    assert row["is_manual"] is True
    assert row["match_method"] == "manual_correction"
    assert row["match_confidence"] == pytest.approx(1.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
venv/bin/pytest tests/unit/test_vote_matcher.py -v
```

Expected: ImportError (`_upsert_link` doesn't exist yet).

- [ ] **Step 3: Add `_upsert_link` to `vote_matcher.py`**

In `src/docket/analysis/vote_matcher.py`, add at module scope (after the imports):

```python
def _upsert_link(
    cur,
    *,
    vote_id: int,
    agenda_item_id: int,
    association_type: str,
    match_method: str | None,
    match_confidence: float,
    excerpt_context: str | None,
    provisional: bool,
) -> None:
    """Insert or update a vote_agenda_items row.

    Respects the is_manual shield: app-level pre-check + DB-level WHERE
    on the UPDATE branch. Manual edits never get overwritten.
    """
    cur.execute(
        "SELECT is_manual FROM vote_agenda_items WHERE vote_id = %s AND agenda_item_id = %s",
        (vote_id, agenda_item_id),
    )
    existing = cur.fetchone()
    if existing and existing["is_manual"]:
        return  # human-locked, leave alone

    cur.execute(
        """INSERT INTO vote_agenda_items
            (vote_id, agenda_item_id, association_type, match_method,
             match_confidence, excerpt_context, provisional)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (vote_id, agenda_item_id) DO UPDATE
             SET association_type = EXCLUDED.association_type,
                 match_method = EXCLUDED.match_method,
                 match_confidence = EXCLUDED.match_confidence,
                 excerpt_context = EXCLUDED.excerpt_context,
                 updated_at = NOW()
             WHERE vote_agenda_items.is_manual = FALSE""",
        (
            vote_id, agenda_item_id, association_type, match_method,
            match_confidence, excerpt_context, provisional,
        ),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
venv/bin/pytest tests/unit/test_vote_matcher.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/docket/analysis/vote_matcher.py tests/unit/test_vote_matcher.py
git commit -m "feat(matcher): add _upsert_link with app+DB-level is_manual shield"
```

---

## Task 2.4: Implement `_classify_vote()` (substantive vs consent block) + tests

**Files:**
- Modify: `src/docket/analysis/vote_matcher.py`
- Modify: `tests/unit/test_vote_matcher.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_vote_matcher.py`:

```python
from docket.analysis.vote_matcher import _classify_vote


def test_classify_vote_substantive_when_no_phrase():
    vote = {"raw_text": "A standalone resolution. The resolution was read by the City Clerk.",
            "match_context": "A standalone resolution."}
    assert _classify_vote(vote) == "substantive"


def test_classify_vote_consent_when_phrase_in_raw_text():
    vote = {
        "raw_text": "...the resolutions and ordinances introduced as consent agenda matters were read by the City Clerk...",
        "match_context": "trailing only",
    }
    assert _classify_vote(vote) == "consent_block"


def test_classify_vote_consent_when_phrase_only_in_match_context():
    """Falls back to match_context for legacy votes with empty raw_text."""
    vote = {
        "raw_text": None,
        "match_context": "items on consent agenda matters were read by the City Clerk",
    }
    assert _classify_vote(vote) == "consent_block"


def test_classify_vote_substantive_when_both_empty():
    vote = {"raw_text": None, "match_context": None}
    assert _classify_vote(vote) == "substantive"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
venv/bin/pytest tests/unit/test_vote_matcher.py::test_classify_vote_substantive_when_no_phrase -v
```

Expected: ImportError on `_classify_vote`.

- [ ] **Step 3: Add the function to `vote_matcher.py`**

```python
from docket.analysis.minutes_parser import CONSENT_BLOCK_PHRASES


def _classify_vote(vote_row) -> str:
    """Return 'substantive' or 'consent_block' for a vote.

    Reads raw_text first (preferred), falls back to match_context for
    legacy votes ingested before the parser was widened. dict-like or
    psycopg2 RealDictRow.
    """
    haystack = (vote_row.get("raw_text") or "") + " " + (vote_row.get("match_context") or "")
    haystack = haystack.lower()
    if any(phrase in haystack for phrase in CONSENT_BLOCK_PHRASES):
        return "consent_block"
    return "substantive"
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
venv/bin/pytest tests/unit/test_vote_matcher.py -v
```

Expected: all matcher tests pass (3 from previous task + 4 from this one = 7).

- [ ] **Step 5: Commit**

```bash
git add src/docket/analysis/vote_matcher.py tests/unit/test_vote_matcher.py
git commit -m "feat(matcher): classify each vote as substantive or consent_block"
```

---

## Task 2.5: Refactor `_match_substantive` to use `_upsert_link` + integrate

**Files:**
- Modify: `src/docket/analysis/vote_matcher.py`
- Modify: `tests/unit/test_vote_matcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_vote_matcher.py`:

```python
def test_match_substantive_inserts_explicit_link_with_resolution_match(sample_vote_and_item):
    """A substantive vote with a resolution number that appears in the agenda title
    should produce an 'explicit' link with method='resolution_number' and confidence=0.9."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Set up: agenda item title contains resolution 1854-25, vote has that resolution number
            cur.execute(
                "UPDATE agenda_items SET title = 'Resolution 1854-25 Test' WHERE id = %s",
                (sample_vote_and_item["agenda_item_id"],),
            )
            cur.execute(
                "UPDATE votes SET resolution_number = '1854-25', match_context = 'context' WHERE id = %s",
                (sample_vote_and_item["vote_id"],),
            )
        conn.commit()

    from docket.analysis.vote_matcher import match_votes_for_meeting
    result = match_votes_for_meeting(sample_vote_and_item["meeting_id"])

    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM vote_agenda_items WHERE vote_id = %s",
            (sample_vote_and_item["vote_id"],),
        )
        row = cur.fetchone()

    assert row is not None
    assert row["association_type"] == "explicit"
    assert row["match_method"] == "resolution_number"
    assert row["match_confidence"] == pytest.approx(0.9)
    assert row["provisional"] is False
```

- [ ] **Step 2: Run to verify it fails**

```bash
venv/bin/pytest tests/unit/test_vote_matcher.py::test_match_substantive_inserts_explicit_link_with_resolution_match -v
```

Expected: fails — `match_votes_for_meeting` still uses the old singular-FK update path.

- [ ] **Step 3: Refactor the matcher functions**

In `src/docket/analysis/vote_matcher.py`, replace the existing `match_votes_by_text` and `match_votes_by_timestamp` functions with these refactors that route through `_upsert_link`. Replace the entire body of these two functions and `match_votes_for_meeting`:

```python
def match_votes_by_timestamp(meeting_id: int) -> int:
    """Match video OCR votes to agenda items by timestamp proximity. Inserts to vote_agenda_items."""
    matched = 0
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, video_timestamp_seconds FROM agenda_items
                   WHERE meeting_id = %s AND video_timestamp_seconds IS NOT NULL
                   ORDER BY video_timestamp_seconds""",
                (meeting_id,),
            )
            items = cur.fetchall()
            if not items:
                return 0
            item_timestamps = [r["video_timestamp_seconds"] for r in items]
            item_ids = [r["id"] for r in items]

            cur.execute(
                """SELECT v.id, v.video_timestamp, v.needs_review
                   FROM votes v
                   LEFT JOIN vote_agenda_items vai ON vai.vote_id = v.id AND vai.is_active
                   WHERE v.meeting_id = %s AND v.source = 'video_ocr'
                     AND v.video_timestamp IS NOT NULL
                     AND vai.id IS NULL""",
                (meeting_id,),
            )
            votes = cur.fetchall()
            for vote in votes:
                vt = vote["video_timestamp"]
                idx = bisect_right(item_timestamps, vt) - 1
                if idx < 0:
                    continue
                gap = vt - item_timestamps[idx]
                conf = compute_confidence(gap, needs_review=vote["needs_review"])
                if conf <= 0:
                    continue
                _upsert_link(
                    cur,
                    vote_id=vote["id"],
                    agenda_item_id=item_ids[idx],
                    association_type="explicit",
                    match_method="timestamp",
                    match_confidence=conf,
                    excerpt_context=None,
                    provisional=False,
                )
                matched += 1
        conn.commit()
    return matched


def _match_substantive(meeting_id: int) -> int:
    """Match substantive (1:1) minutes votes via 3-tier heuristics."""
    matched = 0
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, item_number, title, COALESCE(description, '') AS description "
                "FROM agenda_items WHERE meeting_id = %s",
                (meeting_id,),
            )
            items = cur.fetchall()
            if not items:
                return 0

            cur.execute(
                """SELECT v.id, v.resolution_number, v.match_context, v.raw_text
                   FROM votes v
                   LEFT JOIN vote_agenda_items vai ON vai.vote_id = v.id AND vai.is_active
                   WHERE v.meeting_id = %s AND v.source = 'minutes_text'
                     AND vai.id IS NULL""",
                (meeting_id,),
            )
            votes = cur.fetchall()
            for vote in votes:
                if _classify_vote(vote) != "substantive":
                    continue
                result = (
                    _try_resolution_match(vote, items)
                    or _try_item_number_match(vote, items)
                    or _try_keyword_match(vote, items)
                )
                if result:
                    item_id, conf, method = result
                    _upsert_link(
                        cur,
                        vote_id=vote["id"],
                        agenda_item_id=item_id,
                        association_type="explicit",
                        match_method=method,
                        match_confidence=conf,
                        excerpt_context=(vote.get("match_context") or "")[:300] or None,
                        provisional=False,
                    )
                    matched += 1
        conn.commit()
    return matched
```

Update `_try_resolution_match` to also search `description`:

```python
def _try_resolution_match(vote, items):
    res_num = vote["resolution_number"]
    if not res_num:
        return None
    for item in items:
        haystack = (item["title"] or "") + " " + (item.get("description") or "")
        if re.search(rf"\b{re.escape(res_num)}\b", haystack):
            return (item["id"], 0.9, "resolution_number")
    return None
```

Modify `match_votes_for_meeting` to dispatch through both substantive and consent-block paths (consent will be added in 2.6 — for now leave a stub):

```python
def match_votes_for_meeting(meeting_id: int) -> dict:
    ts_matched = match_votes_by_timestamp(meeting_id)
    sub_matched = _match_substantive(meeting_id)
    consent_matched = _match_consent_block(meeting_id)  # added in Task 2.6
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE processing_status SET votes_matched = TRUE WHERE meeting_id = %s",
                (meeting_id,),
            )
        conn.commit()
    return {
        "timestamp_matched": ts_matched,
        "substantive_matched": sub_matched,
        "consent_matched": consent_matched,
    }
```

Add a placeholder so the import doesn't break before 2.6:

```python
def _match_consent_block(meeting_id: int) -> int:
    """Stub — implemented in Task 2.6."""
    return 0
```

Delete the old `match_votes_by_text` function (the substantive path now lives in `_match_substantive`).

- [ ] **Step 4: Run the test to verify it passes**

```bash
venv/bin/pytest tests/unit/test_vote_matcher.py -v
```

Expected: all tests pass (8 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docket/analysis/vote_matcher.py tests/unit/test_vote_matcher.py
git commit -m "refactor(matcher): substantive matcher writes through _upsert_link to vote_agenda_items"
```

---

## Task 2.6: Implement `_match_consent_block` (named callout + default fill)

**Files:**
- Modify: `src/docket/analysis/vote_matcher.py`
- Modify: `tests/unit/test_vote_matcher.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_vote_matcher.py`:

```python
@pytest.fixture
def consent_block_meeting():
    """Create a meeting with one consent-block vote and three is_consent agenda items."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   SELECT id, 'TEST_CONSENT', '2099-01-02', 'council'
                   FROM municipalities ORDER BY id LIMIT 1
                   RETURNING id""",
            )
            mid = cur.fetchone()["id"]
            ai_ids = []
            for item_num, title in [
                ("12", "A Resolution authorizing HCL Contracting paving services 9th Avenue"),
                ("13", "A Resolution authorizing OLB Enterprises liquor license"),
                ("14", "A Resolution authorizing East Side Lounge license"),
            ]:
                cur.execute(
                    """INSERT INTO agenda_items (meeting_id, title, item_number, is_consent)
                       VALUES (%s, %s, %s, TRUE) RETURNING id""",
                    (mid, title, item_num),
                )
                ai_ids.append(cur.fetchone()["id"])
            cur.execute(
                """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                       confidence, needs_review, raw_text, match_context)
                   VALUES (%s, 'minutes_text', 'passed', 5, 0, 0, 'high', FALSE, %s, %s)
                   RETURNING id""",
                (
                    mid,
                    "Some preamble mentioning HCL Contracting paving 9th Avenue. The resolutions "
                    "and ordinances introduced as consent agenda matters were read by the City Clerk.",
                    "consent agenda matters",
                ),
            )
            vid = cur.fetchone()["id"]
        conn.commit()
    yield {"meeting_id": mid, "vote_id": vid, "agenda_item_ids": ai_ids}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vote_agenda_items WHERE vote_id = %s", (vid,))
            cur.execute("DELETE FROM votes WHERE id = %s", (vid,))
            cur.execute("DELETE FROM agenda_items WHERE meeting_id = %s", (mid,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mid,))
        conn.commit()


def test_consent_block_links_named_item_with_confidence_1(consent_block_meeting):
    """Items whose title keywords appear in the vote's raw_text get consent_named, conf=1.0."""
    from docket.analysis.vote_matcher import match_votes_for_meeting
    match_votes_for_meeting(consent_block_meeting["meeting_id"])

    with db_cursor() as cur:
        cur.execute(
            "SELECT agenda_item_id, association_type, match_confidence FROM vote_agenda_items "
            "WHERE vote_id = %s ORDER BY agenda_item_id",
            (consent_block_meeting["vote_id"],),
        )
        rows = cur.fetchall()

    by_item = {r["agenda_item_id"]: r for r in rows}
    hcl_id = consent_block_meeting["agenda_item_ids"][0]
    olb_id = consent_block_meeting["agenda_item_ids"][1]

    assert by_item[hcl_id]["association_type"] == "consent_named"
    assert by_item[hcl_id]["match_confidence"] == pytest.approx(1.0)
    assert by_item[olb_id]["association_type"] == "consent_implicit"
    assert by_item[olb_id]["match_confidence"] == pytest.approx(0.8)


def test_consent_block_links_default_fill_provisional(consent_block_meeting):
    """All consent-block links start provisional=True."""
    from docket.analysis.vote_matcher import match_votes_for_meeting
    match_votes_for_meeting(consent_block_meeting["meeting_id"])

    with db_cursor() as cur:
        cur.execute(
            "SELECT provisional FROM vote_agenda_items WHERE vote_id = %s",
            (consent_block_meeting["vote_id"],),
        )
        rows = cur.fetchall()

    assert len(rows) == 3
    assert all(r["provisional"] for r in rows)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
venv/bin/pytest tests/unit/test_vote_matcher.py::test_consent_block_links_named_item_with_confidence_1 -v
```

Expected: only 0 links inserted (the stub returns 0).

- [ ] **Step 3: Implement `_match_consent_block`**

Replace the stub in `vote_matcher.py`:

```python
import math


NAMED_CALLOUT_FLOOR = 2
NAMED_CALLOUT_CAP = 3
NAMED_CALLOUT_RATIO = 0.6


def _named_callout_threshold(n_significant_words: int) -> int | None:
    """Required word-overlap count for the consent named-callout heuristic.

    Returns None if the title is too short (1 significant word) — skip keyword pass.
    Otherwise: max(NAMED_CALLOUT_FLOOR, min(NAMED_CALLOUT_CAP, ceil(0.6 * N))).
    """
    if n_significant_words < 2:
        return None
    return max(
        NAMED_CALLOUT_FLOOR,
        min(NAMED_CALLOUT_CAP, math.ceil(NAMED_CALLOUT_RATIO * n_significant_words)),
    )


def _match_consent_block(meeting_id: int) -> int:
    """Match consent-block (1:N) votes by named callout + default fill.

    For each consent-block vote in the meeting, link to all is_consent=TRUE
    agenda items: items named in the vote's raw_text get consent_named/1.0;
    remaining is_consent items get consent_implicit/0.8. All start provisional.
    """
    matched = 0
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, item_number, title FROM agenda_items "
                "WHERE meeting_id = %s AND is_consent = TRUE",
                (meeting_id,),
            )
            consent_items = cur.fetchall()
            if not consent_items:
                return 0

            cur.execute(
                """SELECT v.id, v.raw_text, v.match_context, v.resolution_number
                   FROM votes v
                   LEFT JOIN vote_agenda_items vai ON vai.vote_id = v.id AND vai.is_active
                   WHERE v.meeting_id = %s AND v.source = 'minutes_text'
                     AND vai.id IS NULL""",
                (meeting_id,),
            )
            votes = cur.fetchall()

            for vote in votes:
                if _classify_vote(vote) != "consent_block":
                    continue
                vote_text = ((vote.get("raw_text") or "") + " " + (vote.get("match_context") or "")).lower()
                if not vote_text.strip():
                    continue

                # Named callout pass
                named_ids: set[int] = set()
                for item in consent_items:
                    title = item["title"] or ""
                    item_num = item["item_number"] or ""

                    item_num_pattern = rf"\b(?:item|ITEM)\s+(?:no\.?\s*)?{re.escape(item_num)}\b" if item_num else None
                    if item_num and item_num_pattern and re.search(item_num_pattern, vote_text, re.IGNORECASE):
                        named_ids.add(item["id"])
                        _upsert_link(
                            cur, vote_id=vote["id"], agenda_item_id=item["id"],
                            association_type="consent_named",
                            match_method="consent_block_named",
                            match_confidence=1.0,
                            excerpt_context=_extract_snippet(vote.get("raw_text") or "", item_num),
                            provisional=True,
                        )
                        matched += 1
                        continue

                    title_words = _significant_words(title)
                    threshold = _named_callout_threshold(len(title_words))
                    if threshold is None:
                        continue
                    text_words = _significant_words(vote_text)
                    overlap = len(title_words & text_words)
                    if overlap >= threshold:
                        named_ids.add(item["id"])
                        # snippet around the first overlapping word
                        snippet_word = next(iter(title_words & text_words), None)
                        _upsert_link(
                            cur, vote_id=vote["id"], agenda_item_id=item["id"],
                            association_type="consent_named",
                            match_method="consent_block_named",
                            match_confidence=1.0,
                            excerpt_context=_extract_snippet(vote.get("raw_text") or "", snippet_word or ""),
                            provisional=True,
                        )
                        matched += 1

                # Default fill pass
                for item in consent_items:
                    if item["id"] in named_ids:
                        continue
                    _upsert_link(
                        cur, vote_id=vote["id"], agenda_item_id=item["id"],
                        association_type="consent_implicit",
                        match_method="consent_block_default",
                        match_confidence=0.8,
                        excerpt_context=None,
                        provisional=True,
                    )
                    matched += 1
        conn.commit()
    return matched


def _extract_snippet(haystack: str, needle: str, window: int = 100) -> str | None:
    """Return ~200 chars of haystack centered on the first occurrence of needle."""
    if not needle:
        return None
    idx = haystack.lower().find(needle.lower())
    if idx == -1:
        return None
    start = max(0, idx - window)
    end = min(len(haystack), idx + len(needle) + window)
    return haystack[start:end]
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
venv/bin/pytest tests/unit/test_vote_matcher.py -v
```

Expected: all 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/docket/analysis/vote_matcher.py tests/unit/test_vote_matcher.py
git commit -m "feat(matcher): consent-block matcher with named-callout + default-fill passes"
```

---

## Task 2.7: Implement `strict_reparse_meeting()` + tests

**Files:**
- Modify: `src/docket/analysis/vote_matcher.py`
- Modify: `tests/unit/test_vote_matcher.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_vote_matcher.py`:

```python
def test_strict_reparse_promotes_provisional_to_official(consent_block_meeting):
    """A provisional consent_implicit link, after strict re-parse with the item in the
    enumerated list, becomes provisional=False, confidence=1.0, method=consent_enumerated."""
    from docket.analysis.vote_matcher import match_votes_for_meeting, strict_reparse_meeting

    match_votes_for_meeting(consent_block_meeting["meeting_id"])

    enumerated_text = """
    RESOLUTION 1854-25 A Resolution authorizing HCL Contracting paving services 9th Avenue
    RESOLUTION 1855-25 A Resolution authorizing OLB Enterprises liquor license
    RESOLUTION 1856-25 A Resolution authorizing East Side Lounge license
    The resolutions and ordinances introduced as consent agenda matters were read by the
    City Clerk... Ayes: Alexander, Smitherman, Williams, O'Quinn / Nays: None
    """
    strict_reparse_meeting(consent_block_meeting["meeting_id"], minutes_text=enumerated_text)

    with db_cursor() as cur:
        cur.execute(
            "SELECT provisional, match_method, match_confidence, is_active "
            "FROM vote_agenda_items WHERE vote_id = %s ORDER BY agenda_item_id",
            (consent_block_meeting["vote_id"],),
        )
        rows = cur.fetchall()
    assert all(not r["provisional"] for r in rows)
    assert all(r["match_method"] == "consent_enumerated" for r in rows)
    assert all(r["match_confidence"] == pytest.approx(1.0) for r in rows)
    assert all(r["is_active"] for r in rows)


def test_strict_reparse_deactivates_pulled_from_consent(consent_block_meeting):
    """An item linked provisionally but NOT in the enumerated list becomes is_active=False."""
    from docket.analysis.vote_matcher import match_votes_for_meeting, strict_reparse_meeting

    match_votes_for_meeting(consent_block_meeting["meeting_id"])

    # Enumerated list mentions only HCL and OLB. East Side Lounge is "pulled".
    enumerated_text = """
    RESOLUTION 1854-25 A Resolution authorizing HCL Contracting paving services 9th Avenue
    RESOLUTION 1855-25 A Resolution authorizing OLB Enterprises liquor license
    The resolutions and ordinances introduced as consent agenda matters were read by the
    City Clerk... Ayes: Alexander, Smitherman, Williams / Nays: None
    """
    strict_reparse_meeting(consent_block_meeting["meeting_id"], minutes_text=enumerated_text)

    east_side_id = consent_block_meeting["agenda_item_ids"][2]
    with db_cursor() as cur:
        cur.execute(
            "SELECT is_active FROM vote_agenda_items WHERE vote_id = %s AND agenda_item_id = %s",
            (consent_block_meeting["vote_id"], east_side_id),
        )
        row = cur.fetchone()
    assert row["is_active"] is False


def test_strict_reparse_respects_is_manual(consent_block_meeting):
    """is_manual=True links must NOT be deactivated even if pulled from consent."""
    from docket.analysis.vote_matcher import match_votes_for_meeting, strict_reparse_meeting

    match_votes_for_meeting(consent_block_meeting["meeting_id"])

    east_side_id = consent_block_meeting["agenda_item_ids"][2]
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE vote_agenda_items SET is_manual = TRUE "
                "WHERE vote_id = %s AND agenda_item_id = %s",
                (consent_block_meeting["vote_id"], east_side_id),
            )
        conn.commit()

    enumerated_text = "RESOLUTION 1854-25 HCL Contracting"  # East Side missing — would normally deactivate
    strict_reparse_meeting(consent_block_meeting["meeting_id"], minutes_text=enumerated_text)

    with db_cursor() as cur:
        cur.execute(
            "SELECT is_active, is_manual FROM vote_agenda_items "
            "WHERE vote_id = %s AND agenda_item_id = %s",
            (consent_block_meeting["vote_id"], east_side_id),
        )
        row = cur.fetchone()
    assert row["is_manual"] is True
    assert row["is_active"] is True  # protected by manual shield
```

- [ ] **Step 2: Run to verify it fails**

```bash
venv/bin/pytest tests/unit/test_vote_matcher.py::test_strict_reparse_promotes_provisional_to_official -v
```

Expected: ImportError on `strict_reparse_meeting`.

- [ ] **Step 3: Implement `strict_reparse_meeting`**

Add to `vote_matcher.py`:

```python
_ENUM_RESOLUTION_RE = re.compile(
    r"(?:RESOLUTION|ORDINANCE)\s+(?:NO\.\s*)?(?P<num>\d[\d-]*)\s+(?P<desc>[^\n\r]{0,200})",
    re.IGNORECASE,
)


def _parse_enumerated_consent_list(minutes_text: str) -> list[tuple[str, str]]:
    """Extract (resolution_number, description) tuples from the consent enumeration.

    Looks for "RESOLUTION 1854-25 A Resolution authorizing..." lines that typically
    appear in Birmingham minutes before the consent-vote roll call.
    """
    return [(m.group("num"), m.group("desc").strip()) for m in _ENUM_RESOLUTION_RE.finditer(minutes_text)]


def _resolve_enumerated_to_agenda_items(
    cur, meeting_id: int, enumerated: list[tuple[str, str]]
) -> set[int]:
    """For each enumerated entry, return matching agenda_item ids (is_consent=TRUE).

    Match by resolution number occurrence in the title/description first;
    otherwise by significant-word overlap with the description (≥3 words).
    """
    cur.execute(
        "SELECT id, item_number, title, COALESCE(description, '') AS description "
        "FROM agenda_items WHERE meeting_id = %s AND is_consent = TRUE",
        (meeting_id,),
    )
    items = cur.fetchall()
    resolved: set[int] = set()
    for res_num, desc in enumerated:
        # Resolution-number match
        for item in items:
            haystack = (item["title"] or "") + " " + item["description"]
            if re.search(rf"\b{re.escape(res_num)}\b", haystack):
                resolved.add(item["id"])
                break
        else:
            # Keyword fallback
            desc_words = _significant_words(desc)
            if len(desc_words) < 3:
                continue
            best_id, best_overlap = None, 0
            for item in items:
                title_words = _significant_words(item["title"] or "")
                overlap = len(desc_words & title_words)
                if overlap >= 3 and overlap > best_overlap:
                    best_overlap = overlap
                    best_id = item["id"]
            if best_id is not None:
                resolved.add(best_id)
    return resolved


def strict_reparse_meeting(meeting_id: int, *, minutes_text: str | None = None) -> dict:
    """Promote provisional consent links to official; deactivate pulled-from-consent links.

    minutes_text: pass-through for tests. In production, callers fetch the PDF and pass the text.
    Respects is_manual=TRUE on every UPDATE.
    """
    if minutes_text is None:
        from docket.analysis.minutes_parser import (
            download_minutes_pdf, extract_text_from_pdf,
        )
        with db_cursor() as cur:
            cur.execute("SELECT minutes_url FROM meetings WHERE id = %s", (meeting_id,))
            row = cur.fetchone()
        if not row or not row["minutes_url"]:
            logger.warning("strict_reparse: no minutes_url for meeting %s", meeting_id)
            return {"promoted": 0, "deactivated": 0}
        pdf = download_minutes_pdf(row["minutes_url"])
        if not pdf:
            return {"promoted": 0, "deactivated": 0}
        minutes_text = extract_text_from_pdf(pdf)

    enumerated = _parse_enumerated_consent_list(minutes_text)
    if not enumerated:
        logger.warning("strict_reparse: no enumerated list found for meeting %s", meeting_id)
        return {"promoted": 0, "deactivated": 0}

    promoted = 0
    deactivated = 0
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            target_item_ids = _resolve_enumerated_to_agenda_items(cur, meeting_id, enumerated)

            cur.execute(
                """SELECT vai.id, vai.vote_id, vai.agenda_item_id
                   FROM vote_agenda_items vai
                   JOIN votes v ON v.id = vai.vote_id
                   WHERE v.meeting_id = %s
                     AND vai.is_manual = FALSE
                     AND vai.is_active = TRUE
                     AND vai.association_type IN ('consent_named', 'consent_implicit')""",
                (meeting_id,),
            )
            existing_links = cur.fetchall()
            existing_by_item = {(r["vote_id"], r["agenda_item_id"]): r["id"] for r in existing_links}

            # Promote: items in enumerated set that are linked → flip provisional
            cur.execute(
                """UPDATE vote_agenda_items
                   SET provisional = FALSE,
                       match_confidence = 1.0,
                       match_method = 'consent_enumerated',
                       association_type = 'consent_named',
                       updated_at = NOW()
                   FROM votes v
                   WHERE v.id = vote_agenda_items.vote_id
                     AND v.meeting_id = %s
                     AND vote_agenda_items.is_manual = FALSE
                     AND vote_agenda_items.agenda_item_id = ANY(%s)
                     AND vote_agenda_items.association_type IN ('consent_named', 'consent_implicit')""",
                (meeting_id, list(target_item_ids)),
            )
            promoted = cur.rowcount

            # Deactivate: linked items NOT in enumerated set
            cur.execute(
                """UPDATE vote_agenda_items
                   SET is_active = FALSE, updated_at = NOW()
                   FROM votes v
                   WHERE v.id = vote_agenda_items.vote_id
                     AND v.meeting_id = %s
                     AND vote_agenda_items.is_manual = FALSE
                     AND vote_agenda_items.is_active = TRUE
                     AND vote_agenda_items.association_type IN ('consent_named', 'consent_implicit')
                     AND NOT (vote_agenda_items.agenda_item_id = ANY(%s))""",
                (meeting_id, list(target_item_ids)),
            )
            deactivated = cur.rowcount

            # Insert any enumerated items that weren't previously linked
            for item_id in target_item_ids:
                cur.execute(
                    """SELECT v.id AS vote_id FROM votes v
                       LEFT JOIN vote_agenda_items vai
                         ON vai.vote_id = v.id AND vai.agenda_item_id = %s
                       WHERE v.meeting_id = %s AND v.source = 'minutes_text'
                         AND vai.id IS NULL""",
                    (item_id, meeting_id),
                )
                for r in cur.fetchall():
                    if _classify_vote(_fetch_vote_for_classify(cur, r["vote_id"])) == "consent_block":
                        _upsert_link(
                            cur, vote_id=r["vote_id"], agenda_item_id=item_id,
                            association_type="consent_named",
                            match_method="consent_enumerated",
                            match_confidence=1.0,
                            excerpt_context=None,
                            provisional=False,
                        )

            # Substantive safety pass
            cur.execute(
                """UPDATE vote_agenda_items
                   SET provisional = FALSE, updated_at = NOW()
                   FROM votes v
                   WHERE v.id = vote_agenda_items.vote_id
                     AND v.meeting_id = %s
                     AND vote_agenda_items.is_manual = FALSE
                     AND vote_agenda_items.association_type = 'explicit'""",
                (meeting_id,),
            )
        conn.commit()

    return {"promoted": promoted, "deactivated": deactivated}


def _fetch_vote_for_classify(cur, vote_id: int) -> dict:
    cur.execute("SELECT raw_text, match_context FROM votes WHERE id = %s", (vote_id,))
    return cur.fetchone() or {}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
venv/bin/pytest tests/unit/test_vote_matcher.py -v
```

Expected: all 13 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/docket/analysis/vote_matcher.py tests/unit/test_vote_matcher.py
git commit -m "feat(matcher): strict_reparse_meeting promotes provisional consent links to official"
```

---

## Task 2.8: Wire matcher-side strict re-parse trigger

**Files:**
- Modify: `src/docket/analysis/vote_matcher.py`

- [ ] **Step 1: Update `match_votes_for_meeting` to call strict_reparse if adopted**

Replace the existing `match_votes_for_meeting`:

```python
def match_votes_for_meeting(meeting_id: int) -> dict:
    ts_matched = match_votes_by_timestamp(meeting_id)
    sub_matched = _match_substantive(meeting_id)
    consent_matched = _match_consent_block(meeting_id)

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE processing_status SET votes_matched = TRUE WHERE meeting_id = %s",
                (meeting_id,),
            )
            cur.execute(
                "SELECT minutes_adopted_at FROM meetings WHERE id = %s",
                (meeting_id,),
            )
            row = cur.fetchone()
        conn.commit()

    reparse_result = {"promoted": 0, "deactivated": 0}
    if row and row[0] is not None:
        # Adoption already recorded — promote provisional links immediately
        try:
            reparse_result = strict_reparse_meeting(meeting_id)
        except Exception as e:
            logger.warning("strict_reparse failed for meeting %s: %s", meeting_id, e)

    return {
        "timestamp_matched": ts_matched,
        "substantive_matched": sub_matched,
        "consent_matched": consent_matched,
        "promoted": reparse_result["promoted"],
        "deactivated": reparse_result["deactivated"],
    }
```

- [ ] **Step 2: Verify no test regression**

```bash
venv/bin/pytest tests/unit/test_vote_matcher.py -v
```

Expected: all tests still pass (matcher-side trigger is a no-op when minutes_adopted_at is NULL).

- [ ] **Step 3: Run ruff**

```bash
venv/bin/ruff check src/docket/analysis/
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add src/docket/analysis/vote_matcher.py
git commit -m "feat(matcher): trigger strict_reparse when matching a pre-adopted meeting"
```

---

## Task 2.9: Phase 2 verification

- [ ] **Step 1: Run all unit tests**

```bash
venv/bin/pytest tests/unit/ -v
```

Expected: all unit tests pass except `tests/unit/test_query_list_votes.py` (doesn't exist yet) and any service-layer tests that depend on the not-yet-rewritten `query.list_votes()`. The dataclass, parser, matcher, and pre-existing unit tests all pass.

- [ ] **Step 2: Run ruff**

```bash
venv/bin/ruff check src/
```

Expected: clean.

- [ ] **Step 3: Tag the Phase 2 checkpoint**

```bash
git tag phase-2-complete
```

---

# Phase 3 — Adoption + Reader + UI

Goal: complete the lifecycle. The adoption sweep detects approved minutes; reader serves the new shape; templates render N:M with provisional/adopted state.

## Task 3.1: Adoption pattern detection + validity checks

**Files:**
- Create: `src/docket/services/minutes_adoption.py`
- Create: `tests/unit/test_minutes_adoption.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_minutes_adoption.py
"""Tests for adoption-pattern detection."""

from datetime import date

from docket.services.minutes_adoption import (
    extract_adoption_target,
    is_adoption_title,
    AdoptionParseError,
)


def test_is_adoption_title_matches_canonical_patterns():
    assert is_adoption_title("Approval of Minutes from January 7, 2026")
    assert is_adoption_title("Adoption of the Minutes from December 5, 2024")
    assert is_adoption_title("Approval of the December 5, 2024 Minutes")
    assert is_adoption_title("Minutes from the Council Meeting of December 5, 2024")
    assert is_adoption_title("Minutes from the Regular Meeting of December 5, 2024")


def test_is_adoption_title_rejects_unrelated():
    assert not is_adoption_title("A Resolution authorizing HCL Contracting")
    assert not is_adoption_title("Approval of Contract with Acme Corp")


def test_extract_adoption_target_returns_date():
    target = extract_adoption_target(
        "Approval of Minutes from December 5, 2024",
        adoption_meeting_date=date(2026, 1, 7),
    )
    assert target == date(2024, 12, 5)


def test_extract_adoption_target_rejects_invalid_date():
    """Feb 31 is not a real date."""
    import pytest
    with pytest.raises(AdoptionParseError, match="invalid date"):
        extract_adoption_target(
            "Approval of Minutes from February 31, 2024",
            adoption_meeting_date=date(2026, 1, 7),
        )


def test_extract_adoption_target_rejects_future_date():
    import pytest
    with pytest.raises(AdoptionParseError, match="future"):
        extract_adoption_target(
            "Approval of Minutes from January 1, 2030",
            adoption_meeting_date=date(2026, 1, 7),
        )


def test_extract_adoption_target_rejects_too_old():
    """24-month window."""
    import pytest
    with pytest.raises(AdoptionParseError, match="window"):
        extract_adoption_target(
            "Approval of Minutes from January 1, 2020",
            adoption_meeting_date=date(2026, 1, 7),
        )
```

- [ ] **Step 2: Run to verify it fails**

```bash
venv/bin/pytest tests/unit/test_minutes_adoption.py -v
```

Expected: ImportError — module doesn't exist.

- [ ] **Step 3: Create the module with detection logic only**

```python
# src/docket/services/minutes_adoption.py
"""Detect and resolve council adoption of prior-meeting minutes.

Approach: stateless sweep over each city's agenda items. Idempotent —
re-running doesn't change resolved adoptions but picks up newly-ingested
target meetings. Triggers strict re-parse on each flip.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from dateutil import parser as dateparser  # already a dependency via requests/etc., else add to requirements

from docket.db import db, db_cursor

logger = logging.getLogger(__name__)


class AdoptionParseError(ValueError):
    """Raised when an adoption-pattern title cannot be resolved to a valid date."""


_ADOPTION_PATTERNS = [
    re.compile(r"approval of (?:the )?minutes from .*?(?P<date>\w+\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
    re.compile(r"adoption of (?:the )?minutes from .*?(?P<date>\w+\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
    re.compile(r"approval of (?:the )?(?P<date>\w+\s+\d{1,2},?\s+\d{4}) minutes", re.IGNORECASE),
    re.compile(r"minutes from the (?:\w+\s+)?meeting of (?P<date>\w+\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
]

_LOOKBACK_MONTHS = 24


def is_adoption_title(title: str) -> bool:
    """True if the title matches any adoption pattern."""
    if not title:
        return False
    return any(p.search(title) for p in _ADOPTION_PATTERNS)


def _extract_date_string(title: str) -> str | None:
    for p in _ADOPTION_PATTERNS:
        m = p.search(title)
        if m:
            return m.group("date")
    return None


def extract_adoption_target(title: str, *, adoption_meeting_date: date) -> date:
    """Parse the adoption target date from an agenda title.

    Validates: real date, not in future, within 24-month lookback window.
    Raises AdoptionParseError on any failure.
    """
    date_str = _extract_date_string(title)
    if date_str is None:
        raise AdoptionParseError(f"no date in title: {title!r}")

    try:
        parsed = dateparser.parse(date_str).date()
    except (ValueError, TypeError) as e:
        raise AdoptionParseError(f"invalid date {date_str!r}: {e}") from e

    if parsed > adoption_meeting_date:
        raise AdoptionParseError(
            f"date {parsed} is in the future relative to adoption meeting {adoption_meeting_date}"
        )

    months_back = (adoption_meeting_date.year - parsed.year) * 12 + (adoption_meeting_date.month - parsed.month)
    if months_back > _LOOKBACK_MONTHS:
        raise AdoptionParseError(
            f"date {parsed} is more than {_LOOKBACK_MONTHS} months before adoption meeting "
            f"{adoption_meeting_date} — outside window"
        )

    return parsed
```

- [ ] **Step 4: Verify dateutil is available**

```bash
venv/bin/python -c "from dateutil import parser as dp; print(dp.parse('December 5, 2024'))"
```

Expected: prints `2024-12-05 00:00:00`. If ImportError, run `venv/bin/pip install python-dateutil` and add `python-dateutil>=2.8` to `requirements.txt` and `pyproject.toml`.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
venv/bin/pytest tests/unit/test_minutes_adoption.py -v
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add src/docket/services/minutes_adoption.py tests/unit/test_minutes_adoption.py
# If you had to add python-dateutil:
# git add requirements.txt pyproject.toml
git commit -m "feat(adoption): add adoption-title pattern detection with validity + 24-month window"
```

---

## Task 3.2: Implement `sweep_adoptions()` with multi-match logging

**Files:**
- Modify: `src/docket/services/minutes_adoption.py`
- Modify: `tests/unit/test_minutes_adoption.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_minutes_adoption.py`:

```python
import pytest
import psycopg2.extras

from docket.db import db, db_cursor
from docket.services.minutes_adoption import sweep_adoptions


@pytest.fixture
def adoption_scenario():
    """Adoption meeting on 2026-01-07 has an agenda item adopting minutes from 2024-12-05.
    The 2024-12-05 meeting also exists in the DB."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM municipalities ORDER BY id LIMIT 1")
            muni_id = cur.fetchone()["id"]

            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   VALUES (%s, 'Council Meeting', '2024-12-05', 'council') RETURNING id""",
                (muni_id,),
            )
            target_id = cur.fetchone()["id"]

            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   VALUES (%s, 'Council Meeting', '2026-01-07', 'council') RETURNING id""",
                (muni_id,),
            )
            adoption_id = cur.fetchone()["id"]

            cur.execute(
                """INSERT INTO agenda_items (meeting_id, title, item_number, is_consent)
                   VALUES (%s, 'Approval of Minutes from December 5, 2024', '5', FALSE)
                   RETURNING id""",
                (adoption_id,),
            )
            agenda_id = cur.fetchone()["id"]

            cur.execute(
                """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                       confidence, needs_review)
                   VALUES (%s, 'minutes_text', 'passed', 5, 0, 0, 'high', FALSE) RETURNING id""",
                (adoption_id,),
            )
            vote_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO vote_agenda_items
                    (vote_id, agenda_item_id, association_type, match_method,
                     match_confidence, provisional)
                   VALUES (%s, %s, 'explicit', 'manual_test', 1.0, FALSE)""",
                (vote_id, agenda_id),
            )
        conn.commit()

    yield {"municipality_id": muni_id, "target_id": target_id, "adoption_id": adoption_id,
           "agenda_id": agenda_id, "vote_id": vote_id}

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vote_agenda_items WHERE vote_id = %s", (vote_id,))
            cur.execute("DELETE FROM votes WHERE id = %s", (vote_id,))
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (agenda_id,))
            cur.execute("DELETE FROM meetings WHERE id IN (%s, %s)", (target_id, adoption_id))
        conn.commit()


def test_sweep_adoptions_sets_minutes_adopted_at_on_target(adoption_scenario):
    flipped = sweep_adoptions(adoption_scenario["municipality_id"])
    assert adoption_scenario["target_id"] in flipped

    with db_cursor() as cur:
        cur.execute(
            "SELECT minutes_adopted_at FROM meetings WHERE id = %s",
            (adoption_scenario["target_id"],),
        )
        row = cur.fetchone()
    assert row["minutes_adopted_at"] is not None


def test_sweep_adoptions_idempotent(adoption_scenario):
    """Re-running doesn't overwrite or duplicate."""
    sweep_adoptions(adoption_scenario["municipality_id"])
    with db_cursor() as cur:
        cur.execute(
            "SELECT minutes_adopted_at FROM meetings WHERE id = %s",
            (adoption_scenario["target_id"],),
        )
        first_ts = cur.fetchone()["minutes_adopted_at"]

    flipped_second = sweep_adoptions(adoption_scenario["municipality_id"])
    assert adoption_scenario["target_id"] not in flipped_second  # already adopted

    with db_cursor() as cur:
        cur.execute(
            "SELECT minutes_adopted_at FROM meetings WHERE id = %s",
            (adoption_scenario["target_id"],),
        )
        second_ts = cur.fetchone()["minutes_adopted_at"]
    assert first_ts == second_ts
```

- [ ] **Step 2: Run to verify it fails**

```bash
venv/bin/pytest tests/unit/test_minutes_adoption.py -v
```

Expected: ImportError on `sweep_adoptions`.

- [ ] **Step 3: Implement `sweep_adoptions`**

Append to `src/docket/services/minutes_adoption.py`:

```python
def sweep_adoptions(municipality_id: int) -> list[int]:
    """Walk all adoption-pattern agenda items in this city and resolve them.

    For each passed-vote adoption agenda item with a parsed target date:
      - 0 candidate target meetings: log debug, leave for next sweep
      - 1 candidate: set minutes_adopted_at if currently NULL, return id
      - 2+ candidates: warn-log structured event, skip

    Returns: list of meeting ids whose minutes_adopted_at flipped from NULL → date.
    """
    flipped: list[int] = []
    with db() as conn:
        with conn.cursor(cursor_factory=__import__("psycopg2").extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT ai.id AS agenda_item_id, ai.title, m.id AS meeting_id,
                          m.meeting_date AS adoption_meeting_date
                   FROM agenda_items ai
                   JOIN meetings m ON m.id = ai.meeting_id
                   JOIN votes v ON v.meeting_id = m.id
                   WHERE m.municipality_id = %s
                     AND v.result = 'passed'""",
                (municipality_id,),
            )
            candidates = cur.fetchall()

            for c in candidates:
                if not is_adoption_title(c["title"]):
                    continue
                try:
                    target_date = extract_adoption_target(
                        c["title"],
                        adoption_meeting_date=c["adoption_meeting_date"],
                    )
                except AdoptionParseError as e:
                    logger.debug(
                        "adoption_parse_skip municipality_id=%s agenda_item_id=%s reason=%s",
                        municipality_id, c["agenda_item_id"], e,
                    )
                    continue

                cur.execute(
                    """SELECT id FROM meetings
                       WHERE municipality_id = %s AND meeting_date = %s""",
                    (municipality_id, target_date),
                )
                rows = cur.fetchall()
                if len(rows) == 0:
                    logger.debug(
                        "adoption_target_missing municipality_id=%s agenda_item_id=%s target_date=%s",
                        municipality_id, c["agenda_item_id"], target_date,
                    )
                    continue
                if len(rows) > 1:
                    logger.warning(
                        "adoption_multi_match municipality_id=%s agenda_item_id=%s "
                        "parsed_date=%s candidate_meeting_ids=%s",
                        municipality_id, c["agenda_item_id"], target_date,
                        [r["id"] for r in rows],
                    )
                    continue

                target_id = rows[0]["id"]
                cur.execute(
                    "SELECT minutes_adopted_at FROM meetings WHERE id = %s",
                    (target_id,),
                )
                if cur.fetchone()["minutes_adopted_at"] is not None:
                    logger.warning(
                        "adoption_already_recorded target_meeting_id=%s adoption_meeting_id=%s",
                        target_id, c["meeting_id"],
                    )
                    continue

                cur.execute(
                    "UPDATE meetings SET minutes_adopted_at = %s WHERE id = %s",
                    (c["adoption_meeting_date"], target_id),
                )
                flipped.append(target_id)
        conn.commit()

    return flipped
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
venv/bin/pytest tests/unit/test_minutes_adoption.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/docket/services/minutes_adoption.py tests/unit/test_minutes_adoption.py
git commit -m "feat(adoption): sweep_adoptions resolves adoption-pattern items to target meetings"
```

---

## Task 3.3: Wire sweep-side strict re-parse trigger

**Files:**
- Modify: `src/docket/services/minutes_adoption.py`

- [ ] **Step 1: Update `sweep_adoptions` to call strict_reparse for each flipped meeting**

Replace the end of `sweep_adoptions` with:

```python
                cur.execute(
                    "UPDATE meetings SET minutes_adopted_at = %s WHERE id = %s",
                    (c["adoption_meeting_date"], target_id),
                )
                flipped.append(target_id)
        conn.commit()

    # Trigger strict re-parse on each newly-flipped meeting (outside the txn)
    if flipped:
        from docket.analysis.vote_matcher import strict_reparse_meeting
        for mid in flipped:
            try:
                strict_reparse_meeting(mid)
            except Exception as e:
                logger.warning("strict_reparse failed for meeting %s after sweep: %s", mid, e)

    return flipped
```

- [ ] **Step 2: Verify existing tests still pass**

```bash
venv/bin/pytest tests/unit/test_minutes_adoption.py -v
```

Expected: all pass (strict_reparse is a no-op when there are no provisional consent links to promote, which is the case in the test fixture).

- [ ] **Step 3: Commit**

```bash
git add src/docket/services/minutes_adoption.py
git commit -m "feat(adoption): sweep triggers strict_reparse on each newly-flipped meeting"
```

---

## Task 3.4: Wire ingest pipeline to call `sweep_adoptions`

**Files:**
- Modify: `src/docket/services/ingest.py`

- [ ] **Step 1: Locate the end of the ingest pipeline**

```bash
venv/bin/grep -n "def ingest_municipality\|def ingest" src/docket/services/ingest.py
```

Find the function that orchestrates a full ingest run for a municipality.

- [ ] **Step 2: Add the sweep call at the end**

In the ingest orchestration function, before its `return`:

```python
    from docket.services.minutes_adoption import sweep_adoptions
    try:
        flipped = sweep_adoptions(municipality_id)
        logger.info("adoption_sweep municipality_id=%s flipped=%s", municipality_id, len(flipped))
    except Exception as e:
        logger.warning("adoption_sweep failed for municipality %s: %s", municipality_id, e)
```

(Adjust `municipality_id` to whatever variable name the function uses.)

- [ ] **Step 3: Verify the import works**

```bash
venv/bin/python -c "from docket.services import ingest"
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/docket/services/ingest.py
git commit -m "feat(ingest): call sweep_adoptions at end of municipality ingest run"
```

---

## Task 3.5: Rewrite `query.list_votes()` to use the join table

**Files:**
- Modify: `src/docket/services/query.py`
- Create: `tests/unit/test_query_list_votes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_query_list_votes.py
"""Tests for query.list_votes — N:M join-table read path."""

import pytest
import psycopg2.extras

from docket.db import db, db_cursor
from docket.services.query import list_votes


@pytest.fixture
def vote_with_two_links():
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM municipalities ORDER BY id LIMIT 1")
            muni_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   VALUES (%s, 'TEST_QUERY', '2099-01-03', 'council') RETURNING id""",
                (muni_id,),
            )
            mid = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO agenda_items (meeting_id, title, item_number, is_consent)
                   VALUES (%s, 'Item A', '1', TRUE), (%s, 'Item B', '2', TRUE)
                   RETURNING id""",
                (mid, mid),
            )
            ai_ids = [r["id"] for r in cur.fetchall()]
            cur.execute(
                """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                       confidence, needs_review)
                   VALUES (%s, 'minutes_text', 'passed', 5, 0, 0, 'high', FALSE) RETURNING id""",
                (mid,),
            )
            vid = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO vote_agenda_items
                    (vote_id, agenda_item_id, association_type, match_method,
                     match_confidence, excerpt_context, provisional)
                   VALUES
                    (%s, %s, 'consent_named', 'consent_block_named', 1.0, 'snip A', TRUE),
                    (%s, %s, 'consent_implicit', 'consent_block_default', 0.8, NULL, TRUE)""",
                (vid, ai_ids[0], vid, ai_ids[1]),
            )
        conn.commit()
    yield {"meeting_id": mid, "vote_id": vid, "agenda_item_ids": ai_ids}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vote_agenda_items WHERE vote_id = %s", (vid,))
            cur.execute("DELETE FROM votes WHERE id = %s", (vid,))
            cur.execute("DELETE FROM agenda_items WHERE meeting_id = %s", (mid,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mid,))
        conn.commit()


def test_list_votes_returns_vote_with_agenda_links(vote_with_two_links):
    votes = list_votes(vote_with_two_links["meeting_id"])
    assert len(votes) == 1
    vote = votes[0]
    assert len(vote.agenda_links) == 2
    assert vote.is_consent_block is True
    assert vote.has_provisional_links is True


def test_list_votes_excludes_excerpt_by_default(vote_with_two_links):
    votes = list_votes(vote_with_two_links["meeting_id"])
    for link in votes[0].agenda_links:
        assert link.excerpt_context is None


def test_list_votes_includes_excerpt_when_requested(vote_with_two_links):
    votes = list_votes(vote_with_two_links["meeting_id"], include_excerpts=True)
    excerpts = [l.excerpt_context for l in votes[0].agenda_links]
    assert "snip A" in excerpts
    assert None in excerpts  # the consent_implicit link has NULL excerpt
```

- [ ] **Step 2: Run to verify it fails**

```bash
venv/bin/pytest tests/unit/test_query_list_votes.py -v
```

Expected: failures — current `list_votes` builds Vote with the old shape.

- [ ] **Step 3: Rewrite `list_votes` in `query.py`**

Replace the existing `list_votes` function:

```python
def list_votes(meeting_id: int, *, include_excerpts: bool = False) -> list[Vote]:
    """Return votes for a meeting, with N:M agenda links and member votes."""
    from docket.models.vote import AgendaItemLink

    excerpt_select = "vai.excerpt_context" if include_excerpts else "NULL AS excerpt_context"

    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM votes WHERE meeting_id = %s ORDER BY id",
            (meeting_id,),
        )
        vote_rows = cur.fetchall()
        if not vote_rows:
            return []

        vote_ids = [r["id"] for r in vote_rows]

        cur.execute(
            f"""SELECT vai.id, vai.vote_id, vai.agenda_item_id,
                       vai.association_type, vai.match_method, vai.match_confidence,
                       vai.provisional, vai.is_manual, vai.is_active,
                       {excerpt_select},
                       ai.item_number, ai.title, ai.is_consent
                FROM vote_agenda_items vai
                JOIN agenda_items ai ON ai.id = vai.agenda_item_id
                WHERE vai.vote_id = ANY(%s)
                ORDER BY vai.vote_id, vai.match_confidence DESC, vai.id ASC""",
            (vote_ids,),
        )
        link_rows = cur.fetchall()

        cur.execute(
            "SELECT * FROM member_votes WHERE vote_id = ANY(%s) ORDER BY vote_id, id",
            (vote_ids,),
        )
        member_rows = cur.fetchall()

    links_by_vote: dict[int, list] = {}
    for r in link_rows:
        links_by_vote.setdefault(r["vote_id"], []).append(AgendaItemLink(
            id=r["id"],
            agenda_item_id=r["agenda_item_id"],
            item_number=r["item_number"],
            title=r["title"],
            is_consent=r["is_consent"],
            association_type=r["association_type"],
            match_method=r["match_method"],
            match_confidence=r["match_confidence"],
            excerpt_context=r["excerpt_context"],
            provisional=r["provisional"],
            is_manual=r["is_manual"],
            is_active=r["is_active"],
        ))

    members_by_vote: dict[int, list] = {}
    for r in member_rows:
        members_by_vote.setdefault(r["vote_id"], []).append(MemberVote(
            member_name=r["member_name"],
            position=r["position"],
            council_member_id=r.get("council_member_id"),
        ))

    return [
        Vote(
            id=r["id"], meeting_id=r["meeting_id"], external_id=r.get("external_id"),
            result=r.get("result", ""), yeas=r.get("yeas"), nays=r.get("nays"),
            abstentions=r.get("abstentions"), source=r.get("source", ""),
            confidence=r.get("confidence", ""), header_result=r.get("header_result"),
            needs_review=bool(r.get("needs_review", False)), review_reason=r.get("review_reason"),
            resolution_number=r.get("resolution_number"),
            video_timestamp=r.get("video_timestamp"),
            agenda_links=links_by_vote.get(r["id"], []),
            member_votes=members_by_vote.get(r["id"], []),
        )
        for r in vote_rows
    ]
```

Make sure the imports at the top of `query.py` include `from docket.models.vote import AgendaItemLink, MemberVote, Vote`.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
venv/bin/pytest tests/unit/test_query_list_votes.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Verify other callers of list_votes still work**

```bash
venv/bin/grep -rn "list_votes" src/docket/web/ src/docket/services/
```

Check each caller — they likely access `vote.agenda_item_id`, `vote.match_confidence`, etc., which no longer exist. Patch each caller to use the new properties (`vote.primary_link`, `vote.is_consent_block`, etc.). For now if any caller fails, fix it inline; the template change in 3.6 will cover the main consumer.

- [ ] **Step 6: Commit**

```bash
git add src/docket/services/query.py tests/unit/test_query_list_votes.py
git commit -m "refactor(query): list_votes uses 3-query join-table pattern with include_excerpts opt"
```

---

## Task 3.6: Update `meeting.html` template for N:M

**Files:**
- Modify: `src/docket/web/templates/meeting.html` (or whichever template renders meeting detail with votes)

- [ ] **Step 1: Locate the template that renders votes**

```bash
venv/bin/grep -rln "vote.agenda_item\|agenda_item_title\|votes" src/docket/web/templates/
```

Find the template file that loops over votes and renders agenda item info.

- [ ] **Step 2: Replace the vote render block**

Find the loop over votes and replace whatever currently shows `vote.agenda_item_title` / `vote.match_confidence` / etc. with this Jinja block (adapt class names and styling to match existing template):

```jinja
{% for vote in votes %}
  <div class="vote-block {{ 'vote-consent-block' if vote.is_consent_block else 'vote-substantive' }}">
    <div class="vote-header">
      <span class="vote-result vote-result-{{ vote.result }}">{{ vote.result|upper }}</span>
      <span class="vote-tally">{{ vote.yeas }} yea / {{ vote.nays }} nay
        {%- if vote.abstentions %} / {{ vote.abstentions }} abstain{% endif -%}
      </span>
      {% if vote.has_provisional_links %}
        <span class="pill pill-provisional" title="Council has not yet adopted these minutes">Provisional</span>
      {% elif vote.is_consent_block %}
        <span class="pill pill-adopted" title="Minutes adopted by council">Adopted</span>
      {% endif %}
      <span class="vote-source-badge vote-source-{{ vote.source }}">{{ vote.source|replace('_', ' ')|title }}</span>
    </div>

    {% if vote.is_consent_block %}
      {% set active_links = vote.active_links %}
      <details class="consent-block-detail">
        <summary>Consent vote — covers {{ active_links|length }} item{{ 's' if active_links|length != 1 else '' }}</summary>
        <ul class="consent-item-list">
          {% for link in active_links %}
            <li class="consent-item">
              <span class="item-number">[{{ link.item_number or '?' }}]</span>
              <span class="item-title">{{ link.title }}</span>
              {% if link.association_type == 'consent_named' %}
                <span class="match-badge match-badge-named">named in vote</span>
              {% else %}
                <span class="match-badge match-badge-default">consent default</span>
              {% endif %}
            </li>
          {% endfor %}
        </ul>
      </details>
      {% if vote.excluded_links %}
        <div class="consent-excluded">
          <em>Pulled from consent — voted separately:</em>
          <ul>
            {% for link in vote.excluded_links %}
              <li>[{{ link.item_number or '?' }}] {{ link.title }}</li>
            {% endfor %}
          </ul>
        </div>
      {% endif %}
    {% elif vote.primary_link %}
      <div class="substantive-link">
        <span class="item-number">[{{ vote.primary_link.item_number or '?' }}]</span>
        <span class="item-title">{{ vote.primary_link.title }}</span>
        <span class="match-badge match-badge-{{ vote.primary_link.match_method }}">
          {{- vote.primary_link.match_method|replace('_', ' ')|title -}}
        </span>
      </div>
    {% else %}
      <div class="unmatched-vote"><em>No agenda item linked.</em></div>
    {% endif %}

    {% if vote.member_votes %}
      <div class="vote-members">
        <strong>Ayes:</strong>
        {{ vote.member_votes|selectattr('position','equalto','yea')|map(attribute='member_name')|join(', ') }}
        {% set nays = vote.member_votes|selectattr('position','equalto','nay')|map(attribute='member_name')|list %}
        {% if nays %}<br><strong>Nays:</strong> {{ nays|join(', ') }}{% endif %}
      </div>
    {% endif %}
  </div>
{% endfor %}
```

- [ ] **Step 3: Smoke test the template renders without exception**

```bash
venv/bin/python -c "
from docket.web import create_app
from docket.services.query import list_meetings
app = create_app()
client = app.test_client()
# Find any meeting with votes — fall back to ID 1 if none
import psycopg2
with app.app_context():
    from docket.db import db_cursor
    with db_cursor() as cur:
        cur.execute('SELECT m.id, mn.slug FROM meetings m JOIN municipalities mn ON m.municipality_id=mn.id JOIN votes v ON v.meeting_id=m.id LIMIT 1')
        row = cur.fetchone()
        if row:
            r = client.get(f'/al/{row[\"slug\"]}/meetings/{row[\"id\"]}/')
            print('Status:', r.status_code)
            print('Length:', len(r.data))
"
```

Expected: status 200, non-zero length.

- [ ] **Step 4: Run ruff**

```bash
venv/bin/ruff check src/
```

Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/docket/web/templates/meeting.html
git commit -m "feat(template): N:M vote render — consent block collapse, provisional/adopted pills"
```

---

## Task 3.7: Phase 3 verification

- [ ] **Step 1: Run all unit tests**

```bash
venv/bin/pytest tests/unit/ -v
```

Expected: all unit tests pass.

- [ ] **Step 2: Run ruff**

```bash
venv/bin/ruff check src/
```

Expected: clean.

- [ ] **Step 3: Run flask dev server, click through 3 meeting pages**

```bash
venv/bin/flask run
```

In a browser, navigate to 3 different meeting detail pages. Verify:
- Substantive votes show single agenda link with method badge
- Consent block votes show collapsed "Consent vote — covers N items" with expand
- Provisional pill shows on un-adopted meetings; Adopted pill shows on adopted ones (will mostly be Provisional pre-backfill)
- Member votes still render with Ayes/Nays

Stop the server with Ctrl-C.

- [ ] **Step 4: Tag the Phase 3 checkpoint**

```bash
git tag phase-3-complete
```

---

# Operational Phase — Local Backfill + Railway Sync

These tasks are **mostly manual** (long-running scripts, manual verification, push to Railway). Each task has a verify step before moving on.

## Task 4.1: Update `backfill_vote_context.py` with JSON cache

**Files:**
- Modify: `scripts/backfill_vote_context.py`

- [ ] **Step 1: Read existing script**

```bash
venv/bin/cat scripts/backfill_vote_context.py | head -100
```

Note the loop structure and how it iterates meetings.

- [ ] **Step 2: Add caching layer**

At the top of the script, add:

```python
import json
from pathlib import Path

CACHE_DIR = Path("data/minutes_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def cache_path(meeting_id: int) -> Path:
    return CACHE_DIR / f"{meeting_id}.json"


def cached_parse(meeting_id: int, minutes_url: str):
    """Return cached parse result if present, else parse and cache."""
    p = cache_path(meeting_id)
    if p.exists():
        return json.loads(p.read_text())
    from docket.analysis.minutes_parser import (
        download_minutes_pdf, extract_text_from_pdf, parse_minutes,
    )
    pdf = download_minutes_pdf(minutes_url)
    if not pdf:
        return None
    text = extract_text_from_pdf(pdf)
    parsed = parse_minutes(text)
    payload = {
        "full_text": parsed.full_text,
        "votes": [
            {
                "ayes": v.ayes, "nays": v.nays, "abstentions": v.abstentions,
                "result": v.result, "resolution_number": v.resolution_number,
                "context": v.context, "raw_text": v.raw_text,
                "is_likely_consent": v.is_likely_consent,
            }
            for v in parsed.votes
        ],
    }
    p.write_text(json.dumps(payload))
    return payload
```

Update the existing loop to call `cached_parse(...)` instead of doing inline download/parse.

- [ ] **Step 3: Verify the script runs against one meeting**

```bash
# Pick a known meeting with a minutes URL
venv/bin/psql -U docket -d docket_db -c "SELECT id, minutes_url FROM meetings WHERE minutes_url IS NOT NULL LIMIT 1"

# Run a small subset (you'll need to add a CLI flag or just run it as-is and let it cache)
venv/bin/python scripts/backfill_vote_context.py 2>&1 | head -20
```

Expected: file `data/minutes_cache/<meeting_id>.json` exists after first run for at least one meeting.

- [ ] **Step 4: Commit**

```bash
git add scripts/backfill_vote_context.py
# Add the cache dir to .gitignore so we don't commit hundreds of JSONs
echo "data/minutes_cache/" >> .gitignore
git add .gitignore
git commit -m "feat(scripts): cache minutes parse output to data/minutes_cache/ JSON files"
```

---

## Task 4.2: Run full PDF re-parse locally (manual, long-running)

- [ ] **Step 1: Run the backfill script**

```bash
venv/bin/python scripts/backfill_vote_context.py 2>&1 | tee /tmp/backfill.log
```

Expected: hours of output, one line per meeting. Final state: `data/minutes_cache/` contains ~788 JSON files.

- [ ] **Step 2: Verify cache populated**

```bash
ls data/minutes_cache/ | wc -l
```

Expected: ~788 files (matches Birmingham meeting count with minutes).

- [ ] **Step 3: Spot-check raw_text was persisted to votes table**

```bash
venv/bin/psql -U docket -d docket_db -c "SELECT COUNT(*) AS with_raw FROM votes WHERE source='minutes_text' AND raw_text IS NOT NULL AND length(raw_text) > 200"
```

Expected: ~9,934 — all minutes votes have non-empty raw_text.

---

## Task 4.3: Run new matcher locally (manual)

- [ ] **Step 1: Snapshot pre-matcher state**

```bash
venv/bin/psql -U docket -d docket_db -c "SELECT 'before' AS phase, association_type, COUNT(*) FROM vote_agenda_items GROUP BY association_type ORDER BY association_type"
```

Save the output for comparison after.

- [ ] **Step 2: Run the matcher**

```bash
venv/bin/python scripts/run_vote_matching.py 2>&1 | tee /tmp/matcher.log
```

Expected: prints summary across 788 meetings — substantive, consent, timestamp counts.

- [ ] **Step 3: Snapshot post-matcher state**

```bash
venv/bin/psql -U docket -d docket_db -c "SELECT 'after' AS phase, association_type, COUNT(*) FROM vote_agenda_items GROUP BY association_type ORDER BY association_type"
```

Expected: substantial increase in `consent_named` and `consent_implicit`. Total link count > 50,000 if Birmingham's consent ratio holds.

---

## Task 4.4: Local verification gate before Railway sync

- [ ] **Step 1: Match-rate diff query**

```bash
venv/bin/psql -U docket -d docket_db <<'EOF'
SELECT
  (SELECT COUNT(*) FROM votes WHERE source='minutes_text') AS total_minutes_votes,
  (SELECT COUNT(DISTINCT vote_id) FROM vote_agenda_items vai
     JOIN votes v ON v.id=vai.vote_id WHERE v.source='minutes_text' AND vai.is_active) AS minutes_votes_matched,
  (SELECT COUNT(*) FROM vote_agenda_items WHERE is_active) AS total_active_links,
  (SELECT COUNT(*) FROM vote_agenda_items WHERE provisional AND is_active) AS provisional_links;
EOF
```

Expected: minutes_votes_matched / total_minutes_votes is well above the 1.1% baseline (target 60-80%).

- [ ] **Step 2: Spot-check 5 random consent blocks**

```bash
venv/bin/psql -U docket -d docket_db <<'EOF'
WITH random_consent AS (
  SELECT v.id, v.meeting_id FROM votes v
  WHERE v.source = 'minutes_text'
    AND EXISTS (SELECT 1 FROM vote_agenda_items vai WHERE vai.vote_id = v.id AND vai.association_type LIKE 'consent_%')
  ORDER BY RANDOM() LIMIT 5
)
SELECT v.id AS vote_id, v.meeting_id, m.meeting_date,
       (SELECT COUNT(*) FROM vote_agenda_items WHERE vote_id = v.id AND is_active) AS link_count,
       (SELECT json_agg(json_build_object('item_num', ai.item_number, 'title', LEFT(ai.title, 60), 'type', vai.association_type, 'conf', vai.match_confidence))
        FROM vote_agenda_items vai JOIN agenda_items ai ON ai.id=vai.agenda_item_id
        WHERE vai.vote_id = v.id AND vai.is_active) AS links
FROM votes v
JOIN meetings m ON m.id = v.meeting_id
WHERE v.id IN (SELECT id FROM random_consent);
EOF
```

Visually inspect: do the linked items make sense for a consent vote? Are named items reasonable?

- [ ] **Step 3: Spot-check 5 random substantive matches**

```bash
venv/bin/psql -U docket -d docket_db <<'EOF'
SELECT v.id AS vote_id, vai.match_method, vai.match_confidence,
       LEFT(ai.title, 80) AS agenda_title, v.resolution_number
FROM vote_agenda_items vai
JOIN votes v ON v.id = vai.vote_id
JOIN agenda_items ai ON ai.id = vai.agenda_item_id
WHERE vai.association_type = 'explicit'
  AND v.source = 'minutes_text'
ORDER BY RANDOM() LIMIT 5;
EOF
```

Visually inspect: do the matches look plausible? Resolution numbers should appear in titles for `resolution_number` matches.

- [ ] **Step 4: Run flask dev server, click through 3 meeting pages**

```bash
venv/bin/flask run
```

Spot-check 3 meetings in browser — consent blocks render expanded list, substantive votes link to agenda items, provisional pills present.

- [ ] **Step 5: Run pytest**

```bash
venv/bin/pytest tests/unit/ -v
```

Expected: all green.

**🛑 Gate: do not proceed if any of the above looks wrong.** Tune matcher and re-run.

---

## Task 4.5: Run adoption sweep (manual)

- [ ] **Step 1: Run the sweep across all cities**

```bash
venv/bin/python -c "
from docket.services.minutes_adoption import sweep_adoptions
from docket.db import db_cursor
with db_cursor() as cur:
    cur.execute('SELECT id, slug FROM municipalities WHERE active = TRUE')
    for row in cur.fetchall():
        flipped = sweep_adoptions(row['id'])
        print(f'{row[\"slug\"]}: flipped {len(flipped)} meetings')
"
```

Expected: Birmingham flips ~10–25 meetings (per memory's batch-adoption scenario in early 2026).

- [ ] **Step 2: Verify provisional → false transitions**

```bash
venv/bin/psql -U docket -d docket_db -c "SELECT provisional, COUNT(*) FROM vote_agenda_items WHERE is_active GROUP BY provisional"
```

Expected: a meaningful number of links flipped from `t` (true) to `f` (false). Meetings whose minutes were adopted should have all their consent links non-provisional now.

- [ ] **Step 3: Spot-check one adopted meeting in browser**

```bash
venv/bin/flask run
```

Find a meeting flagged as adopted (`SELECT id, meeting_date FROM meetings WHERE minutes_adopted_at IS NOT NULL LIMIT 1`), navigate to it. Verify "Adopted" pill instead of "Provisional".

---

## Task 4.6: Re-verify locally after sweep

- [ ] **Step 1: Re-run pytest**

```bash
venv/bin/pytest tests/unit/ -v
```

Expected: green.

- [ ] **Step 2: Final stats query**

```bash
venv/bin/psql -U docket -d docket_db <<'EOF'
SELECT
  COUNT(*) FILTER (WHERE is_active) AS active_links,
  COUNT(*) FILTER (WHERE NOT is_active) AS ghost_links,
  COUNT(*) FILTER (WHERE provisional AND is_active) AS provisional,
  COUNT(*) FILTER (WHERE NOT provisional AND is_active) AS official
FROM vote_agenda_items;

SELECT COUNT(*) FROM meetings WHERE minutes_adopted_at IS NOT NULL;
EOF
```

Expected: official > 0 (sweep did its job); ghost links may be 0 if no items were pulled from consent in adopted meetings.

**🛑 Gate: do not proceed if anything looks wrong.**

---

## Task 4.7: Backup Railway, then sync

- [ ] **Step 1: Take a Railway backup**

```bash
pg_dump $RAILWAY_DATABASE_URL > /tmp/railway-backup-$(date +%Y%m%d-%H%M).sql
ls -lh /tmp/railway-backup-*.sql
```

Expected: a non-empty SQL dump file.

- [ ] **Step 2: Apply migrations 009 + 010 against Railway**

```bash
DATABASE_URL=$RAILWAY_DATABASE_URL venv/bin/python -m docket.migrations.runner --status
DATABASE_URL=$RAILWAY_DATABASE_URL venv/bin/python -m docket.migrations.runner
DATABASE_URL=$RAILWAY_DATABASE_URL venv/bin/python -m docket.migrations.runner --status
```

Expected first call: shows 009 and 010 as `pending`. After running, both `applied`.

- [ ] **Step 3: Sync the votes table content**

```bash
pg_dump $LOCAL_DATABASE_URL --table=votes --data-only --no-owner | psql $RAILWAY_DATABASE_URL
```

Note: this will fail with FK conflicts unless we TRUNCATE first. Better:

```bash
psql $RAILWAY_DATABASE_URL -c "TRUNCATE votes RESTART IDENTITY CASCADE"
pg_dump $LOCAL_DATABASE_URL --table=votes --table=member_votes --table=vote_agenda_items --data-only --no-owner | psql $RAILWAY_DATABASE_URL
```

(TRUNCATE CASCADE wipes member_votes and vote_agenda_items as well; the dump restores all three.)

- [ ] **Step 4: Targeted UPDATE for `meetings.minutes_adopted_at`**

```bash
venv/bin/python <<'EOF'
import os, psycopg2
local = psycopg2.connect(os.environ["LOCAL_DATABASE_URL"])
remote = psycopg2.connect(os.environ["RAILWAY_DATABASE_URL"])
with local.cursor() as lc, remote.cursor() as rc:
    lc.execute("SELECT id, minutes_adopted_at FROM meetings WHERE minutes_adopted_at IS NOT NULL")
    for mid, ts in lc.fetchall():
        rc.execute("UPDATE meetings SET minutes_adopted_at = %s WHERE id = %s", (ts, mid))
remote.commit()
print("done")
EOF
```

- [ ] **Step 5: Verify row counts match**

```bash
echo "LOCAL:"
psql $LOCAL_DATABASE_URL -c "SELECT 'votes' AS t, COUNT(*) FROM votes UNION ALL SELECT 'links', COUNT(*) FROM vote_agenda_items UNION ALL SELECT 'mv', COUNT(*) FROM member_votes UNION ALL SELECT 'adopted', COUNT(*) FROM meetings WHERE minutes_adopted_at IS NOT NULL"
echo "RAILWAY:"
psql $RAILWAY_DATABASE_URL -c "SELECT 'votes' AS t, COUNT(*) FROM votes UNION ALL SELECT 'links', COUNT(*) FROM vote_agenda_items UNION ALL SELECT 'mv', COUNT(*) FROM member_votes UNION ALL SELECT 'adopted', COUNT(*) FROM meetings WHERE minutes_adopted_at IS NOT NULL"
```

Expected: matching counts.

---

## Task 4.8: Deploy code to Railway

- [ ] **Step 1: Push the branch to origin and merge or deploy**

```bash
git push origin main
railway up --detach
```

(Per memory: use `railway up --detach`, NOT `railway redeploy`.)

- [ ] **Step 2: Verify the live site**

Open `https://docket-web-production-6110.up.railway.app/` in a browser. Click into Birmingham, then a recent meeting. Expected: meeting page renders with new N:M layout, no 500s.

- [ ] **Step 3: Spot-check from production**

```bash
curl -sI https://docket-web-production-6110.up.railway.app/al/birmingham/ | head -5
```

Expected: HTTP/2 200.

---

## Plan complete

After Task 4.8, the system is at the new steady state:
- Schema: `vote_agenda_items` join table populated locally + on Railway
- Match rate: 1.1% → ~60-80% (final number known after backfill)
- Lifecycle: provisional consent links flipping to official as the sweep runs after each ingest
- UI: consent blocks render collapsed, provisional/adopted pills, member-vote rendering preserved

**PR 2 (separate plan, after PR 1 is verified stable):** drop singular columns `votes.agenda_item_id`, `votes.match_method`, `votes.match_confidence` via migration 011. Not in this plan.

**Original 4-step plan steps 3 (re-enable landing page vote sections) and 4 (deploy):** separate work, can now proceed against the new shape.
