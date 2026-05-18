# Upcoming-meeting forward-voice AI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop showing completed-action AI text on upcoming meetings. Ship a same-night template-level suppression for tomorrow's BHM meeting (2232), then ship a proper forked-prompt + voice-aware AI pipeline with a daily re-cascade that automatically rewrites in completed voice once the meeting actually happens.

**Architecture:** Two-phase delivery. **Phase 1** is template-only — gate `executive_summary` / `headline` / `why_it_matters` / legacy `summary` rendering when `meeting.meeting_date >= today`. **Phase 2** adds a forked Haiku/Sonnet prompt that writes in forward voice for upcoming meetings, persists which voice was used (`ai_rewrite_voice` column on `agenda_items`, `executive_summary_voice` on `meetings`), and adds a daily 04:45 CT cron task that re-queues items whose meeting just rolled into the past — so the existing completed-action prompt overwrites in place.

**Tech Stack:** Flask + Jinja2 templates, PostgreSQL 18 (Railway), Anthropic SDK (Haiku 4.5 items + Sonnet 4.6 meetings), APScheduler `BlockingScheduler` in `docket.worker`.

**Spec:** `docs/superpowers/specs/2026-05-18-upcoming-meeting-forward-voice-design.md`

---

## File Map

### Phase 1 — Template patch
- Modify: `src/docket/web/templates/meeting_detail.html` (exec summary section ~L41-57; consent blurb ~L251-253)
- Modify: `src/docket/web/templates/partials/_card_shell.html` (`card_headline_text` block ~L75-84; `card_why_block` ~L86-90)
- Modify: `src/docket/web/templates/partials/card_v2_fallback.html` (suppress legacy summary on upcoming)
- Modify: `src/docket/web/templates/item_detail.html` (why_it_matters block ~L60-70)
- Create: `tests/unit/web/test_upcoming_meeting_voice_layer1.py`

