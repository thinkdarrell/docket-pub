# Conservative Policy Badge Application — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop policy badges from appearing on items where Haiku merely suggested them. Only items with a deterministic backing signal (keyword/action_type/topic match) get an `applied` (citizen-visible) badge; LLM-only suggestions go into a `flagged` admin-review queue. Refactor #2 from the Wave 1 eval — addresses the 71% over-tag rate on `public_safety_tech_privacy` and similar over-application across all policy badges.

**Architecture:**
- New `status` column on `agenda_item_badges` with values `applied` | `flagged` | `rejected`. Default `applied` preserves legacy semantics. Reader queries filter `status = 'applied'` so flagged rows are invisible to citizens by default.
- `compute_policy_badges` becomes a stricter classifier: `both` and `deterministic` signals → `applied`; `llm` alone → `flagged`. Process badges (which are always deterministic) are unaffected.
- New admin blueprint `/admin/badge-review` lists flagged badges with approve/reject actions (single + bulk). Approve promotes to `applied`; reject sets status to `rejected` (kept for audit).
- One-shot backfill reclassifies existing `source='llm'` badges to `flagged`, pulling ~400 over-tagged rows off the public surface.

**Tech Stack:** Python 3.10+, Flask + Jinja2 + HTMX (existing admin pattern), psycopg2, pytest. No new dependencies.

