# G4 Opus Review #2 — Frontend / UX / Auth

**Reviewer:** Opus 4.7 (1M context)
**Scope:** templates, HTMX wiring, CSS, form semantics + validation UX, accessibility, auth coverage on routes, side-by-side listing UX
**Commits reviewed:** 602b4d5..8dcd406 (7 commits, `feat/impact-first-phase-2-track-3`)
**Date:** 2026-05-10
**Counterpart:** Opus Review #1 (backend / services / handlers / transactions) — independent in parallel

## Summary

G4's frontend ships the four resolution surfaces with the right HTMX shape (form-expander GETs for the three multi-field actions, direct POST for Accept Stage 2), correct swap-target ids (`row-{{ item.id }}`), and Jinja autoescape coverage on every user-controlled string. The three inline form templates implement decision #6 (HTMX 4xx UX with `hx-on:htmx:response-error` + `<span class="form-error" role="alert">`) and decision #12 (TOCTOU 409 surfaces through the same `.form-error` slot, no status-code filtering in the handler) verbatim. Auth coverage is uniform: all 8 new routes mount under the `admin.` blueprint, the `before_request` hook fires, and `test_*_requires_login` integration tests assert anonymous → 302 to `/admin/login`.

There is one **REQUIRED** finding (token drift — G4 invents a `var(--mono, …)` token that doesn't exist in `styles.css`, identical in shape to the G3 finding called out in the review packet). One **SUGGESTED** finding worth addressing pre-merge (the listing's direct-submit Accept Stage 2 button has no surfacing for the 404/race response — silent failure UX on the rare race-loss path). The rest are NICE-TO-HAVE: a hard-coded "Verdict: PROCEDURAL" template label that bakes in today's reconcile direction, missing `<time>` wrappers, raw enum strings for conflict reasons, the well-flagged `ai_generated_at` semantic mismatch in secondary sort (mostly moot — resolved items filter out — but a freshness display would still confuse).

