# Category-landing context + source-anchor writer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Smart Brevity Cards on category-landing pages (e.g. `/al/birmingham/housing_stability/`) show meeting date, item-number reference, and a working "View Source" link. Closes three gaps left over from Phase 2: category landing query didn't fetch `m.meeting_date`, card templates don't render `item_number`, and nothing in the codebase writes `agenda_items.source_anchor`.

**Architecture:**
- **Section A (display only):** add `m.meeting_date` to `list_items_by_badge` projection + a slim meta strip (date + item reference) on Smart Brevity Cards, gated by a `show_meeting_context` flag so meeting-detail (where the date is in the page chrome) stays unchanged.
- **Section B (write path):** extend `RawAgendaItem` with `source_anchor: SourceAnchor | None` (the Pydantic model defined in Section D). Adapters populate it from data they already have. `services/ingest.py` writes it to `agenda_items.source_anchor` in the INSERT. A pure helper module `services/source_anchors.py` owns the derivation logic so adapters and the backfill script use one source of truth.
- **Section C (backfill):** one-shot script that walks every `agenda_items` row with `source_anchor IS NULL`, joins the parent meeting, runs the same derivation, batched UPDATEs back. Idempotent. Safe to re-run.
- **Section D (hardening — Layer 1):** Pydantic `SourceAnchor` model becomes the spine of every write. Replaces the opaque `dict | None` everywhere. Catches typos in `type`, missing `url`, and URLs that would fail the render-side allowlist gate — at WRITE time, not silently three weeks later.
- **Section E (hardening — Layer 2):** CI coverage assertion that each adapter's happy-path fixture produces a non-None anchor + `/admin/source-anchor-coverage` view showing per-municipality coverage % + a structured log line every time `source_anchor_button.html` falls through (no link rendered). Makes silent regressions visible.

**Tech Stack:** Python 3.10+, Flask + Jinja2, psycopg2, pytest. No new packages.

**Scope check:** Three loosely-coupled changes; each is shippable on its own and rolls back independently. Decomposed into three sub-sections in this single plan because they share enough context (the `source_anchor` JSONB shape, the category-landing template) that splitting them would force the reader to flip between files. Each section ends with a commit/PR boundary so they can ship serially.

**Out of scope:**
- Haiku over-suggesting policy badges on irrelevant items (separate prompt-tuning ticket).
- PDF page-number / bbox anchors for minutes-derived items. The current anchor button template already handles `{type: 'pdf', page: N}`; a follow-up could derive page numbers from minutes parser output. This plan ships HTML + video anchors only.
- Sub-item HTML anchors (e.g. `#item-3`). Granicus / CivicClerk agenda pages don't have stable per-item DOM anchors today.

---

## File Structure

**Create:**
- `src/docket/models/source_anchor.py` — Pydantic `SourceAnchor` model with type/url/locator fields + URL-safety validator. **(Section D)**
- `tests/unit/test_source_anchor_model.py` — Pydantic validation tests. **(Section D)**
- `src/docket/services/source_anchors.py` — pure derivation function (no I/O), returns `SourceAnchor | None`.
- `tests/unit/test_source_anchors.py` — unit tests for the derivation.
- `scripts/backfill_source_anchors.py` — one-shot ops script for existing rows.
- `tests/integration/test_backfill_source_anchors.py` — integration test that hits a local DB.
- `src/docket/migrations/019_backfill_source_anchors.py` — sentinel migration noting the manual backfill.
- `src/docket/web/admin_coverage.py` — admin blueprint with `/admin/source-anchor-coverage` view. **(Section E)**
- `src/docket/web/templates/admin/source_anchor_coverage.html` — coverage view template. **(Section E)**
- `tests/integration/test_adapter_source_anchor_coverage.py` — CI test that every adapter's happy-path fixture produces a non-None anchor. **(Section E)**

**Modify:**
- `src/docket/models/protocol.py` — add `source_anchor: SourceAnchor | None` to `RawAgendaItem`.
- `src/docket/adapters/granicus.py` — populate `source_anchor` in `fetch_agenda_items`.
- `src/docket/adapters/civicclerk.py` — same.
- `src/docket/adapters/generic_cms.py` — same.
- `src/docket/services/ingest.py:222-241` — write `source_anchor` in the INSERT.
- `src/docket/services/query.py:list_items_by_badge` — add `m.meeting_date` to projection.
- `src/docket/web/public.py:category_landing` — pass `show_meeting_context=True` to the template.
- `src/docket/web/templates/partials/card_smart_brevity.html` — render meta strip when flag set.
- `src/docket/web/templates/partials/card_v2_fallback.html` — same.
- `src/docket/web/templates/partials/card_pending.html` — same.
- `src/docket/web/templates/partials/source_anchor_button.html` — emit a structured log line on the no-render fallthrough. **(Section E)**
- `src/docket/web/__init__.py` — register the admin_coverage blueprint. **(Section E)**
- `src/docket/migrations/runner.py:MIGRATIONS` — register migration 019.
- Existing adapter / ingest tests in `tests/unit/test_granicus.py`, `tests/unit/test_civicclerk.py`, `tests/unit/test_generic_cms.py`, `tests/unit/test_ingest.py` — extend assertions.

---

## Section A — Category landing card context (meeting date + item_number)

The smallest, lowest-risk fix. Two field additions to the query, one meta strip in three card templates, gated by a context flag.

### Task A1: Extend `list_items_by_badge` projection

