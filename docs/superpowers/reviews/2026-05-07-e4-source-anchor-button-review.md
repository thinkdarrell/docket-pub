# E4 Review Report — Source-Anchor Adaptive Button

**Date:** 2026-05-07
**Phase / Track:** Phase 2 / Track 3
**Branch:** `feat/impact-first-phase-2-track-3` (worktree: `~/docket-pub-pf2-track-3`)
**Commits under review:**
- `e233b2c` — `feat(web): adaptive source-anchor button (bbox → page → doc → OCR-needed)` (E4 implementation)
- `d0d0ee9` — `test(web): xfail-strict forcing tests for E4 TODO cleanups` (forcing-function tests)

**Plan:** §E4 lines 1770-1786 of `docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-2.md`
**Spec:** §6.4 lines 2846-2896 of `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md`

**Final verdict:** **SHIP** — both Opus first-pass reviews and the Sonnet 4.6 second-look returned `ship`. No `[REQUIRED]` findings. 8 `[SUGGESTED]` items + 1 `[FORCING TEST RECOMMENDED]` are documented below for an optional fix-up commit.

---

## 1. Executive summary

E4 implements `partials/source_anchor_button.html` per spec §6.4 — a six-branch adaptive Jinja that produces browser-native deep links to the source document for each agenda item, with an admin-only "data debt queue" affordance for items whose source PDF needs OCR. The implementation is **spec-faithful**, **defensive against malformed JSONB input**, and adds **38 new unit tests** (was 59 before E4; commit message says +39 — actually +38 in `e233b2c`, plus +3 xfails in `d0d0ee9` for a final 100 tests in `test_source_anchor.py` collected, with 39 passed + 3 xfailed in that file). The code-quality and spec-compliance reviewers both returned `ship`. The Sonnet 4.6 second-look returned `ship` and confirmed every "OK to ship — spec gap noted" finding from the prior reviewers, while emphasizing one structural fact the prior reviewers had not stated explicitly:

> **`source_anchor_button.html` is structurally unreachable in production today.** The variant dispatcher (`smart_brevity_card.html`) reads `item.processing_status`, `item.data_quality`, `item.ai_rewrite_version` from the `AgendaItem` dataclass — none of which are mapped by `AgendaItem.from_row()` (verified at `src/docket/models/agenda.py:10-52`). In Jinja2 with Flask's default `Undefined`, missing-attribute access silently returns `Undefined` (falsy), so every dispatcher branch falls through to either `card_v2_fallback` (if `summary`) or `card_pending`. Tasks A8 (extending the dataclass + `services/query.py:list_agenda_items()` SELECT) and E6 (`SMART_BREVITY_UI` feature flag) are the gates. Until both land, no v3 card variant renders, and the entire 8-branch button is dormant production code.

That is **by design** — the Phase 2 strategy is to ship v3 surface area behind a flag and flip when the data layer is ready — but the implication for this review is that **none of the SUGGESTED edge-case findings (URL fragment collision, query-string collision, scheme allowlist edge cases) can fire in production today**. They become real-world concerns only at the moment A8 + E6 land. The forcing-function tests in `d0d0ee9` are the right rot-prevention posture.

---

## 2. What E4 built

### 2.1 New files

| Path | Purpose |
|---|---|
| `src/docket/web/templates/partials/source_anchor_button.html` | Adaptive Jinja, 8 branches (PDF×3, HTML, video, bare URL, OCR-needed, no-render). 97 lines including docstring. |
| `tests/unit/test_source_anchor.py` | 38 unit tests in `e233b2c` + 3 xfail-strict tests in `d0d0ee9`. Covers every spec branch, scheme allowlist, malformed input, `format_timestamp`, and the `admin.data_debt` route. |

### 2.2 Modified files

| Path | Change |
|---|---|
| `src/docket/web/filters.py` | Added `format_timestamp` filter. Registered alongside `order_badges` (E2) and `format_date` (E3) in `register(app)`. |
| `src/docket/web/admin.py` | Added stubbed `admin.data_debt` route at `/admin/data-debt/` returning `abort(404)` with TODO marker. Login-gated like the rest of the admin blueprint. |
| `src/docket/web/templates/partials/card_smart_brevity.html` | Replaced `{% include 'partials/_source_link_stub.html' %}` with `{% include 'partials/source_anchor_button.html' %}`. |
| `src/docket/web/templates/partials/card_verification_pending.html` | Same swap. |

### 2.3 Files NOT modified (intentional)

