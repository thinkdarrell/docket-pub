# Vote ↔ Agenda Item Matching Redesign

**Status:** Design — pending user review before implementation plan
**Date:** 2026-05-01
**Owner:** Darrell Nance (with Brennan Holzer's prior matcher work as foundation)
**Scope:** docket-pub-dw-dev — Birmingham minutes votes (extensible to other cities)

---

## Problem

The existing matcher (`analysis/vote_matcher.py`) links 110 of 9,934 minutes-text votes to agenda items (1.1%). Three structural causes:

1. **Schema mismatch.** Resolution numbers ("1854-25") are assigned at meeting time and appear in the minutes, but they are not present in the corresponding agenda item titles or descriptions. Of 267 unmatched-with-resolution-number votes, **0** had their resolution number anywhere in the agenda items for that meeting.
2. **Wrong context window.** `minutes_parser.py` captures 500 chars before each vote block and then keeps only the last 200 — exactly the procedural boilerplate ("The resolution was read by the City Clerk, whereupon Councilmember…"). The first 300 chars (where the resolution body and applicant/contract content live) are discarded.
3. **N:M relationship.** Birmingham council votes one combined motion to adopt the entire consent agenda. One minutes vote covers many agenda items. The current schema (`votes.agenda_item_id` singular FK) cannot represent this.

Today, agenda items lacking a high-confidence link display as orphan entries — votes are matched to a small minority. Fixing this is the difference between docket.pub being a "selective audit" tool and being a "complete record."

## Solution Summary

1. **Schema:** introduce `vote_agenda_items` join table (N:M) with link-level metadata; deprecate the singular FK on `votes`.
2. **Parser:** widen the captured context to 1500 chars and persist the full vote block in `votes.raw_text`.
3. **Matcher:** classify each vote as substantive (1:1) or consent block (1:N). Substantive matching uses the existing three-tier heuristics over the richer context. Consent block matching links to all `is_consent=TRUE` items for the meeting, with named callouts upgraded to confidence 1.0.
4. **Adoption lifecycle:** new `services/minutes_adoption.py` runs a stateless sweep after each ingest, detecting "Approval of Minutes from <date>" agenda items in passed votes. Resolves prior meetings and sets `minutes_adopted_at`. Triggers a strict re-parse that flips consent-block links from provisional to official.
5. **API:** new `AgendaItemLink` dataclass; `query.list_votes()` returns each vote with a list of links; convenience properties for templates; `include_excerpts=False` default for payload size.
6. **Backfill:** local re-parse of 788 minutes PDFs with caching, run new matcher locally, push to Railway via pg_dump (not bulk UPDATEs).

## Non-Goals

- AI / LLM-based matching. Heuristics only. AI features remain deferred per CLAUDE.md.
- Manual link-correction admin UI. The schema supports it (`is_manual` column) but the form/route lands in a separate spec.
- Search-votes endpoint. No FTS index on votes; addressed when needed.
- Backfill of cities other than Birmingham. Other cities currently have no minutes votes; this design is general but only Birmingham is exercised.
- Bridge view masking the new schema. Direct rewrite of `query.list_votes()` instead.

## Section 1 — Schema & Migrations

### Migration 009 — additive

```sql
CREATE TABLE vote_agenda_items (
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
CREATE INDEX idx_vai_vote ON vote_agenda_items(vote_id);
CREATE INDEX idx_vai_agenda_item ON vote_agenda_items(agenda_item_id);
CREATE INDEX idx_vai_provisional ON vote_agenda_items(provisional) WHERE provisional;
CREATE INDEX idx_vai_active ON vote_agenda_items(is_active) WHERE is_active;

ALTER TABLE meetings ADD COLUMN minutes_adopted_at TIMESTAMPTZ NULL;
```

Column semantics:

| Column | Purpose |
|---|---|
| `association_type` | How the link was inferred. `explicit` = substantive 1:1. `consent_named` = consent block, item explicitly named in vote text. `consent_implicit` = consent block, inferred from agenda's `is_consent` flag. `positional` reserved for future. |
| `match_method` | Granular heuristic that produced the link: `resolution_number`, `item_number`, `text_similarity`, `consent_block_named`, `consent_block_default`, `consent_enumerated` (set by strict re-parse). Free-form text (not enum) for forward extensibility. |
| `match_confidence` | 0.0–1.0 |
| `excerpt_context` | Snippet of minutes text that drove this link. NULL for `consent_implicit` (no specific trigger). For substantive, the resolution body. For `consent_named`, the named callout. |
| `provisional` | TRUE until council adopts the minutes. Substantive matches insert with `FALSE` (no consent ambiguity). Consent matches insert with `TRUE` and flip after adoption sweep + strict re-parse. |
| `is_manual` | A human edited this link — automated matcher must not overwrite. Default FALSE. |
| `is_active` | FALSE = "ghost" link kept for audit only (item was on consent agenda but pulled and voted separately). Readers filter `is_active=TRUE` by default. |

### Migration 010 — backfill existing 110 matches

```sql
INSERT INTO vote_agenda_items
    (vote_id, agenda_item_id, association_type, match_method,
     match_confidence, provisional, is_manual, is_active)
SELECT id, agenda_item_id, 'explicit', match_method,
       match_confidence, FALSE, FALSE, TRUE
FROM votes
WHERE agenda_item_id IS NOT NULL
ON CONFLICT (vote_id, agenda_item_id) DO NOTHING;
```

Idempotent. Pre-N:M matches are unambiguous, so `provisional=FALSE`.

### Migration 011 — drops singular columns (separate PR)

```sql
ALTER TABLE votes
  DROP COLUMN agenda_item_id,
  DROP COLUMN match_method,
  DROP COLUMN match_confidence;
```

**Ships in PR 2, not PR 1.** PR 1 leaves the singular columns in place — unreferenced but undeleted — as the rollback safety net. PR 2 ships only after PR 1 is verified stable in production.

### What stays on `votes`

`resolution_number`, `match_context`, `header_result`, `raw_text`, `confidence`, `source`, `result`, `yeas`, `nays`, `abstentions`, `needs_review`, `review_reason`, `video_timestamp`, `external_id`. These are properties of the vote itself, not of any link.

## Section 2 — Matcher Refactor

`analysis/vote_matcher.py` becomes:

```
match_all_unmatched()              -- existing entry point, refactored
match_votes_for_meeting(mid)       -- existing top-level dispatch
  ├─ _classify_vote(vote)          -- NEW: substantive vs consent
  ├─ _match_substantive(vote, items)   -- existing 3-tier, refactored
  ├─ _match_consent_block(vote, items) -- NEW
  └─ _upsert_link(...)             -- NEW: insert/update with manual guard
strict_reparse_meeting(mid)        -- NEW: triggered by adoption
```

### Stage 1 — classify each vote

A vote is a consent block if its `raw_text` (or `match_context`) contains any of:

```python
CONSENT_BLOCK_PHRASES = [
    "the resolutions and ordinances introduced as consent agenda matters",
    "consent agenda matters were read by the city clerk",
    "all items on the consent agenda",
    "items on consent",
    # extensible
]
```

Single-phrase match → consent block. Otherwise → substantive.

The `ParsedVote.is_likely_consent` flag set by the parser is the cheap path; falling back to text scan handles cases parsed before the parser was updated.

### Stage 2a — substantive votes

Three tiers (existing logic, run over the richer context):

| Tier | Match | Confidence | `match_method` |
|---|---|---|---|
| 1 | Resolution number found in agenda item title or description | 0.9 | `resolution_number` |
| 2 | Item number from context | 0.7 | `item_number` |
| 3 | Keyword overlap ≥ 0.3 | 0.5–0.8 | `text_similarity` |

`association_type='explicit'`, `provisional=FALSE`. Insert via `_upsert_link()`.

### Stage 2b — consent block votes

Two passes:

1. **Named callout pass.** For each agenda item where `is_consent=TRUE` for the meeting, scan the vote's `raw_text` for any of:
   - The agenda item's resolution number (if present), as `\bRES_NUM\b`
   - The agenda item's item number, as `\b(Item|ITEM)\s+(?:No\.?\s*)?ITEM_NUM\b` or `#ITEM_NUM\b`
   - **Strong title-keyword overlap**: at least 3 distinct significant words (using the existing `_significant_words` helper — 4+ chars, not stop words) from the agenda title appearing in `raw_text`

   Hits → `_upsert_link()` with `association_type='consent_named'`, `match_confidence=1.0`, `match_method='consent_block_named'`, `excerpt_context=<the surrounding 200-char snippet>`, `provisional=TRUE`. The 3-word minimum is the named-callout threshold and is a tunable constant.
2. **Default consent fill.** For each remaining `is_consent=TRUE` agenda item not already linked → `_upsert_link()` with `association_type='consent_implicit'`, `match_confidence=0.8`, `match_method='consent_block_default'`, `excerpt_context=NULL`, `provisional=TRUE`.

### `_upsert_link()` — manual shield + idempotency

```python
def _upsert_link(cur, vote_id, agenda_item_id, *,
                 association_type, match_method, match_confidence,
                 excerpt_context, provisional):
    cur.execute(
        "SELECT is_manual FROM vote_agenda_items WHERE vote_id=%s AND agenda_item_id=%s",
        (vote_id, agenda_item_id),
    )
    existing = cur.fetchone()
    if existing and existing['is_manual']:
        return  # human-locked — leave alone

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
        (vote_id, agenda_item_id, association_type, match_method,
         match_confidence, excerpt_context, provisional),
    )
```

The `WHERE is_manual = FALSE` on the UPDATE is a DB-level dead-man's switch — protects human edits even if app-level code regresses.

The matcher **never** flips `provisional` — that is exclusively the strict re-parse's job (Section 4).

## Section 3 — Parser Changes (`analysis/minutes_parser.py`)

### 3a. Widen the captured context

Replace `_build_vote()`'s windowing:

```python
PRE_VOTE_WINDOW = 1500
POST_VOTE_WINDOW = 200

pre_start = max(0, match.start() - PRE_VOTE_WINDOW)
post_end  = min(len(text), match.end() + POST_VOTE_WINDOW)
context   = text[pre_start : match.start()].strip()
raw_text  = text[pre_start : post_end].strip()

return ParsedVote(..., context=context, raw_text=raw_text,
                  is_likely_consent=_contains_consent_phrase(context))
```

The 1500-char window captures the resolution body that today's parser discards.

### 3b. Persist `raw_text`

`ParsedVote` already has the field; ingest currently writes only `context` to `votes.match_context`. Update ingest to also write `raw_text` to `votes.raw_text`.

### 3c. New `is_likely_consent` flag on `ParsedVote`

Convenience flag set by parser, used by matcher's classifier as the fast path. Fallback text scan handles legacy votes with empty/old contexts.

### What does NOT change

- Roll call / attendance parsing
- Result determination
- Resolution number regex (unchanged, just runs over the wider window now)
- Vote name parsing (curly-apostrophe handling for O'Quinn, etc.)

## Section 4 — Adoption Lifecycle

### 4a. Sweep-based detection

New `services/minutes_adoption.py`:

```python
def sweep_adoptions(municipality_id: int) -> list[int]:
    """Stateless adoption resolver. Walks all agenda items in this city
    that match adoption-pattern titles AND have a passed vote. Resolves
    referenced meetings; sets minutes_adopted_at where currently NULL.
    Returns list of meeting IDs whose adoption status flipped."""
```

Patterns (case-insensitive):

```python
ADOPTION_TITLE_PATTERNS = [
    r"approval of (?:the )?minutes from .*?(?P<date>\w+ \d{1,2},? \d{4})",
    r"adoption of (?:the )?minutes from .*?(?P<date>\w+ \d{1,2},? \d{4})",
    r"approval of (?:the )?(?P<date>\w+ \d{1,2},? \d{4}) minutes",
    r"minutes from the (?:\w+ )?meeting of (?P<date>\w+ \d{1,2},? \d{4})",
    # extensible
]
```

For each match in passed votes:

1. Parse `<date>` to a Python `date`. If invalid (e.g. "Feb 31") → skip + log.
2. Reject if parsed date is in the future relative to the adoption meeting's date → skip + log.
3. Reject if parsed date is more than 24 months prior to the adoption meeting's date → skip + log (catches "1994" hallucinations and pathological cases).
4. Look up referenced meeting:

   ```sql
   SELECT id FROM meetings
   WHERE municipality_id = $1
     AND meeting_date = $2
     AND meeting_type = $3
   ```

   - 0 candidates → debug log, leave for next sweep run.
   - 1 candidate → set `minutes_adopted_at = adoption_meeting.meeting_date` (semantic: the legal adoption date, not our scrape time). Skip if already non-NULL (idempotent — never overwrite). On attempted overwrite, warn-log with both meeting IDs.
   - 2+ candidates → warn-log with title and candidate IDs, **skip**. Don't guess.

The sweep runs at the end of `services/ingest.py`'s ingest pipeline. Stateless, no queue, no extra columns, idempotent.

### 4b. Strict re-parse trigger — dual-trigger contract

Strict re-parse runs when both:
- A meeting's `minutes_adopted_at` is non-NULL, AND
- That meeting has provisional consent links.

Two natural firing points:

1. **Sweep side**: when `sweep_adoptions()` flips a meeting NULL → adopted, immediately call `strict_reparse_meeting(mid)` if the meeting has any provisional links.
2. **Matcher side**: when the regular matcher finishes a meeting, check `minutes_adopted_at`. If non-NULL → call `strict_reparse_meeting(mid)`.

Either path lands the same end state. Order independent.

### 4c. Strict re-parse logic — `strict_reparse_meeting(meeting_id)`

**Critical: like the regular matcher, the strict re-parse must respect the `is_manual` shield.** Every UPDATE/INSERT in the steps below carries an implicit `WHERE is_manual = FALSE` predicate. Manual edits never get overwritten or deactivated by automated re-parse.

For each consent-block vote in the meeting:

1. Fetch the minutes PDF text (re-download or use a local cache if Section 6's cache is in place).
2. **Find the enumerated consent list** in the ~3000 chars before the vote block. Regex anchored on `RESOLUTION|ORDINANCE\s+\d[\d-]*` produces an ordered list of `(resolution_number, description)` tuples.
3. **Resolve each enumerated entry to an `agenda_item_id`** via:
   - Resolution number match against `agenda_items.resolution_number` (if column exists/populated)
   - Else keyword overlap against agenda item titles where `is_consent=TRUE`
4. **Reconcile against existing `vote_agenda_items` for this vote** (each branch skips rows where `is_manual=TRUE`):
   - Item in enumerated list AND already linked → flip `provisional=FALSE`, set `match_confidence=1.0`, set `match_method='consent_enumerated'`, `association_type='consent_named'`. Update `excerpt_context` with the enumerated entry text.
   - Item linked but NOT in enumerated list → set `is_active=FALSE` (ghost link, kept for audit). The actual vote will exist elsewhere in the minutes as a substantive vote and the regular matcher will pick it up.
   - Item in enumerated list but NOT previously linked → insert with `provisional=FALSE`, `confidence=1.0`, `association_type='consent_named'`.
5. For substantive votes in this meeting → safety pass: `UPDATE … SET provisional=FALSE WHERE association_type='explicit' AND is_manual=FALSE` (no-op for existing data; protects against any stray explicit link inserted as provisional).

Skip with warning-log if step 2 returns an empty list — better to keep provisional matches than blank them out on parser failure.

### 4d. Edge cases

- **Adoption never happens.** Links stay provisional; UI shows "Provisional"; data still useful.
- **Re-adoption / amendment.** Never overwrite `minutes_adopted_at`; warn-log only.
- **Adoption recorded before minutes ingested.** Sweep sets `minutes_adopted_at` on a meeting with no votes yet (no-op for the strict re-parse). When minutes are later ingested and matcher runs, matcher-side trigger fires → strict re-parse runs.

## Section 5 — API / Reader Changes

### 5a. New dataclass

`models/vote.py`:

```python
@dataclass(frozen=True)
class AgendaItemLink:
    id: int
    agenda_item_id: int
    item_number: str | None
    title: str
    is_consent: bool
    association_type: str       # 'explicit' | 'consent_named' | 'consent_implicit'
    match_method: str | None
    match_confidence: float
    excerpt_context: str | None  # populated only when include_excerpts=True
    provisional: bool
    is_manual: bool
    is_active: bool
```

### 5b. `Vote` dataclass changes

```python
@dataclass(frozen=True)
class Vote:
    id: int
    meeting_id: int
    external_id: str | None
    result: str
    yeas: int | None
    nays: int | None
    abstentions: int | None
    source: str
    confidence: str
    header_result: str | None
    needs_review: bool
    review_reason: str | None
    resolution_number: str | None
    agenda_links: list[AgendaItemLink]   # replaces singular agenda_item_id
    member_votes: list[MemberVote]

    @property
    def active_links(self) -> list[AgendaItemLink]:
        return [l for l in self.agenda_links if l.is_active]

    @property
    def is_consent_block(self) -> bool:
        return any(l.association_type.startswith('consent_') for l in self.active_links)

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

`agenda_item_id: int | None` is removed entirely (no transitional shape).

### 5c. `query.list_votes(meeting_id, *, include_excerpts=False)` rewrite

Three queries, grouped in Python:

```python
def list_votes(meeting_id: int, *, include_excerpts: bool = False) -> list[Vote]:
    excerpt_col = "vai.excerpt_context" if include_excerpts else "NULL AS excerpt_context"

    with db_cursor() as cur:
        cur.execute("SELECT * FROM votes WHERE meeting_id = %s ORDER BY id", (meeting_id,))
        votes_rows = cur.fetchall()
        if not votes_rows:
            return []
        vote_ids = [r['id'] for r in votes_rows]

        cur.execute(f"""
            SELECT vai.id, vai.vote_id, vai.agenda_item_id,
                   vai.association_type, vai.match_method, vai.match_confidence,
                   vai.provisional, vai.is_manual, vai.is_active,
                   {excerpt_col},
                   ai.item_number, ai.title, ai.is_consent
            FROM vote_agenda_items vai
            JOIN agenda_items ai ON ai.id = vai.agenda_item_id
            WHERE vai.vote_id = ANY(%s)
            ORDER BY vai.vote_id, vai.match_confidence DESC, vai.id ASC
        """, (vote_ids,))
        link_rows = cur.fetchall()

        cur.execute(
            "SELECT * FROM member_votes WHERE vote_id = ANY(%s) ORDER BY vote_id, id",
            (vote_ids,),
        )
        member_rows = cur.fetchall()

    # group in Python and return
    ...
```

Three round trips per page, no N+1. Deterministic ordering on links (`match_confidence DESC, id ASC`) ensures stable `primary_link`.

### 5d. Template changes (`web/templates/.../meeting.html`)

Two render modes per vote, driven by `vote.is_consent_block`:

- **Substantive** (single active link): show one agenda item card with the existing match-method badge.
- **Consent block** (≥1 active links, all `consent_*`): collapsed "Consent vote — covers N items" header with expand affordance. Inside, list each link with badge differentiating `consent_named` ("named in vote") from `consent_implicit` ("consent agenda default").

Pills at the vote level:
- `has_provisional_links` → "Provisional — pending council adoption"
- All links non-provisional → "Adopted" or no pill (UI design choice, not specified here)

`excluded_links` render in a small "Pulled from consent — see Vote #X" callout if the template wants to show that signal. Optional.

### 5e. What does NOT change

- `member_votes` table and `Vote.member_votes` list shape
- Search / council-member / dashboard endpoints
- `Vote.from_row()` becomes unused, deleted

## Section 6 — Backfill Plan

### Step ordering

| Step | Where | Notes |
|---|---|---|
| 1 | Migration 009 (add tables/columns) | Local + Railway |
| 2 | Code rewrite (parser, matcher, adoption, reader, templates) | PR 1 |
| 3a | Migration 010 (copy 110 existing matches) | Local first, then Railway |
| 3b | Re-parse 788 minutes PDFs locally with raw-text cache | Local only |
| 3c | Run new matcher locally (`scripts/run_vote_matching.py`) | Local only |
| 4 | Run `sweep_adoptions()` for all cities locally | Local only |
| 5 | Push to Railway via pg_dump (NOT individual UPDATEs) | Local → Railway |
| 6 | Re-enable landing page vote sections (separate spec, original 4-step plan step 3) | — |
| 7 | `railway up --detach` (separate spec, original 4-step plan step 4) | — |

Steps 6–7 are outside this spec.

### Step 3b — re-parse with cache

Update `scripts/backfill_vote_context.py` to:

1. Use the new parser (1500-char window + `raw_text`).
2. Cache each meeting's parse output to `data/minutes_cache/<meeting_id>.json` containing `{full_text, votes: [{ayes, nays, resolution_number, context, raw_text, ...}]}`.
3. On re-run, skip meetings whose cache files exist (idempotent).

The cache is the safety net: if matcher logic needs tuning later, re-run the matcher against cached text — no PDF re-download.

### Step 3c — run matcher

```bash
venv/bin/python scripts/run_vote_matching.py
```

Idempotent via `_upsert_link()`'s `ON CONFLICT DO UPDATE`. The 110 existing matches refresh in place. Expectation: match rate jumps from 1.1% to roughly 60–80%, dominated by consent-block coverage.

### Step 4 — adoption sweep

```bash
venv/bin/python -c "
from docket.services.minutes_adoption import sweep_adoptions
from docket.db import db_cursor
with db_cursor() as cur:
    cur.execute('SELECT id FROM municipalities WHERE active')
    for row in cur.fetchall():
        sweep_adoptions(row['id'])
"
```

Resolves recent adoption events; flips affected meetings to `provisional=FALSE` via the matcher-side trigger of strict re-parse.

### Step 5 — Railway sync (in order)

1. **Backup**: `pg_dump $RAILWAY_DATABASE_URL > backup-$(date +%Y%m%d).sql`
2. **Sync `votes`**: `pg_dump --table=votes --data-only $LOCAL_URL | psql $RAILWAY_URL` — refreshes `raw_text`, `match_context`, etc.
3. **Sync `vote_agenda_items`**: `pg_dump --table=vote_agenda_items $LOCAL_URL | psql $RAILWAY_URL` — straight load (new table on Railway).
4. **Targeted `minutes_adopted_at` update** for the resolved meetings: small set (<100 rows), individual UPDATEs are acceptable here per memory's constraint (don't run *bulk* UPDATEs; small targeted UPDATEs are fine).
5. **Verify**: row counts match between local and Railway for `votes`, `vote_agenda_items`, and `meetings.minutes_adopted_at` IS NOT NULL.

### Rollback story

If anything goes wrong post-deploy of PR 1:

- Migrations 009 and 010 are reversible (`python -m docket.migrations.runner --down 1` twice).
- The singular columns (`votes.agenda_item_id`, `votes.match_method`, `votes.match_confidence`) are still intact in PR 1 — they're dropped only in PR 2.
- Revert code → re-deploy → site returns to the pre-spec state with the original 110 matches.

This is exactly why PR 1 leaves the singular columns in place.

## Open Questions

None at design time — all architectural questions resolved during brainstorming. Implementation may surface tactical questions; those go to a writing-plans pass.

## Out of Scope (for explicit deferral)

- Manual link-correction admin UI (column ready, UI deferred)
- Search-votes endpoint (no FTS index on votes; not needed yet)
- Materialized vote-level FTS index (premature at 10K votes)
- Bridge view masking the new schema (skip; rewrite `query.list_votes()` directly)
- Automated minutes-adoption email/notification (data event captured; surfacing deferred)
- Cities other than Birmingham (no minutes votes elsewhere yet; this design generalizes when needed)

## Estimated Effort

- Schema migrations: minutes
- Code work: bulk of effort, broken down by writing-plans
- Re-parse 788 PDFs: hours of background CPU (run overnight)
- Matcher run: minutes
- Sweep + strict re-parse: minutes
- Railway sync: minutes

Single-engineer-day for code + half-day for backfill + verification time.