**Files:**
- Modify: `src/docket/services/query.py` (around line 900, the SELECT in `list_items_by_badge`)
- Test: `tests/unit/test_query_list_items_by_badge.py` (create if missing — search the file first; if it doesn't exist, add a test alongside the closest related file)

- [ ] **Step 1: Add a failing test that asserts `meeting_date` is present in returned rows**

If a test file for `list_items_by_badge` already exists, add this test there. Otherwise create the file.

```python
# tests/unit/test_query_list_items_by_badge.py
"""Tests for services.query.list_items_by_badge projection."""
from datetime import date
from docket.services import query
from tests.unit.conftest_db import test_city, test_meeting, test_item_with_badge  # adapt to actual fixtures


def test_list_items_by_badge_includes_meeting_date(test_city, test_meeting, test_item_with_badge):
    """Category-landing cards need meeting_date inline — it's the only place
    the user gets temporal context for the item (the page itself spans many
    meetings)."""
    test_meeting(date(2026, 4, 15))
    test_item_with_badge('housing_stability', confidence=0.9)
    rows = query.list_items_by_badge(test_city.id, 'housing_stability')
    assert rows[0].meeting_date == date(2026, 4, 15)
```

Read the existing `services/query.py:list_items_by_badge` fixtures first — the project's pattern is to use `_Bag` / fixture helpers in `tests/integration/`; this test may belong there instead. Reuse the closest pattern.

- [ ] **Step 2: Run the test, confirm it fails**

```
venv/bin/python -m pytest tests/unit/test_query_list_items_by_badge.py -v
```
Expected: `AttributeError: 'AgendaItem' object has no attribute 'meeting_date'` or `KeyError: 'meeting_date'` depending on the AgendaItem from_row implementation.

- [ ] **Step 3: Add `m.meeting_date` to the SELECT projection in `list_items_by_badge`**

In `src/docket/services/query.py` inside `list_items_by_badge`, find the existing SELECT (it currently selects `ai.id`, `ai.meeting_id`, ..., ending at `ai.source_anchor`, then a `jsonb_strip_nulls(...) AS extracted_facts`). Add `m.meeting_date,` right after `ai.meeting_id,` (or just before the JOIN clause, anywhere in the column list before the FROM):

```python
        SELECT
            ai.id,
            ai.meeting_id,
            m.meeting_date,           -- NEW: needed for category-landing meta strip
            ai.external_id,
            ai.item_number,
            ...
```

- [ ] **Step 4: Update `AgendaItem.from_row` if it doesn't already pass `meeting_date` through**

Open `src/docket/models/agenda.py`, search for `from_row`. If `meeting_date` is already there (it should be — `list_agenda_items` returns it for meeting_detail), no change needed. If not, add it:

```python
meeting_date=row.get("meeting_date"),
```

- [ ] **Step 5: Run the test, confirm it passes**

```
venv/bin/python -m pytest tests/unit/test_query_list_items_by_badge.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/docket/services/query.py src/docket/models/agenda.py tests/unit/test_query_list_items_by_badge.py
git commit -m "feat(query): include meeting_date in list_items_by_badge projection

Category-landing cards span multiple meetings and need date context per
item. Previously the JOIN to meetings was only used for ORDER BY, so the
date wasn't visible to the template."
```

### Task A2: Render meta strip on Smart Brevity Card variants when `show_meeting_context` is set

**Files:**
- Modify: `src/docket/web/templates/partials/card_smart_brevity.html`
- Modify: `src/docket/web/templates/partials/card_v2_fallback.html`
- Modify: `src/docket/web/templates/partials/card_pending.html`
- Test: `tests/integration/test_category_landing_render.py` (extend if exists, create otherwise)

- [ ] **Step 1: Write a failing render test**

```python
# tests/integration/test_category_landing_render.py
"""Tests for the category-landing card meta strip (date + item ref)."""
from datetime import date


def test_smart_brevity_card_shows_date_and_item_ref_on_category_landing(
    flask_app_client, test_birmingham, test_meeting_with_completed_item
):
    """When the route passes show_meeting_context=True (category landing
    surface), each card must render the meeting date + 'Item #N' reference.
    On meeting-detail (show_meeting_context not set), the same template
    must NOT render the meta strip — date is in the page chrome."""
    meeting_date = date(2026, 4, 15)
    item = test_meeting_with_completed_item(meeting_date=meeting_date,
                                            item_number='42',
                                            badge_slug='housing_stability')
    response = flask_app_client.get('/al/birmingham/housing_stability/')
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'April 15, 2026' in body
    assert 'Item #42' in body
```

If integration test infrastructure doesn't exist for the Flask app yet, fall back to a Jinja-render unit test that loads the template directly with a mock `item` dict. Look at `tests/integration/test_meeting_detail_render.py` (or similar) for the project's preferred pattern.

- [ ] **Step 2: Run the test, confirm it fails**

```
venv/bin/python -m pytest tests/integration/test_category_landing_render.py -v
```
Expected: FAIL — body doesn't contain the date string.

- [ ] **Step 3: Add the meta strip to `card_smart_brevity.html`**

Open `src/docket/web/templates/partials/card_smart_brevity.html`. Inside the `<article>` block, after the `<header>` with badge chips and BEFORE the headline, add:

```jinja
{% if show_meeting_context %}
  <div class="smart-brevity-card__meta-strip t-meta">
    {% if item.meeting_date %}
      <span class="smart-brevity-card__meeting-date">
        {{ item.meeting_date.strftime('%B %-d, %Y') }}
      </span>
    {% endif %}
    {% if item.item_number %}
      <span class="smart-brevity-card__sep">·</span>
      <span class="smart-brevity-card__item-ref t-mono">Item #{{ item.item_number }}</span>
    {% endif %}
  </div>
{% endif %}
```

- [ ] **Step 4: Add the same meta strip to `card_v2_fallback.html` and `card_pending.html`**

Same block, same position (after header, before title/headline). Older items will render with the v2 fallback — the meta strip must show there too so the page is consistent regardless of which items have been v3-processed.

- [ ] **Step 5: Plumb `show_meeting_context=True` from the route**

In `src/docket/web/public.py:category_landing`, find the `return render_template("category_landing.html", ...)` block at the bottom. Add `show_meeting_context=True` to the context. Then in `category_landing.html`, when it includes/calls into the item list partial, pass the flag through. Same for the HTMX-partial branch (the `if request.headers.get('HX-Request') == 'true'` block earlier in the function).

Concretely two render_template calls need the flag:

```python
    if request.headers.get("HX-Request") == "true":
        return render_template(
            "partials/_item_list.html",
            items=items,
            next_offset=next_offset,
            cross_filters=cross_filters,
            show_meeting_context=True,   # NEW
        )

    return render_template(
        "category_landing.html",
        ...,
        show_meeting_context=True,       # NEW
    )
```

Then in `category_landing.html` and `_item_list.html`, when the `{% include 'partials/smart_brevity_card.html' %}` happens inside the `{% for item in items %}`, Jinja will pass the surrounding context through by default — confirm by checking the templates have no `with` clause on the include. If they do, add `show_meeting_context=show_meeting_context`.

- [ ] **Step 6: Add CSS for the meta strip**

Open `src/docket/web/static/styles.css` (or `layout.css` — check which holds the existing `.smart-brevity-card__*` rules). Add minimal styling:

```css
.smart-brevity-card__meta-strip {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.85em;
    color: var(--color-muted, #666);
    margin-bottom: 8px;
}

.smart-brevity-card__sep {
    opacity: 0.5;
}
```

Match the existing token names (`var(--color-muted)` etc.) — search the CSS file for `color-muted` or similar tokens already in use.

- [ ] **Step 7: Run the render test, confirm it passes**

```
venv/bin/python -m pytest tests/integration/test_category_landing_render.py -v
```
Expected: PASS.

- [ ] **Step 8: Verify meeting-detail page is unchanged**

```
venv/bin/python -m pytest tests/integration/test_meeting_detail_render.py -v
```
Expected: all existing assertions still pass. The meta strip should NOT appear on meeting-detail (no `show_meeting_context` flag passed there).

- [ ] **Step 9: Commit**

```bash
git add src/docket/web/templates/partials/card_smart_brevity.html \
        src/docket/web/templates/partials/card_v2_fallback.html \
        src/docket/web/templates/partials/card_pending.html \
        src/docket/web/public.py \
        src/docket/web/static/styles.css \
        tests/integration/test_category_landing_render.py
git commit -m "feat(web): render meeting date + item ref on category landing cards

Adds an optional meta strip above each Smart Brevity Card variant, gated
by show_meeting_context. Meeting detail (where date is in page chrome)
opts out; category landing (where every item is from a different meeting)
opts in. v3 + v2-fallback + pending variants all render consistently."
```

### Task A3: Open a small PR for Section A

- [ ] **Step 1: Push the branch and open a PR**

```bash
git push -u origin feat/category-landing-meta-strip
gh pr create --title "feat(web): meeting date + item ref on category landing cards" --body "$(cat <<'EOF'
## Summary
Closes the first of three gaps on https://docket.pub/al/birmingham/<category>/ pages: items now show their meeting date and Item #N reference inline. v3 / v2-fallback / pending variants all render consistently.

## Test plan
- [x] New unit test for query projection
- [x] New integration test for render
- [x] Existing meeting-detail render tests still pass (no meta strip there)
- [ ] Spot-check on staging after deploy
EOF
)"
```

Wait for the PR to merge before starting Section B.

---

## Section D — Pydantic `SourceAnchor` model (Layer 1 hardening)

Lands before Section B so Section B can use it as the field type. Without this, `source_anchor` is opaque `dict | None` everywhere and a typo in a writer (e.g. `{type: 'vide', url: ...}`) lands silently in the DB and never renders.

### Task D1: Pydantic SourceAnchor model

**Files:**
- Create: `src/docket/models/source_anchor.py`
- Test: `tests/unit/test_source_anchor_model.py`

- [ ] **Step 1: Write the failing tests first**

```python
# tests/unit/test_source_anchor_model.py
"""Validation tests for the SourceAnchor Pydantic model.

This model is the single source of truth for the shape of
agenda_items.source_anchor — adapters, the derivation helper, the
backfill script, and the render layer all read/write through it.
"""

import pytest
from pydantic import ValidationError

from docket.models.source_anchor import SourceAnchor


def test_video_anchor_with_timestamp_validates():
    out = SourceAnchor(
        type='video',
        url='https://bhamal.granicus.com/player/clip/9',
        timestamp_seconds=120,
    )
    assert out.type == 'video'
    assert out.timestamp_seconds == 120


def test_html_anchor_with_optional_fragment_validates():
    out = SourceAnchor(type='html',
                       url='https://vh.civicclerk.com/Web/Document/123',
                       anchor='#item-3')
    assert out.anchor == '#item-3'


def test_pdf_anchor_with_page_validates():
    out = SourceAnchor(type='pdf',
                       url='https://homewoodal.gov/agenda.pdf',
                       page=7)
    assert out.page == 7


def test_invalid_type_raises():
    with pytest.raises(ValidationError):
        SourceAnchor(type='vide',  # typo — not in Literal
                     url='https://granicus.com/')


def test_disallowed_host_raises():
    """URL safety check fires at construction time, not render time."""
    with pytest.raises(ValidationError) as exc_info:
        SourceAnchor(type='html', url='https://evil.tld/page')
    assert 'allowlist' in str(exc_info.value).lower()


def test_javascript_url_raises():
    with pytest.raises(ValidationError):
        SourceAnchor(type='html', url='javascript:alert(1)')


def test_missing_url_raises():
    with pytest.raises(ValidationError):
        SourceAnchor(type='html')  # url is required


def test_model_dump_round_trips_through_jsonb_shape():
    """The model's dict representation must match what the existing
    source_anchor_button.html template reads — type, url, plus
    optional locator fields. Catches future drift between model and
    template."""
    anchor = SourceAnchor(type='video',
                          url='https://granicus.com/player/9',
                          timestamp_seconds=600)
    out = anchor.model_dump(exclude_none=True)
    assert out == {'type': 'video',
                   'url': 'https://granicus.com/player/9',
                   'timestamp_seconds': 600}
```

- [ ] **Step 2: Run the tests, confirm they fail**

```
venv/bin/python -m pytest tests/unit/test_source_anchor_model.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement the model**

```python
# src/docket/models/source_anchor.py
"""Pydantic SourceAnchor model — single source of truth for the
agenda_items.source_anchor JSONB shape.

Used by:
  - docket.services.source_anchors.derive_source_anchor — output type
  - docket.models.protocol.RawAgendaItem — field type
  - docket.services.ingest — round-trips through model_dump for the
    INSERT, which catches a malformed dict from an adapter at write
    time rather than at render time
  - scripts/backfill_source_anchors.py — same shape, same validation
  - tests of all of the above

The render-side template (partials/source_anchor_button.html) reads
the JSONB as an opaque mapping; the model's model_dump shape is what
ends up in the column, so any drift between the model's fields and
the template's expectations would surface immediately in render tests.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
section 6.4 (source-anchor adaptive button).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class SourceAnchor(BaseModel):
    """Per-item deep link descriptor stored in agenda_items.source_anchor.

    Attribute semantics:
      - ``type``: which renderer branch handles this anchor.
      - ``url``: the destination URL, gated by is_source_url_safe.
      - Locator fields (page/bbox/anchor/timestamp_seconds): optional
        refinements interpreted only by their matching ``type``. e.g.
        ``timestamp_seconds`` is ignored for ``type='pdf'``.

    The url-safety check runs in a model_validator so any writer that
    bypasses the validator (raw dict shoved into Pydantic via
    ``model_validate`` works too) still pays the cost. We don't trust
    callers to pre-validate.
    """

    model_config = ConfigDict(extra='forbid')  # catch typo'd keys early

    type: Literal['pdf', 'html', 'video']
    url: str
    page: int | None = None
    bbox: list[float] | None = None
    anchor: str | None = None
    timestamp_seconds: int | None = None

    @model_validator(mode='after')
    def url_must_be_safe(self):
        # Lazy import — source_security imports from web layer, and this
        # model is also imported by adapter/services code paths that
        # shouldn't pull in Flask at module load.
        from docket.web.source_security import is_source_url_safe
        if not is_source_url_safe(self.url):
            raise ValueError(
                f"SourceAnchor.url failed allowlist: {self.url!r}"
            )
        return self
```

- [ ] **Step 4: Run the tests, confirm they pass**

```
venv/bin/python -m pytest tests/unit/test_source_anchor_model.py -v
```
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/docket/models/source_anchor.py tests/unit/test_source_anchor_model.py
git commit -m "feat(models): Pydantic SourceAnchor model for source_anchor JSONB

Single source of truth for the shape. Used by derive_source_anchor,
RawAgendaItem, ingest, and the backfill script. url-safety check runs
at construction so any writer that produces a non-allowlisted URL
fails immediately rather than silently landing in the DB and failing
the render-side gate three weeks later."
```

### Task D2: Ship Section D as its own PR (it's a no-op until Section B starts using it)

- [ ] **Step 1: Push + open PR**

```bash
git push -u origin feat/source-anchor-model
gh pr create --title "feat(models): Pydantic SourceAnchor model" --body "Foundation for the upcoming source_anchor writer (Section B of the category-landing plan). No callers yet — pure addition."
```

After merge, Section B can begin.

---

## Section B — Source-anchor writer (adapters + ingest)

The big one. Three adapters get a derivation step; ingest writes the result through the validated `SourceAnchor` model; a pure derivation function in `services/source_anchors.py` keeps the logic in one place.

### Task B1: Add `source_anchor` field to `RawAgendaItem`

**Files:**
- Modify: `src/docket/models/protocol.py`
- Test: `tests/unit/test_protocol_models.py` (create if missing — keep tiny)

- [ ] **Step 1: Failing test for the new field default**

```python
# tests/unit/test_protocol_models.py
"""Sanity tests for the adapter contract dataclasses."""
from docket.models.protocol import RawAgendaItem
from docket.models.source_anchor import SourceAnchor


def test_raw_agenda_item_has_source_anchor_field_with_none_default():
    """source_anchor is optional on the adapter contract — adapters that
    can't compute one leave it None, ingest writes NULL."""
    item = RawAgendaItem(
        external_id='ext-1', meeting_external_id='mtg-1',
        item_number=None, title='t', description=None,
        section=None, is_consent=False, sponsor=None,
    )
    assert item.source_anchor is None


def test_raw_agenda_item_accepts_source_anchor_instance():
    item = RawAgendaItem(
        external_id='ext-1', meeting_external_id='mtg-1',
        item_number=None, title='t', description=None,
        section=None, is_consent=False, sponsor=None,
        source_anchor=SourceAnchor(type='html',
                                   url='https://bhamal.granicus.com/agenda/9'),
    )
    assert item.source_anchor.type == 'html'
```

- [ ] **Step 2: Run the test, confirm it fails**

```
venv/bin/python -m pytest tests/unit/test_protocol_models.py -v
```
Expected: `TypeError` or `AttributeError` about the missing field.

- [ ] **Step 3: Add the field**

Open `src/docket/models/protocol.py`. Add the import at the top:

```python
from docket.models.source_anchor import SourceAnchor
```

In `RawAgendaItem`:

```python
@dataclass(frozen=True)
class RawAgendaItem:
    """An agenda item as returned by a platform adapter."""

    external_id: str
    meeting_external_id: str
    item_number: str | None
    title: str
    description: str | None
    section: str | None  # 'Consent Agenda', 'New Business', etc.
    is_consent: bool
    sponsor: str | None
    video_timestamp_seconds: float | None = None
    source_anchor: SourceAnchor | None = None  # validated at construction
```

- [ ] **Step 4: Run the test, confirm it passes**

```
venv/bin/python -m pytest tests/unit/test_protocol_models.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/docket/models/protocol.py tests/unit/test_protocol_models.py
git commit -m "feat(models): add source_anchor to RawAgendaItem

Optional dict the adapter populates with the per-item deep link
descriptor (PDF/HTML/video + url + locator). Defaults to None so
adapters that haven't been updated keep compiling; ingest writes
NULL in that case."
```

### Task B2: Pure derivation helper module

**Files:**
- Create: `src/docket/services/source_anchors.py`
- Create: `tests/unit/test_source_anchors.py`

- [ ] **Step 1: Write the failing tests first**

```python
# tests/unit/test_source_anchors.py
"""Unit tests for source_anchor derivation.

The function is pure (no DB, no HTTP) — all inputs are dicts, output is
a dict-or-None matching the JSONB shape rendered by
``partials/source_anchor_button.html``.
"""

import pytest

from docket.services.source_anchors import derive_source_anchor


def test_granicus_item_with_video_timestamp_yields_video_anchor():
    """If an item has video_timestamp_seconds, link to the player URL
    at that offset (richest signal — deep-links into the meeting video
    at the moment that item was discussed)."""
    out = derive_source_anchor(
        platform='granicus',
        meeting={'video_url': 'https://bhamal.granicus.com/player/clip/123',
                 'source_url': 'https://bhamal.granicus.com/agenda/clip/123',
                 'minutes_url': None},
        item={'video_timestamp_seconds': 1284},
    )
    assert out == {
        'type': 'video',
        'url': 'https://bhamal.granicus.com/player/clip/123',
        'timestamp_seconds': 1284,
    }


def test_granicus_item_without_timestamp_falls_back_to_html_agenda():
    """When timestamp is missing, fall back to the agenda HTML page."""
    out = derive_source_anchor(
        platform='granicus',
        meeting={'video_url': 'https://x/player/clip/9',
                 'source_url': 'https://x/agenda/clip/9',
                 'minutes_url': None},
        item={'video_timestamp_seconds': None},
    )
    assert out == {'type': 'html', 'url': 'https://x/agenda/clip/9'}


def test_civicclerk_item_yields_html_event_anchor():
    """CivicClerk doesn't expose per-item URLs; link to the event page."""
    out = derive_source_anchor(
        platform='civicclerk',
        meeting={'source_url': 'https://vh.civicclerk.com/Web/Document/123',
                 'video_url': None, 'minutes_url': None},
        item={},
    )
    assert out == {'type': 'html',
                   'url': 'https://vh.civicclerk.com/Web/Document/123'}


def test_generic_cms_item_with_minutes_url_yields_pdf_anchor():
    """Homewood ships agenda + minutes as PDFs — link to the PDF when
    we have a URL."""
    out = derive_source_anchor(
        platform='generic_cms',
        meeting={'source_url': 'https://homewoodal.gov/archive',
                 'video_url': None,
                 'minutes_url': 'https://homewoodal.gov/agenda-2026-04-15.pdf'},
        item={},
    )
    assert out == {'type': 'pdf',
                   'url': 'https://homewoodal.gov/agenda-2026-04-15.pdf'}


def test_generic_cms_item_without_minutes_falls_back_to_archive_html():
    out = derive_source_anchor(
        platform='generic_cms',
        meeting={'source_url': 'https://homewoodal.gov/archive',
                 'video_url': None, 'minutes_url': None},
        item={},
    )
    assert out == {'type': 'html', 'url': 'https://homewoodal.gov/archive'}


def test_returns_none_when_no_usable_url():
    """Edge: meeting has nothing — return None so the card renders no link
    rather than a broken one."""
    out = derive_source_anchor(
        platform='granicus',
        meeting={'video_url': None, 'source_url': None, 'minutes_url': None},
        item={},
    )
    assert out is None


def test_unknown_platform_returns_none_and_logs_warning(caplog):
    out = derive_source_anchor(
        platform='wordpress',
        meeting={'source_url': 'https://x.example/page'},
        item={},
    )
    assert out is None
    assert any('unknown platform' in r.message for r in caplog.records)
```

- [ ] **Step 2: Run the tests, confirm they fail**

```
venv/bin/python -m pytest tests/unit/test_source_anchors.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement the derivation**

Update the unit tests in Step 1 to assert against `SourceAnchor` instances (not dicts). The constructor calls below produce the same JSONB on `model_dump(exclude_none=True)`, so existing tests' equality checks adapt with one line:
```python
assert out == SourceAnchor(type='video', url='...', timestamp_seconds=1284)
```

Create `src/docket/services/source_anchors.py`:

```python
"""Pure derivation of agenda_items.source_anchor from raw meeting/item data.

Called by every platform adapter at ingest time AND by the one-shot
backfill script. Returns a validated SourceAnchor (Pydantic model with
URL-safety check baked in) or None when no usable URL exists. Keeping
derivation here (not inside each adapter) lets adapter unit tests stay
focused on scraping correctness and lets the backfill rely on the same
logic without re-running adapter scrapes.

This first cut implements the "anchor to the parent meeting" shape for
all three supported platforms; richer per-item anchors (PDF page from
minutes parser, HTML id from agenda page) are follow-ups documented in
the plan that introduced this module.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from docket.models.source_anchor import SourceAnchor

log = logging.getLogger(__name__)

KnownPlatform = {'granicus', 'civicclerk', 'civicplus', 'generic_cms'}


def derive_source_anchor(
    *,
    platform: str,
    meeting: dict[str, Any],
    item: dict[str, Any],
) -> SourceAnchor | None:
    """Build the SourceAnchor for one agenda item.

    Args:
        platform: ``'granicus'`` / ``'civicclerk'`` / ``'civicplus'`` /
            ``'generic_cms'``. Matches ``municipalities.platform``.
        meeting: dict-like with at least these optional keys —
            ``source_url`` (HTML agenda or event page),
            ``video_url`` (e.g. Granicus player URL),
            ``minutes_url`` (PDF).
        item: dict-like with optional ``video_timestamp_seconds``.

    Returns:
        A validated ``SourceAnchor`` or None. URL-safety failures from
        Pydantic come back as None + a warning log — at scale the
        derivation produces 1 result per call; we'd rather no anchor
        than a broken one.
    """
    if platform not in KnownPlatform:
        log.warning("derive_source_anchor: unknown platform %r", platform)
        return None

    try:
        if platform == 'granicus':
            ts = item.get('video_timestamp_seconds')
            video_url = meeting.get('video_url')
            if ts is not None and video_url:
                return SourceAnchor(type='video', url=video_url,
                                    timestamp_seconds=int(ts))
            source_url = meeting.get('source_url')
            if source_url:
                return SourceAnchor(type='html', url=source_url)
            return None

        if platform in ('civicclerk', 'civicplus'):
            url = meeting.get('source_url')
            return SourceAnchor(type='html', url=url) if url else None

        if platform == 'generic_cms':
            minutes = meeting.get('minutes_url')
            if minutes:
                return SourceAnchor(type='pdf', url=minutes)
            source_url = meeting.get('source_url')
            if source_url:
                return SourceAnchor(type='html', url=source_url)
            return None
    except ValidationError as e:
        # URL failed allowlist or another shape check. Log and return
        # None so the item still ingests without an anchor (better than
        # blocking the whole ingest on one bad URL).
        log.warning(
            "derive_source_anchor: validation failed for platform=%r meeting=%r: %s",
            platform, meeting.get('external_id'), e,
        )
        return None

    return None  # unreachable; keeps mypy happy
```

- [ ] **Step 4: Run the tests, confirm they pass**

```
venv/bin/python -m pytest tests/unit/test_source_anchors.py -v
```
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/docket/services/source_anchors.py tests/unit/test_source_anchors.py
git commit -m "feat(services): pure source_anchor derivation helper

Shared by every adapter's fetch_agenda_items and by the
backfill script. Output shape matches the JSONB consumed by
partials/source_anchor_button.html. First cut anchors to the parent
meeting (video w/ timestamp when available, else HTML agenda, else
PDF for generic_cms). Per-item PDF page anchors are a follow-up."
```

### Task B3: Granicus adapter populates `source_anchor`

**Files:**
- Modify: `src/docket/adapters/granicus.py` (around line 110, the `RawAgendaItem(...)` constructor inside `fetch_agenda_items`)
- Test: extend `tests/unit/test_granicus.py`

- [ ] **Step 1: Failing test**

Open `tests/unit/test_granicus.py`, find an existing test that exercises `fetch_agenda_items` (most likely uses a fixture that mocks `httpx` or `requests`). Add:

```python
def test_fetch_agenda_items_populates_source_anchor_with_video_timestamp(
    granicus_adapter, mock_granicus_player_with_index_points,
):
    """Items with a video timestamp get a video anchor pointing at the
    player URL with the seconds offset — that's the deepest deep-link
    Granicus exposes."""
    meeting = RawMeeting(
        external_id='clip-9', municipality_slug='birmingham',
        title='Council', meeting_date=date(2026, 4, 15),
        meeting_type='council',
        source_url='https://bhamal.granicus.com/agenda/clip/9',
        video_url='https://bhamal.granicus.com/player/clip/9',
        minutes_url=None,
    )
    items = granicus_adapter.fetch_agenda_items(meeting)
    item_with_ts = next(i for i in items if i.video_timestamp_seconds == 120)
    assert item_with_ts.source_anchor == {
        'type': 'video',
        'url': 'https://bhamal.granicus.com/player/clip/9',
        'timestamp_seconds': 120,
    }
```

Existing fixture naming may differ — match what's there. The key assertion is that each `RawAgendaItem` carries a `source_anchor`.

- [ ] **Step 2: Run the test, confirm it fails**

```
venv/bin/python -m pytest tests/unit/test_granicus.py -k source_anchor -v
```

- [ ] **Step 3: Update the Granicus adapter**

In `src/docket/adapters/granicus.py`, find the `RawAgendaItem(...)` constructor inside `fetch_agenda_items`. Just before constructing each item, call the helper:

```python
from docket.services.source_anchors import derive_source_anchor

# inside the loop where each item is built:
anchor = derive_source_anchor(
    platform='granicus',
    meeting={
        'source_url': meeting.source_url,
        'video_url': meeting.video_url,
        'minutes_url': meeting.minutes_url,
    },
    item={'video_timestamp_seconds': video_timestamp},
)
items.append(RawAgendaItem(
    ...,  # existing fields
    video_timestamp_seconds=video_timestamp,
    source_anchor=anchor,
))
```

- [ ] **Step 4: Run the tests, confirm they pass**

```
venv/bin/python -m pytest tests/unit/test_granicus.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/docket/adapters/granicus.py tests/unit/test_granicus.py
git commit -m "feat(granicus): populate RawAgendaItem.source_anchor at scrape time"
```

### Task B4: CivicClerk adapter populates `source_anchor`

**Files:**
- Modify: `src/docket/adapters/civicclerk.py` (around line 198)
- Test: extend `tests/unit/test_civicclerk.py`

- [ ] **Step 1: Failing test**

```python
def test_fetch_agenda_items_populates_html_source_anchor(civicclerk_adapter, ...):
    """CivicClerk doesn't expose per-item deep links; every item gets
    an html anchor pointing at the meeting/event page."""
    items = civicclerk_adapter.fetch_agenda_items(test_meeting_with_known_source_url)
    for it in items:
        assert it.source_anchor == {
            'type': 'html',
            'url': test_meeting_with_known_source_url.source_url,
        }
```

- [ ] **Step 2: Confirm it fails**

```
venv/bin/python -m pytest tests/unit/test_civicclerk.py -k source_anchor -v
```

- [ ] **Step 3: Update the CivicClerk adapter**

Same pattern as Granicus — import the helper and pass to `RawAgendaItem`.

- [ ] **Step 4: Confirm tests pass + commit**

```bash
git add src/docket/adapters/civicclerk.py tests/unit/test_civicclerk.py
git commit -m "feat(civicclerk): populate RawAgendaItem.source_anchor at scrape time"
```

### Task B5: GenericCMS (Homewood) adapter populates `source_anchor`

**Files:**
- Modify: `src/docket/adapters/generic_cms.py`
- Test: extend `tests/unit/test_generic_cms.py`

Same shape as B3/B4. Homewood prefers PDF anchors (the minutes URL) when available; falls back to the archive page.

- [ ] **Step 1: Failing test** (PDF anchor when minutes_url is set)
- [ ] **Step 2: Run, confirm fails**
- [ ] **Step 3: Update the adapter**
- [ ] **Step 4: Confirm passes + commit**

```bash
git add src/docket/adapters/generic_cms.py tests/unit/test_generic_cms.py
git commit -m "feat(generic_cms): populate RawAgendaItem.source_anchor at scrape time"
```

### Task B6: Ingest writes `source_anchor` into `agenda_items`

**Files:**
- Modify: `src/docket/services/ingest.py:222-241` (the agenda-item INSERT)
- Test: extend `tests/unit/test_ingest.py` or `tests/integration/test_ingest_pipeline.py`

- [ ] **Step 1: Failing test that asserts source_anchor lands in the DB**

```python
def test_ingest_writes_source_anchor_from_adapter(
    test_db, mock_adapter_returning_items_with_anchor,
):
    """When the adapter returns items with source_anchor populated,
    services.ingest writes the JSONB to agenda_items.source_anchor."""
    # ... seed a meeting, run ingest_municipality with the mock adapter ...
    with db_cursor() as cur:
        cur.execute("SELECT source_anchor FROM agenda_items WHERE external_id = %s",
                    ['ext-1'])
        anchor = cur.fetchone()['source_anchor']
    assert anchor == {'type': 'video',
                      'url': 'https://x/player/clip/9',
                      'timestamp_seconds': 600}
```

- [ ] **Step 2: Confirm fails**

- [ ] **Step 3: Update the INSERT**

In `src/docket/services/ingest.py:222-241`, the INSERT into `agenda_items` lists 13 columns and 13 values. Add `source_anchor` as a 14th column. Use `Json` from `psycopg2.extras` to encode the validated model:

```python
from psycopg2.extras import Json
# ...
anchor_payload = (
    Json(item.source_anchor.model_dump(exclude_none=True))
    if item.source_anchor is not None
    else None
)
cur.execute(
    """
    INSERT INTO agenda_items (
        meeting_id, external_id, item_number, title,
        description, section, is_consent, sponsor,
        dollars_amount, topic,
        significance_score, consent_placement_score,
        video_timestamp_seconds,
        source_anchor
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (meeting_id, external_id) DO NOTHING
    """,
    (
        meeting_id, item.external_id, item.item_number,
        title, item.description, item.section,
        item.is_consent, sponsor,
        enriched["dollars_amount"],
        enriched["topic"],
        enriched["significance_score"],
        enriched["consent_placement_score"],
        item.video_timestamp_seconds,
        anchor_payload,
    ),
)
```

The ``model_dump(exclude_none=True)`` call is the right serialization
choice: it drops locator fields that don't apply to the variant (e.g.
``page`` on a video anchor), keeping the stored JSONB minimal and the
existing render template's ``or {}`` guards intact.

- [ ] **Step 4: Confirm test passes**

- [ ] **Step 5: Run the full test suite to catch any adapter-test regressions**

```
venv/bin/python -m pytest --ignore=tests/live 2>&1 | tail -5
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/docket/services/ingest.py tests/unit/test_ingest.py
git commit -m "feat(ingest): write source_anchor to agenda_items at INSERT time

ON CONFLICT DO NOTHING means existing rows are unchanged — the
backfill script (next task) handles in-place updates."
```

### Task B7: Section B PR

- [ ] **Step 1: Push branch, open PR**

```bash
git push -u origin feat/source-anchor-writer
gh pr create --title "feat(ingest): write source_anchor at scrape time" --body "..."
```

Wait for merge. After merge, deploy to Railway via `railway up --service docket-web --detach` + `railway up --service worker --detach`. New ingest cycles will populate `source_anchor`; existing rows still NULL — Section C handles those.

---

## Section C — Backfill source_anchor for existing rows

~58K agenda_items currently have `source_anchor IS NULL`. This task backfills them in one pass.

### Task C1: Sentinel migration that documents the backfill (no SQL)

**Files:**
- Create: `src/docket/migrations/019_backfill_source_anchors.py`
- Modify: `src/docket/migrations/runner.py:MIGRATIONS`

- [ ] **Step 1: Write the sentinel migration**

```python
# src/docket/migrations/019_backfill_source_anchors.py
"""Migration 019 — sentinel for source_anchor backfill (manual script).

The actual data work happens in
``scripts/backfill_source_anchors.py``; this migration is a no-op
that records the slot. Keeps the audit trail honest — anyone running
``runner.py --status`` sees that the backfill was a defined step,
even though the runtime data application lives outside the migration
system (the backfill needs adapter-platform context that's awkward
to express in SQL).
"""

from __future__ import annotations

SQL_UP = "-- intentional no-op; see scripts/backfill_source_anchors.py\n"
SQL_DOWN = "-- intentional no-op\n"
```

- [ ] **Step 2: Register in `runner.py`**

```python
MIGRATIONS = [
    ...
    "docket.migrations.018_ai_batches_ingested_at",
    "docket.migrations.019_backfill_source_anchors",
]
```

- [ ] **Step 3: Apply locally**

```
venv/bin/python -m docket.migrations.runner
```
Expected: "Applied migration 19".

- [ ] **Step 4: Commit**

```bash
git add src/docket/migrations/019_backfill_source_anchors.py src/docket/migrations/runner.py
git commit -m "migrate(019): sentinel slot for source_anchor backfill"
```

### Task C2: Backfill script + tests

**Files:**
- Create: `scripts/backfill_source_anchors.py`
- Create: `tests/integration/test_backfill_source_anchors.py`

- [ ] **Step 1: Write the integration test first**

```python
# tests/integration/test_backfill_source_anchors.py
"""Integration test for scripts/backfill_source_anchors.py against local DB."""

import json
import subprocess
import sys
from datetime import date

import pytest

from docket.db import db_cursor


def test_backfill_populates_source_anchor_for_null_rows(local_db_with_seed):
    """A row with source_anchor IS NULL should pick up the derived
    anchor; an existing non-null row must NOT be overwritten."""
    # seed a meeting + two items: one NULL, one preset
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO meetings (municipality_id, title, meeting_date,
                                  meeting_type, source_url, video_url)
            VALUES ((SELECT id FROM municipalities WHERE slug='birmingham'),
                    'Test', %s, 'council',
                    'https://x/agenda/9', 'https://x/player/9')
            RETURNING id
        """, [date(2026, 4, 15)])
        mtg_id = cur.fetchone()['id']
        cur.execute("""
            INSERT INTO agenda_items (meeting_id, external_id, title,
                                      is_consent, video_timestamp_seconds,
                                      source_anchor)
            VALUES (%s, 'a', 't', false, 120, NULL),
                   (%s, 'b', 't', false, NULL,
                    %s::jsonb)
        """, [mtg_id, mtg_id,
              json.dumps({'type': 'html', 'url': 'preset'})])

    subprocess.check_call(
        [sys.executable, 'scripts/backfill_source_anchors.py'],
        cwd='.',
    )

    with db_cursor() as cur:
        cur.execute("SELECT external_id, source_anchor FROM agenda_items "
                    "WHERE meeting_id = %s ORDER BY external_id", [mtg_id])
        rows = {r['external_id']: r['source_anchor'] for r in cur.fetchall()}
    # NULL row got derived video anchor
    assert rows['a'] == {'type': 'video', 'url': 'https://x/player/9',
                         'timestamp_seconds': 120}
    # Preset row unchanged
    assert rows['b'] == {'type': 'html', 'url': 'preset'}
```

- [ ] **Step 2: Run the test, confirm it fails (script doesn't exist)**

```
venv/bin/python -m pytest tests/integration/test_backfill_source_anchors.py -v
```
Expected: FAIL on the subprocess.check_call (script not found).

- [ ] **Step 3: Write the script**

```python
# scripts/backfill_source_anchors.py
"""One-shot backfill: populate agenda_items.source_anchor for existing rows.

Reads every (meeting, item) pair where source_anchor IS NULL, joins
the meeting's URLs, infers platform from municipalities.platform, calls
``services.source_anchors.derive_source_anchor``, batched UPDATE back.
Idempotent: re-running skips rows that already have a non-null anchor.

Run from the project root inside the deployed container:

    railway ssh --service worker "cd /app && python scripts/backfill_source_anchors.py"

Or against a local DB:

    venv/bin/python scripts/backfill_source_anchors.py
"""

from __future__ import annotations

import json
import logging
import sys
from psycopg2.extras import Json

from docket.db import db, db_cursor
from docket.services.source_anchors import derive_source_anchor

log = logging.getLogger("backfill_source_anchors")

BATCH_SIZE = 500


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    with db_cursor() as cur:
        cur.execute("""
            SELECT ai.id, ai.video_timestamp_seconds,
                   m.source_url, m.video_url, m.minutes_url,
                   muni.platform
              FROM agenda_items ai
              JOIN meetings m ON m.id = ai.meeting_id
              JOIN municipalities muni ON muni.id = m.municipality_id
             WHERE ai.source_anchor IS NULL
             ORDER BY ai.id
        """)
        rows = cur.fetchall()
    log.info("backfill: %d rows pending", len(rows))

    pending: list[tuple[int, dict]] = []
    for row in rows:
        anchor = derive_source_anchor(
            platform=row["platform"],
            meeting={
                "source_url": row["source_url"],
                "video_url":  row["video_url"],
                "minutes_url": row["minutes_url"],
            },
            item={"video_timestamp_seconds": row["video_timestamp_seconds"]},
        )
        if anchor is None:
            continue
        pending.append((row["id"], anchor))

    log.info("backfill: %d rows will receive an anchor", len(pending))

    n_written = 0
    for i in range(0, len(pending), BATCH_SIZE):
        chunk = pending[i:i + BATCH_SIZE]
        with db() as conn, conn.cursor() as cur:
            for item_id, anchor in chunk:
                cur.execute(
                    """
                    UPDATE agenda_items
                       SET source_anchor = %s::jsonb
                     WHERE id = %s AND source_anchor IS NULL
                    """,
                    [Json(anchor), item_id],
                )
                n_written += cur.rowcount
        log.info("backfill: wrote chunk %d-%d (cumulative %d)",
                 i, i + len(chunk), n_written)

    log.info("backfill: complete, %d rows updated", n_written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test, confirm it passes**

```
venv/bin/python -m pytest tests/integration/test_backfill_source_anchors.py -v
```

- [ ] **Step 5: Dry-run against local DB to gauge scale**

```
venv/bin/python scripts/backfill_source_anchors.py 2>&1 | tail -10
```

Expected: ~58K rows pending, ~58K written, takes < 1 minute on local PG.

- [ ] **Step 6: Commit**

```bash
git add scripts/backfill_source_anchors.py tests/integration/test_backfill_source_anchors.py
git commit -m "feat(scripts): one-shot backfill for source_anchor

Idempotent: only touches rows where source_anchor IS NULL. Uses
the same derive_source_anchor helper the adapters use at scrape time."
```

### Task C3: Run the backfill on Railway

- [ ] **Step 1: Sanity-count `NULL` rows on Railway**

```bash
DATABASE_URL=$(railway variables --service docket-web --kv | grep '^DATABASE_PUBLIC_URL=' | cut -d= -f2-) \
  /opt/homebrew/opt/postgresql@18/bin/psql -c \
  "SELECT COUNT(*) FROM agenda_items WHERE source_anchor IS NULL;"
```
Record the number.

- [ ] **Step 2: Run the script inside the worker container**

```bash
railway ssh --service worker "cd /app && python scripts/backfill_source_anchors.py"
```

Run inside the container — the script does many small UPDATEs, and per-row latency over the public proxy would make it slow. Watch the output. Expect ~1-3 min total.

- [ ] **Step 3: Verify**

```bash
DATABASE_URL=$DATABASE_PUBLIC_URL /opt/homebrew/opt/postgresql@18/bin/psql -c \
  "SELECT COUNT(*) AS total,
          COUNT(source_anchor) AS with_anchor,
          COUNT(*) FILTER (WHERE source_anchor->>'type'='video') AS video_count,
          COUNT(*) FILTER (WHERE source_anchor->>'type'='html')  AS html_count,
          COUNT(*) FILTER (WHERE source_anchor->>'type'='pdf')   AS pdf_count
     FROM agenda_items;"
```

Expected: `with_anchor` is close to `total` (anything left at NULL is meeting-level data gap — meetings with no `source_url` / `video_url` / `minutes_url`).

- [ ] **Step 4: Spot-check the live page**

Open https://docket.pub/al/birmingham/housing_stability/ in a browser. Each card should now show:
- Meeting date (April 15, 2026)
- Item #N reference
- "View Source: video at MM:SS →" or "View Source: PDF →" / "View Source: agenda item →" button.

### Task C4: PR for Section C

```bash
git push -u origin feat/source-anchor-backfill
gh pr create --title "feat: backfill source_anchor for ~58K existing agenda items" --body "..."
```

After merge, the three gaps from the user's question are closed.

---

## Section E — Coverage observability (Layer 2 hardening)

After Sections A–D ship, links land — but there's no signal if a future adapter forgets to populate them. Three additions: a CI test that every adapter produces an anchor on its happy-path fixture, an admin view that reports per-municipality coverage, and a structured log on the no-render fallthrough.

### Task E1: CI invariant — every adapter's happy-path fixture yields a non-None anchor

**Files:**
- Create: `tests/integration/test_adapter_source_anchor_coverage.py`

- [ ] **Step 1: Write the test**

```python
# tests/integration/test_adapter_source_anchor_coverage.py
"""CI invariant — every supported adapter populates RawAgendaItem.source_anchor
for a canonical happy-path meeting.

This catches the failure mode "new adapter PR forgot to wire up the
source_anchor field" before merge: the test fails immediately on any
adapter whose fetch_agenda_items returns rows with source_anchor=None
for an input that has the URL fields needed to derive one.
"""

import pytest

from docket.adapters.granicus import GranicusAdapter
from docket.adapters.civicclerk import CivicClerkAdapter
from docket.adapters.generic_cms import GenericCMSAdapter


@pytest.mark.parametrize(
    "adapter_factory, meeting_fixture",
    [
        ("granicus_factory", "granicus_meeting_with_video"),
        ("civicclerk_factory", "civicclerk_meeting"),
        ("generic_cms_factory", "homewood_meeting_with_minutes"),
    ],
)
def test_adapter_fetch_agenda_items_populates_source_anchor(
    request, adapter_factory, meeting_fixture,
):
    """Each adapter's fetch_agenda_items must produce SourceAnchor
    instances on every item when the meeting has the URL fields the
    derivation needs.

    'Happy path' means a meeting with the platform's expected URL
    field populated: video_url for Granicus, source_url for
    CivicClerk, minutes_url for GenericCMS."""
    adapter = request.getfixturevalue(adapter_factory)
    meeting = request.getfixturevalue(meeting_fixture)
    items = adapter.fetch_agenda_items(meeting)
    assert items, "fixture must produce at least one item"
    for it in items:
        assert it.source_anchor is not None, (
            f"adapter {adapter.__class__.__name__} returned an item "
            f"with source_anchor=None despite the meeting having the "
            f"necessary URL fields. Did fetch_agenda_items forget to "
            f"call derive_source_anchor?"
        )
```

The three fixture names map to fixtures defined in the adapter test files (`tests/unit/test_granicus.py` etc.). If the project keeps adapter fixtures local to each file, refactor them into a shared `tests/conftest.py` or `tests/fixtures/adapters.py` first.

- [ ] **Step 2: Confirm test passes**

After Sections B's adapter changes have landed:

```
venv/bin/python -m pytest tests/integration/test_adapter_source_anchor_coverage.py -v
```
Expected: 3 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_adapter_source_anchor_coverage.py
git commit -m "test(adapters): CI invariant — every adapter populates source_anchor"
```

### Task E2: Admin coverage view at `/admin/source-anchor-coverage`

**Files:**
- Create: `src/docket/web/admin_coverage.py`
- Create: `src/docket/web/templates/admin/source_anchor_coverage.html`
- Modify: `src/docket/web/__init__.py` (register the blueprint)
- Test: `tests/integration/test_admin_coverage.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_admin_coverage.py
def test_admin_coverage_view_requires_login(flask_app_client):
    rv = flask_app_client.get('/admin/source-anchor-coverage')
    assert rv.status_code in (302, 401)


def test_admin_coverage_view_renders_per_municipality_stats(
    admin_flask_app_client, seeded_v3_items_with_partial_coverage,
):
    """The view shows: total completed v3 items per city, count with
    non-null source_anchor, percentage. A regression in one adapter
    would show as a sudden drop in that city's % week-over-week."""
    rv = admin_flask_app_client.get('/admin/source-anchor-coverage')
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert 'Birmingham' in body
    # Stats table heading
    assert 'completed' in body.lower()
    assert 'with anchor' in body.lower() or 'coverage' in body.lower()
```

Adapt to existing admin-test patterns. If there's no `admin_flask_app_client` fixture yet, copy the login-required pattern from `tests/integration/test_admin_council_members.py` or similar.

- [ ] **Step 2: Confirm fails**

- [ ] **Step 3: Implement the blueprint**

```python
# src/docket/web/admin_coverage.py
"""Admin view: source_anchor coverage per municipality.

Surfaces the percentage of completed v3 agenda items with a non-null
source_anchor, broken down by municipality. A sudden drop in one city's
coverage week-over-week is a signal that the adapter regressed — likely
a missed plumbing step in a recent PR.

Spec: docs/superpowers/plans/2026-05-11-category-landing-context-and-source-anchors.md
Section E (Layer 2 hardening).
"""

from __future__ import annotations

from flask import Blueprint, render_template

from docket.db import db_cursor
from docket.web.auth import login_required

bp = Blueprint("admin_coverage", __name__, url_prefix="/admin")


@bp.route("/source-anchor-coverage")
@login_required
def source_anchor_coverage():
    """Per-municipality coverage stats for agenda_items.source_anchor."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT muni.id,
                   muni.slug,
                   muni.name,
                   COUNT(*) FILTER (
                       WHERE ai.processing_status = 'completed'
                   ) AS completed_count,
                   COUNT(*) FILTER (
                       WHERE ai.processing_status = 'completed'
                         AND ai.source_anchor IS NOT NULL
                   ) AS with_anchor_count
              FROM municipalities muni
              JOIN meetings m       ON m.municipality_id = muni.id
              JOIN agenda_items ai  ON ai.meeting_id = m.id
             WHERE muni.active = TRUE
             GROUP BY muni.id, muni.slug, muni.name
             ORDER BY muni.name
            """
        )
        rows = cur.fetchall()

    coverage = []
    for r in rows:
        completed = r["completed_count"] or 0
        with_anchor = r["with_anchor_count"] or 0
        pct = round(100.0 * with_anchor / completed, 1) if completed else None
        coverage.append({
            "slug": r["slug"],
            "name": r["name"],
            "completed": completed,
            "with_anchor": with_anchor,
            "pct": pct,
        })

    return render_template(
        "admin/source_anchor_coverage.html",
        coverage=coverage,
    )