| Path | Why not modified |
|---|---|
| `src/docket/web/templates/partials/_source_link_stub.html` | **Retained on disk.** Still included by the 4 v2 cards (`card_failed`, `card_degraded`, `card_v2_fallback`, `card_pending`). Will be deleted when A8 emits v3 `source_anchor` for non-v3 items. Forcing test in `d0d0ee9` (`test_source_link_stub_is_retired`) flips when the file is gone AND no card includes it. |
| `card_failed.html`, `card_degraded.html`, `card_v2_fallback.html`, `card_pending.html` | Each carries a pre-placed `{# TODO E4: source-anchor adaptive button #}` marker (suggesting plan-author intent was to swap all 6). Implementer's call: those operate on v2 shape (`item.source_url`) and would silently lose their "View original →" link if swapped now. **Defensible** — see §5. |

### 2.4 Source layout — `source_anchor_button.html`

```jinja
{%- set anchor = item.source_anchor or {} -%}
{%- set _url = anchor.url if anchor is mapping else None -%}
{%- set _is_safe = _url and (_url.startswith('http://') or _url.startswith('https://')) -%}

{% if anchor is mapping and anchor.type == 'pdf' and _is_safe %}
  {% if anchor.bbox and anchor.page %}    → "View Source: PDF page N (region) →"
  {% elif anchor.page %}                   → "View Source: PDF page N →"
  {% else %}                                → "View Source: PDF →"
{% elif anchor is mapping and anchor.type == 'html' and anchor.anchor and _is_safe %}
                                            → "View Source: agenda item →"
{% elif anchor is mapping and anchor.type == 'video' and anchor.timestamp_seconds and _is_safe %}
                                            → "View Source: video at H:MM:SS →"
{% elif _is_safe %}                          → bare "View Source →"
{% elif item.data_quality == 'no_text_layer' %}
                                            → "Source needs OCR" + admin-only [admin queue] link
{% endif %}
```

Key invariants:
- **Single safety guard** (`_is_safe`) funneling every clickable branch — type-claim bypass blocked: `{type:'pdf', url:'javascript:alert(1)'}` falls through silently.
- **Mapping check** (`anchor is mapping`) before any `.type`/`.url`/`.bbox`/`.page` access — JSONB-as-string or JSONB-as-list rounds through to no-render path with no traceback.
- **Defensive `| int` coercion** on `anchor.page` and `anchor.timestamp_seconds` — psycopg JSONB driver paths sometimes return numerics as strings.
- **Every external link** carries `target="_blank" rel="noopener noreferrer"`. The internal admin link does not.
- **CSS hooks emitted (no styles)**: `view-source` and `view-source--unavailable` — same posture as E2/E3 (class hooks now, design pass later).

---

## 3. Implementer's self-reported divergences