The reviewer-1 deviation note about `ai_generated_at` replacing `updated_at` in the helper is **not template-relevant** in the way the packet feared: the listing template does NOT render `ai_generated_at` anywhere (the date shown is `meeting_date`, the meeting's calendar date). There is no tooltip or label saying "last admin action." So the listing won't confuse admins; the only semantic question is the secondary sort behavior, which is moot for the cross_stage_conflict scope.

---

## REQUIRED

### R1 — CSS token drift: `var(--mono, …)` is not defined; correct token is `--font-mono`

**Files:** `src/docket/web/static/tweaks.css:317`, `src/docket/web/templates/admin/_conflict_form_edit_facts.html:17`

G4 introduces two references to a token that doesn't exist:

```css
/* tweaks.css line 317 */
.conflict-queue .stage-1 .facts-json,
.conflict-queue .raw .raw-text {
  font-family: var(--mono, ui-monospace, "JetBrains Mono", monospace);
  ...
}
```

```html
<!-- _conflict_form_edit_facts.html line 17 -->
<textarea name="new_facts_json" rows="12" required
          style="font-family: var(--mono, ui-monospace, monospace); font-size: 0.8rem;"
          spellcheck="false">{{ existing_facts | tojson(indent=2) }}</textarea>
```

`grep --` over `styles.css` shows the only defined monospace token is **`--font-mono`** (declared at `styles.css:42`). Verified with `grep -n "mono" src/docket/web/static/styles.css`:

```
42:  --font-mono:    "JetBrains Mono", "IBM Plex Mono", ui-monospace, monospace;
71:  font-family: var(--font-mono);
77:.t-mono { font-family: var(--font-mono); font-feature-settings: "tnum" 1; }
```

Six other call sites across `styles.css`, `layout.css`, `mobile.css`, `councilmatic.css` use `var(--font-mono)`. G4 invented `var(--mono)`.

**Effect:** the fallback chain (`ui-monospace, "JetBrains Mono", monospace`) kicks in, so the JSON and the raw description text DO render in a monospace face — but **not the editorial design system's JetBrains Mono + IBM Plex Mono stack** with the same precedence the rest of the app uses. Specifically, `--font-mono`'s first fallback is `IBM Plex Mono` (which the page is loading); G4's invented token skips IBM Plex Mono entirely. On admin machines without JetBrains Mono installed, the textarea and the facts JSON will render in `ui-monospace` (system mono) while every other monospace element on the page renders in IBM Plex Mono. Cosmetic drift, but visible.

This is the same class of finding the G3 review packet flagged about `--surface-2` / `--border` / `--muted` token invention; the G4 plan even says (decision packet line 12) "verify G4's CSS uses the established `--paper-2/--rule/--ink-3/--mono` tokens." Note the packet itself wrote `--mono` — both the implementer and the packet author were working from the same incorrect assumption. **The real token is `--font-mono`.**

**Fix:** s/var(--mono,/var(--font-mono,/g across the two locations. Keep the fallback chain.

---

## SUGGESTED

### S1 — Accept Stage 2 direct-submit form has no error surfacing on 4xx (decisions #6/#12 not extended to this path)

**File:** `src/docket/web/templates/admin/review_conflicts.html:97–104`

The Accept Stage 2 affordance is a one-click form posted directly from the listing (no form-expander step):

```html
<form hx-post="{{ url_for('admin.conflict_accept_stage_2', item_id=item.id) }}"
      hx-target="#row-{{ item.id }}"
      hx-swap="outerHTML"
      style="display: block;">
  <button type="submit" class="btn-accept-s2">
    ❌ Accept Stage 2 (clear facts)
  </button>
</form>
```

The handler at `admin.py:1078–1098` can return:

- **200** + the resolved partial (happy path)
- **400** if the optional `reason` field in `accept_stage_2` exceeds 500 chars
- **404** if the item is no longer in `cross_stage_conflict` (TOCTOU loss — another admin resolved it first)

HTMX 1.x does NOT swap on 4xx by default. The Accept Stage 1 / Re-prompt / Edit-facts forms compensate with the decision #6 pair (`hx-on:htmx:response-error` + `<span class="form-error" role="alert">`); this listing button compensates with **nothing**. The admin clicks the red button, gets a silent 404 (race-loss), and sees no change in the DOM — they may click again and STILL see nothing. No `flash` message, no row swap, no on-screen feedback.

In practice the 400 path is unreachable from THIS listing (the listing button submits an empty body — no `reason` field — and 0 ≤ 500). So only the 404 (race-loss) and Werkzeug's own 405-on-GET matter here. The 404 IS a real race scenario covered by reviewer-1's TOCTOU contract: two admins on the same item, one fast-resolves while the other is mid-page. Today the slow admin sees no feedback.

**Fix options (cheapest first):**

1. Add `hx-on:htmx:response-error="alert(event.detail.xhr.responseText)"` to the form. Crude but honest — at least the admin sees the message instead of silent nothing.
2. Mirror the inline-form pattern: put a `<span class="conflict-flash form-error" role="alert"></span>` after the form (still inside `td.actions`) and route the response text into it. Keeps the design language consistent.
3. Make Accept Stage 2 a two-step like the others (form expander with a `.form-error` slot). Heavier change — and arguably overkill for a single-button affordance — but yields the most consistent UX.

Recommended: option 2. Matches the decision #6 contract, no architecture change, ~3 lines.

(Reviewer-1 may also want to confirm whether `accept_stage_2`'s LookupError path is the correct race response here vs the 409 used by re_prompt/edit_facts. From a UX standpoint, either is fine — both are non-2xx and would surface through the same `.form-error` mechanism.)

---

### S2 — `tweaks.css:307–337` reverts to `--mono`/loose tokens; revisit alongside R1

While fixing R1, also check the rest of the `.conflict-queue` block uses the existing token names. Quick audit of `tweaks.css:307–380`:

- `var(--rule, #e6e6e0)` — `--rule` IS defined; good. The fallback hex `#e6e6e0` doesn't match the actual oklch value (`oklch(0.88 0.008 85)`), but G3 inherits the same loose-fallback pattern so this is consistent with the codebase.
- `var(--paper-2, #f6f6f4)` — `--paper-2` IS defined; good.
- `var(--mono, …)` — broken (R1).

No additional broken tokens; just R1.

---

### S3 — Listing template hard-codes the Stage 2 direction as "PROCEDURAL"

**File:** `src/docket/web/templates/admin/review_conflicts.html:76–88`

```html
<td class="stage-2">
  <h4>Stage 2 — Verdict: PROCEDURAL</h4>
  <p>(no headline / why_it_matters generated)</p>
  ...
```

The template assumes every cross-stage conflict has Stage 2 saying procedural and Stage 1 finding substance. This matches **today's** reconcile contract — every conflict reason in the spec (`stage1_has_counterparty_but_stage2_procedural`, `yellow_tier_dollars_but_stage2_procedural`, …) is shaped Stage1=substantive vs Stage2=procedural — but it's a hidden contract dependency.

If a future reconcile decision introduces conflicts in the other direction (e.g. Stage 2 returns `is_substantive=True` with a headline but Stage 1 facts say procedural), this template would render "Verdict: PROCEDURAL" + "(no headline / why_it_matters generated)" while the actual `agenda_items.headline` column is non-NULL — a falsehood.

**Cheap fix:** drive the label from the row:

```jinja
{% if item.headline %}
  <h4>Stage 2 — Verdict: SUBSTANTIVE</h4>
  <p><strong>{{ item.headline }}</strong></p>
  <p>{{ item.why_it_matters }}</p>
{% else %}
  <h4>Stage 2 — Verdict: PROCEDURAL</h4>
  <p>(no headline / why_it_matters generated)</p>
{% endif %}
```

The helper already SELECTs `ai.headline` and `ai.why_it_matters`, so no query change is needed.

(Non-blocking — today's reconcile decisions all point one direction, and B5 hasn't shipped yet to force the issue. Worth a one-line `{% if item.headline %}` guard now while it's easy.)

---

## NICE-TO-HAVE

### N1 — `meeting_date` rendered as plain text; wrap in `<time datetime="…">`

**File:** `review_conflicts.html:60`

```html
{{ item.meeting_date.strftime('%Y-%m-%d') if item.meeting_date else '—' }}
```

`badges_audit.html:77` already uses the `<time>` element for accessibility / SEO / SR-user benefit:

```html
<td><time datetime="{{ r.occurred_at.isoformat() }}">{{ r.occurred_at.strftime('%Y-%m-%d %H:%M') }}</time></td>
```

The G4 listing's date is a date, not a datetime, but a `<time datetime="{{ item.meeting_date.isoformat() }}">…</time>` wrap costs nothing and matches the precedent. Skipped here, presumably because the date is parenthetical metadata rather than the primary content.

### N2 — Conflict reasons render as raw enum strings inside `<code>`

**File:** `review_conflicts.html:82–86`

```html
<ul class="conflict-reasons">
  {% for reason in conflicts %}
    <li><code>{{ reason }}</code></li>
  {% endfor %}
</ul>
```

Readable to engineers; opaque to admins. The strings `stage1_has_counterparty_but_stage2_procedural` and `yellow_tier_dollars_but_stage2_procedural` are CHECK-constraint-stable enum values from migration 013, so a human-readable mapping is straightforward to add — a Jinja `{% set REASON_LABELS = { ... } %}` macro and `{{ REASON_LABELS.get(reason, reason) }}`. Decisions baked into the plan don't ask for this, and the admin surface is internal-vocabulary-acceptable per the G1/G2/G3 precedent, so genuinely optional. Future enhancement: hover-tooltip with the human-readable form.

### N3 — `ai_generated_at` secondary sort: orphan freshness signal in the conflict queue

**Files:** `query.py:2054`, `review_conflicts.html` (template doesn't render `ai_generated_at` but inherits its sort order)

Per the deviations report — the listing helper substituted `ai_generated_at` for the non-existent `updated_at` column. The template DOESN'T display this column; it displays `meeting_date`. So there is **no labelled-as-X-but-actually-Y bug** in the rendered HTML. (Verified by `grep ai_generated_at src/docket/web/templates/admin/review_conflicts.html` → no matches.)

The secondary sort, however, does mean rows are ordered by when Stage 2 last touched them — not when they entered cross_stage_conflict state. In practice this is fine because cross_stage_conflict is a single-direction transition out of Stage 2 (reconcile sets it), so `ai_generated_at` IS approximately "when this became a conflict." The mismatch only matters if Stage 2 re-runs for non-conflict reasons update the field. The implementer's deviation note is correct: there's no perfect column today.

Reviewer's stance: accept the deviation; the template doesn't compound the confusion. If/when reviewer-1's plan brings in a `cross_stage_conflict_at` column or a generic `status_changed_at` column, the helper and template should adopt it together.

### N4 — `<details><summary>Original description</summary>` opens collapsed by default ✓

**File:** `review_conflicts.html:63–65`

```html
<details><summary>Original description</summary>
  <pre class="raw-text">{{ item.description or '(empty)' }}</pre>
</details>
```

No `open` attribute, so the browser default applies (collapsed). Correct initial state per the review packet question.

### N5 — Each row has unique `id="row-{{ item.id }}"`; HTMX swap targets resolve cleanly ✓

**File:** `review_conflicts.html:55`

`<tr id="row-{{ item.id }}">` is the row's id. Form-expander `hx-target="#row-{{ item.id }} .actions"` (innerHTML swap of the actions cell). Submit `hx-target="#row-{{ item.id }}"` (outerHTML swap of the whole row). `_conflict_resolved.html:14` renders a new `<tr id="row-{{ result.item_id }}">` with the same id so subsequent in-page actions on the resolved row would still target it (though the row no longer has actions, so this is dead code defensively). Resolved partial uses `<td colspan="4">` matching the 4-column listing. All HTMX shapes verified consistent.

### N6 — `style="display: block;"` inline on the Accept Stage 2 form

**File:** `review_conflicts.html:100`

```html
<form hx-post="{{ url_for('admin.conflict_accept_stage_2', item_id=item.id) }}"
      hx-target="#row-{{ item.id }}"
      hx-swap="outerHTML"
      style="display: block;">
```

Inline style on a `<form>` that's a child of a `<td>` block-context. The `display: block` is technically a no-op (forms are already block-level by default), but it's an intentional override to ensure the wrapping form doesn't collapse to inline if a future global CSS rule changes form display. Minor pattern drift vs the rest of the `.conflict-queue` block (which puts all styling in `tweaks.css`), but it's a one-line defensive override and the cost of pulling it into `tweaks.css` would be a `.conflict-queue .actions form { display: block; }` selector — fine either way. Not worth changing.

### N7 — Action button color palette

**File:** `tweaks.css:348–359`

```css
.btn-accept-s1 { background: #d4edda; border: 1px solid #155724; color: #155724; }  /* green */
.btn-accept-s2 { background: #f8d7da; border: 1px solid #721c24; color: #721c24; }  /* red */
.btn-re-prompt  { background: #fff3cd; border: 1px solid #856404; color: #856404; }  /* yellow */
.btn-edit-facts { background: #d1ecf1; border: 1px solid #0c5460; color: #0c5460; }  /* blue */
```

The hex values are Bootstrap 4's alert palette — not the editorial design system's oklch tokens. Already an established G3 pattern (`badge-action-added` / `-removed` / `-modified` at `tweaks.css:276–278` uses the same hexes). Contrast ratios (background vs text): green 7.5:1, red 7.2:1, yellow 8.0:1, blue 7.4:1 — all well above WCAG AA 4.5:1. Accept as-is.

Semantic mapping: green=approve / red=reject / yellow=retry-with-input / blue=edit-and-retry. Reasonable. The red Accept Stage 2 button is somewhat counterintuitive (it "accepts" stage 2 by clearing Stage 1; the red implies destructive, which matches the underlying "drop the facts" semantic). The wording "Accept Stage 2 (clear facts)" makes the destruction explicit. Good.

### N8 — `.form-error` span positioning inside the form (decisions #6/#12 mechanics) ✓

All three inline forms place `<span class="form-error" role="alert"></span>` INSIDE the `<form>` and AFTER the submit button:

- `_conflict_form_accept_s1.html:33` (right before `</form>`)
- `_conflict_form_re_prompt.html:19`
- `_conflict_form_edit_facts.html:25`

This is correct: on 4xx the form is NOT swapped out (because there's no swap on non-2xx in HTMX 1.x), so the span remains in the DOM and `this.querySelector('.form-error')` finds it. On 2xx the row is replaced wholesale and the form (with its error span) vanishes, which is the desired behavior.

The handler:

```html
hx-on:htmx:response-error="this.querySelector('.form-error').textContent = event.detail.xhr.responseText"
```

uses `responseText` (correct property for plain-text bodies in HTMX 1.x; `event.detail.xhr.response` would also work but is type-dependent on responseType, and HTMX leaves it as text by default). All three forms use the same pattern verbatim. Decision #12 (TOCTOU 409) is handled by the same mechanism — the handler doesn't filter on status code, so any non-2xx response (400 validation, 409 race-loss, 404 not-found) renders into the span. Verified by the test `test_re_prompt_returns_409_when_item_resolved_during_llm_call`:

```python
assert resp.status_code == 409
assert "resolved by another admin" in resp.get_data(as_text=True)
```

The body text is plain "resolved by another admin during your LLM call" — exactly the text that would land in the `.form-error` span via the hx-on handler. Correct end-to-end.

### N9 — `tojson(indent=2)` inside `<textarea>` preserves newlines (Decision #6 sub-concern resolved)

**File:** `_conflict_form_edit_facts.html:18`

```html
<textarea name="new_facts_json" rows="12" required ...>{{ existing_facts | tojson(indent=2) }}</textarea>
```

Flask's `tojson` filter calls `htmlsafe_dumps` under the hood, which:

1. Marks the result `Markup` (already-safe — no double-escape inside `<textarea>`).
2. HTML-escapes `<`, `>`, `&`, `'` to `<`, `>`, `&`, `'` inside the JSON string values — XSS-safe even when embedded in HTML text content.
3. With `indent=2`, the indentation includes **literal newline bytes** (`\n` character, not the two-character `\n` escape).

Inside `<textarea>`, HTML5 treats `\n` as a line break per spec. So the JSON renders as multi-line, indented, editable, and the admin sees what they'd expect. Verified the implementation matches the assumption.

(One subtle gotcha that does NOT apply here: HTML5 `<textarea>` strips one leading `\n` if present immediately after the opening tag. The `tojson` output starts with `{` not `\n`, so this never triggers.)

### N10 — Anti-XSS: every user-controlled string flows through Jinja autoescape; zero `|safe` filters ✓

```
$ grep -n "|safe\|| safe" src/docket/web/templates/admin/review_conflicts.html src/docket/web/templates/admin/_conflict_*.html
(no matches)
```

User-controlled strings rendered in templates:

| Source | Template + line | Render context |
|---|---|---|
| `item.title` | `review_conflicts.html:57` | inside `<h3>` (autoescape) |
| `item.description` | `review_conflicts.html:64` | inside `<pre>` (autoescape) |
| `item.extracted_facts` | `review_conflicts.html:73` | through `tojson` (htmlsafe_dumps) |
| `reason` (conflict enum) | `review_conflicts.html:84` | inside `<code>` (autoescape, but values are CHECK-constrained enum literals so not strictly user-controlled) |
| `item.municipality_name` | `review_conflicts.html:59` | autoescape |
| `existing_facts` | `_conflict_form_edit_facts.html:18` | through `tojson` |
| `result.action` / `result.new_status` / `result.detail` | `_conflict_resolved.html:23–25` | all server-authored static strings (verified by `grep "detail=" src/docket/services/conflict_resolution.py` — no user input flows in) |

No injection vectors. The `<code>{{ reason }}</code>` pattern is fine — `<code>` doesn't disable autoescape; `{{ }}` still escapes. The `tojson` filter additionally escapes JSON string contents.

### N11 — CSRF: project-wide gap; G4 follows G2/G3 precedent ✓

No CSRF tokens on any of the four POST forms. Matches G2/G3 which also omit Flask-WTF / CSRF middleware. Project-wide architectural decision; out of G4's scope to fix.

(Worth recording in the technical-report aggregation: the four new POST routes — `accept-stage-1`, `accept-stage-2`, `re-prompt-stage-2`, `edit-stage-1-facts` — are subject to the same CSRF gap as every other admin POST in the codebase. A logged-in admin clicking a malicious cross-origin link would trigger a state-change. The fix is project-wide, not per-route.)

### N12 — Nav-link strip across 6 admin templates includes `Conflicts` ✓

Cross-link verification — `git diff` of `8dcd406`:

| Template | Conflicts link present | Position in strip |
|---|---|---|
| `data_debt.html` | ✓ | between "Badge audit" and "Calibration" |
| `errors.html` | ✓ | between "Badge audit" and "Calibration" |
| `calibration.html` | ✓ | between "Badge audit" and "AI Pipeline →" |
| `ai_panel.html` | ✓ | after "Badge audit" (terminal) |
| `members.html` | ✓ | between "Badge audit" and "AI Pipeline →" |
| `badges_audit.html` | ✓ | between "Council Members ←" and "Calibration" |
| `review_conflicts.html` | (this page itself) | links to other queues outward |

Order is inconsistent across pages (e.g. `data_debt.html` puts Conflicts between Badge-audit and Calibration; `badges_audit.html` puts it between Council-Members and Calibration). The same inconsistency exists pre-G4 across the strip — adding Conflicts at different positions mirrors what was already there. Not a regression; arguably worth a sweep later but out of scope.

### N13 — Empty state copy: "No items in cross_stage_conflict state."

**File:** `review_conflicts.html:50–51`

```jinja
<p class="t-meta">No items in cross_stage_conflict state. The v3 pipeline
has not produced any conflicts (or all have been resolved).</p>
```

Admin-precise tone, internal vocabulary acceptable (`cross_stage_conflict` is the literal enum value, recognizable to anyone working with `processing_status`). Matches G2's R-S-NEW-2 fix-up convention (admin-precise, not over-friendly). Plus the test `test_review_conflicts_empty_state` accepts either "No items in cross_stage_conflict" or "No conflicts" — slightly more permissive than the actual copy, but it passes against the actual template.

### N14 — Listing column widths: `width: 25%` × 4 cells

**File:** `tweaks.css:309–313`

```css
.conflict-queue td {
  vertical-align: top;
  padding: 0.6rem;
  width: 25%;
}
```

4-column layout, each cell 25%. The two heavy cells are Stage 1 facts (a `<pre>` with `max-height: 18rem; overflow: auto;` — capped scroll) and Original description (a `<details><pre>` — collapsed by default). The actions cell holds 4 stacked block buttons (`display: block; width: 100%`). Reasonable for desktop admin at 1280–1920px viewports. At narrow widths (< 1024px), the JSON cells will wrap awkwardly, but the spec calls this an admin desktop surface, so acceptable.

No `@media` queries for the conflict-queue. Matches the G2/G3 admin-table precedent (also desktop-only). The review packet asked specifically about mobile-friendly creep — there is none.

### N15 — Accept Stage 1 / Re-prompt / Edit-facts buttons have meaningful text + decorative emoji ✓

```html
<button class="btn-accept-s1" …> ✅ Accept Stage 1 </button>
<button type="submit" class="btn-accept-s2"> ❌ Accept Stage 2 (clear facts) </button>
<button class="btn-re-prompt" …> 🔁 Re-prompt Stage 2 </button>
<button class="btn-edit-facts" …> 📝 Edit Stage 1 facts </button>
```

Emoji + text combo. Screen readers will announce both (the emoji as its Unicode name, e.g. "Check Mark"). Slight verbosity but not misleading. No emoji-only buttons. Form labels (`<label>Headline (10–60 chars)<input …></label>`) are visible above inputs with the input wrapped inside the label — implicit label association, accessible.

### N16 — Form-expander GET routes use sentence-case verbs in path; POST routes use kebab-case ✓

GET paths (form expanders):
- `/admin/review/conflicts/<int:item_id>/_form/accept-stage-1`
- `/admin/review/conflicts/<int:item_id>/_form/re-prompt`
- `/admin/review/conflicts/<int:item_id>/_form/edit-facts`

POST paths (actions):
- `/admin/review/conflicts/<int:item_id>/accept-stage-1`
- `/admin/review/conflicts/<int:item_id>/accept-stage-2`
- `/admin/review/conflicts/<int:item_id>/re-prompt-stage-2`
- `/admin/review/conflicts/<int:item_id>/edit-stage-1-facts`

The `_form/` namespace prefix on the GETs is a nice convention — clearly distinguishes form expanders from the action endpoints. Action verbs use the spec decision #1 forms (`accept_stage_1` etc.) in their URL forms (`accept-stage-1`).

Slight asymmetry: the GET for re-prompt is `_form/re-prompt` (no `-stage-2` suffix), while the POST is `re-prompt-stage-2`. Likewise `_form/edit-facts` vs `edit-stage-1-facts`. The GET paths drop the stage qualifier — not a bug, but a small consistency nit if someone is reading the URL space cold. Worth zero engineering time to fix; flag for awareness only.

### N17 — Auth coverage on all 8 new routes ✓

The 8 new routes (1 listing + 3 form-expander GETs + 4 action POSTs) all mount on the `admin` blueprint via `@bp.route(...)`. The blueprint's `before_request` hook (`admin.py:27–35`) runs for every request whose endpoint starts with `admin.`:

```python
@bp.before_request
def require_login():
    from flask import session
    if request.endpoint and request.endpoint.startswith("admin."):
        if "admin_user" not in session:
            return redirect(url_for("auth.login", next=request.path))
```

All 8 endpoints have `admin.` prefixes (e.g. `admin.review_conflicts`, `admin.conflict_form_accept_s1`, `admin.conflict_accept_stage_1`, …). Test coverage:

| Route | Test |
|---|---|
| GET `/admin/review/conflicts` | `test_review_conflicts_redirects_anonymous` |
| POST `accept-stage-1` | `test_accept_s1_requires_login` |
| POST `accept-stage-2` | `test_accept_s2_requires_login` |
| POST `re-prompt-stage-2` | `test_re_prompt_requires_login` |
| POST `edit-stage-1-facts` | `test_edit_facts_requires_login` |
| GET `_form/accept-stage-1` | (no explicit anonymous test; inherits hook) |
| GET `_form/re-prompt` | (no explicit anonymous test; inherits hook) |
| GET `_form/edit-facts` | (no explicit anonymous test; inherits hook) |

The three form-expander GETs don't have anonymous-redirect tests, but they're architecturally identical to the others (same `@bp.route` decorator → `admin.` endpoint name → same `before_request` hook). The 5 routes that ARE tested for `requires_login` and the 3 that aren't are bound to the same hook through the same registration pattern. Acceptable test coverage — adding the missing 3 anonymous-redirect tests would be belt-and-suspenders, no architectural risk being papered over.

### N18 — GET-vs-POST hygiene ✓

The 4 action endpoints use `methods=["POST"]`. Tests `test_accept_s1_requires_post` and `test_accept_s2_requires_post` assert 405 on GET. The other two (`re-prompt-stage-2`, `edit-stage-1-facts`) don't have explicit 405-on-GET tests but inherit from `methods=["POST"]` only. Acceptable.

The listing GET and the 3 form-expander GETs use default Flask methods (GET only). No accidental POST handlers.

---

## Decisions to escalate to author

None blocking.

Soft preference for the author to accept:

- **R1 fix** is mandatory (token drift). 2-line change across 2 files.
- **S1 fix** would be nice (silent-failure UX on Accept Stage 2 race-loss). 3 lines max if going with option 2 of the suggested fixes.
- **S3 fix** is cheap insurance against a future reconcile-direction change. 4 lines of Jinja conditional.

Reviewer-1 is on the hook for service correctness and the SQL/transaction semantics behind decision #12; I have not duplicated their checks.

---

## Verified-correct (recorded for the audit trail)

Things the review packet asked about that ARE correct in the implementation:

- HTMX swap-target ids unique per row ✓
- Form-expander GETs use `hx-target="#row-N .actions"` + `hx-swap="innerHTML"` ✓
- Direct submission for Accept Stage 2 uses `hx-target="#row-N"` + `hx-swap="outerHTML"` ✓
- Resolved partial renders `<tr id="row-{item.id}"><td colspan="4">` matching the 4-column listing ✓
- All three form templates have `hx-on:htmx:response-error="this.querySelector('.form-error').textContent = event.detail.xhr.responseText"` ✓
- All three form templates have `<span class="form-error" role="alert"></span>` INSIDE the form ✓
- The `hx-on` handler uses `responseText` (not `response`) ✓
- The handler doesn't filter on status code — 400, 404, 409 all surface through the same path ✓
- TOCTOU 409 plain-text body "resolved by another admin" surfaces in `.form-error` ✓ (verified by integration test assertion)
- Auth: all 8 routes hit the `before_request` hook ✓ (5 tested explicitly, 3 inherited)
- GET vs POST hygiene: 4 POST-only actions, 4 GET-only readers ✓
- Anti-XSS: zero `|safe` filters; every user string autoescaped or routed through `tojson` ✓
- CSRF: project-wide gap, G4 follows G2/G3 precedent ✓
- Side-by-side 4-column layout with 25% widths ✓
- `<details><summary>` renders collapsed by default ✓
- Cross-template `Conflicts` nav-link added to all 6 admin pages ✓
- Empty-state copy admin-precise ✓
- `tojson(indent=2)` inside `<textarea>` preserves newlines ✓
- Sign-Out header pattern matches G1/G2/G3 ✓
- Pager `prev_offset = 0 → offset=none → url_for omits param` ✓

---

## File-by-file finding density

| File | REQUIRED | SUGGESTED | NICE-TO-HAVE |
|---|---|---|---|
| `review_conflicts.html` | 0 | 1 (S1) + 1 (S3) | 5 (N1, N3, N4, N5, N6) |
| `_conflict_resolved.html` | 0 | 0 | 0 (all checks pass) |
| `_conflict_form_accept_s1.html` | 0 | 0 | 1 (N8 verification) |
| `_conflict_form_re_prompt.html` | 0 | 0 | 1 (N8 verification) |
| `_conflict_form_edit_facts.html` | 1 (R1 inline `--mono`) | 0 | 1 (N9 verification) |
| `tweaks.css` | 1 (R1 css `--mono`) | 1 (S2 audit) | 2 (N7, N14) |
| Cross-template nav-link edits | 0 | 0 | 1 (N12) |
| Tests (HTML-relevant assertions only) | 0 | 0 | 2 (N13, N17) |

**Totals: REQUIRED = 1 (one issue, two file locations) · SUGGESTED = 3 · NICE-TO-HAVE = 18**