```

Template:

```jinja
{# src/docket/web/templates/admin/source_anchor_coverage.html #}
{% extends "base.html" %}
{% block content %}
<section class="admin-panel">
  <h1>Source-anchor coverage</h1>
  <p class="t-meta">
    Percentage of completed v3 items with a non-null source_anchor per
    municipality. A regression in one adapter shows as a sudden drop
    in that row.
  </p>
  <table class="admin-table">
    <thead>
      <tr><th>City</th><th>Completed</th><th>With anchor</th><th>Coverage</th></tr>
    </thead>
    <tbody>
      {% for row in coverage %}
      <tr>
        <td>{{ row.name }}</td>
        <td class="t-mono">{{ row.completed }}</td>
        <td class="t-mono">{{ row.with_anchor }}</td>
        <td class="t-mono">
          {% if row.pct is not none %}{{ row.pct }}%{% else %}—{% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</section>
{% endblock %}
```

- [ ] **Step 4: Register the blueprint**

In `src/docket/web/__init__.py`:

```python
from docket.web.admin_coverage import bp as admin_coverage_bp
# ...inside create_app...
app.register_blueprint(admin_coverage_bp)
```

- [ ] **Step 5: Confirm test passes**

- [ ] **Step 6: Commit**

```bash
git add src/docket/web/admin_coverage.py \
        src/docket/web/templates/admin/source_anchor_coverage.html \
        src/docket/web/__init__.py \
        tests/integration/test_admin_coverage.py
git commit -m "feat(admin): /admin/source-anchor-coverage per-municipality view"
```

### Task E3: Structured log on render-side fallthrough

**Files:**
- Modify: `src/docket/web/templates/partials/source_anchor_button.html`
- Modify: `src/docket/web/filters.py` (or wherever Jinja globals are registered) — add a tiny logging shim usable from the template.

- [ ] **Step 1: Add a Jinja global `record_anchor_fallthrough(item_id)`**

```python
# in src/docket/web/filters.py or app factory
import logging
_anchor_log = logging.getLogger("docket.web.source_anchor")

def record_anchor_fallthrough(item_id):
    """Called from source_anchor_button.html when no link renders.

    Emits a single log line so we can aggregate 'how often does the
    button silently fall through' from production logs. Returns empty
    string so the template can call it from a {{ }} expression
    without leaking output."""
    _anchor_log.info("source_anchor fallthrough item_id=%s", item_id)
    return ""

# register in create_app:
app.jinja_env.globals['record_anchor_fallthrough'] = record_anchor_fallthrough
```

- [ ] **Step 2: Call it from the final fallthrough branch in `source_anchor_button.html`**

At the very bottom of the template, BEFORE the closing `{% endif %}`, after every conditional has fallen through:

```jinja
{% else %}
  {# no anchor matched any branch — surface for observability #}
  {{ record_anchor_fallthrough(item.id) }}
{% endif %}
```

Place this `{% else %}` carefully — the template currently ends with a `{% elif _is_safe %}` block. The new `{% else %}` attaches to that. Re-read the file before editing to make sure the indentation matches.

- [ ] **Step 3: Add a test**

```python
def test_source_anchor_button_logs_when_no_link_rendered(
    flask_app_client, caplog, item_without_source_anchor,
):
    """If the button falls through every branch (no anchor at all),
    a single log line is emitted with the item id so we can aggregate."""
    with caplog.at_level('INFO', logger='docket.web.source_anchor'):
        rv = flask_app_client.get(f'/al/birmingham/meetings/{item_without_source_anchor.meeting_id}/')
    assert any(
        'source_anchor fallthrough' in rec.message and str(item_without_source_anchor.id) in rec.message
        for rec in caplog.records
    )
```

- [ ] **Step 4: Commit**

```bash
git add src/docket/web/templates/partials/source_anchor_button.html \
        src/docket/web/filters.py \
        tests/integration/test_source_anchor_fallthrough_log.py
git commit -m "feat(web): structured log when source_anchor button renders nothing

A grep on production logs (or any aggregation tool) now gives a true
'how often did the link silently fail to render' signal. Coupled
with the admin coverage view, regressions stop being invisible."
```

### Task E4: PR for Section E

```bash
git push -u origin feat/source-anchor-coverage-observability
gh pr create --title "feat: source-anchor coverage observability (CI test + admin view + render log)" --body "..."
```

After merge, future adapter regressions either fail CI or surface visibly in the admin view + logs.

---

## Self-Review

**Spec coverage** (cross-referenced to "what's broken" notes from the conversation + the user's hardening question):
- ✅ Meeting date missing from category-landing — Task A1 (query) + A2 (render)
- ✅ Reference (item_number) not rendered — Task A2 (template)
- ✅ source_anchor never written — Section B (adapters + ingest) + Section C (backfill)
- ✅ Cards land consistently on v3 / v2-fallback / pending variants — A2 step 4
- ✅ meeting-detail page unchanged — A2 step 8
- ✅ Layer 1 hardening (Pydantic shape) — Section D
- ✅ Layer 2 hardening (CI coverage + admin view + render log) — Section E

**Placeholder scan:** No "TODO" / "TBD" / "fill in later". Test stubs reference fixtures that may not exist verbatim in the repo — explicit instructions to adapt to existing fixture naming are written into each task ("adapt to actual fixtures", "match what's there"). The fallback Jinja-render unit test is described concretely.

**Type consistency:**
- `SourceAnchor` Pydantic model — single source of truth for the shape. Used by `derive_source_anchor` (return type), `RawAgendaItem.source_anchor` (field type), `services/ingest.py` (writes via `model_dump(exclude_none=True)`), and the backfill script (same).
- `derive_source_anchor(platform, meeting, item)` — keyword-only, return `SourceAnchor | None`.
- `RawAgendaItem.source_anchor: SourceAnchor | None = None` — typed; adapters that can't compute one leave it None.
- Model fields match what `partials/source_anchor_button.html` reads: `type`, `url`, `timestamp_seconds`, `page`, `bbox`, `anchor`.
- `show_meeting_context` template flag — set to `True` in `category_landing` route only; absent everywhere else.
- `record_anchor_fallthrough(item_id)` Jinja global — returns empty string (callable from `{{ }}` without leaking output).

**Section ordering / dependency:**
1. **Section A** ships alone (no schema change, no backfill, no model).
2. **Section D** ships next — pure addition of the Pydantic model, no callers yet.
3. **Section B** depends on D (uses the model as the field type).
4. **Section C** depends on B (backfills the column the writer populates).
5. **Section E** depends on B (CI test needs adapter changes; admin view + render log need the column populated to be meaningful).

Five PRs, ordered. Each is independently deployable.

---

## What ships at the end

- `/al/birmingham/<badge_slug>/` (and every other category landing) shows date + item reference + working View Source link on every card.
- Future ingest cycles populate `source_anchor` at write time, validated via Pydantic — invalid shapes / disallowed URLs fail at ingest, not silently at render.
- ~58K legacy items get retroactive source links via the backfill.
- A CI invariant fails any future adapter PR that forgets to wire up `source_anchor`.
- An admin coverage view + structured fallthrough log surface silent regressions within hours, not weeks.
- Meeting-detail page rendering unchanged.

## Follow-up tickets (NOT in this plan)

- **Layer 3 — link rot detection.** Sampled HEAD-request cron + `link_health` table + admin allowlist-drift dashboard. Catches months-long decay (Granicus tenant migrations, site redesigns). ~2-3h + a migration. Worth doing once the backfill is stable.
- **Layer 4 — re-derivation on upstream changes.** Cron that re-derives anchors when a meeting's URL fields change. Needs an `updated_at` on `meetings` plus a checksum strategy. ~3-4h.
- Haiku over-suggesting `housing_stability` (and other policy badges) on items that don't fit — prompt-tuning + raise the `min_confidence` threshold for category landing (currently 0.6). User noted a planned refactor of "summaries and assignments" that may address this.
- Per-item PDF page anchors derived from `minutes_parser` output — would make the View Source button on minutes-derived items deep-link to the page where the resolution appears.
- Per-item HTML anchors when Granicus / CivicClerk agenda pages expose stable per-item DOM ids.