**Scope check:** One subsystem — policy-badge application + admin queue. Process badges (deterministic-only) are unaffected. Phase 3 backfill / Wave 2 spend is unaffected by this change but benefits enormously from it (Wave 2's 28K items would otherwise inherit the same over-tag rate).

**Out of scope:**
- Process-badge logic changes (process badges are deterministic-only by design — no Haiku suggestion path)
- Reworking Haiku's prompt to suggest fewer badges (a separate, smaller fix could be done later — but the stricter writer makes that less urgent)
- Auto-approving common patterns ("always approve `surveillance_alpr` when keywords match") — that's already covered by the new `applied`-on-deterministic rule

---

## File Structure

**Create:**
- `src/docket/migrations/021_badge_status_column.py` — migration adding `agenda_item_badges.status` + index + audit-action enum extension. (Slot 020 was taken by `020_raise_headline_caps.py` shipped 2026-05-11 evening as a hotfix to align DB constraints with the new Pydantic caps.)
- `src/docket/web/admin_badge_review.py` — admin blueprint with the review queue routes.
- `src/docket/web/templates/admin/badge_review.html` — queue table + approve/reject buttons.
- `src/docket/web/templates/admin/_badge_review_row.html` — HTMX partial for one row (returned after approve/reject for in-place swap).
- `scripts/backfill_flag_llm_only_badges.py` — one-shot reclassifier for existing rows.
- `tests/integration/test_admin_badge_review.py` — admin queue tests.
- `tests/integration/test_backfill_flag_llm_only_badges.py` — backfill script test.

**Modify:**
- `src/docket/ai/badges_policy.py:67-115` — split `resolve_policy_badge_confidence` into a `decide_status_and_confidence(llm, det) -> tuple[str, float]` helper; update `compute_policy_badges` to return 5-tuples `(slug, confidence, source, metadata, status)`.
- `src/docket/ai/pipeline.py:391-416` — `finalize_from_rewrite`'s Phase C INSERT includes the new `status` column.
- `src/docket/services/query.py:list_items_by_badge` (line ~952) — add `AND aib.status = 'applied'` filter.
- `src/docket/services/query.py:category_kpis` — same filter.
- `src/docket/services/query.py:badge_volume_series` (line ~1519) — same filter.
- `src/docket/services/query.py:resolve_matcher_hints` — no change needed.
- `src/docket/ai/badges_process.py` — explicitly write `status='applied'` (process badges always apply; no flagging path).
- `src/docket/web/__init__.py` — register the admin_badge_review blueprint.
- `src/docket/migrations/runner.py:MIGRATIONS` — register 020.
- `tests/unit/test_badges_policy.py` — extend tests for the new return shape + status logic.
- `tests/integration/test_pipeline_e2e.py` — extend tests for `status` write in Phase C.

---

## Section A — Migration + write-path refactor

### Task A1: Migration 021 adds `agenda_item_badges.status`

**Files:**
- Create: `src/docket/migrations/021_badge_status_column.py`
- Modify: `src/docket/migrations/runner.py`

- [ ] **Step 1: Write the migration**

```python
# src/docket/migrations/021_badge_status_column.py
"""Migration 020 — agenda_item_badges.status (applied/flagged/rejected).

Refactor #2 from the Wave 1 evaluation: badges suggested by Haiku
alone (no deterministic keyword/action-type signal) need to land in a
review state instead of going straight to citizens. The new ``status``
column gates that — citizen-facing readers filter ``status='applied'``;
admin queue reads ``status='flagged'``.

Default ``'applied'`` preserves legacy semantics — every existing row
(set before the audit caught the over-tagging) keeps rendering until
the backfill script (Section E) reclassifies them.

The audit table's ``action`` CHECK constraint is widened to include
the new admin actions (``approved`` / ``rejected``) so /admin/badge-review
can record status changes through the existing audit pipeline.
"""

from __future__ import annotations

SQL_UP = r"""
ALTER TABLE agenda_item_badges
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'applied'
    CHECK (status IN ('applied', 'flagged', 'rejected'));

CREATE INDEX IF NOT EXISTS idx_agenda_item_badges_status_slug
    ON agenda_item_badges (status, city_id, badge_slug)
    WHERE status = 'flagged';

-- Widen the audit-action enum so admin status changes are recorded.
ALTER TABLE agenda_item_badges_audit
    DROP CONSTRAINT IF EXISTS agenda_item_badges_audit_action_check;
ALTER TABLE agenda_item_badges_audit
    ADD CONSTRAINT agenda_item_badges_audit_action_check
    CHECK (action IN ('added', 'removed', 'modified',
                      'flagged', 'approved', 'rejected'));
"""

SQL_DOWN = r"""
ALTER TABLE agenda_item_badges_audit
    DROP CONSTRAINT IF EXISTS agenda_item_badges_audit_action_check;
ALTER TABLE agenda_item_badges_audit
    ADD CONSTRAINT agenda_item_badges_audit_action_check
    CHECK (action IN ('added', 'removed', 'modified'));

DROP INDEX IF EXISTS idx_agenda_item_badges_status_slug;
ALTER TABLE agenda_item_badges DROP COLUMN IF EXISTS status;
"""
```

- [ ] **Step 2: Register in runner**

In `src/docket/migrations/runner.py:MIGRATIONS`, append after 019:

```python
"docket.migrations.019_backfill_source_anchors",  # if 019 is already in the list
"docket.migrations.021_badge_status_column",
```

(If 019 is not in the list yet because the source-anchor plan hasn't shipped, register 020 directly after 018.)

- [ ] **Step 3: Apply locally**

```
venv/bin/python -m docket.migrations.runner
```
Expected: `Applied migration 20`.

- [ ] **Step 4: Verify the column landed**

```
venv/bin/python -c "
from docket.db import db_cursor
with db_cursor() as cur:
    cur.execute(\"SELECT status, COUNT(*) FROM agenda_item_badges GROUP BY 1\")
    print(list(cur.fetchall()))
"
```
Expected: one row with `'applied'` and the existing count. Default backfilled every existing row.

- [ ] **Step 5: Commit**

```bash
git add src/docket/migrations/021_badge_status_column.py src/docket/migrations/runner.py
git commit -m "migrate(020): agenda_item_badges.status column for review queue

applied (default — citizen-visible) | flagged (admin review) | rejected
(archived). Default preserves legacy behavior; Section E backfill
reclassifies LLM-only badges to 'flagged' after the writer ships."
```

### Task A2: `decide_status_and_confidence` helper

**Files:**
- Modify: `src/docket/ai/badges_policy.py:67-115`
- Modify: `tests/unit/test_badges_policy.py`

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_badges_policy.py`, add a new test class:

```python
class TestDecideStatusAndConfidence:
    """The new gating function for policy-badge writes.

    Rules:
      - llm=True AND det=True  → ('applied', 1.0)   — strong signal both sides
      - llm=False AND det=True → ('applied', 0.8)   — deterministic alone is enough
      - llm=True AND det=False → ('flagged', 0.4)   — LLM alone goes to review
      - llm=False AND det=False → (None, None)      — no row written
    """

    def test_both_signals_applied_high_confidence(self):
        from docket.ai.badges_policy import decide_status_and_confidence
        assert decide_status_and_confidence(llm=True, det=True) == ('applied', 1.0)

    def test_deterministic_only_applied_medium_confidence(self):
        from docket.ai.badges_policy import decide_status_and_confidence
        assert decide_status_and_confidence(llm=False, det=True) == ('applied', 0.8)

    def test_llm_only_flagged_low_confidence(self):
        """The whole point of refactor #2: LLM-only goes to admin review,
        not directly to citizens."""
        from docket.ai.badges_policy import decide_status_and_confidence
        assert decide_status_and_confidence(llm=True, det=False) == ('flagged', 0.4)

    def test_neither_returns_none(self):
        from docket.ai.badges_policy import decide_status_and_confidence
        assert decide_status_and_confidence(llm=False, det=False) == (None, None)
```

- [ ] **Step 2: Run, confirm fails**

```
venv/bin/python -m pytest tests/unit/test_badges_policy.py::TestDecideStatusAndConfidence -v
```
Expected: 4 fails (function not defined).

- [ ] **Step 3: Implement the function**

In `src/docket/ai/badges_policy.py`, replace `resolve_policy_badge_confidence` with `decide_status_and_confidence`:

```python
def decide_status_and_confidence(
    llm: bool, det: bool,
) -> tuple[str | None, float | None]:
    """Per-badge decision: status + confidence based on which sources fired.

    Refactor #2 (2026-05-11): LLM-only suggestions no longer auto-apply
    to public-facing surfaces. They land in the admin review queue
    (``status='flagged'``) so a human decides whether to promote them.
    Deterministic signals (keyword/action-type/topic match) are trusted
    enough to apply directly.

    Returns ``(None, None)`` when no row should be written.
    """
    if llm and det:
        return ('applied', 1.0)
    if det:
        return ('applied', 0.8)
    if llm:
        return ('flagged', 0.4)
    return (None, None)


# Kept for the brief overlap while callers migrate — same signature as before,
# routes through the new function. Delete once compute_policy_badges is the
# only caller (Task A3).
def resolve_policy_badge_confidence(
    slug: str, llm_suggested: bool, deterministic_match: bool,
) -> float | None:
    _, conf = decide_status_and_confidence(llm=llm_suggested, det=deterministic_match)
    return conf
```

- [ ] **Step 4: Run tests, confirm pass**

```
venv/bin/python -m pytest tests/unit/test_badges_policy.py -v
```
Expected: all pass including the new 4.

- [ ] **Step 5: Commit**

```bash
git add src/docket/ai/badges_policy.py tests/unit/test_badges_policy.py
git commit -m "feat(badges): decide_status_and_confidence helper

LLM-only suggestions go to status='flagged' (admin review); det signals
go to status='applied' (citizen-visible). Old resolve_policy_badge_confidence
kept as a temporary shim — removed once compute_policy_badges is the
sole caller (Task A3)."
```

### Task A3: `compute_policy_badges` returns 5-tuples

**Files:**
- Modify: `src/docket/ai/badges_policy.py:88-117`
- Modify: `tests/unit/test_badges_policy.py`

- [ ] **Step 1: Failing test**

```python
class TestComputePolicyBadgesReturnsStatus:
    def test_llm_only_emits_flagged_row(self, monkeypatch):
        """When Haiku suggests a badge but no deterministic signal fires,
        the row carries status='flagged' so it won't render publicly."""
        from docket.ai.badges_policy import compute_policy_badges
        # ... build item/facts/rewrite where Haiku suggests 'housing_stability'
        # but no keyword/action_type matches ...
        # mock list_enabled_policy_badges to return ['housing_stability']
        # ... assert returned tuple is (slug, 0.4, 'llm', metadata, 'flagged')
        pass  # full test body fills in based on existing test fixtures in
              # tests/unit/test_badges_policy.py — re-use the
              # _enabled_policy_badge / _make_item helpers there.

    def test_both_signals_emit_applied_row(self):
        """Deterministic + LLM both fire → status='applied'."""
        pass  # similar shape — full body modeled after the existing
              # "test_compute_policy_badges_both" test.

    def test_deterministic_only_emits_applied_row(self):
        """Deterministic alone is enough for applied status."""
        pass
```

Look at the existing tests in `test_badges_policy.py` for the fixture / mock pattern. The placeholder bodies above pin the contract; fill them in with the same helpers the existing `compute_policy_badges` tests use.

- [ ] **Step 2: Update `compute_policy_badges` to emit the status**

```python
def compute_policy_badges(item, facts, rewrite, city_id: int):
    """Returns list of (slug, confidence, source, matching_metadata, status) tuples.

    Status logic (refactor #2):
      - 'applied'  — deterministic backing exists (citizen-visible)
      - 'flagged'  — LLM-only suggestion (admin review only)
    """
    from docket.services.badges import list_enabled_policy_badges

    enabled = list_enabled_policy_badges(city_id)
    out = []

    suggested = set(rewrite.suggested_badge_slugs or [])
    suggested &= {b.slug for b in enabled}

    for badge in enabled:
        llm = badge.slug in suggested
        det, det_metadata = deterministic_policy_match(
            item, facts, rewrite, badge.matcher_hints,
        )
        status, conf = decide_status_and_confidence(llm=llm, det=det)
        if status is None:
            continue

        if llm and det:
            metadata = {'both': True, **det_metadata}
        elif llm:
            metadata = {'llm_only': True}
        else:
            metadata = det_metadata

        out.append((badge.slug, conf, resolve_source(llm, det), metadata, status))

    return out
```

- [ ] **Step 3: Run tests, confirm pass**

```
venv/bin/python -m pytest tests/unit/test_badges_policy.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/docket/ai/badges_policy.py tests/unit/test_badges_policy.py
git commit -m "feat(badges): compute_policy_badges returns 5-tuples with status

Section A.3 of the conservative-policy-badges plan. Callers updated in
the next task (pipeline.finalize_from_rewrite Phase C INSERT)."
```

### Task A4: `pipeline.finalize_from_rewrite` writes the status

**Files:**
- Modify: `src/docket/ai/pipeline.py:391-416` (the Phase C INSERT loops)
- Modify: `tests/integration/test_pipeline_e2e.py`

- [ ] **Step 1: Failing test**

In `tests/integration/test_pipeline_e2e.py`, after the existing happy-path test:

```python
def test_pipeline_writes_status_applied_when_deterministic_backing(bag, monkeypatch):
    """A badge backed by a deterministic keyword/action-type match
    lands at status='applied' (citizen-visible)."""
    # Use the existing test pattern — substantive item, Stage 1 facts
    # with action_type matching one of the policy badges, Stage 2
    # suggesting the same badge. Then read the agenda_item_badges row
    # and assert status='applied'.
    # ... full body modeled after test_process_item_happy_path_completes_and_writes_badges


def test_pipeline_writes_status_flagged_when_llm_only(bag, monkeypatch):
    """When Stage 2 suggests a badge with no deterministic backing,
    the badge row lands at status='flagged' so it's invisible to
    citizens until an admin promotes it."""
    # Force the matcher to return (False, {}) so only the LLM signal fires.
    # Then assert the resulting badge row has status='flagged'.
```

- [ ] **Step 2: Update the INSERT loops in `finalize_from_rewrite`**

In `src/docket/ai/pipeline.py`, find the policy-badges loop in Phase C (around line ~405). Change:

```python
        for slug, conf, source, metadata in compute_policy_badges(
            item, facts, rewrite, item.city_id,
        ):
            cur.execute(
                """
                INSERT INTO agenda_item_badges
                  (agenda_item_id, city_id, badge_slug, kind, confidence,
                   source, matching_metadata)
                VALUES (%s, %s, %s, 'policy', %s, %s, %s::jsonb)
                ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING
                """,
                (item.id, item.city_id, slug, conf, source, json.dumps(metadata)),
            )
```

to:

```python
        for slug, conf, source, metadata, status in compute_policy_badges(
            item, facts, rewrite, item.city_id,
        ):
            cur.execute(
                """
                INSERT INTO agenda_item_badges
                  (agenda_item_id, city_id, badge_slug, kind, confidence,
                   source, matching_metadata, status)
                VALUES (%s, %s, %s, 'policy', %s, %s, %s::jsonb, %s)
                ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING
                """,
                (item.id, item.city_id, slug, conf, source, json.dumps(metadata), status),
            )
```

Also update the process-badges loop just above it to write `status='applied'` explicitly (process badges always apply):

```python
        for slug, conf in compute_on_write_process_badges(...):
            cur.execute(
                """
                INSERT INTO agenda_item_badges
                  (agenda_item_id, city_id, badge_slug, kind, confidence,
                   source, matching_metadata, status)
                VALUES (%s, %s, %s, 'process', %s, 'deterministic', '{}'::jsonb, 'applied')
                ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING
                """,
                (item.id, item.city_id, slug, conf),
            )
```

- [ ] **Step 3: Verify batch ingest path catches up**

`docket.ai.batch_ingest._ingest_stage2_message` calls `finalize_from_rewrite` — no separate INSERT path, so the update above covers both sync and batch ingest. No batch_ingest changes needed. (Confirm by reading the module and checking that no `agenda_item_badges` INSERT lives there.)

- [ ] **Step 4: Run tests**

```
venv/bin/python -m pytest tests/integration/test_pipeline_e2e.py tests/unit/test_badges_policy.py tests/unit/test_batch_ingest.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/docket/ai/pipeline.py tests/integration/test_pipeline_e2e.py
git commit -m "feat(pipeline): finalize_from_rewrite writes badge status

Process badges always land status='applied'; policy badges land
'applied' when deterministic backing exists, 'flagged' for LLM-only
suggestions (admin review queue)."
```

### Task A5: Open + merge PR for Section A

```bash
git push -u origin feat/badge-status-write-path
gh pr create --title "feat(badges): policy-badge status column + flagged for LLM-only" --body "Section A of conservative-policy-badges plan: migration 021, decide_status_and_confidence helper, 5-tuple return from compute_policy_badges, status threaded through pipeline.finalize_from_rewrite Phase C INSERT.

Reader queries still ignore status (Section C lands those). Backfill of existing LLM-only rows still pending (Section E). Net effect after this PR: new items get status correctly; existing rows unchanged."
```

After merge: deploy `worker` + `docket-web`. Wave 1 v4 results (still being measured at this writing) will already have landed under the OLD rules; that's fine — Section E backfill picks them up.

---

## Section B — Reader queries filter to `status='applied'`

### Task B1: Update `list_items_by_badge` to filter on status

**Files:**
- Modify: `src/docket/services/query.py:949` (the WHERE clause in the SELECT)
- Modify: `tests/integration/test_list_items_by_badge.py`

- [ ] **Step 1: Failing test**

In `tests/integration/test_list_items_by_badge.py`, after the existing tests:

```python
def test_flagged_badges_excluded_from_list_items_by_badge(bag):
    """Items whose only badge link is status='flagged' should NOT appear
    in the citizen-facing listing. Section B contract."""
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    a = bag.add_item(m, title="Genuinely about housing", significance_score=5)
    b = bag.add_item(m, title="LLM mis-suggested housing", significance_score=5)

    # `a` gets a deterministic match → status='applied'
    bag.add_badge(a, bag.city_id, "housing_stability", confidence=1.0,
                  status='applied')
    # `b` is the over-tag case — LLM-only → status='flagged'
    bag.add_badge(b, bag.city_id, "housing_stability", confidence=0.4,
                  source='llm', status='flagged')

    items = list_items_by_badge(bag.city_id, "housing_stability")
    ids = [it.id for it in items]
    assert a in ids
    assert b not in ids
```

The `bag.add_badge` fixture needs a `status` kwarg — extend it if not already present.

- [ ] **Step 2: Run, confirm fails** (b is currently returned by the reader because filter doesn't exist yet)

- [ ] **Step 3: Update `list_items_by_badge` WHERE clause**

In `src/docket/services/query.py` inside `list_items_by_badge`, find the WHERE:

```sql
        WHERE aib.city_id = %s
          AND aib.badge_slug = %s
          AND aib.confidence >= %s
          AND ai.processing_status = 'completed'
```

Add the status filter:

```sql
        WHERE aib.city_id = %s
          AND aib.badge_slug = %s
          AND aib.confidence >= %s
          AND aib.status = 'applied'                  -- Section B: hide flagged/rejected
          AND ai.processing_status = 'completed'
```

- [ ] **Step 4: Run tests**

```
venv/bin/python -m pytest tests/integration/test_list_items_by_badge.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/docket/services/query.py tests/integration/test_list_items_by_badge.py
git commit -m "feat(query): list_items_by_badge filters to status='applied' only"
```

### Task B2: Update `category_kpis` to filter on status

**Files:**
- Modify: `src/docket/services/query.py:category_kpis` (find via grep)
- Modify: `tests/integration/test_category_landing.py`

- [ ] **Step 1: Failing test**

```python
def test_category_kpis_excludes_flagged_badges(bag):
    """The category landing 'X items this year' counter should only
    reflect applied badges. Otherwise the headline number is misleading."""
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    a = bag.add_item(m, title="Real housing item", significance_score=5,
                     dollars_amount=50_000)
    b = bag.add_item(m, title="Mis-tagged item", significance_score=5,
                     dollars_amount=50_000)
    bag.add_badge(a, bag.city_id, "housing_stability", confidence=1.0,
                  status='applied')
    bag.add_badge(b, bag.city_id, "housing_stability", confidence=0.4,
                  source='llm', status='flagged')

    kpis = category_kpis(bag.city_id, "housing_stability", year=2026)
    assert kpis['item_count'] == 1
```

- [ ] **Step 2: Update `category_kpis`**

In `src/docket/services/query.py:category_kpis` (search for the function), add `AND aib.status = 'applied'` to its WHERE clauses. There may be multiple SELECTs in the function — update every one that joins `agenda_item_badges`.

- [ ] **Step 3: Run tests + commit**

```bash
git add src/docket/services/query.py tests/integration/test_category_landing.py
git commit -m "feat(query): category_kpis filters to applied badges only"
```

### Task B3: Update `badge_volume_series` + materialized view

**Files:**
- Modify: `src/docket/services/query.py:badge_volume_series` (around line 1519)
- Modify: `src/docket/migrations/013_impact_first_refactor.py` mv definition — or new migration 021 to REFRESH after a definition change.

Materialized view `mv_badge_volume_monthly` was defined in migration 013. If it joins `agenda_item_badges` without a status filter, it'll inflate the timeline with flagged badges. Best approach: redefine the view to filter `status='applied'` and add a migration that does `DROP MATERIALIZED VIEW + CREATE` with the new shape, plus a manual `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_badge_volume_monthly`.

- [ ] **Step 1: Read the existing MV definition**

```bash
grep -n "mv_badge_volume_monthly" src/docket/migrations/013_impact_first_refactor.py
```

Note the CREATE MATERIALIZED VIEW block — its SELECT shape.

- [ ] **Step 2: Write migration 021**

```python
# src/docket/migrations/021_badge_mv_status_filter.py
"""Migration 021 — mv_badge_volume_monthly filters on status='applied'.

Counterpart to migration 021 + Section B of the conservative-badges plan.
The materialized view's timeline counts now reflect only badges visible
to citizens (status='applied'), not the flagged-in-review backlog.
"""

from __future__ import annotations

SQL_UP = r"""
DROP MATERIALIZED VIEW IF EXISTS mv_badge_volume_monthly;
CREATE MATERIALIZED VIEW mv_badge_volume_monthly AS
-- COPY the original SELECT body from migration 013, add
-- ``AND aib.status = 'applied'`` to its WHERE.
-- The full SELECT is too long to repeat here; copy from
-- src/docket/migrations/013_impact_first_refactor.py and add the
-- filter line.
SELECT ...
WITH NO DATA;

REFRESH MATERIALIZED VIEW mv_badge_volume_monthly;
"""

SQL_DOWN = r"""
-- Roll back to the pre-021 definition (copy original SELECT from 013).
DROP MATERIALIZED VIEW IF EXISTS mv_badge_volume_monthly;
CREATE MATERIALIZED VIEW mv_badge_volume_monthly AS
SELECT ...   -- original 013 shape
WITH NO DATA;
REFRESH MATERIALIZED VIEW mv_badge_volume_monthly;
"""
```

When implementing, run:
```bash
grep -A 50 "CREATE MATERIALIZED VIEW mv_badge_volume_monthly" src/docket/migrations/013_impact_first_refactor.py
```
to get the original SELECT body, copy verbatim, add one WHERE line.

- [ ] **Step 3: Update `badge_volume_series` reader (if it queries the MV — likely does)**

If `badge_volume_series` queries `mv_badge_volume_monthly`, the filter is already in the MV — no app code change needed. If it queries `agenda_item_badges` directly, add `AND aib.status = 'applied'` like the other readers.

- [ ] **Step 4: Run integration tests**

The MV refresh happens during migration apply. After apply:

```bash
venv/bin/python -m pytest tests/integration/test_badge_volume_series.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/docket/migrations/021_badge_mv_status_filter.py src/docket/services/query.py src/docket/migrations/runner.py
git commit -m "feat(badges): mv_badge_volume_monthly filters on status='applied'"
```

### Task B4: PR + merge Section B

```bash
git push -u origin feat/badge-status-readers
gh pr create --title "feat(query): badge readers filter to status='applied'" --body "Section B of conservative-policy-badges. Citizens see only applied badges. Flagged rows stay in DB for admin review (Section D) — invisible to public surfaces."
```

After merge: deploy `docket-web`. Citizens immediately see fewer (correct) badges — but until Section E backfill runs, existing LLM-only badges are still `status='applied'` in the DB, so visible impact is zero until Section E ships.

---

## Section D — Admin review queue (`/admin/badge-review`)

> *Section C in this plan's letter-numbering is reserved for "Section C" parity with the source-anchor plan; we skip it here since this plan has no separate backfill-aware reader work beyond Section B.*

### Task D1: Admin blueprint shell

**Files:**
- Create: `src/docket/web/admin_badge_review.py`
- Create: `src/docket/web/templates/admin/badge_review.html`
- Modify: `src/docket/web/__init__.py`
- Test: `tests/integration/test_admin_badge_review.py`

- [ ] **Step 1: Failing test — list view requires login**

```python
# tests/integration/test_admin_badge_review.py
def test_review_view_requires_login(flask_app_client):
    rv = flask_app_client.get('/admin/badge-review')
    assert rv.status_code in (302, 401)


def test_review_view_lists_flagged_badges(admin_flask_app_client, bag):
    """The queue lists agenda_item_badges rows with status='flagged',
    one row per badge with item title + slug + city + suggested-source."""
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    item = bag.add_item(m, title="Mis-tagged housing item",
                        significance_score=5)
    bag.add_badge(item, bag.city_id, "housing_stability",
                  status='flagged', source='llm', confidence=0.4)

    rv = admin_flask_app_client.get('/admin/badge-review')
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert 'housing_stability' in body
    assert 'Mis-tagged housing item' in body
```

Look at `tests/integration/test_admin_*.py` for the existing admin-client fixture pattern.

- [ ] **Step 2: Implement the blueprint**

```python
# src/docket/web/admin_badge_review.py
"""Admin review queue for badges Haiku suggested but no deterministic
signal backed.

Refactor #2: rather than auto-applying LLM-only badge suggestions to
citizen-facing surfaces (which produced a 71% over-tag rate on
public_safety_tech_privacy in Wave 1), suggestions land in
status='flagged' and require admin approval to be promoted to
'applied'. This blueprint exposes the queue + approve/reject actions.

Spec: docs/superpowers/plans/2026-05-11-conservative-policy-badges.md
"""

from __future__ import annotations

from flask import Blueprint, abort, render_template, request, session

from docket.db import db, db_cursor
from docket.web.auth import login_required

bp = Blueprint("admin_badge_review", __name__, url_prefix="/admin")

PER_PAGE = 50


@bp.route("/badge-review")
@login_required
def review_queue():
    """List badges with status='flagged' for human review."""
    badge_slug_filter = request.args.get("slug")
    city_id_filter = request.args.get("city_id", type=int)

    sql = """
        SELECT b.id AS badge_id,
               b.agenda_item_id, b.city_id, b.badge_slug,
               b.confidence::float, b.matching_metadata, b.detected_at,
               ai.title AS item_title,
               m.meeting_date,
               muni.name AS city_name,
               muni.slug AS city_slug
          FROM agenda_item_badges b
          JOIN agenda_items ai     ON ai.id = b.agenda_item_id
          JOIN meetings m          ON m.id = ai.meeting_id
          JOIN municipalities muni ON muni.id = b.city_id
         WHERE b.status = 'flagged'
    """
    params: list = []
    if badge_slug_filter:
        sql += " AND b.badge_slug = %s"
        params.append(badge_slug_filter)
    if city_id_filter:
        sql += " AND b.city_id = %s"
        params.append(city_id_filter)
    sql += " ORDER BY b.detected_at DESC LIMIT %s"
    params.append(PER_PAGE)

    with db_cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())

    return render_template(
        "admin/badge_review.html",
        flagged_badges=rows,
        badge_slug_filter=badge_slug_filter,
        city_id_filter=city_id_filter,
    )
```

Template:

```jinja
{# src/docket/web/templates/admin/badge_review.html #}
{% extends "base.html" %}
{% block content %}
<section class="admin-panel">
  <h1>Badge review queue</h1>
  <p class="t-meta">
    Badges Haiku suggested but no deterministic signal (keyword /
    action-type / topic) confirmed. Approve to promote to
    citizen-facing; reject to archive. {{ flagged_badges | length }} shown.
  </p>

  {% if flagged_badges %}
  <table class="admin-table">
    <thead>
      <tr>
        <th>Item</th><th>Badge</th><th>City</th>
        <th>Meeting</th><th>Action</th>
      </tr>
    </thead>
    <tbody>
      {% for row in flagged_badges %}
        {% include 'admin/_badge_review_row.html' %}
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p>No flagged badges. Queue empty.</p>
  {% endif %}
</section>
{% endblock %}
```

Row partial:

```jinja
{# src/docket/web/templates/admin/_badge_review_row.html #}
<tr id="badge-row-{{ row.badge_id }}">
  <td>
    <a href="/al/{{ row.city_slug }}/items/{{ row.agenda_item_id }}/">
      {{ row.item_title | truncate(60) }}
    </a>
  </td>
  <td><code>{{ row.badge_slug }}</code></td>
  <td>{{ row.city_name }}</td>
  <td>{{ row.meeting_date.strftime('%Y-%m-%d') }}</td>
  <td>
    <button hx-post="/admin/badge-review/{{ row.badge_id }}/approve"
            hx-target="#badge-row-{{ row.badge_id }}"
            hx-swap="outerHTML">Approve</button>
    <button hx-post="/admin/badge-review/{{ row.badge_id }}/reject"
            hx-target="#badge-row-{{ row.badge_id }}"
            hx-swap="outerHTML">Reject</button>
  </td>
</tr>
```

Register blueprint in `src/docket/web/__init__.py:create_app`:

```python
from docket.web.admin_badge_review import bp as admin_badge_review_bp
app.register_blueprint(admin_badge_review_bp)
```

- [ ] **Step 3: Run tests + commit**

```bash
git add src/docket/web/admin_badge_review.py src/docket/web/templates/admin/ src/docket/web/__init__.py tests/integration/test_admin_badge_review.py
git commit -m "feat(admin): /admin/badge-review queue lists flagged policy badges"
```

### Task D2: Approve / reject actions

**Files:**
- Modify: `src/docket/web/admin_badge_review.py`
- Modify: `tests/integration/test_admin_badge_review.py`

- [ ] **Step 1: Failing tests**

```python
def test_approve_promotes_badge_to_applied(admin_flask_app_client, bag):
    """POST /admin/badge-review/<id>/approve sets status='applied' and
    writes an audit row with action='approved'."""
    # seed a flagged badge, POST approve, assert DB state
    pass


def test_reject_marks_badge_rejected(admin_flask_app_client, bag):
    """POST /admin/badge-review/<id>/reject sets status='rejected'."""
    pass


def test_approve_returns_partial_for_htmx_swap(admin_flask_app_client, bag):
    """The response body is the row partial with the row gone (swapped
    out to empty) so HTMX can replace the row in place."""
    # POST approve, check response is the (empty) row body or a removed marker
    pass
```

- [ ] **Step 2: Implement the routes**

In `src/docket/web/admin_badge_review.py`:

```python
@bp.route("/badge-review/<int:badge_id>/approve", methods=["POST"])
@login_required
def approve_badge(badge_id: int):
    return _set_status_and_audit(badge_id, "applied", "approved")


@bp.route("/badge-review/<int:badge_id>/reject", methods=["POST"])
@login_required
def reject_badge(badge_id: int):
    return _set_status_and_audit(badge_id, "rejected", "rejected")


def _set_status_and_audit(badge_id: int, new_status: str, audit_action: str):
    """Atomic status change + audit row write."""
    actor = session.get("admin_user", "unknown")
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agenda_item_badges
               SET status = %s
             WHERE id = %s
             RETURNING agenda_item_id, badge_slug, status
            """,
            (new_status, badge_id),
        )
        row = cur.fetchone()
        if row is None:
            abort(404)
        agenda_item_id, badge_slug, _ = row
        cur.execute(
            """
            INSERT INTO agenda_item_badges_audit
              (agenda_item_id, badge_slug, action, actor, actor_role, reason)
            VALUES (%s, %s, %s, %s, 'admin', %s)
            """,
            (agenda_item_id, badge_slug, audit_action, actor,
             f"admin review queue: {audit_action}"),
        )
    # Return empty body so HTMX swap removes the row from the queue.
    return ("", 200)
```

- [ ] **Step 3: Run tests + commit**

```bash
git add src/docket/web/admin_badge_review.py tests/integration/test_admin_badge_review.py
git commit -m "feat(admin): approve/reject actions on /admin/badge-review

Status change is atomic with an audit row insert. HTMX swap returns
empty body so the row vanishes from the queue in-place."
```

### Task D3: PR + merge Section D

```bash
git push -u origin feat/admin-badge-review
gh pr create --title "feat(admin): /admin/badge-review queue (Section D)"
```

After merge: deploy `docket-web`. Admins can now approve/reject; nothing visible to citizens changes until Section E backfill.

---

## Section E — Backfill: reclassify existing LLM-only badges to `flagged`

### Task E1: Backfill script

**Files:**
- Create: `scripts/backfill_flag_llm_only_badges.py`
- Test: `tests/integration/test_backfill_flag_llm_only_badges.py`

- [ ] **Step 1: Failing test**

```python
# tests/integration/test_backfill_flag_llm_only_badges.py
def test_backfill_reclassifies_llm_only_to_flagged(local_db_with_seed):
    """source='llm' + status='applied' + no deterministic backing
    rows get status='flagged'. Other rows untouched."""
    # seed:
    #   - row A: source='deterministic', status='applied' → unchanged
    #   - row B: source='llm', status='applied'           → flagged
    #   - row C: source='both', status='applied'          → unchanged
    #   - row D: source='manual', status='applied'        → unchanged (manual = trusted)
    # run the script, assert final statuses
    pass
```

- [ ] **Step 2: Implement**

```python
# scripts/backfill_flag_llm_only_badges.py
"""One-shot: reclassify existing LLM-only badges to status='flagged'.

Refactor #2 — companion to the new writer in src/docket/ai/badges_policy.py.
The writer now classifies LLM-only suggestions as 'flagged' at INSERT
time; this script catches up the rows that landed under the old
auto-apply rules. After running, all source='llm' rows that landed
without deterministic backing (no 'both' source) live in the admin
review queue.

Idempotent: only touches rows where (source='llm' AND status='applied').
Re-running has no effect — those rows now have status='flagged'.

Run from project root:
    venv/bin/python scripts/backfill_flag_llm_only_badges.py
"""

from __future__ import annotations

import os
import subprocess
import sys

import psycopg2


def _resolve_db_url() -> str:
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    out = subprocess.check_output(
        ["railway", "variables", "--service", "docket-web", "--kv"], text=True,
    )
    for line in out.splitlines():
        if line.startswith("DATABASE_PUBLIC_URL="):
            return line.split("=", 1)[1]
    sys.exit("DATABASE_URL not resolvable")


def main() -> int:
    conn = psycopg2.connect(_resolve_db_url())
    cur = conn.cursor()

    cur.execute(
        """
        SELECT source, status, COUNT(*)
          FROM agenda_item_badges
         WHERE kind = 'policy'
         GROUP BY source, status
         ORDER BY source, status
        """
    )
    print("Pre-backfill breakdown (policy badges):")
    for row in cur.fetchall():
        print(f"  {row}")

    cur.execute(
        """
        UPDATE agenda_item_badges
           SET status = 'flagged'
         WHERE kind = 'policy'
           AND source = 'llm'
           AND status = 'applied'
        """
    )
    n_flagged = cur.rowcount
    print(f"\nFlagged {n_flagged} previously-applied LLM-only policy badges.")

    # Audit rows so the change is recorded.
    cur.execute(
        """
        INSERT INTO agenda_item_badges_audit
          (agenda_item_id, badge_slug, action, actor, actor_role, reason)
        SELECT agenda_item_id, badge_slug, 'flagged',
               'backfill_flag_llm_only_badges.py', 'cron',
               'Refactor #2 backfill: LLM-only suggestions moved to review queue'
          FROM agenda_item_badges
         WHERE kind = 'policy'
           AND source = 'llm'
           AND status = 'flagged'
        """
    )
    conn.commit()
    print(f"Wrote {n_flagged} audit rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run test + commit**

```bash
git add scripts/backfill_flag_llm_only_badges.py tests/integration/test_backfill_flag_llm_only_badges.py
git commit -m "feat(scripts): backfill_flag_llm_only_badges.py reclassifier"
```

### Task E2: Run the backfill on Railway

- [ ] **Step 1: Pre-count**

```bash
DATABASE_URL=$(railway variables --service docket-web --kv | grep '^DATABASE_PUBLIC_URL=' | cut -d= -f2-) \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT source, COUNT(*) FROM agenda_item_badges
 WHERE kind = 'policy' AND status = 'applied'
 GROUP BY source ORDER BY 2 DESC;
"
```
Record the `source='llm'` count — that's how many rows will move to flagged.

- [ ] **Step 2: Run the script in-VPC**

```bash
railway ssh --service worker "cd /app && python scripts/backfill_flag_llm_only_badges.py"
```

Many small UPDATEs over the public proxy are slow; in-VPC is fast.

- [ ] **Step 3: Verify**

```bash
DATABASE_URL=$DATABASE_PUBLIC_URL /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT kind, source, status, COUNT(*) FROM agenda_item_badges
 GROUP BY kind, source, status ORDER BY kind, status, source;
"
```

Expected: every (kind=policy, source=llm, status=applied) row from before now appears under (kind=policy, source=llm, status=flagged).

- [ ] **Step 4: Refresh the volume-timeline MV**

If Section B Task B3 redefined the MV with the status filter, refresh it now so the citizen-facing timelines reflect the reclassification:

```bash
railway ssh --service worker "cd /app && python -c \"
from docket.db import db_cursor
with db_cursor() as cur:
    cur.execute('REFRESH MATERIALIZED VIEW CONCURRENTLY mv_badge_volume_monthly')
print('MV refreshed')
\""
```

- [ ] **Step 5: Spot-check**

Open https://docket.pub/al/birmingham/public_safety_tech_privacy in a browser. Item count should have dropped from ~435 to closer to 30 (the deterministic-keyword-match count).

Open `/admin/badge-review` — should show several hundred newly-flagged rows for human triage.

---

## Self-Review

**Spec coverage** (cross-referenced to the eval findings + user principles):
- ✅ "Rather flag than over-tag" — Section A.2 decision rule; Section A.4 writer; Section E backfill.
- ✅ "Public_safety_tech_privacy on 71% is too broad" — Section E backfill drops it to deterministic-only.
- ✅ "Admin queue to triage" — Section D.
- ✅ Citizen-facing surfaces respect the new status — Section B.
- ✅ Audit trail preserved — Task D2 writes audit row on every approve/reject.
- ✅ Process badges unaffected — Task A.4 sets them to status='applied' explicitly; they have no LLM path.

**Placeholder scan:**
- Section D Task D1 / D2 / E1 have test bodies that say `pass` with adjacent comments indicating which existing fixtures to reuse. That's intentional — the existing test fixtures (`bag`, `flask_app_client`, etc.) are project-specific and the executor needs to look them up rather than have me invent fixture names. Each placeholder explicitly names the existing test file to model after.
- Section B Task B3 has the migration's SELECT body referenced as "copy from 013" — executor needs to actually copy the verbatim SELECT. Documented inline so it isn't forgotten.

**Type consistency:**
- `decide_status_and_confidence(llm: bool, det: bool) -> tuple[str | None, float | None]` — used the same way in A.2 (definition) and A.3 (caller).
- `compute_policy_badges` returns 5-tuples `(slug, confidence, source, matching_metadata, status)` — pinned in A.3, used in A.4.
- DB column `agenda_item_badges.status TEXT NOT NULL DEFAULT 'applied'` — created in A.1, referenced consistently in B / D / E.
- HTMX swap returns `("", 200)` empty body — D.2 spec matches the row-partial test in D.1.

**Section ordering / dependency:**
1. A — schema + writer (independent; new badges land correctly afterward, no existing data changed)
2. B — readers (citizen surfaces start filtering applied-only; no visible change until E runs)
3. D — admin queue (operator can review, queue empty until E)
4. E — backfill (reclassifies ~400 over-tagged rows → admin queue + visible badge-count drop)

Five PRs, ordered. Each is independently deployable. Section D can ship before B/E if a preview of the empty queue is wanted, but B + E together are what make the impact citizen-visible.

---

## What ships at the end

- New writes: policy badges land `applied` only when there's a deterministic signal; LLM-only suggestions land `flagged`.
- Existing data: ~400 over-applied LLM-only badges move to `flagged` via backfill, removing them from public surfaces.
- Operators: `/admin/badge-review` queue for human triage. Approve / reject with audit trail.
- Wave 2 (~28K items) will inherit the conservative rules from the start — no post-hoc cleanup.
- `public_safety_tech_privacy` drops from 71% to ~5% application rate.

## Follow-up tickets (NOT in this plan)

- Per-pattern auto-approve rules (e.g. "always approve `surveillance_alpr` when `flock` appears in the title even when LLM didn't suggest it"). Would extend `deterministic_policy_match` with a "promote to applied" pattern set per badge.
- Bulk approve/reject UI in admin queue (currently single-row only).
- Tighten Haiku's prompt to suggest fewer badges (additive — strictness on the writer side keeps us safe regardless of prompt quality).