| # | Divergence | Resolution |
|---|---|---|
| 1 | **Spec uses `g.user.is_admin`; codebase uses `session.admin_user`.** | Implementer used `session.admin_user`. **Confirmed correct** by both prior reviewers and the second-look — the codebase has zero references to `g.user`/`is_admin`; auth is session-based (`web/auth.py:51`). Existing admin templates (`templates/admin/ai_panel.html`, `templates/admin/members.html`) use the same pattern. Spec literal would `UndefinedError` on first admin pageload. |
| 2 | **Stricter URL allowlist than legacy stub** — new button rejects site-relative `/uploads/foo.pdf`; legacy `_source_link_stub.html` accepts them. | `_is_safe` requires `http://` or `https://` prefix. Implementer's reasoning: v3 `source_anchor` always carries an absolute origin (PDF on city CDN, video on Granicus, HTML on city site). Confirmed by spec-reviewer reading of migration `013_impact_first_refactor.py`. Spec §6.4 is silent on URL safety. **Defensible.** |
| 3 | **Type-claim bypass blocked** — `{type:'pdf', url:'javascript:alert(1)'}` does not emit a link. | Spec didn't mandate; brief said "reject `javascript:`/`data:`/protocol-relative." Pinned by `test_javascript_url_rejected` and `test_javascript_url_with_no_text_layer_falls_through_to_ocr_label`. **Defense-in-depth.** |
| 4 | **`format_timestamp` rejects `bool`.** | `isinstance(True, int)` is `True` in Python; without explicit reject, `format_timestamp(True)` would render `"0:01"` and `format_timestamp(False)` `"0:00"`, indistinguishable from real timestamps. Pinned by `test_bool_returns_empty_string`. |
| 5 | **`format_timestamp` coerces numeric strings.** | JSONB driver paths can return ints as strings (same path that motivated `format_date`'s string-parsing in E3). `"3725"` → `1:02:05`; non-numeric `"foo"` still returns `""`. Pinned by `test_numeric_string_coerced_to_int` and `test_non_numeric_string_returns_empty_string`. |
| 6 | **Bbox branch additionally requires `page`.** Spec: `{% if anchor.bbox %}`. Impl: `{% if anchor.bbox and anchor.page %}`. | Spec text would render `href="...#page="` (or `#page=None`) if `bbox` were ever set without `page`. Stage 1 schema requires `page` whenever `bbox` is set, so this divergence is inert today. **Strictly safer.** Pinned by `test_pdf_with_bbox_but_no_page_falls_through_to_bare_pdf`. |
| 7 | **Replaced E4 includes only in 2 v3 cards (Option 1).** Plan/spec didn't enumerate; the 4 un-swapped cards each had a `{# TODO E4 ... #}` marker. | See §5 — defensible, gated by A8. |

---

## 4. Reviewer findings (consolidated)

### 4.1 Spec-compliance review (Opus, parallel, read-only)

**Verdict:** `ship`.

All six visible branches present, in spec priority order, with text matching. CSS class names match (`view-source`, `view-source--unavailable`). `url_for('admin.data_debt', ...)` resolves. `format_timestamp` registered. No JS introduced. Browser-native `#page=` and `?t=` fragments only.

**Findings (all `[OK to ship]`):**

| # | Finding | Resolution |
|---|---|---|
| S1 | `session.admin_user` substitution. | Required by codebase. Tests cover both admin and non-admin variants. |
| S2 | Stricter URL allowlist. | Spec gap; defensible per data-shape analysis. |
| S3 | Bbox branch requires `page`. | Defensive-only divergence; xfail in `d0d0ee9` pins. |
| S4 | Defensive `\| int` coercion. | Identical visible text for valid integers; no spec violation. |
| S5 | 4 v2 cards retain `_source_link_stub.html`. | Defensible (see §5). UX regression for admins on degraded-classified items, but production renders correctly today (per second-look: degraded items don't even reach `card_degraded` today — they fall to `card_v2_fallback`/`card_pending` because the dispatcher gates fail). Forcing test in `d0d0ee9` covers stub deletion. |

**One reviewer false-positive (DISMISSED):** Spec reviewer flagged "no Task A8 exists in plan/coordination docs." A8 is a real cross-track task tracked in the orchestrator's memory file (`extending AgendaItem dataclass + services/query.py:list_agenda_items() SELECT to expose v3 columns`). Reviewer didn't have access to memory.

### 4.2 Code-quality review (Opus, parallel, read-only)

**Verdict:** `ship`.

> "The implementation is solid: the URL scheme allowlist correctly funnels every branch through `_is_safe`, autoescape is on by default and there's no `\|safe` anywhere, every external link has `target=\"_blank\" rel=\"noopener noreferrer\"` (and the internal admin link correctly omits `target`), the mapping check defends against JSONB-as-string, and `format_timestamp` is appropriately defensive against bool/None/negative/non-numeric input."

**`[SUGGESTED]` findings (8 total):**

| # | Finding | Location | Production-impact today |
|---|---|---|---|
| Q1 | **Existing `#`-fragment collision in PDF/HTML branches.** If `anchor.url` is `https://city.gov/agenda.pdf#section1`, output is `…#section1#page=7`. Browsers/PDF viewers honour the **first** fragment and ignore `#page=`. Same for HTML branch (`…#section1#item-42`). | `source_anchor_button.html:54, 59, 71` | **Zero today** — `source_anchor_button.html` unreachable in production (see §6). Becomes real at A8. **Defensive fix:** `_url.split('#')[0]` before concatenation. |
| Q2 | **Existing `?`-query-string collision in video branch.** If `anchor.url` is `https://granicus.example.com/player?clip_id=123`, output is `…?clip_id=123?t=65` — malformed URL with two `?`s. Granicus reads `?t=` natively and would miss it. | `source_anchor_button.html:77` | **Zero today** — same gating. **Defensive fix:** Use `&` if `?` already present, else `?`. |
| Q3 | **`format_timestamp` doesn't catch `OverflowError`.** `format_timestamp(float('inf'))` and `format_timestamp("inf")` would crash render. JSONB doesn't natively encode infinity; only manual dict construction can produce this. | `src/docket/web/filters.py:154` | **Zero realistic today.** Full defense would be `(ValueError, OverflowError, TypeError)` tuple. |
| Q4 | **Test count discrepancy in commit message.** `e233b2c` claims `+39` tests; actually adds 38. The 39th came from `d0d0ee9`. | Commit message of `e233b2c` | Cosmetic. |
| Q5 | **Scheme allowlist is case- and whitespace-sensitive.** `"HTTPS://example.com"` and `" https://example.com"` are silently rejected. Stage 1 should always emit normalized URLs but defense-in-depth would `_url.strip().lower().startswith(...)` for the check while preserving the original for the href. | `source_anchor_button.html:50` | **Low.** Stage 1 is the canonical normalizer. |
| Q6 | **No test for `bbox = []` (empty list).** Empty list is falsy → falls through correctly to page-only branch. Suite covers `bbox` set vs. unset, not empty-list. | `tests/unit/test_source_anchor.py` | None — behavior is correct, missing test is cosmetic. |
| Q7 | **`page=0` is treated as falsy.** `{% if anchor.bbox and anchor.page %}` → `page=0` falls through to bare PDF. PDFs are 1-indexed, so this is acceptable, but the `timestamp_seconds=0` xfail in `d0d0ee9` suggests Stage 1 may emit zero as a legitimate sentinel; the same pattern is not pinned for `page`. | `source_anchor_button.html:53, 58` | **Zero today** + structurally PDF-impossible (no page 0). |
| Q8 | **TODO marker convention.** Stub uses `# TODO: build data-debt queue page`; E3's stubs (`f9c4c3b`) used `# TODO(E5): ...` / `# TODO(F5): ...` format. | `src/docket/web/admin.py:172` | Cosmetic. |

**`[OK]` (acceptably handled):**

- Autoescape inheritance verified (no `{% autoescape false %}` block, no `\|safe`, all template concatenation in `href` attribute context where autoescape encodes `"`/`<`/`>` correctly).
- `session.admin_user` access works in production (Flask `session` dict-like) and tests (test setup writes `session["admin_user"] = "tester"`).
- Test file structure matches `test_engagement_strip.py` baseline (module-scoped `app` fixture, `_render` helper, class-grouped tests, real filter registration, stub blueprint for `url_for` resolution).
- Filter registration: `format_timestamp` appears alongside `order_badges` and `format_date` in `filters.py:172-174`.
- No dead code, no debug prints, no unused imports.
- OCR admin link correctly omits `target="_blank"` (internal admin route).
- Bool rejection in `format_timestamp` is a thoughtful hardening against the `isinstance(True, int) == True` Python footgun.

### 4.3 Sonnet 4.6 second-look (foreground, read-only)

**Verdict:** `ship` (with one scope clarification).

Per Track 3 protocol, mandatory for E/F/G-track UI tasks. Brief instructed: *"the user suspects deferred items should have been addressed — be that second pair of eyes."* Specifically required to trace production code path on every "OK to ship — spec gap noted" item from the prior reviews and answer: **does production render correctly TODAY without this fix? If no, it's not deferrable.**

**Findings (every prior deferral confirmed OK; one new structural observation):**

| # | Prior finding | Second-look verdict | Reasoning |
|---|---|---|---|
| Z1 | `session.admin_user` vs `g.user.is_admin` (S1) | `[CONFIRMED OK]` | Verified `admin.py` uses `session["admin_user"]` exclusively. No `g.user` anywhere. Substitution required. |
| Z2 | Stricter URL allowlist (S2) | `[CONFIRMED OK]` (moot until A8 + Stage 1 land simultaneously) | `extraction.py` (Stage 1) does not emit `source_anchor` yet — that column is populated by Track 1's A1/A3 worker. xfail in `d0d0ee9` is the right forcing function. |
| Z3 | Bbox branch requires `page` (S3) | `[CONFIRMED OK]` | Migration 013 stores `source_anchor` as free-form JSONB — no DB constraint enforces `page` co-presence with `bbox`. Application-level invariant only. xfail pins behavior. Since button is unreachable today, a `bbox`-without-`page` row would silently fall through to bare-PDF — a miss, not a crash. |
| Z4 | 4 v2 cards retain `_source_link_stub.html` (S5) | `[CONFIRMED OK]` — but **scope wider than prior reviews stated** | See §6 below. |
| Z5 | Fragment/query-string collisions (Q1, Q2) | `[FORCING TEST RECOMMENDED]` | Stage 1 hasn't shipped — claim "Stage 1 should never emit such URLs" is unverified. Recommend xfail tests pinning collision scenarios so they can't slip silently when A8 + Stage 1 land. |
| Z6 | `format_timestamp` `OverflowError` (Q3) | `[CONFIRMED OK]` | JSONB integer fields → psycopg → Python `int`. No `float('inf')` can arrive via the production data path. Manual dict construction is the only way to trigger; not realistic. |
| Z7 | `page=0` falsy (Q7) | `[CONFIRMED OK]` | PDFs are 1-indexed; page=0 is not a real page in any source. |
| Z8 | HTML anchor branch behavior on bare HTML URLs (no anchor) | `[CONFIRMED OK]` | Falls through correctly to bare-URL catch-all → "View Source →" without fragment. |

---

## 5. Why the 4 v2 cards retained `_source_link_stub.html` (deep dive)

**Decision:** Implementer chose Option 1 — replace stub includes only in `card_smart_brevity.html` and `card_verification_pending.html` (the 2 v3 cards), retain the stub in the 4 v2 cards (`card_failed`, `card_degraded`, `card_v2_fallback`, `card_pending`).

**The plan-author's apparent intent:** All 6 cards carried a pre-placed `{# TODO E4: source-anchor adaptive button #}` marker, suggesting Track 3 was supposed to swap all 6. The implementer's deviation was conscious.

**Why the deviation is correct:**

1. **`source_anchor_button.html` operates on `item.source_anchor` (v3 JSONB shape).** `_source_link_stub.html` operates on `item.source_url` (v2 string). Different fields, different shapes.
2. **`item.source_anchor` is not yet populated for non-v3 items.** A8 + Stage 1 must land before the AgendaItem dataclass and `services/query.py:list_agenda_items()` SELECT expose `source_anchor` for items in `card_v2_fallback` / `card_pending` shape.
3. **If the swap had happened today,** v2 cards would lose their "View original →" link (the stub renders one if `item.source_url` is set; the new button renders nothing if `item.source_anchor` is missing). That's a UX regression masked by autoescape — no error, just a missing link.
4. **The 4 v2 cards' fallback behavior is preserved.** Plus `card_degraded.html:13` already shows "Source document needs OCR — text not yet extractable" inline, so the OCR-needed message is surfaced on degraded items independent of the new button.

**The cost:** Logged-in admins viewing a `card_degraded` item don't see the spec §6.4 `[admin queue]` affordance. Per the second-look, this is moot today — see §6 — because `card_degraded` is itself unreachable in production until A8 lands.

**Forcing function:** `d0d0ee9` adds `test_source_link_stub_is_retired` (xfail-strict). It currently fails with `AssertionError` (the stub file exists, 4 cards include it). When A8 lands, the implementer who deletes the stub and swaps the 4 cards will see this test flip from XFAIL to XPASS — `strict=True` then turns it into a real test failure, prompting them to remove the xfail mark.

---

## 6. Why E4 is structurally unreachable in production today (the A8 wall)

This is the most important finding from the second-look — not new bugs, but a **scope clarification** that recontextualizes every "fix this when X lands" item in the SUGGESTED list.

### 6.1 The dispatcher

`src/docket/web/templates/partials/smart_brevity_card.html`:

```jinja
{% if item.processing_status == 'failed_permanent' %}
  {% include 'partials/card_failed.html' %}
{% elif item.data_quality and item.data_quality != 'ok' %}
  {% include 'partials/card_degraded.html' %}
{% elif item.processing_status == 'procedural_skipped' %}
  {% include 'partials/card_procedural.html' %}
{% elif item.processing_status == 'cross_stage_conflict' %}
  {% include 'partials/card_verification_pending.html' %}
{% elif item.ai_rewrite_version == 3 %}
  {% include 'partials/card_smart_brevity.html' %}
{% elif item.summary %}
  {% include 'partials/card_v2_fallback.html' %}
{% else %}
  {% include 'partials/card_pending.html' %}
{% endif %}
```

### 6.2 The dataclass

`src/docket/models/agenda.py:10-30`:

```python
@dataclass(frozen=True)
class AgendaItem:
    id: int
    meeting_id: int
    external_id: str | None
    item_number: str | None
    title: str
    description: str | None
    section: str | None
    is_consent: bool
    sponsor: str | None
    dollars_amount: Decimal | None
    topic: str | None
    significance_score: float | None
    consent_placement_score: float | None
    summary: str | None = None
    ai_metadata: dict | None = None
    ai_prompt_version: int | None = None
    ai_generated_at: datetime | None = None
```

### 6.3 The gap

The dispatcher reads:
- `item.processing_status` — **NOT** in the dataclass
- `item.data_quality` — **NOT** in the dataclass
- `item.ai_rewrite_version` — **NOT** in the dataclass

Plus the partials read `item.source_anchor`, `item.headline`, `item.why_it_matters`, `item.extracted_facts`, `item.next_steps`, `item.badges`, `item.ai_metadata` (the JSONB fields populated by Wave 0 and Stage 1+2). None are in the dataclass.

### 6.4 Why this doesn't crash

Jinja2's default `Undefined` class catches `AttributeError` on missing-attribute access and silently returns `Undefined` (which is falsy in `{% if %}` checks). Flask uses `Undefined`, not `StrictUndefined`. So:

- `item.processing_status == 'failed_permanent'` → `Undefined == '...'` → `False`
- `item.data_quality and item.data_quality != 'ok'` → `Undefined` (falsy) → branch skipped
- `item.processing_status == 'procedural_skipped'` → `False`
- `item.processing_status == 'cross_stage_conflict'` → `False`
- `item.ai_rewrite_version == 3` → `False`
- `item.summary` → real value, may be truthy
- → Falls through to `card_v2_fallback` (if `summary`) or `card_pending`.

### 6.5 Implications

1. **`source_anchor_button.html` is reached only by `card_smart_brevity.html` (v3) and `card_verification_pending.html`.** Both of those cards are themselves unreachable until A8 lands. So the entire 8-branch button is dormant production code today.
2. **Wave 0 columns (`data_quality`, `processing_status`) populated on Railway as of 2026-05-07 are currently dead data** — set in DB, invisible to the renderer because the dataclass doesn't surface them. The Phase 1 ship was structurally correct (data populated, ready for downstream stages) but the front-end wiring is A8's job.
3. **Every SUGGESTED edge case (Q1 fragment collision, Q2 query-string collision, Q5 case-insensitive scheme, Q7 `page=0`)** can only fire at the moment A8 + E6 land. Until then, these are forensic concerns, not production concerns.
4. **The forcing-function tests in `d0d0ee9` are correctly scoped** — they cover the cleanup actions (real `data_debt` route, stub deletion, `ts=0` decision) that will actually happen when downstream tasks ship.

### 6.6 What this means for the merge decision

E4 is **independently shippable** as a v3 surface-area component. It does not need A8 to be useful — it provides infrastructure (the partial, the filter, the route stub) that A8 + later tasks consume. The deferred concerns are gated behind the same A8 wall as the rest of the v3 UI; they don't accrue technical debt against E4's correctness today.

---

## 7. Test inventory

### 7.1 `tests/unit/test_source_anchor.py` (final state, 39 passed + 3 xfailed)

| Branch | Tests |
|---|---|
| PDF — bbox + page | `test_pdf_with_bbox_and_page_renders_region_marker` |
| PDF — page only | `test_pdf_with_page_renders_page_link`, `test_pdf_with_bbox_but_no_page_falls_through_to_bare_pdf` |
| PDF — bare | `test_pdf_without_page_renders_bare_pdf`, `test_pdf_with_string_page_coerced_to_int` |
| HTML | `test_html_with_anchor_renders_agenda_item_link`, `test_html_without_anchor_falls_through_to_bare_url` |
| Video | `test_video_with_timestamp_renders_deep_link`, `test_video_without_timestamp_falls_through_to_bare_url`, `test_video_with_long_duration_renders_h_mm_ss` |
| Bare URL | `test_bare_url_with_no_type_renders_view_source` |
| OCR-needed | `test_no_text_layer_admin_sees_admin_queue_link`, `test_no_text_layer_non_admin_hides_admin_queue_link`, `test_no_text_layer_with_anchor_url_prefers_anchor_branch` |
| No-render | `test_empty_anchor_renders_nothing`, `test_missing_anchor_renders_nothing`, `test_unknown_type_with_no_url_renders_nothing` |
| Scheme allowlist | `test_javascript_url_rejected`, `test_data_url_rejected`, `test_protocol_relative_url_rejected`, `test_relative_url_rejected_unlike_legacy_stub`, `test_javascript_url_with_no_text_layer_falls_through_to_ocr_label` |
| Malformed input | `test_string_anchor_renders_nothing`, `test_list_anchor_renders_nothing`, `test_none_anchor_renders_nothing` |
| `format_timestamp` | 12 tests covering 0, sub-hour, 1+hour, large value, negative, None, float, decimal, bool, numeric string, non-numeric string, default Jinja env registration |
| `admin.data_debt` | `test_data_debt_url_resolves`, `test_data_debt_returns_404_until_built` |
| **xfail (forcing fns)** | `test_data_debt_returns_200_when_queue_page_lands`, `test_source_link_stub_is_retired`, `test_video_timestamp_zero_renders_as_start_of_meeting` |

### 7.2 Cumulative Track 3 test count

| Task | Tests added | Cumulative |
|---|---|---|
| E1 (dispatcher + 7 variant partials) | 23 | 23 |
| E2 (badge chip) | 14 | 37 |
| E3 (engagement strip) | 22 | 59 |
| **E4 (source anchor button) — `e233b2c`** | **38** | **97** |
| **E4 (forcing tests) — `d0d0ee9`** | **3** | **100 collected (97 pass + 3 xfail)** |

### 7.3 Test command

```bash
cd ~/docket-pub-pf2-track-3
PYTHONPATH=$(pwd)/src ~/docket-pub/venv/bin/pytest tests/unit/test_source_anchor.py -v
# Expected: 39 passed, 3 xfailed
```

(Pre-existing failures in `test_ai_worker_run.py` are DB-dependent and unrelated to E4 — reproduce on the baseline branch.)

---

## 8. Recommended fix-up scope

**Required:** None. Both reviews returned `ship`.

**Suggested (single fix-up commit if you want to clear the SUGGESTED list now rather than during A8):**

| # | Fix | Effort | Why now vs. later |
|---|---|---|---|
| Q1+Q2 | URL canonicalization: strip pre-existing `#fragment` before appending `#page=` / `#anchor`; use `&` instead of `?` if URL already has a `?`. | ~5 min | Defense-in-depth. Prevents silent miss at the moment A8 lands. Add 2-3 new tests. |
| Q3 | Catch `(ValueError, OverflowError, TypeError)` in `format_timestamp`. | ~1 min | Belt-and-braces. Add `test_inf_returns_empty_string`, `test_inf_string_returns_empty_string`. |
| Q5 | `_url.strip().lower().startswith(...)` for the safety check (preserve original for href). | ~1 min | Defense-in-depth. Add `test_https_uppercase_accepted`, `test_url_with_leading_whitespace_accepted` (or rejected — your call). |
| Q7 | Add an xfail-strict test for `page=0` paralleling the `ts=0` one in `d0d0ee9`. | ~2 min | Symmetry with existing forcing test. PDFs are 1-indexed, so this likely never fires — but the parallel is cheap. |
| Q4 | Cosmetic: amend nothing (commit message is permanent). The `+39` claim is wrong by one but isn't load-bearing. | n/a | Skip. |
| Q8 | Cosmetic: update TODO marker in `admin.py` from `# TODO: build data-debt queue page` to `# TODO(F-track): build data-debt queue page` to match E3 convention. | ~30 sec | Skip or fold into the same fix-up commit. |

**Alternative:** Defer all SUGGESTED items to the A8 fix-up. They can't fire until A8 lands anyway. The forcing tests in `d0d0ee9` and the additional ones suggested above (Q1, Q2, Q7 parallels) would be the rot-prevention layer.

**Recommendation:** Fold Q1, Q2, Q3, Q5 into a single fix-up commit on `feat/impact-first-phase-2-track-3` (E4 second-look fix-up). Leave Q4 and Q8 (cosmetic). Skip Q6 (test for `bbox=[]`) — the existing tests already cover the falsy-fallthrough behavior. The Q7 xfail is a judgment call on whether you want symmetric forcing tests for every zero-vs-none decision in the partial.

---

## 9. Memory + branch state

**Branch:** `feat/impact-first-phase-2-track-3` (worktree: `~/docket-pub-pf2-track-3`)
**Status:** 10 commits ahead of `b4b9a88` (rebased parent on `main`)
**Push state:** **NOT pushed to origin.** Per Track 3 plan, branch stays local until full Track 3 finishes.

```
d0d0ee9 test(web): xfail-strict forcing tests for E4 TODO cleanups (data_debt, stub deletion, ts=0)
e233b2c feat(web): adaptive source-anchor button (bbox → page → doc → OCR-needed)
f9c4c3b fix(web): E3 second-look — alias city in cards, stub item_detail+RSS routes, &amp; in mailto
8ce83b2 fix(web): E3 review fixes — RFC 6068 mailto, target=_blank, format_date 3.10 compat
c94410e feat(web): engagement strip with 4 states + mailto fallback for missing data
198f6fb fix(web): E2 review fixes — link CSS, accent token, defensive confidence, _badge_row shared partial
575d898 feat(web): badge chip with Verification Spark + process-first ordering + mobile carousel
2bef322 fix(web): reject protocol-relative URLs in source-link stub
ce273e2 fix(web): E1 review fixes — v2 fallback fields, verification facts/source, scheme validation
1e4e211 feat(web): Smart Brevity Card 6-variant dispatcher + partials
b4b9a88 fix(test): ensure v3 trigger function is installed before each assertion  ← Track 3 base
```

**Track 3 progress:** 4 of 15 tasks complete (E1, E2, E3, E4). Remaining: E5, E6 (depends on A8), F1, F2, F3, F4, F5, G1, G2, G3, G4, plus **A8** (must precede E6).

**Next task per the plan:** E5 — Dollar Tier with WCAG Markup (plan §E5, lines 1788-1804). Spec §6.1 dollar-tier accessibility section.

---

## 10. Decisions for the lead engineer

1. **Ship E4 as-is or do the optional fix-up commit first?** Recommendation: do the Q1+Q2+Q3+Q5 fix-up now (~10 minutes), since they're all defensive hardening that costs nothing today and prevents subtle bugs at the A8 launch. But shipping as-is is also defensible — none of the SUGGESTED items can fire in production today.
2. **Do you want the `[admin queue]` affordance on `card_degraded` (UX regression S5)?** It's spec §6.4 intent. Three options: (a) accept the regression, gated by A8 anyway; (b) backport the OCR-needed branch into `card_degraded.html` directly (independent of `source_anchor_button.html`); (c) defer to A8 cleanup.
3. **Continue to E5 next, or wait for A8 to unblock E6 and run E5+E6 together?** Plan suggests E5 next (independent), then E6 after A8.
4. **Do you want the parallel `page=0` forcing test (Q7) added?** Cheap, but the case is structurally PDF-impossible (no 1-indexed page 0), so adding it is more for symmetry with the `ts=0` test than for actual coverage.

---

## 11. Files reviewed (absolute paths)

- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/templates/partials/source_anchor_button.html` (E4 partial under review)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/templates/partials/_source_link_stub.html` (legacy stub, retained)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/templates/partials/smart_brevity_card.html` (variant dispatcher)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/templates/partials/card_smart_brevity.html` (v3 card, swapped to new button)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/templates/partials/card_verification_pending.html` (v3 card, swapped to new button)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/templates/partials/card_failed.html` (v2, retained on stub)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/templates/partials/card_degraded.html` (v2, retained on stub)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/templates/partials/card_v2_fallback.html` (v2, retained on stub)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/templates/partials/card_pending.html` (v2, retained on stub)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/templates/partials/card_procedural.html` (v3, doesn't use source link)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/filters.py` (added `format_timestamp`)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/admin.py` (added `data_debt` stub)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/auth.py` (auth model — informed `session.admin_user` decision)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/__init__.py` (filter/blueprint registration)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/models/agenda.py` (AgendaItem dataclass — A8 gap)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/migrations/013_impact_first_refactor.py` (v3 schema)
- `/Users/darrellnance/docket-pub-pf2-track-3/tests/unit/test_source_anchor.py` (E4 test suite)
- `/Users/darrellnance/docket-pub-pf2-track-3/tests/unit/test_engagement_strip.py` (style baseline)
- `/Users/darrellnance/docket-pub-pf2-track-3/tests/unit/test_smart_brevity_card_dispatcher.py` (style baseline)
- `/Users/darrellnance/docket-pub-pf2-track-3/docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` (§6.1, §6.4)
- `/Users/darrellnance/docket-pub-pf2-track-3/docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-2.md` (E1-E6)
- `/Users/darrellnance/docket-pub-pf2-track-3/docs/superpowers/plans/2026-05-06-impact-first-phase-2-coordination.md` (track decomposition)

---

## Appendix A — Reviewer prompts (for reproducibility)

Both first-pass reviews used the **default Opus model** (Sonnet 4.6 was held back for the second-look). Both were dispatched via the `Agent` tool with `run_in_background: true` and read-only access. The second-look used `model: "sonnet"` and ran in foreground.

The full briefs explicitly forbade these phrases:
- "out of scope"
- "downstream task territory"
- "spec gap not implementation gap"
- "track for follow-up"

…per the lesson from E3 second-look (memory: `feedback_reviewer_defer_verify.md`). The bar for `[REQUIRED]` was: "production crashes, mis-renders, leaks data, or fails the security model TODAY without the fix." Anything "would break when X lands" was demoted to `[FORCING TEST RECOMMENDED]`.

---

## Appendix B — Glossary

| Term | Meaning |
|---|---|
| **A8** | Cross-track task: extend `AgendaItem` dataclass + `services/query.py:list_agenda_items()` SELECT to expose v3 columns (`processing_status`, `data_quality`, `ai_rewrite_version`, `headline`, `why_it_matters`, `extracted_facts`, `next_steps`, `source_anchor`, `badges`, `ai_metadata`). Blocks E6's `SMART_BREVITY_UI=true` flip. |
| **E6** | Plan task: gate v3 rendering behind `SMART_BREVITY_UI` env flag. Depends on A8. |
| **`source_anchor`** | JSONB column on `agenda_items`. Shape: `{type, url, page?, bbox?, anchor?, timestamp_seconds?}`. Populated by Stage 1 (Track 1). |
| **Wave 0** | Phase 1 non-LLM classifier — sets `data_quality`, `data_debt_priority`, `processing_status`. Live on Railway as of 2026-05-07. |
| **Stage 1 / Stage 2 / Stage 2.5** | Phase 2 v3 LLM pipeline — extraction, Smart Brevity rewrite, score floors + reconcile. |
| **Smart Brevity Card** | v3 citizen card UI. 6 variants (smart_brevity, verification_pending, degraded, failed, procedural, pending) + 1 v2 fallback. Spec §6.1. |
| **Track 3** | Phase 2 sub-track owning the Smart Brevity Card UI work (E1-E6, F1-F5, G1-G4). |