### Phase 2 — Forward-voice prompt fork
- Modify: `src/docket/web/filters.py` (register `is_upcoming` filter — Task 6, follow-up from PR #71 review)
- Modify: existing PR #71 + PR #68 template gate sites to use `item|is_upcoming` (Task 6)
- Create: `tests/unit/web/test_is_upcoming_filter.py` (Task 6)
- Create: `src/docket/migrations/031_ai_rewrite_voice.py`
- Modify: `src/docket/migrations/runner.py` (register 031)
- Modify: `src/docket/ai/prompts.py` (add `MEETING_SYSTEM_UPCOMING` + version constant)
- Modify: `src/docket/ai/rewrite.py` (add `SYSTEM_PROMPT_UPCOMING` + version + `_select_item_prompt` helper)
- Modify: `src/docket/ai/client.py` (read voice in `summarize_meeting`, pass right system prompt)
- Modify: `src/docket/ai/worker.py` (persist `executive_summary_voice` column on meeting write paths)
- Modify: `src/docket/ai/pipeline.py` (persist `ai_rewrite_voice` on item write path) — verify file name in Task 9
- Modify: `src/docket/worker/tasks.py` (new `_do_recast_post_meeting_ai`, add to `TASKS` dict)
- Modify: `src/docket/worker/scheduler.py` (register new cron at 04:45 CT)
- Create: `tests/unit/ai/test_voice_selection.py`
- Create: `tests/unit/worker/test_recast_post_meeting_ai.py`
- Create: `tests/live/test_upcoming_prompt_voice_smoke.py`

---

## Phase 1: Tactical patch (ships tonight, ahead of BHM meeting 2232 on 2026-05-19)

### Task 1: Write failing tests for Layer 1 template gates

**Files:**
- Create: `tests/unit/web/test_upcoming_meeting_voice_layer1.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Layer 1 tests for upcoming-meeting forward voice — template-only gates.

Spec: docs/superpowers/specs/2026-05-18-upcoming-meeting-forward-voice-design.md
"""
from __future__ import annotations

import datetime as _dt
from types import SimpleNamespace

import pytest

from docket.web import create_app


@pytest.fixture
def app():
    app = create_app()
    app.config.update(TESTING=True)
    return app


def _item(**overrides):
    base = dict(
        id=1,
        item_number=1,
        title="Authorize $1.2M contract with Acme Co.",
        headline="Council approved $1.2M Acme contract",
        why_it_matters="Residents can now access expanded recycling.",
        summary=None,
        description=None,
        topic=None,
        sponsor=None,
        section=None,
        is_consent=False,
        dollars_amount=None,
        ai_rewrite_version=4,
        ai_metadata=None,
        processing_status="completed",
        data_quality="ok",
        extracted_facts=None,
        meeting_id=2232,
        meeting_date=_dt.date(2026, 5, 19),
        municipality_slug="birmingham",
        badges=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _meeting(**overrides):
    base = dict(
        id=2232,
        title="Regular City Council Meeting",
        meeting_type="regular",
        meeting_date=_dt.date(2026, 5, 19),
        agenda_url="https://bhamal.granicus.com/AgendaViewer.php?view_id=2&event_id=2692",
        minutes_url=None,
        video_url=None,
        source_url=None,
        executive_summary="The council approved a $1.2M contract with Acme.",
        ai_metadata={"phase": "provisional", "confidence": "high"},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _muni(**overrides):
    base = dict(slug="birmingham", name="Birmingham")
    base.update(overrides)
    return SimpleNamespace(**base)


def _render_card_shell(app, item, today):
    """Render _card_shell.html with a stubbed `today`."""
    with app.test_request_context():
        from flask import render_template_string
        return render_template_string(
            "{% set today = today_value %}"
            "{% include 'partials/_card_shell.html' %}",
            item=item,
            today_value=today,
            show_meeting_context=False,
            coverage_counts={},
            municipality=_muni(),
        )


def _render_meeting_detail(app, meeting, today, agenda_items=None, consent_items=None):
    with app.test_request_context():
        from flask import render_template
        return render_template(
            "meeting_detail.html",
            meeting=meeting,
            municipality=_muni(),
            today=today,
            agenda_items=agenda_items or [],
            consent_items=consent_items or [],
            regular_items=[],
            votes=[],
            total_dollars_formatted="$0",
            dollar_count=0,
        )


# --- _card_shell upcoming gate ----------------------------------------------

def test_card_shell_upcoming_hides_headline_text(app):
    """On an upcoming meeting, the headline link falls back to item.title."""
    today = _dt.date(2026, 5, 18)
    item = _item(meeting_date=_dt.date(2026, 5, 19))
    html = _render_card_shell(app, item, today)
    assert "Authorize $1.2M contract with Acme Co." in html
    assert "Council approved $1.2M Acme contract" not in html


def test_card_shell_upcoming_hides_why_it_matters(app):
    """On an upcoming meeting, the why-it-matters paragraph is suppressed."""
    today = _dt.date(2026, 5, 18)
    item = _item(meeting_date=_dt.date(2026, 5, 19))
    html = _render_card_shell(app, item, today)
    assert "Residents can now access expanded recycling." not in html


def test_card_shell_past_meeting_unchanged(app):
    """On a past meeting, headline + why render exactly as before."""
    today = _dt.date(2026, 5, 18)
    item = _item(meeting_date=_dt.date(2026, 5, 12))
    html = _render_card_shell(app, item, today)
    assert "Council approved $1.2M Acme contract" in html
    assert "Residents can now access expanded recycling." in html


def test_card_shell_today_undefined_safe(app):
    """Test-app safety: when `today` is not injected, render baseline (no error)."""
    item = _item(meeting_date=_dt.date(2026, 5, 19))
    with app.test_request_context():
        from flask import render_template_string
        html = render_template_string(
            "{% include 'partials/_card_shell.html' %}",
            item=item,
            show_meeting_context=False,
            coverage_counts={},
            municipality=_muni(),
        )
    # No UndefinedError; baseline (past-meeting) rendering — headline shows.
    assert "Council approved $1.2M Acme contract" in html


# --- meeting_detail.html gates ----------------------------------------------

def test_meeting_detail_upcoming_exec_summary_replaced(app):
    """Upcoming meeting renders a static notice in place of executive summary."""
    today = _dt.date(2026, 5, 18)
    meeting = _meeting(meeting_date=_dt.date(2026, 5, 19))
    html = _render_meeting_detail(app, meeting, today)
    assert "The council approved a $1.2M contract with Acme." not in html
    assert "meeting hasn&#39;t happened yet" in html.lower() or "hasn't happened yet" in html.lower()


def test_meeting_detail_past_exec_summary_unchanged(app):
    """Past meeting renders the Sonnet executive_summary unchanged."""
    today = _dt.date(2026, 5, 18)
    meeting = _meeting(meeting_date=_dt.date(2026, 5, 12))
    html = _render_meeting_detail(app, meeting, today)
    assert "The council approved a $1.2M contract with Acme." in html


def test_meeting_detail_upcoming_consent_blurb_forward(app):
    """Upcoming meeting renders the forward-voice consent calendar blurb."""
    today = _dt.date(2026, 5, 18)
    meeting = _meeting(meeting_date=_dt.date(2026, 5, 19))
    consent = [_item(id=10, item_number=10, is_consent=True,
                     meeting_date=_dt.date(2026, 5, 19))]
    html = _render_meeting_detail(app, meeting, today, consent_items=consent)
    assert "expected to pass" in html.lower()
    assert "items passed as a group" not in html.lower()


def test_meeting_detail_past_consent_blurb_completed(app):
    """Past meeting keeps the existing past-tense consent blurb."""
    today = _dt.date(2026, 5, 18)
    meeting = _meeting(meeting_date=_dt.date(2026, 5, 12))
    consent = [_item(id=10, item_number=10, is_consent=True,
                     meeting_date=_dt.date(2026, 5, 12))]
    html = _render_meeting_detail(app, meeting, today, consent_items=consent)
    assert "items passed as a group" in html.lower()
```

- [ ] **Step 2: Run the tests to confirm they fail in the expected way**

Run: `venv/bin/pytest tests/unit/web/test_upcoming_meeting_voice_layer1.py -v`

Expected: Tests collected. The four "upcoming" assertions will FAIL (headline + why_it_matters + Sonnet summary + past-tense consent blurb still render); the four "past meeting" / "today undefined" tests should PASS already.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/unit/web/test_upcoming_meeting_voice_layer1.py
git commit -m "test(web): add failing tests for upcoming-meeting forward voice (Layer 1)"
```

---

### Task 2: Gate `_card_shell.html` (headline + why-it-matters)

**Files:**
- Modify: `src/docket/web/templates/partials/_card_shell.html`

- [ ] **Step 1: Read the existing block structure**

The shell has these template blocks:
- `card_headline_text` (default: `{{ item.headline or item.title }}`) at ~L82
- `card_why_block` (default: renders `<p class="why">{{ item.why_it_matters }}</p>`) at ~L86-90

Both need an upcoming gate. The condition mirrors the existing `today is defined and item.meeting_date >= today` already used for the `Upcoming` chip at L39.

- [ ] **Step 2: Edit `card_headline_text` block to gate the headline**

Replace lines 80-84 in `src/docket/web/templates/partials/_card_shell.html`:

```jinja
    <a class="card-link {% block card_headline_class %}{% endblock %}"
       href="{{ url_for('public.item_detail', slug=card_slug, item_id=item.id) }}">
      {% block card_headline_text %}
        {%- if today is defined and item.meeting_date is not none and item.meeting_date >= today -%}
          {{ item.title }}
        {%- else -%}
          {{ item.headline or item.title }}
        {%- endif -%}
      {% endblock %}
    </a>
```

- [ ] **Step 3: Edit `card_why_block` to suppress why-it-matters on upcoming**

Replace lines 86-90 in `src/docket/web/templates/partials/_card_shell.html`:

```jinja
  {% block card_why_block %}
    {% if item.why_it_matters and not (today is defined and item.meeting_date is not none and item.meeting_date >= today) %}
      <p class="why">{{ item.why_it_matters }}</p>
    {% endif %}
  {% endblock %}
```

- [ ] **Step 4: Run the card_shell tests to confirm they now pass**

Run: `venv/bin/pytest tests/unit/web/test_upcoming_meeting_voice_layer1.py::test_card_shell_upcoming_hides_headline_text tests/unit/web/test_upcoming_meeting_voice_layer1.py::test_card_shell_upcoming_hides_why_it_matters tests/unit/web/test_upcoming_meeting_voice_layer1.py::test_card_shell_past_meeting_unchanged tests/unit/web/test_upcoming_meeting_voice_layer1.py::test_card_shell_today_undefined_safe -v`

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/docket/web/templates/partials/_card_shell.html
git commit -m "feat(web): suppress AI headline + why on upcoming meetings (Layer 1)"
```

---

### Task 3: Gate `meeting_detail.html` (executive summary + consent blurb)

**Files:**
- Modify: `src/docket/web/templates/meeting_detail.html`

- [ ] **Step 1: Replace the Executive Summary section (lines 41-57)**

Find this block in `src/docket/web/templates/meeting_detail.html`:

```jinja
{# ── Executive Summary ────────────────────────────── #}
{% if meeting.executive_summary %}
<section class="exec-summary">
  <h2 class="exec-summary-heading">Executive Summary</h2>
  <p class="exec-summary-body">{{ meeting.executive_summary }}</p>
  <div class="exec-summary-meta">
    {% if meeting.ai_metadata and meeting.ai_metadata.phase == 'provisional' %}
    <span class="badge badge-provisional">Provisional · minutes not yet adopted</span>
    {% elif meeting.ai_metadata and meeting.ai_metadata.phase == 'adopted' %}
    <span class="badge badge-adopted">Adopted</span>
    {% endif %}
    {% if meeting.ai_metadata and meeting.ai_metadata.confidence == 'low' %}
    <span class="badge badge-review">Auto summary — under review</span>
    {% endif %}
  </div>
</section>
{% endif %}
```

Replace with:

```jinja
{# ── Executive Summary ────────────────────────────── #}
{% set _is_upcoming = today is defined and meeting.meeting_date and meeting.meeting_date >= today %}
{% if _is_upcoming %}
<section class="exec-summary exec-summary--upcoming">
  <h2 class="exec-summary-heading">Agenda published</h2>
  <p class="exec-summary-body">
    This agenda was published by the city. The meeting hasn't happened yet, so no
    summary of what was decided is available.
    {% if meeting.agenda_url %}
    <a class="link" href="{{ meeting.agenda_url }}" target="_blank" rel="noreferrer">View the agenda ↗</a>
    {% endif %}
  </p>
</section>
{% elif meeting.executive_summary %}
<section class="exec-summary">
  <h2 class="exec-summary-heading">Executive Summary</h2>
  <p class="exec-summary-body">{{ meeting.executive_summary }}</p>
  <div class="exec-summary-meta">
    {% if meeting.ai_metadata and meeting.ai_metadata.phase == 'provisional' %}
    <span class="badge badge-provisional">Provisional · minutes not yet adopted</span>
    {% elif meeting.ai_metadata and meeting.ai_metadata.phase == 'adopted' %}
    <span class="badge badge-adopted">Adopted</span>
    {% endif %}
    {% if meeting.ai_metadata and meeting.ai_metadata.confidence == 'low' %}
    <span class="badge badge-review">Auto summary — under review</span>
    {% endif %}
  </div>
</section>
{% endif %}
```

- [ ] **Step 2: Replace the consent calendar blurb (line 252)**

Find this line in the Consent Agenda section of `meeting_detail.html`:

```jinja
            <p class="t-meta" style="margin-top: 8px; max-width: 600px;">
                Items passed as a group without individual discussion unless pulled by a council member.
            </p>
```

Replace with:

```jinja
            <p class="t-meta" style="margin-top: 8px; max-width: 600px;">
                {% if today is defined and meeting.meeting_date and meeting.meeting_date >= today %}
                Items expected to pass as a group without individual discussion unless pulled by a council member.
                {% else %}
                Items passed as a group without individual discussion unless pulled by a council member.
                {% endif %}
            </p>
```

- [ ] **Step 3: Run the meeting_detail tests**

Run: `venv/bin/pytest tests/unit/web/test_upcoming_meeting_voice_layer1.py::test_meeting_detail_upcoming_exec_summary_replaced tests/unit/web/test_upcoming_meeting_voice_layer1.py::test_meeting_detail_past_exec_summary_unchanged tests/unit/web/test_upcoming_meeting_voice_layer1.py::test_meeting_detail_upcoming_consent_blurb_forward tests/unit/web/test_upcoming_meeting_voice_layer1.py::test_meeting_detail_past_consent_blurb_completed -v`

Expected: 4 PASS.

- [ ] **Step 4: Commit**

```bash
git add src/docket/web/templates/meeting_detail.html
git commit -m "feat(web): replace exec summary + consent blurb on upcoming meetings (Layer 1)"
```

---

### Task 4: Gate `item_detail.html` (why-it-matters body block) and `card_v2_fallback.html`

**Files:**
- Modify: `src/docket/web/templates/item_detail.html`
- Modify: `src/docket/web/templates/partials/card_v2_fallback.html`

- [ ] **Step 1: Replace the item_detail body block (lines 60-70)**

Find in `src/docket/web/templates/item_detail.html`:

```jinja
{# ── Why it matters + facts ────────────────────────── #}
{% if item.why_it_matters or item.summary %}
<section class="item-body">
    {% if item.why_it_matters %}
    <p class="item-body-why">{{ item.why_it_matters }}</p>
    {% elif item.summary %}
    <p class="item-body-why">{{ item.summary }}</p>
    {% endif %}
    {% include 'partials/_facts_strip.html' %}
</section>
{% endif %}
```

Replace with:

```jinja
{# ── Why it matters + facts ────────────────────────── #}
{% set _item_is_upcoming = today is defined and item.meeting_date and item.meeting_date >= today %}
{% if (item.why_it_matters or item.summary or item.extracted_facts) and not _item_is_upcoming %}
<section class="item-body">
    {% if item.why_it_matters %}
    <p class="item-body-why">{{ item.why_it_matters }}</p>
    {% elif item.summary %}
    <p class="item-body-why">{{ item.summary }}</p>
    {% endif %}
    {% include 'partials/_facts_strip.html' %}
</section>
{% elif _item_is_upcoming and item.extracted_facts %}
<section class="item-body item-body--upcoming">
    {# Facts strip is tense-neutral — keep it. Hide the AI narrative. #}
    {% include 'partials/_facts_strip.html' %}
</section>
{% endif %}
```

Also update the hero `<h1>` at line ~30 from `{{ item.headline or item.title }}` to gate the headline:

Find:
```jinja
            <h1 class="hero-title t-display">{{ item.headline or item.title }}</h1>
```

Replace with:
```jinja
            <h1 class="hero-title t-display">{% if today is defined and item.meeting_date and item.meeting_date >= today %}{{ item.title }}{% else %}{{ item.headline or item.title }}{% endif %}</h1>
```

- [ ] **Step 2: Update `card_v2_fallback.html` headline block**

Find in `src/docket/web/templates/partials/card_v2_fallback.html`:

```jinja
{% block card_headline_text %}
  {{- (item.summary[:80] + '…') if (item.summary and item.summary|length > 80) else (item.summary or item.title) -}}
{% endblock %}
```

Replace with:

```jinja
{% block card_headline_text %}
  {%- if today is defined and item.meeting_date is not none and item.meeting_date >= today -%}
    {{ item.title }}
  {%- else -%}
    {{- (item.summary[:80] + '…') if (item.summary and item.summary|length > 80) else (item.summary or item.title) -}}
  {%- endif -%}
{% endblock %}
```

(The shell's `card_why_block` override stays empty — v2 fallbacks never had a why-it-matters paragraph.)

- [ ] **Step 3: Run the full Layer 1 test suite**

Run: `venv/bin/pytest tests/unit/web/test_upcoming_meeting_voice_layer1.py -v`

Expected: all 8 tests PASS.

- [ ] **Step 4: Run any pre-existing template tests to check for regressions**

Run: `venv/bin/pytest tests/unit/web/ tests/unit/test_smart_brevity_ui_flag.py -v`

Expected: green. Anything new red here is a regression — investigate before continuing.

- [ ] **Step 5: Commit**

```bash
git add src/docket/web/templates/item_detail.html src/docket/web/templates/partials/card_v2_fallback.html
git commit -m "feat(web): gate item_detail body + v2 fallback headline on upcoming meetings (Layer 1)"
```

---

### Task 5: Manual verification + Layer 1 deploy

- [ ] **Step 1: Start the dev server**

Run: `cd /Users/darrellnance/docket-pub && venv/bin/python -m flask --app docket.web run --port 5000` (background)

- [ ] **Step 2: Verify on meeting 2232**

In a browser, open `http://localhost:5000/al/birmingham/meetings/2232/`. Confirm:
- Hero eyebrow still shows the upcoming chip
- Executive Summary section renders the "Agenda published" notice with the agenda link, NOT the Sonnet completed-voice text
- Consent Agenda section blurb says "expected to pass"
- Each item card shows `item.title` (raw agenda text) as the heading, NOT the AI-generated headline
- No `why` paragraph appears under any item

Then visit `http://localhost:5000/al/birmingham/items/<some-item-id-from-2232>/`. Confirm:
- Hero `<h1>` shows `item.title`, not `item.headline`
- No `why_it_matters` paragraph
- Facts strip (dollars, dates) still renders

Spot-check a past meeting (e.g. `/al/birmingham/meetings/1980/`) to confirm everything still renders as before.

- [ ] **Step 3: Open the Layer 1 PR**

```bash
git push -u origin feat/upcoming-forward-voice-layer1  # or whatever branch name
gh pr create --title "Suppress completed-action AI text on upcoming meetings (Layer 1)" --body "$(cat <<'EOF'
## Summary
- Layer 1 of the upcoming-meeting forward-voice spec — template-only suppression of completed-action AI text on upcoming meetings
- Tonight's tactical patch ahead of BHM meeting 2232 (2026-05-19); Layer 2 (forked Haiku/Sonnet prompts + voice column + re-cascade cron) follows in a separate PR
- Spec: docs/superpowers/specs/2026-05-18-upcoming-meeting-forward-voice-design.md

## Test plan
- [x] 8 new template unit tests cover headline/why/exec-summary/consent-blurb across upcoming and past meetings + `today is defined` test-app safety
- [x] Manual: `/al/birmingham/meetings/2232/` reads correctly with chip + notice + raw titles; past meeting (1980) unchanged
- [x] Existing tests/unit/web/ green

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: After PR merge, deploy Layer 1**

```bash
git checkout main && git pull
railway up --service docket-web --detach
```

Layer 1 ships to prod. Verify on `https://docket.pub/al/birmingham/meetings/2232/` and end-state Phase 1 here.

---

## Phase 2: Forward-voice prompt fork (ships next few days)

### Task 6: Centralize the upcoming gate as an `is_upcoming` Jinja filter

Surfaced by PR #71 review. The condition `today is defined and item.meeting_date and item.meeting_date >= today` is repeated across 5+ template sites (`_card_shell.html`, `card_v2_fallback.html`, `meeting_detail.html` exec-summary + consent blurb, `item_detail.html` hero + body, plus the existing PR #68 chip gates in `_vote_result_block.html`, `meeting_card.html`, etc.). Refactor into a single `is_upcoming` Jinja filter so future per-city timezone work and Layer 2 changes only touch one place.

**Files:**
- Modify: `src/docket/web/filters.py` (register `is_upcoming`)
- Modify: each Layer 1 + PR #68 template that uses the gate (find via `grep`)
- Create: `tests/unit/web/test_is_upcoming_filter.py`

- [ ] **Step 1: Write the failing filter test**

Create `tests/unit/web/test_is_upcoming_filter.py`:

```python
"""Tests for the is_upcoming Jinja filter — centralizes the meeting-date
comparison used across upcoming-meeting templates.

Surfaced by PR #71 review.
Spec: docs/superpowers/specs/2026-05-18-upcoming-meeting-forward-voice-design.md
"""
from __future__ import annotations

import datetime as _dt
from types import SimpleNamespace

import pytest

from docket.web.filters import is_upcoming


def test_filter_future_date_returns_true():
    item = SimpleNamespace(meeting_date=_dt.date.today() + _dt.timedelta(days=2))
    assert is_upcoming(item) is True


def test_filter_today_returns_true():
    item = SimpleNamespace(meeting_date=_dt.date.today())
    assert is_upcoming(item) is True


def test_filter_past_date_returns_false():
    item = SimpleNamespace(meeting_date=_dt.date.today() - _dt.timedelta(days=7))
    assert is_upcoming(item) is False


def test_filter_none_meeting_date_returns_false():
    item = SimpleNamespace(meeting_date=None)
    assert is_upcoming(item) is False


def test_filter_dict_input():
    """Works on dict-shaped items (some templates pass dicts)."""
    assert is_upcoming({"meeting_date": _dt.date.today() + _dt.timedelta(days=2)}) is True
    assert is_upcoming({"meeting_date": _dt.date.today() - _dt.timedelta(days=2)}) is False
    assert is_upcoming({}) is False


def test_filter_missing_attribute_returns_false():
    """Defensive: an object with no meeting_date attribute degrades to False
    rather than raising."""
    obj = SimpleNamespace()
    assert is_upcoming(obj) is False
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `venv/bin/pytest tests/unit/web/test_is_upcoming_filter.py -v`

Expected: ImportError or AttributeError — `is_upcoming` not yet defined in `docket.web.filters`.

- [ ] **Step 3: Implement the filter**

Add to `src/docket/web/filters.py`:

```python
import datetime as _dt
from zoneinfo import ZoneInfo as _ZoneInfo

_LOCAL_TZ = _ZoneInfo("America/Chicago")


def is_upcoming(obj) -> bool:
    """Return True if the object's meeting_date is today or in the future.

    Anchored to America/Chicago to match the `today` context processor.
    Accepts objects with a `meeting_date` attribute OR dict-shaped items
    with a `meeting_date` key. Returns False on missing/None values so
    templates can use `{% if item|is_upcoming %}` without guards.
    """
    today = _dt.datetime.now(_LOCAL_TZ).date()
    if isinstance(obj, dict):
        d = obj.get("meeting_date")
    else:
        d = getattr(obj, "meeting_date", None)
    return d is not None and d >= today
```

Then register in the `register()` function (find the existing pattern — likely `app.jinja_env.filters["..."] = ...`):

```python
def register(app):
    ...existing filters...
    app.jinja_env.filters["is_upcoming"] = is_upcoming
```

- [ ] **Step 4: Verify the filter tests pass**

Run: `venv/bin/pytest tests/unit/web/test_is_upcoming_filter.py -v`

Expected: 6 PASS.

- [ ] **Step 5: Find every gate site and refactor to use the filter**

Run: `grep -rn "today is defined and.*meeting_date.*>=\|today is defined and.*meeting_date.*>= *today" src/docket/web/templates/ | sort -u`

For each match, replace the long condition with `item|is_upcoming` or `meeting|is_upcoming`. Examples:

Before:
```jinja
{% if today is defined and item.meeting_date is not none and item.meeting_date >= today %}
```

After:
```jinja
{% if item|is_upcoming %}
```

Sites to update (verify via grep — list may have grown):
- `partials/_card_shell.html` (headline gate + why gate + chip gate from PR #68)
- `partials/card_v2_fallback.html` (headline gate)
- `partials/_vote_result_block.html` (no-vote upcoming branch from PR #68)
- `partials/meeting_card.html` (chip gate from PR #68)
- `meeting_detail.html` (hero chip + exec summary `_meeting_is_upcoming` set + consent blurb)
- `item_detail.html` (hero `<h1>` + `_item_is_upcoming` set)

For `meeting_detail.html` and `item_detail.html`, the `{% set _meeting_is_upcoming = ... %}` lines can be replaced by inline `meeting|is_upcoming` at each use, or kept as a set with `{% set _meeting_is_upcoming = meeting|is_upcoming %}` if multiple uses warrant the local.

- [ ] **Step 6: Run the full template test suite**

Run: `venv/bin/pytest tests/web/ tests/unit/test_card_shell.py tests/unit/test_card_variants_chrome.py tests/unit/test_smart_brevity_card_dispatcher.py tests/unit/test_smart_brevity_ui_flag.py tests/web/test_partials_visual_refactor.py -v`

Expected: green — including the existing PR #71 Layer 1 tests (which use `app_no_today` for the `today is defined` safety case; since the filter resolves today internally, that safety branch is no longer needed, but the test should still pass because the filter degrades gracefully).

If the `today is defined` safety test (`test_card_shell_today_undefined_safe`) fails, update the test to reflect the new behavior: the filter doesn't need `today` to be defined, so the test now asserts the same "headline visible" baseline but via the filter path.

- [ ] **Step 7: Commit**

```bash
git add src/docket/web/filters.py src/docket/web/templates/ tests/unit/web/test_is_upcoming_filter.py
git commit -m "feat(web): centralize upcoming gate as is_upcoming Jinja filter"
```

---

### Task 7: Migration 031 — voice columns

**Files:**
- Create: `src/docket/migrations/031_ai_rewrite_voice.py`
- Modify: `src/docket/migrations/runner.py`

- [ ] **Step 1: Create the migration**

Create `src/docket/migrations/031_ai_rewrite_voice.py`:

```python
"""Migration 031 — voice column for forward-voice (upcoming) AI text.

Adds:
  - agenda_items.ai_rewrite_voice text NULL — values 'completed' | 'upcoming'
  - meetings.executive_summary_voice text NULL — same values

Backfill: every row with non-NULL ai_rewrite_version / executive_summary today
is in completed voice (no upcoming prompt has ever run). Mark them explicitly
so the re-cascade query can rely on the column.

Spec: docs/superpowers/specs/2026-05-18-upcoming-meeting-forward-voice-design.md
"""
from __future__ import annotations


SQL_UP = r"""
ALTER TABLE agenda_items
    ADD COLUMN IF NOT EXISTS ai_rewrite_voice text;

ALTER TABLE meetings
    ADD COLUMN IF NOT EXISTS executive_summary_voice text;

UPDATE agenda_items
   SET ai_rewrite_voice = 'completed'
 WHERE ai_rewrite_version IS NOT NULL
   AND ai_rewrite_voice IS NULL;

UPDATE meetings
   SET executive_summary_voice = 'completed'
 WHERE executive_summary IS NOT NULL
   AND executive_summary_voice IS NULL;
"""

SQL_DOWN = r"""
ALTER TABLE meetings DROP COLUMN IF EXISTS executive_summary_voice;
ALTER TABLE agenda_items DROP COLUMN IF EXISTS ai_rewrite_voice;
"""
```

- [ ] **Step 2: Register in the runner**

Edit `src/docket/migrations/runner.py`, add `"docket.migrations.031_ai_rewrite_voice"` immediately after `"docket.migrations.030_sponsor_trgm_and_hoover"` in the `MIGRATIONS` list (~L43).

- [ ] **Step 3: Apply the migration locally and verify**

Run: `venv/bin/python -m docket.migrations.runner --status`

Expected: `031_ai_rewrite_voice` shown as `[pending]`.

Run: `venv/bin/python -m docket.migrations.runner`

Expected: `applied: 031_ai_rewrite_voice`.

Verify columns exist:

```bash
psql "$DATABASE_URL" -c "\d agenda_items" | grep ai_rewrite_voice
psql "$DATABASE_URL" -c "\d meetings" | grep executive_summary_voice
```

- [ ] **Step 4: Commit**

```bash
git add src/docket/migrations/031_ai_rewrite_voice.py src/docket/migrations/runner.py
git commit -m "feat(db): add ai_rewrite_voice + executive_summary_voice columns (mig 031)"
```

---

### Task 8: Add upcoming prompts and version constants

**Files:**
- Modify: `src/docket/ai/prompts.py`
- Modify: `src/docket/ai/rewrite.py`

- [ ] **Step 1: Add upcoming Sonnet meeting prompt to `prompts.py`**

Append to `src/docket/ai/prompts.py`:

```python
MEETING_PROMPT_UPCOMING_VERSION = 1


MEETING_SYSTEM_UPCOMING = """You are writing a 2-4 sentence executive summary
of an UPCOMING municipal meeting for citizens reading docket.pub.

The meeting has NOT happened yet. The agenda is published; no votes have
been cast and no decisions have been made.

You MUST write in forward-looking voice. Use phrases like:
  - "The council will consider…"
  - "If approved, the resolution would…"
  - "The proposed contract would…"
  - "Scheduled for consideration…"
  - "The agenda includes…"

You MUST NOT use any of these verbs (in any tense that implies a decision
was made): approved, passed, enacted, adopted, awarded, authorized (past
tense), decided, ratified, settled. If your draft contains any of these
words, rewrite it.

The input separates the meeting's substantive items into TWO groups:

- DISTINCTIVE items: those scored higher significance. These are what
  makes this specific meeting newsworthy — proposed major contracts,
  ordinances, policy decisions, settlements, large appropriations,
  citywide rezones. LEAD with these. Mention specific dollar amounts,
  names, and what would happen IF approved.

- ROUTINE items: the recurring business that happens at most meetings —
  proposed building demolitions of unsafe structures, abatement of
  inoperable vehicles or weeds, routine procurement amendments. The
  input gives you these as counts grouped by category. DO NOT lead with
  these even if they are numerically the largest set. They get at MOST
  one closing sentence framed as background, like "The council will
  also consider X proposed demolition orders, Y vehicle abatements, and
  Z routine procurement matters." If there are no routine items, omit
  that sentence entirely.

Do not invent facts not present in the items.
"""
```

- [ ] **Step 2: Add upcoming Haiku rewrite prompt to `rewrite.py`**

In `src/docket/ai/rewrite.py`, after the existing `ITEM_REWRITE_PROMPT_VERSION = 4` (~L30), add:

```python
ITEM_REWRITE_PROMPT_UPCOMING_VERSION = 1
```

After the existing `SYSTEM_PROMPT = """..."""` block (find the closing `"""` of that constant, ~L160-ish — read it first), append:

```python
SYSTEM_PROMPT_UPCOMING = """You are rewriting a single agenda item for citizens
reading docket.pub. The meeting has NOT happened yet — the agenda has been
published but no votes have been cast and no decisions have been made.

You receive:
  (a) the raw item title + description, and
  (b) structured facts extracted in Stage 1: funding source, counterparty,
      procurement method, location (ward/district, neighborhood, address,
      parcel_id), action type, next steps (committee, hearing date/time,
      comment-period end, implementation date).

You MUST write headline and why_it_matters in forward-looking voice. Examples:
  - headline: "Council to consider $1.2M contract with Acme Co."
  - headline: "Proposed ordinance would restrict short-term rentals downtown"
  - why_it_matters: "If approved, the contract would expand recycling to
    three additional wards."
  - why_it_matters: "The resolution would authorize $400K in matching funds
    for the federal grant."

You MUST NOT use any of these verbs in a tense that implies a decision
was made: approved, passed, enacted, adopted, awarded, authorized (past
tense), decided, ratified, settled. If your draft contains any of these
words, rewrite it in conditional voice.

FIRST decide: is this a substantive item or a procedural item? (Same rules
as the standard prompt.) For procedural items, leave headline/why_it_matters
null and confidence "high".

For substantive items:
  - headline: a concise, forward-looking framing of what the council will
    consider (max 80 chars)
  - why_it_matters: a 1-2 sentence forward-looking statement of impact
    IF the item is approved (max 280 chars)
  - significance_score, consent_placement_score: same rubric as standard
  - confidence: "high" / "medium" / "low" as before
"""
```

- [ ] **Step 3: Verify imports still work**

Run: `venv/bin/python -c "from docket.ai.prompts import MEETING_SYSTEM_UPCOMING, MEETING_PROMPT_UPCOMING_VERSION; from docket.ai.rewrite import SYSTEM_PROMPT_UPCOMING, ITEM_REWRITE_PROMPT_UPCOMING_VERSION; print('OK')"`

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add src/docket/ai/prompts.py src/docket/ai/rewrite.py
git commit -m "feat(ai): add forward-voice upcoming prompts (item + meeting)"
```

---

### Task 9: Inspect call sites and add the voice-selection helper

**Files:**
- Modify: `src/docket/ai/rewrite.py`
- Modify: `src/docket/ai/client.py`
- Create: `tests/unit/ai/test_voice_selection.py`

- [ ] **Step 1: Inspect the item rewrite call site**

Run: `grep -n "SYSTEM_PROMPT\|anthropic_client.messages\|rewrite_item\|def rewrite" src/docket/ai/rewrite.py`

The Haiku call somewhere references `SYSTEM_PROMPT` as the `system=` parameter. Identify the function name and signature. Read 30 lines around it.

Read: `src/docket/ai/rewrite.py` (full file)

You need to know: which function takes the StructuredFacts + raw item and calls Anthropic, and where it receives the meeting context (specifically `meeting_date`). If `meeting_date` is not currently passed in, you will need to add it as a parameter and update every caller.

- [ ] **Step 2: Inspect the meeting summary call site**

Run: `grep -n "summarize_meeting\|MEETING_SYSTEM\|MeetingContext" src/docket/ai/client.py`

`client.summarize_meeting(ctx: MeetingContext)` passes `system=MEETING_SYSTEM` per the head we already saw. Read `src/docket/ai/contexts.py` to confirm `MeetingContext` has `meeting_date` (it should — the existing `phase` logic in `MEETING_SYSTEM` is keyed off whether minutes were adopted, which implies the meeting date is in context).

If `MeetingContext` doesn't carry the meeting_date directly, add it.

- [ ] **Step 3: Write the voice-selection test**

Create `tests/unit/ai/test_voice_selection.py`:

```python
"""Tests for the voice-selection helper used by the rewrite + meeting summary
call sites.

Spec: docs/superpowers/specs/2026-05-18-upcoming-meeting-forward-voice-design.md
"""
from __future__ import annotations

import datetime as _dt

import pytest

from docket.ai.rewrite import select_item_voice, ITEM_REWRITE_PROMPT_VERSION, ITEM_REWRITE_PROMPT_UPCOMING_VERSION
from docket.ai.client import select_meeting_voice
from docket.ai.prompts import MEETING_PROMPT_VERSION, MEETING_PROMPT_UPCOMING_VERSION


@pytest.mark.parametrize("meeting_date,today,expected_voice", [
    (_dt.date(2026, 5, 18), _dt.date(2026, 5, 18), "upcoming"),  # today's meeting
    (_dt.date(2026, 5, 19), _dt.date(2026, 5, 18), "upcoming"),  # future
    (_dt.date(2026, 5, 17), _dt.date(2026, 5, 18), "completed"),  # past
    (None, _dt.date(2026, 5, 18), "completed"),  # missing date defaults completed
])
def test_select_item_voice(meeting_date, today, expected_voice):
    prompt, version, voice = select_item_voice(meeting_date, today=today)
    assert voice == expected_voice
    if expected_voice == "upcoming":
        assert version == ITEM_REWRITE_PROMPT_UPCOMING_VERSION
    else:
        assert version == ITEM_REWRITE_PROMPT_VERSION
    assert prompt  # non-empty


@pytest.mark.parametrize("meeting_date,today,expected_voice", [
    (_dt.date(2026, 5, 19), _dt.date(2026, 5, 18), "upcoming"),
    (_dt.date(2026, 5, 17), _dt.date(2026, 5, 18), "completed"),
])
def test_select_meeting_voice(meeting_date, today, expected_voice):
    system, version, voice = select_meeting_voice(meeting_date, today=today)
    assert voice == expected_voice
    if expected_voice == "upcoming":
        assert version == MEETING_PROMPT_UPCOMING_VERSION
    else:
        assert version == MEETING_PROMPT_VERSION
    assert system  # non-empty
```

- [ ] **Step 4: Implement `select_item_voice` in `rewrite.py`**

Add to `src/docket/ai/rewrite.py` (near the top, after the prompt constants):

```python
import datetime as _dt
from zoneinfo import ZoneInfo


def _today_chicago() -> _dt.date:
    return _dt.datetime.now(ZoneInfo("America/Chicago")).date()


def select_item_voice(
    meeting_date: _dt.date | None,
    *,
    today: _dt.date | None = None,
) -> tuple[str, int, str]:
    """Pick the right Stage 2 rewrite prompt + version for this item.

    Returns (system_prompt, prompt_version, voice).
    voice is 'upcoming' or 'completed'.
    """
    if today is None:
        today = _today_chicago()
    if meeting_date is not None and meeting_date >= today:
        return SYSTEM_PROMPT_UPCOMING, ITEM_REWRITE_PROMPT_UPCOMING_VERSION, "upcoming"
    return SYSTEM_PROMPT, ITEM_REWRITE_PROMPT_VERSION, "completed"
```

- [ ] **Step 5: Implement `select_meeting_voice` in `client.py`**

Add to `src/docket/ai/client.py` (near the top of the file):

```python
import datetime as _dt
from zoneinfo import ZoneInfo

from docket.ai.prompts import (
    MEETING_SYSTEM,
    MEETING_SYSTEM_UPCOMING,
    MEETING_PROMPT_VERSION,
    MEETING_PROMPT_UPCOMING_VERSION,
)


def _today_chicago() -> _dt.date:
    return _dt.datetime.now(ZoneInfo("America/Chicago")).date()


def select_meeting_voice(
    meeting_date: _dt.date | None,
    *,
    today: _dt.date | None = None,
) -> tuple[str, int, str]:
    """Pick the right meeting executive-summary prompt + version.

    Returns (system_prompt, prompt_version, voice).
    """
    if today is None:
        today = _today_chicago()
    if meeting_date is not None and meeting_date >= today:
        return MEETING_SYSTEM_UPCOMING, MEETING_PROMPT_UPCOMING_VERSION, "upcoming"
    return MEETING_SYSTEM, MEETING_PROMPT_VERSION, "completed"
```

- [ ] **Step 6: Run the voice-selection tests**

Run: `venv/bin/pytest tests/unit/ai/test_voice_selection.py -v`

Expected: 6 PASS.

- [ ] **Step 7: Wire the helpers into the real call sites**

Read the existing `rewrite_item()` / equivalent call site in `rewrite.py`. Change the line that does `system=SYSTEM_PROMPT` to:

```python
system_prompt, prompt_version, voice = select_item_voice(meeting_date)
# ... existing code using anthropic_client.messages.create(..., system=system_prompt, ...)
```

Threads `meeting_date` from the caller through. Also: every `cache_key(..., ITEM_REWRITE_PROMPT_VERSION, ...)` reference needs `prompt_version` substituted so the upcoming/completed caches don't collide.

Same in `client.summarize_meeting(ctx)`: replace `system=MEETING_SYSTEM` with `system_prompt, version, voice = select_meeting_voice(ctx.meeting_date); ... system=system_prompt`. Return the `voice` alongside the result so the caller can persist it.

This step has the most file-by-file variance — read the surrounding code carefully, keep the diff minimal, and run the existing AI test suite after each change.

- [ ] **Step 8: Run the full AI test suite**

Run: `venv/bin/pytest tests/unit/ai/ -v`

Expected: green. Any new red is a regression — investigate.

- [ ] **Step 9: Commit**

```bash
git add src/docket/ai/rewrite.py src/docket/ai/client.py tests/unit/ai/test_voice_selection.py
git commit -m "feat(ai): select forward-voice prompt for upcoming meetings"
```

---

### Task 10: Persist `ai_rewrite_voice` + `executive_summary_voice` on write

**Files:**
- Modify: `src/docket/ai/worker.py` (legacy pipeline) — only if confirmed live
- Modify: `src/docket/ai/pipeline.py` (v3 pipeline — confirm name) — both item and meeting write paths

- [ ] **Step 1: Identify all write sites for `ai_rewrite_version` and `executive_summary`**

Run: `grep -rn "ai_rewrite_version\s*=\|SET ai_rewrite_version\|SET executive_summary" src/docket/ai/ --include="*.py" | grep -v __pycache__`

Each location that writes those columns needs to also write the matching `*_voice` column from the `voice` returned by the selector.

- [ ] **Step 2: For each write site, add the voice column**

Pattern (item write):

```python
cur.execute(
    """
    UPDATE agenda_items
       SET headline = %s,
           why_it_matters = %s,
           ai_rewrite_version = %s,
           ai_rewrite_voice = %s,
           ...
     WHERE id = %s
    """,
    (headline, why, prompt_version, voice, ..., item_id),
)
```

Pattern (meeting write):

```python
cur.execute(
    """
    UPDATE meetings
       SET executive_summary = %s,
           executive_summary_voice = %s,
           ai_metadata = %s,
           ...
     WHERE id = %s
    """,
    (exec_summary, voice, Json(metadata), ..., meeting_id),
)
```

- [ ] **Step 3: Add an integration test that round-trips voice**

Add to `tests/unit/ai/test_voice_selection.py`:

```python
def test_voice_persisted_on_item_write(monkeypatch, db_cursor_factory):
    """After rewrite_item runs against an upcoming meeting, the row carries
    ai_rewrite_voice='upcoming'."""
    # The exact fixture pattern depends on how existing rewrite.py tests stub
    # the Anthropic client — mirror that pattern here. The assertion is:
    #   row['ai_rewrite_voice'] == 'upcoming' when meeting_date > today
    #   row['ai_rewrite_voice'] == 'completed' when meeting_date < today
    ...  # TODO: copy structure from an existing rewrite test in this dir
```

(Read an existing item-write test in `tests/unit/ai/` to mirror its fixture pattern — keep the new test consistent with project conventions.)

Run: `venv/bin/pytest tests/unit/ai/ -v`

Expected: green.

- [ ] **Step 4: Commit**

```bash
git add src/docket/ai/worker.py src/docket/ai/pipeline.py tests/unit/ai/test_voice_selection.py
git commit -m "feat(ai): persist ai_rewrite_voice + executive_summary_voice on write"
```

---

### Task 11: Re-cascade cron task

**Files:**
- Modify: `src/docket/worker/tasks.py`
- Modify: `src/docket/worker/scheduler.py`
- Create: `tests/unit/worker/test_recast_post_meeting_ai.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/worker/test_recast_post_meeting_ai.py`:

```python
"""Tests for the daily recast_post_meeting_ai cron task.

Spec: docs/superpowers/specs/2026-05-18-upcoming-meeting-forward-voice-design.md §"Re-cascade trigger"
"""
from __future__ import annotations

import datetime as _dt

import pytest

from docket.worker.tasks import _do_recast_post_meeting_ai


def test_recast_picks_up_past_upcoming_items_with_clip_id(db_with_fixtures):
    """An item with ai_rewrite_voice='upcoming' on a past meeting that has a
    clip_id gets reset (processing_status='pending', voice/version NULL)."""
    meeting_id = db_with_fixtures.add_meeting(
        meeting_date=_dt.date(2026, 5, 12),
        clip_id="5678",
        executive_summary_voice="upcoming",
    )
    item_id = db_with_fixtures.add_item(
        meeting_id=meeting_id,
        ai_rewrite_voice="upcoming",
        ai_rewrite_version=1,
        processing_status="completed",
    )

    _do_recast_post_meeting_ai()

    row = db_with_fixtures.fetch_item(item_id)
    assert row["ai_rewrite_voice"] is None
    assert row["ai_rewrite_version"] is None
    assert row["processing_status"] == "pending"


def test_recast_skips_cancelled_meeting_no_evidence(db_with_fixtures):
    """A past upcoming-voice meeting with NO clip_id and NO minutes_url
    is left alone — assumed cancelled, to be cleaned up separately."""
    meeting_id = db_with_fixtures.add_meeting(
        meeting_date=_dt.date(2026, 5, 12),
        clip_id=None,
        minutes_url=None,
        executive_summary_voice="upcoming",
    )
    item_id = db_with_fixtures.add_item(
        meeting_id=meeting_id,
        ai_rewrite_voice="upcoming",
        ai_rewrite_version=1,
    )

    _do_recast_post_meeting_ai()

    row = db_with_fixtures.fetch_item(item_id)
    assert row["ai_rewrite_voice"] == "upcoming"  # untouched
    assert row["ai_rewrite_version"] == 1


def test_recast_skips_future_meeting(db_with_fixtures):
    """A meeting whose date is still in the future is not touched."""
    meeting_id = db_with_fixtures.add_meeting(
        meeting_date=_dt.date.today() + _dt.timedelta(days=2),
        clip_id="5678",
        executive_summary_voice="upcoming",
    )
    item_id = db_with_fixtures.add_item(
        meeting_id=meeting_id,
        ai_rewrite_voice="upcoming",
        ai_rewrite_version=1,
    )

    _do_recast_post_meeting_ai()

    row = db_with_fixtures.fetch_item(item_id)
    assert row["ai_rewrite_voice"] == "upcoming"


def test_recast_does_not_touch_completed_voice_items(db_with_fixtures):
    """Items already in completed voice are left alone."""
    meeting_id = db_with_fixtures.add_meeting(
        meeting_date=_dt.date(2026, 5, 12),
        clip_id="5678",
        executive_summary_voice="completed",
    )
    item_id = db_with_fixtures.add_item(
        meeting_id=meeting_id,
        ai_rewrite_voice="completed",
        ai_rewrite_version=4,
        processing_status="completed",
    )

    _do_recast_post_meeting_ai()

    row = db_with_fixtures.fetch_item(item_id)
    assert row["ai_rewrite_voice"] == "completed"
    assert row["ai_rewrite_version"] == 4
    assert row["processing_status"] == "completed"
```

NOTE: the `db_with_fixtures` fixture pattern is the existing convention in `tests/unit/worker/` and `tests/integration/`. Check one of those files (e.g. `tests/integration/test_minutes_adoption.py`) to mirror the exact fixture name/setup. If no equivalent exists, the existing convention uses real Postgres via `pytest --db` — read `tests/conftest.py` first.

- [ ] **Step 2: Implement `_do_recast_post_meeting_ai` in `tasks.py`**

Add to `src/docket/worker/tasks.py` (near the other `_do_*` functions):

```python
def _do_recast_post_meeting_ai() -> None:
    """Reset upcoming-voice AI text for meetings that have just rolled into
    the past AND have meeting-happened evidence (clip_id or minutes_url).

    The cleared rows get picked up by `ai_items` / `ai_meetings` later that
    morning and rewritten with the completed-action prompt.

    Spec: docs/superpowers/specs/2026-05-18-upcoming-meeting-forward-voice-design.md
    """
    with db_cursor() as cur:
        cur.execute("""
            UPDATE agenda_items
               SET processing_status = 'pending',
                   ai_rewrite_version = NULL,
                   ai_rewrite_voice = NULL
             WHERE id IN (
                 SELECT ai.id
                   FROM agenda_items ai
                   JOIN meetings m ON m.id = ai.meeting_id
                  WHERE ai.ai_rewrite_voice = 'upcoming'
                    AND m.meeting_date < (now() AT TIME ZONE 'America/Chicago')::date
                    AND (m.clip_id IS NOT NULL OR m.minutes_url IS NOT NULL)
             )
        """)
        items_reset = cur.rowcount
        cur.execute("""
            UPDATE meetings
               SET executive_summary = NULL,
                   executive_summary_voice = NULL,
                   ai_metadata = ai_metadata - 'phase' - 'confidence'
             WHERE executive_summary_voice = 'upcoming'
               AND meeting_date < (now() AT TIME ZONE 'America/Chicago')::date
               AND (clip_id IS NOT NULL OR minutes_url IS NOT NULL)
        """)
        meetings_reset = cur.rowcount
    log.info("recast_post_meeting_ai items=%d meetings=%d", items_reset, meetings_reset)
```

Add the entry to the `TASKS` registry near the bottom of the file (look for the existing `TASKS = {...}` dict):

```python
TASKS = {
    ...,
    "recast_post_meeting_ai": lambda: _safe_run("recast_post_meeting_ai", _do_recast_post_meeting_ai),
}
```

- [ ] **Step 3: Register in the scheduler**

Edit `src/docket/worker/scheduler.py`. Add a new `sched.add_job` block after `refresh_backfill_ratio_mv` (~L97-103):

```python
    # Re-cascade upcoming-voice AI text to completed voice the morning after
    # the meeting happens (evidence-gated by clip_id or minutes_url). Fires
    # before ai_items (07:00 CT) so the reset rows get picked up the same
    # morning. Spec: docs/superpowers/specs/2026-05-18-upcoming-meeting-forward-voice-design.md
    sched.add_job(
        TASKS["recast_post_meeting_ai"],
        CronTrigger(hour=4, minute=45, timezone=timezone),
        id="recast_post_meeting_ai",
        coalesce=True,
        max_instances=1,
    )
```

- [ ] **Step 4: Run the tests**

Run: `venv/bin/pytest tests/unit/worker/test_recast_post_meeting_ai.py -v`

Expected: 4 PASS.

Run: `venv/bin/pytest tests/unit/worker/ -v`

Expected: green for the rest of the worker suite.

- [ ] **Step 5: Smoke-test the task manually**

Run: `venv/bin/python -m docket.worker.scheduler --run-once recast_post_meeting_ai`

Expected: completes without exception. Log line shows item + meeting counts (likely 0 if no upcoming-voice rows exist locally yet — the dry first run is the point).

- [ ] **Step 6: Commit**

```bash
git add src/docket/worker/tasks.py src/docket/worker/scheduler.py tests/unit/worker/test_recast_post_meeting_ai.py
git commit -m "feat(worker): add recast_post_meeting_ai daily cron (04:45 CT)"
```

---

### Task 12: Live smoke test against Anthropic

**Files:**
- Create: `tests/live/test_upcoming_prompt_voice_smoke.py`

- [ ] **Step 1: Inspect an existing live test for shape**

Run: `ls tests/live/`

Read one of the existing live tests (e.g. `tests/live/test_ai_pipeline_e2e.py` or similar) to see how they're skip-gated on `ANTHROPIC_API_KEY` and how they stub the DB.

- [ ] **Step 2: Write the live smoke test**

Create `tests/live/test_upcoming_prompt_voice_smoke.py`:

```python
"""Live smoke test for the upcoming-voice prompts. Gated on ANTHROPIC_API_KEY.

Confirms Haiku produces forward-voice output and does not emit forbidden verbs
(approved, passed, enacted, adopted, awarded, decided).

Spec: docs/superpowers/specs/2026-05-18-upcoming-meeting-forward-voice-design.md
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


FORBIDDEN = {"approved", "passed", "enacted", "adopted", "awarded", "decided", "ratified"}


def test_upcoming_item_rewrite_uses_forward_voice():
    """A sample agenda item run through the upcoming prompt produces forward voice."""
    # Mirror the call pattern from the existing live tests — typically:
    #   from docket.ai.rewrite import rewrite_item, select_item_voice
    #   result = rewrite_item(<sample StructuredFacts>, meeting_date=<future>)
    #   assert result.ai_rewrite_voice == "upcoming"
    #   text = (result.headline or "") + " " + (result.why_it_matters or "")
    #   tokens = text.lower().split()
    #   forbidden_hits = FORBIDDEN.intersection(tokens)
    #   assert not forbidden_hits, f"forward-voice prompt emitted past-tense: {forbidden_hits}"
    ...  # implement against the actual rewrite_item signature


def test_upcoming_meeting_summary_uses_forward_voice():
    """A sample MeetingContext for a future meeting produces forward-voice exec summary."""
    ...
```

(Fill in the placeholders against the actual `rewrite_item` / `summarize_meeting` signatures observed in Task 8.)

- [ ] **Step 3: Run the live smoke**

Run: `ANTHROPIC_API_KEY=$(grep ANTHROPIC_API_KEY ~/.docket-pub.env.local | cut -d= -f2-) venv/bin/pytest tests/live/test_upcoming_prompt_voice_smoke.py -v`

Expected: PASS. If FAIL with forbidden verb in output, the prompt needs reinforcement — strengthen the prompt text and re-run.

- [ ] **Step 4: Commit**

```bash
git add tests/live/test_upcoming_prompt_voice_smoke.py
git commit -m "test(ai-live): smoke test forbidden-verbs guard on upcoming prompts"
```

---

### Task 13: Deploy Layer 2

- [ ] **Step 1: Open the Layer 2 PR**

```bash
git push -u origin feat/upcoming-forward-voice-layer2
gh pr create --title "Forward-voice Haiku/Sonnet prompts for upcoming meetings (Layer 2)" --body "$(cat <<'EOF'
## Summary
- New `ITEM_REWRITE_PROMPT_UPCOMING` (Haiku) + `MEETING_SYSTEM_UPCOMING` (Sonnet), selected at queue time when `meeting.meeting_date >= today (America/Chicago)`
- Migration 031 adds `ai_rewrite_voice` + `executive_summary_voice` columns
- Daily 04:45 CT cron `recast_post_meeting_ai` resets upcoming-voice rows once their meeting has happened (gated on `clip_id` or `minutes_url`)
- Cleared rows are picked up by the existing 07:00 `ai_items` / 08:00 `ai_meetings` tasks and rewritten in completed voice
- Spec: docs/superpowers/specs/2026-05-18-upcoming-meeting-forward-voice-design.md

## Test plan
- [x] Voice-selection unit tests (item + meeting)
- [x] Re-cascade cron tests cover happy path, cancelled-meeting skip, future-meeting skip, completed-voice no-op
- [x] Live smoke against Haiku/Sonnet confirms forbidden-verb guard

## Deploy order
1. Merge + checkout main
2. `railway up --service docket-web --detach` (runs migration 031, then restarts web)
3. `railway up --service worker --detach` (restarts worker with new prompt-fork code)

Reverse order would crash the worker — it would try to write `ai_rewrite_voice` before the column exists.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: After PR merge, deploy in order**

```bash
git checkout main && git pull
railway up --service docket-web --detach
# wait for the web deploy to complete (check `railway logs --service docket-web`),
# then:
railway up --service worker --detach
```

- [ ] **Step 3: Verify migration applied**

```bash
railway ssh --service docket-web "python -m docket.migrations.runner --status" | grep 031
```

Expected: `[applied]`.

- [ ] **Step 4: Verify voice on a fresh upcoming item**

The next BHM ingest cycle (`ingest_all` 06:00 CT, then `ai_items` 07:00 CT) should write new items with `ai_rewrite_voice='upcoming'`. Check next morning:

```bash
psql "$DATABASE_PUBLIC_URL" -c "
SELECT m.id, m.meeting_date, m.executive_summary_voice,
       COUNT(ai.id) FILTER (WHERE ai.ai_rewrite_voice = 'upcoming') AS upcoming_items
  FROM meetings m
  LEFT JOIN agenda_items ai ON ai.meeting_id = m.id
 WHERE m.municipality_id = (SELECT id FROM municipalities WHERE slug='birmingham')
   AND m.meeting_date >= (now() AT TIME ZONE 'America/Chicago')::date
 GROUP BY m.id
 ORDER BY m.meeting_date;
"
```

Expected: at least one BHM upcoming meeting with `executive_summary_voice='upcoming'` and a nonzero `upcoming_items` count.

- [ ] **Step 5: Verify re-cascade after one cycle**

After the next BHM Tuesday meeting (whichever one is next after deploy), the morning-after 04:45 CT recast should reset its items. Verify the next day:

```bash
psql "$DATABASE_PUBLIC_URL" -c "
SELECT id, meeting_date, executive_summary_voice
  FROM meetings
 WHERE municipality_id = (SELECT id FROM municipalities WHERE slug='birmingham')
   AND meeting_date BETWEEN (now() AT TIME ZONE 'America/Chicago')::date - 7
                        AND (now() AT TIME ZONE 'America/Chicago')::date - 1
 ORDER BY meeting_date DESC;
"
```

Expected: the just-past meeting reads `executive_summary_voice='completed'` (or NULL briefly between recast at 04:45 and ai_meetings at 08:00, then `'completed'`). If it's still `'upcoming'`, the cron didn't fire — check `railway logs --service worker`.

- [ ] **Step 6: Update CLAUDE.md status table**

Add an entry to the "What's been ported and what hasn't" table in `CLAUDE.md`:

```markdown
| Upcoming-meeting forward voice (Layer 2) | **LIVE** | Migration 031 + `ITEM_REWRITE_PROMPT_UPCOMING` + `MEETING_SYSTEM_UPCOMING` + daily 04:45 CT `recast_post_meeting_ai` cron. Voice persisted in `agenda_items.ai_rewrite_voice` + `meetings.executive_summary_voice`. Re-cascade gated on `clip_id IS NOT NULL OR minutes_url IS NOT NULL` so cancelled meetings stay in upcoming voice. Spec: `docs/superpowers/specs/2026-05-18-upcoming-meeting-forward-voice-design.md`. |
```

Commit:

```bash
git add CLAUDE.md
git commit -m "docs(claude.md): record upcoming-meeting forward-voice Layer 2 live"
```

---

## Self-review notes

- **Spec coverage** — all six spec sections covered: Layer 1 template patch (Tasks 1-5), `is_upcoming` filter refactor from PR #71 review (Task 6), prompt fork (Tasks 8-9), voice column + migration (Tasks 7, 10), re-cascade trigger (Task 11), live smoke (Task 12), deploy ordering (Task 13). The in-process cache audit ("no action needed") and search_vector trigger verification ("automatic") need no implementation tasks.
- **Placeholder check** — Task 10 step 3 and Task 12 step 2 each contain `...  # TODO` to mirror an existing fixture/call shape. That's intentional: the existing fixture conventions live in the codebase and the executor needs to read them; locking in a wrong shape from this plan would be worse than the explicit handoff.
- **Type consistency** — `select_item_voice` and `select_meeting_voice` both return `(prompt, version, voice)`. `voice` is always the literal string `'upcoming'` or `'completed'`, matching the DB enum-like values inserted in Task 10 and read in Task 11's SQL.
- **Cancelled-meeting evidence** — the re-cascade SQL filter is `clip_id IS NOT NULL OR minutes_url IS NOT NULL`, matching the spec's priority 1+2 evidence. The vote_agenda_items tertiary signal is intentionally not in the SQL gate (per spec: it's a tiebreaker, not a sufficient signal).
