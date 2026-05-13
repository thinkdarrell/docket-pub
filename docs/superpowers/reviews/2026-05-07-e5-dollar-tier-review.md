# E5 Review Report — Dollar Tier with WCAG Markup

**Date:** 2026-05-07 / 2026-05-08
**Phase / Track:** Phase 2 / Track 3
**Branch:** `feat/impact-first-phase-2-track-3` (worktree: `~/docket-pub-pf2-track-3`)
**Commit under review:** `10f52c9` — `feat(web): WCAG-2.1-compliant dollar tier with symbols + sr-only labels`

**Plan:** §E5 lines 1788-1804 of `docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-2.md`
**Spec:** §6.1 (dollar-tier accessibility section) of `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md`. Decisions #71 (dollar-tier accessibility symbols) and #75 (ARIA labels for dollar tiers).

**Final verdict:** **SHIP** — both Opus first-pass reviews and the Sonnet 4.6 second-look returned `ship`. No `[REQUIRED]` findings. 6 `[SUGGESTED]` items from the code-quality review + 1 new `[FORCING TEST RECOMMENDED]` from the second-look (N1 — `aria-label` on `<span>` is invalid per ARIA 1.2). All foldable into a single fix-up commit.

---

## 1. Executive summary

E5 implements the WCAG 2.1 AA dollar-tier markup contract. Every `dollars_amount` in the v3 facts strip now renders with **triple-redundant tier signal**:

- **CSS color class** — `dollars--green | --yellow | --orange | --red`
- **Visible text symbol** — `$ | $$ | $$$ | $$$$` (decision #71 — color is no longer the sole channel for tier perception)
- **Screen-reader label** — both an `<span class="sr-only">` child and a parent `aria-label` (decision #75 — covers both AT traversal modes)

The implementation is **plan-faithful with one creative deviation** that the spec edit subsequently codified: `dollar_tier(amount)` returns a `NamedTuple(color, symbol, description)` whose `__str__` returns just the color so existing v2 templates (`search.html`, `topic_detail.html`, `card_v2_fallback.html`, `city.html`) keep working without churn. 68 new tests cover boundaries, the defensive matrix, the WCAG triple-redundancy contract, and both screen-reader traversal modes.

The Sonnet 4.6 second-look surfaced one finding the Opus reviewers missed: **`aria-label` on a plain `<span>` is invalid per ARIA 1.2** because `<span>` has implicit role `generic`, which is on the "prohibited naming" list. NVDA + VoiceOver may silently ignore the attribute. The partial degrades gracefully — Path B (visible + sr-only) still works — so it's not a today-breaking bug, but it means Path A coverage (which the spec and the partial's own comments advertise) doesn't reliably exist for some screen readers. Fix is one attribute (`role="img"`).

Every other finding is housekeeping: outdated README docstring, missing `.sr-only` CSS utility (the partial emits the class; no stylesheet defines it), `format_dollars` called twice in the partial, a loose substring assertion in one test, and a doc-link comment for the `_TIER_METADATA` threshold prose.

---

## 2. What E5 built

### 2.1 New files

| Path | Purpose |
|---|---|
| `src/docket/web/templates/partials/dollar_tier.html` | WCAG 2.1 AA dollar-tier partial. 49 lines including a 35-line docstring documenting the triple-redundancy contract, double-announcement trade-off, and CSS hook posture. |
| `tests/unit/test_dollar_tier.py` | 68 unit tests across 5 classes (filter behaviour, format dollars, partial per-tier, partial no-render, WCAG contract, facts-strip integration). |

### 2.2 Modified files

| Path | Change |
|---|---|
| `src/docket/web/filters.py` | Added `format_dollars` and `dollar_tier` filters + shared `_coerce_amount` helper + `DollarTier` NamedTuple. Registered alongside `order_badges`, `format_date`, `format_timestamp` in `register(app)`. |
| `src/docket/web/public.py` | Removed legacy `@bp.app_template_filter("dollar_tier")` registration that returned a literal color string — would have clobbered the new global filter at app init. |
| `src/docket/web/templates/partials/_facts_strip.html` | Replaced `{# TODO E5: dollar_tier partial with WCAG markup #}` marker (line 14) with `{% with amount = item.dollars_amount %}{% include 'partials/dollar_tier.html' %}{% endwith %}`. Outer `{% if item.dollars_amount %}` guard preserved. |
| `tests/unit/test_engagement_strip.py` | Fixture switched from inline string-shape `dollar_tier` filter override to real `register_filters` (the inline override was incompatible with the new NamedTuple shape). |
| `tests/unit/test_smart_brevity_card_dispatcher.py` | Same fixture switch. Two assertions strengthened — now pin all three WCAG channels (`"$1.8M"`, `"dollars--red"`, `"($$$$)"`) instead of just the legacy single-color string. |
| `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` | §6.1 canonical Jinja edited so it matches `dollar_tier.html` byte-for-byte (single `tier_data` NamedTuple var, not three separate `tier`/`tier_symbol`/`tier_description` vars). Prose example updated from `$1,800,000` to `$1.8M ($$$$)` to align with decision #71. |

### 2.3 Source — the actual partial body

```jinja
{%- set tier_data = amount | dollar_tier -%}
{%- if tier_data -%}
<span class="dollars dollars--{{ tier_data.color }}"
      aria-label="{{ amount | format_dollars }}, {{ tier_data.color|title }} tier ({{ tier_data.description }})">{{ amount | format_dollars }}
  ({{ tier_data.symbol }})<span class="sr-only">, {{ tier_data.color|title }} tier</span>
</span>
{%- endif -%}
```

Key invariants:
- **Single `dollar_tier` filter call** at top (`{%- set tier_data = amount | dollar_tier -%}`); subsequent references are attribute access, not re-invocation.
- **`format_dollars` IS called twice** (in attribute + in text). Cosmetic — see §4.2 finding CQ-3.
- **`{% if tier_data %}` guard** — when the filter returns `None` (invalid / missing / negative amount), no markup is emitted. Same defensive posture as E4's source-anchor button.
- **CSS class hooks emitted, no styles yet** — `.dollars`, `.dollars--<color>`, `.sr-only`. The partial's own docstring acknowledges `.sr-only` is not yet defined and defers to "the design pass."

---

## 3. Implementer's self-reported divergences

| # | Divergence | Resolution |
|---|---|---|
| 1 | **`dollar_tier` returns a `NamedTuple` with `__str__` returning just the color.** Plan §E5 said the filter returns the 3-tuple `('green'\|...\|'red', '$'\|...\|'$$$$', 'over $X')`. NamedTuple satisfies that (it's tuple-unpackable, iterable, indexable) AND adds `.color`/`.symbol`/`.description` named access for the new partial AND keeps `tier-{{ amt \| dollar_tier }}` working for the four v2 callsites that interpolate the filter result as a string. | **Confirmed plan-compliant** by spec-compliance review. `test_returns_namedtuple_unpackable_as_3_tuple` proves the tuple contract; `test_str_returns_color_for_v2_template_backcompat` pins the v2 path. |
| 2 | **Removed `dollar_tier_filter` from `public.py`.** The old `@bp.app_template_filter("dollar_tier")` lived on the public blueprint and returned a literal color string. Without removal it would have either (a) lost a deterministic registration race against the new global filter or (b) needed to keep the old contract — neither acceptable. | **Confirmed clean removal.** Spec-compliance reviewer verified the new global is registered in `register_filters` and no other code references the old blueprint-level filter. |
| 3 | **Spec edit landed in the same commit.** Same E3 lesson — when implementation deviates from spec text in a way the user is signing off on, edit the spec in lockstep. Spec §6.1 canonical Jinja now matches the partial verbatim. Prose examples bumped from `$1,800,000` to `$1.8M ($$$$)` to match decision #71. | **Confirmed faithful.** Spec-compliance reviewer compared canonical Jinja against partial line-by-line. |
| 4 | **`format_dollars` abbreviates at ≥$1M; sub-$1M renders full precision (cents dropped).** Decisions log #71 says `$1.8M ($$$$)`; pre-E5 spec prose said `$1,800,000`. Implementer used the decisions log as authoritative. | **Confirmed correct.** `_ABBREVIATE_AT = Decimal("1000000")` constant in `filters.py`. Prose example in spec §6.1 now matches. |
| 5 | **Two extra SR-behaviour tests** — `test_screen_reader_path_a_aria_label_only_is_complete` (extracts only the aria-label and asserts it carries amount + tier name + threshold context) and `test_screen_reader_path_b_visible_text_only_is_complete` (regex-strips the aria-label and asserts the remaining DOM still carries amount + symbol + sr-only tier name). Both pin the WCAG contract under both AT traversal modes. | **Confirmed both genuinely exercise their contracts** — spec-compliance review verified both Path A and Path B independently render complete tier semantics. |

---

## 4. Reviewer findings (consolidated)

### 4.1 Spec-compliance review (Opus, parallel, read-only)

**Verdict:** `ship`. No findings.

All four self-reported divergences verified. All eight spec-compliance checks passed:

1. Partial Jinja matches canonical spec §6.1 byte-for-byte.
2. Tier symbol mapping correct: green→`$`, yellow→`$$`, orange→`$$$`, red→`$$$$` (decision #71).
3. Tier thresholds reuse `enrichment/dollars.py:classify_dollar_tier` — no duplication.
4. Threshold descriptions correct: "under $50,000" / "$50,000 to $250,000" / "$250,000 to $1 million" / "over $1 million".
5. `format_dollars` registered alongside the four pre-existing filters in `register(app)`.
6. `_facts_strip.html` integration correct — outer `{% if item.dollars_amount %}` guard preserved; `{% with amount = ... %}` correctly scopes the variable for the partial.
7. v2 backwards-compat verified: all four v2 callsites (`search.html:124`, `city.html:253`, `topic_detail.html:87`, `card_v2_fallback.html:34`) wrap the filter call in `{% if item.dollars_amount %}` guards. Filter never receives `None` from those paths. NamedTuple `__str__` gives `tier-green` exactly as the legacy filter did.
8. `_TIER_METADATA` table in `filters.py:343-348` correctly maps each color to its symbol and prose description.

### 4.2 Code-quality review (Opus, parallel, read-only)

**Verdict:** `ship`. Six SUGGESTED findings, no REQUIRED.

| # | Finding | Location | Production-impact today |
|---|---|---|---|
| **CQ-1** | **`README.md:481` outdated docstring.** Still claims `dollar_tier` returns a literal color string. With the NamedTuple shape it returns `DollarTier(color, symbol, description)` whose `__str__` returns the color. Spec & filter docstrings updated; README missed. | `README.md:481` | **None.** Doc rot only. |
| **CQ-2** | **`.sr-only` CSS missing.** Reviewer verified by reading every loaded stylesheet (`styles.css`, `layout.css`, `councilmatic.css`, `tweaks.css`, `mobile.css`, `css/smart_brevity.css`) — no `.sr-only` rule exists. The partial emits the class hook expecting standard "visually-hidden but screen-reader-readable" semantics; without the CSS, the `<span>` renders as ordinary visible text. | `dollar_tier.html:33-35` (acknowledges this) + missing in stylesheets | **Zero today** — `_facts_strip.html` is reachable only via `card_smart_brevity` (`ai_rewrite_version==3`) or `card_verification_pending` (`processing_status=='cross_stage_conflict'`). Both A8-gated, both unreachable. **At A8 launch**: citizens see ", Green tier" / ", Red tier" rendered visibly next to dollar amounts. The 4-line CSS utility is much smaller than the design pass. |
| **CQ-3** | **`format_dollars` called twice in the partial** — once in `aria-label` attribute, once in visible text. Both go through `_coerce_amount` → `Decimal` → formatting. Cheap but not free. A single `{% set formatted = amount \| format_dollars %}` would halve invocations. | `dollar_tier.html:46` | **None.** Cosmetic micro-optimization. |
| **CQ-4** | **`test_1_25m_rounds_to_one_decimal` uses loose substring match.** Asserts `result.startswith("$1.")` and `result.endswith("M")` rather than pinning the exact rounding output. With `Decimal('1.25')` and Python's default `ROUND_HALF_EVEN` context, `f"${val:.1f}M"` produces `'$1.2M'`. Locking the exact output would close a small loose end. | `tests/unit/test_dollar_tier.py:439-450` | **None.** Test rigor only. |
| **CQ-5** | **`_facts_strip.html:25` `{% with %}` doc note.** Reviewer notes the same partial may eventually be re-used by meeting-level totals; an inline comment would document the input contract. Optional. | `_facts_strip.html:25` | **None.** Cosmetic note. |
| **CQ-6** | **`_TIER_METADATA` prose duplicates threshold constants.** Prose strings ("under $50,000", "over $1 million") live nowhere else. Thresholds themselves come from `enrichment/dollars.py:_TIER_GREEN/_YELLOW/_ORANGE`. If those constants ever change, the prose silently drifts. The "fail-closed" `_TIER_METADATA.get(color)` returning None catches a NEW color, not a CHANGED threshold. CI would catch via the test assertions, but a cross-link comment would tighten the audit trail. | `filters.py:_TIER_METADATA` | **None.** Audit-trail concern; tests guard against silent drift. |

**`[OK]` items (acceptably handled, noted explicitly):**

- **NamedTuple `__str__` footgun verified safe.** `grep -nE 'dollar_tier\s*(==|!=|in)'` returns zero hits. No code does `if amt | dollar_tier == 'green'` (which would silently break — comparing tuple to string is False).
- **None / 0 / negative regression vs. old `dollar_tier_filter`.** Old returned `""` for None and `classify_dollar_tier(0)` → `"green"`. New returns `None` for both, which Jinja renders as literal `"None"`. BUT every v2 callsite has a `{% if dollars_amount %}` guard; both `None` and `Decimal('0')`/`Decimal('0.00')`/`0` are falsy in Jinja so the guard skips. **No regression on any reachable path.**
- **Defensive matrix complete.** None / 0 / negative / bool / NaN (Decimal+float) / Infinity (Decimal+float, ±) / numeric-string / non-numeric / empty / whitespace / list / dict / Decimal — all handled and tested. `_coerce_amount` is shared between both filters as a single source of truth.
- **Float coercion:** `format_dollars(1.234567e9)` goes through `Decimal(str(value))` → `Decimal('1234567000.0')` → `$1234.6M`. Matches `format_dollars(Decimal('1234567000'))`.
- **Boundary conditions all pinned** — $49,999.99→green, $50K→yellow, $250K→orange, $999,999.99→orange, $1M→red.
- **Security:** autoescape on by default, no `|safe`, no `{% autoescape false %}`, no `Markup(...)`. All filter outputs are plain strings of constant prose.
- **Test rigor:** 68 tests across 5 classes; triple-redundancy asserted in single-render + two SR-traversal-mode tests.
- **Test-fixture mutations strengthen rather than weaken** — `test_smart_brevity_card_dispatcher.py` assertion update now pins all three WCAG channels.

### 4.3 Sonnet 4.6 second-look (foreground, read-only)

**Verdict:** `ship` — but with one new `[FORCING TEST RECOMMENDED]` finding the Opus reviewers missed.

**Per Track 3 protocol** (lesson from E3 second-look): mandatory for E/F/G-track UI tasks; brief explicitly directed adversarial verification of every "OK to ship — unreachable today" claim. Sonnet traced:

- Confirmed dispatcher (`smart_brevity_card.html`) gates on `processing_status` / `data_quality` / `ai_rewrite_version` — none of which `AgendaItem.from_row()` exposes (verified by reading `src/docket/models/agenda.py` — A8 wall is real).
- Confirmed `_facts_strip.html` is unreachable in production today (only included by `card_smart_brevity` and `card_verification_pending`, both gated behind v3 conditions).
- Confirmed v2 backcompat: walked all 4 callsites and verified the `{% if dollars_amount %}` guards.
- Confirmed test-fixture mutations strengthen rather than weaken.

#### N1 — `aria-label` on a plain `<span>` is invalid per ARIA 1.2

**Finding:** `dollar_tier.html:45-48` puts `aria-label` on a plain `<span>`. Per ARIA in HTML and ARIA 1.2 §6.2.1, `aria-label` is only valid on elements with an explicit semantic role. A plain `<span>` has implicit role `generic`, which is on ARIA's **"prohibited naming"** role list. NVDA + VoiceOver on Chrome and Safari may silently ignore the attribute.

**Production impact today:** None — the partial is unreachable behind A8.

**Production impact at A8 launch:** **Path A coverage degrades from "covers AT that doesn't traverse children" to "may not work at all on NVDA/VoiceOver/Chrome+Safari."** The triple-redundancy contract degrades to double-redundancy: visible text + sr-only span (Path B) still works on every screen reader that traverses children. The sr-only suffix `, Red tier` carries the tier semantic. So it's not a WCAG AA failure (the information is reachable), but it's a falsehood in the partial's own comments and in spec §6.1 prose, both of which advertise `aria-label` as the canonical accessible name for non-traversing AT.

**Fix options:**
- **(a) `role="img"` on the outer `<span>`.** ARIA-valid; `aria-label` becomes the accessible name. Standard pattern for "self-contained graphic-like content with a text label."
- **(b) `role="text"` on the outer `<span>`.** Newer; less universally supported.
- **(c) Remove `aria-label` and commit to Path B (visible + sr-only) as the sole AT channel.** Honest by absence; loses the "covers non-traversing AT" claim.
- **(d) Restructure as `<figure aria-label="...">$1.8M ($$$$)<span class="sr-only">, Red tier</span></figure>`.** Bigger DOM change; semantically right.

**Sonnet's recommendation:** Option (a). Smallest diff, ARIA-valid, preserves the spec contract. Spec §6.1 needs the matching one-attribute edit.

**Verdict classification:** `[FORCING TEST RECOMMENDED]` — won't break today (path is unreachable). Should fix before A8 launch. A regression test asserting the role attribute is present would prevent future drift if someone removes it during a CSS pass.

#### N2 — `format_dollars` called twice (duplicate of CQ-3)

Confirmed by Sonnet, same as the Opus code-quality reviewer flagged. `[SUGGESTED]` only.

---

## 5. Deep dive — N1 (`aria-label` on `<span>`)

The most substantive finding in this review. Detailed below because:
1. It's the kind of finding that the Sonnet 4.6 second-look pattern is specifically designed to catch (technical-spec compliance vs. project-spec compliance).
2. Both Opus reviewers verified the partial matches spec §6.1, which is true — but the spec ITSELF has the bug.
3. The fix is trivial and the cost of NOT fixing it accrues silently until a citizen using NVDA hits the v3 path post-A8.

### What ARIA 1.2 says

From the [ARIA in HTML spec](https://www.w3.org/TR/html-aria/), `<span>` has implicit role `generic`. The [ARIA 1.2 spec](https://www.w3.org/TR/wai-aria-1.2/), §6.2.1, lists `generic` among the **"prohibited naming"** roles — i.e. roles where `aria-label` and `aria-labelledby` are explicitly **not allowed**. The reasoning: `generic` carries no semantic meaning, so naming it doesn't make sense — there's no "thing" to name.

Different screen readers handle violations differently:
- **NVDA + Chrome:** silently ignores `aria-label` on `<span>`.
- **NVDA + Firefox:** sometimes honours it (older NVDA versions; current NVDA tracks the spec more strictly).
- **VoiceOver + Safari:** silently ignores.
- **VoiceOver + Chrome:** mixed.
- **JAWS:** generally respects but issues a console warning.

So: assume `aria-label` doesn't fire on a plain `<span>` for at least 50% of citizens using assistive tech.

### Why Path B saves us

The partial does NOT rely solely on `aria-label`. The visible text + `<span class="sr-only">, Red tier</span>` carries the same semantic via children. Every screen reader that traverses children (which includes NVDA, JAWS, VoiceOver, Orca, TalkBack, ChromeVox in their normal reading modes) will read the on-screen text + sr-only text. So a citizen using any mainstream screen reader gets the tier semantic via Path B regardless of whether Path A fires.

The cost is that the partial advertises a triple-redundant contract that is, in practice, double-redundant on at least some AT/browser combos. **This is not a WCAG 2.1 AA conformance failure** — the information is perceivable via Path B. But it's a falsehood in the partial's docstring (lines 16-19) and in spec §6.1 prose ("Plus `aria-label` … on the parent for assistive tech that doesn't traverse children. WCAG 2.1 AA compliant.").

### The fix

Adding `role="img"` to the `<span>` is the standard pattern for "this element is a self-contained visual unit with a text label." ARIA-valid. Six characters (`role="img"` plus a space). Spec §6.1 needs the matching edit. One additional test (`test_outer_span_has_role_img_for_aria_label_validity`) locks in.

Alternative: remove `aria-label` entirely (Option C above), accept that Path B is the only AT channel, update spec §6.1 prose to drop the "for AT that doesn't traverse children" claim. This is honest-by-absence but loses a defense-in-depth layer.

**Recommendation:** Option (a). Both prior reviewers and the second-look agree the visible-text + sr-only path works; adding `role="img"` makes the aria-label work too, restoring the triple-redundancy claim to truth.

---

## 6. Deep dive — `.sr-only` CSS missing (CQ-2)

Second-most substantive finding. Same pattern as E4's "structurally unreachable until A8" deferred items: the bug doesn't fire today, but the day A8 launches it becomes a citizen-visible regression — and unlike most A8-gated concerns, this one is a **4-line fix**.

### What citizens see today

Nothing. `_facts_strip.html` is included only by `card_smart_brevity.html` and `card_verification_pending.html`. Both of those are gated by dispatcher conditions (`item.ai_rewrite_version == 3` and `item.processing_status == 'cross_stage_conflict'`) that never fire because the AgendaItem dataclass doesn't expose those columns. The partial never renders in any production code path today.

### What citizens see at A8 launch

Without `.sr-only` CSS, `<span class="sr-only">, Green tier</span>` renders as ordinary visible inline text. So a $87,500 abatement contract on a `card_smart_brevity` would render as:

> $87,500 ($), Green tier

Visibly, on screen. Citizens see the tier name in plain text next to the symbol. Aesthetically jarring and breaks the visual hierarchy the symbol was meant to compress.

### What the fix looks like

The standard sr-only utility class is widely documented. In `src/docket/web/static/styles.css` (or any of the loaded stylesheets):

```css
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
```

Four-ish lines of CSS. Centrally documented. Used by Bootstrap, Tailwind, and the W3C's own ARIA examples. Adding it now means the partial works correctly the moment A8 lands without anyone needing to remember.

### Why fold into the E5 fix-up

- **The class is already emitted.** `dollar_tier.html` writes `<span class="sr-only">` whether the CSS exists or not.
- **The cost of fixing now ≈ zero.** It's smaller than the design pass.
- **The cost of NOT fixing accrues silently.** Whoever lands A8 may not realize the `.sr-only` dependency exists; the regression appears in production with no test failure.
- **A regression test is cheap to add.** Either an integration test that asserts the `sr-only` class is hidden via headless browser, or a static assertion that the CSS rule exists in some loaded stylesheet.

---

## 7. Deep dive — the `NamedTuple __str__` decision

Worth a paragraph because this is the cleverest piece of code in E5 and deserves the audit trail.

### The problem

Plan §E5 says the `dollar_tier(amount)` filter "returns `('green'|...|'red', '$'|...|'$$$$', 'over $X')`." That's a 3-tuple. The new partial needs all three. But four pre-existing v2 templates have `class="tier-{{ amt | dollar_tier }}"` patterns — they expect the filter to return a single string (the color). Two contracts, one filter name.

### Three options the implementer could have taken

1. **Two separate filters** (`dollar_tier_color`, `dollar_tier_full`). Simplest. Loses the plan's contract.
2. **Always return the 3-tuple; rename the v2 callsites** to `class="tier-{{ amt | dollar_tier_color }}"` or `class="tier-{{ (amt | dollar_tier).color }}"`. Plan-compliant. Requires touching 4 v2 templates.
3. **Return a NamedTuple with `__str__` returning the color.** Both contracts via duck typing. Plan-compliant. Zero v2 churn.

The implementer picked option 3.

### Why it works

```python
class DollarTier(NamedTuple):
    color: str
    symbol: str
    description: str

    def __str__(self) -> str:
        return self.color
```

- **For v3 partials:** `tier_data = amount | dollar_tier`; access `.color`, `.symbol`, `.description`. Standard NamedTuple usage.
- **For v2 templates:** `tier-{{ amt | dollar_tier }}` — Jinja autoescape calls `str(value)`. The custom `__str__` returns `self.color`. Output: `tier-green`. Identical to the legacy filter.
- **For tests:** unpacks as a 3-tuple per `test_returns_namedtuple_unpackable_as_3_tuple`.
- **For comparisons:** `dollar_tier(amount) == 'green'` is False (NamedTuple `__eq__` compares as tuple, not string). The code-quality reviewer ran `grep -nE 'dollar_tier\s*(==|!=|in)'` and found zero hits. No code relies on string-equality with the filter result.

### What could break this in the future

- Someone writes `if amount | dollar_tier == 'green'` in a future template. Silently False. Forcing test would catch this.
- Someone does `'green' in (amount | dollar_tier)` — that's a tuple membership check; would be True if `.color == 'green'`. Subtly correct but readable as a string-search bug.
- Future `__hash__` issues with dict keys — NamedTuple hashes as tuple, which is stable, so probably fine.

The implementer wrote `test_str_returns_color_for_v2_template_backcompat` to lock the contract. Worth adding `test_eq_returns_false_when_compared_to_color_string` as a forcing test against the silent-False trap, but this is housekeeping, not required.

---

## 8. Test inventory

### 8.1 `tests/unit/test_dollar_tier.py` (68 tests)

| Class | Count | Coverage |
|---|---|---|
| `TestDollarTierFilter` | ~15 | Boundaries (49,999.99 / 50K / 250K / 999,999.99 / 1M), defensive matrix (None / 0 / negative / bool / NaN / ±Inf / numeric-string / non-numeric / empty / whitespace / list / dict), NamedTuple unpacking, `__str__` returning color |
| `TestFormatDollarsFilter` | ~14 | Sub-$1M full precision, ≥$1M abbreviation, decimal rounding, float coercion via `Decimal(str(...))`, defensive matrix (same set) |
| `TestPartialPerTier` | ~8 | Each color renders correct CSS class + symbol + sr-only text + aria-label per tier |
| `TestPartialNoRender` | ~6 | None / 0 / negative / bool / non-numeric → no `<span>` emitted |
| `TestPartialWcagContract` | ~13 | Triple-redundancy in single render; Path A (aria-label only); Path B (visible + sr-only only); both paths convey complete tier semantics |
| `TestFactsStripDollarTierSwap` | ~12 | `_facts_strip.html` integration: with-block scoping, outer guard preserved, partial renders for each tier, omits cost row when no dollars |

### 8.2 Cumulative Track 3 test count

| Task | Tests added | Cumulative |
|---|---|---|
| E1 (dispatcher + 7 partials) | 23 | 23 |
| E2 (badge chip) | 14 | 37 |
| E3 (engagement strip) | 22 | 59 |
| E4 (source anchor button) `e233b2c` | 38 | 97 |
| E4 (forcing tests) `d0d0ee9` | 3 | 100 |
| E4 (review fix-up) `5f65bc6` | +30 (across `test_source_anchor.py` and new `test_source_security.py`) | ~130 |
| **E5 (dollar tier) `10f52c9`** | **68** | **~200** |

Full v3-partial test suite: **212 passed + 4 xfailed** (the 4 xfails are the E4 forcing tests; nothing new in E5).

### 8.3 Test command

```bash
cd ~/docket-pub-pf2-track-3
PYTHONPATH=$(pwd)/src ~/docket-pub/venv/bin/pytest tests/unit/test_dollar_tier.py -v
# Expected: 68 passed
```

Full track-3 test suite:
```bash
PYTHONPATH=$(pwd)/src ~/docket-pub/venv/bin/pytest \
  tests/unit/test_dispatcher.py \
  tests/unit/test_badges.py \
  tests/unit/test_engagement_strip.py \
  tests/unit/test_source_anchor.py \
  tests/unit/test_source_security.py \
  tests/unit/test_dollar_tier.py \
  tests/unit/test_smart_brevity_card_dispatcher.py \
  -v
# Expected: 212 passed, 4 xfailed
```

---

## 9. Recommended fix-up scope

**Required:** None. All three reviewers say SHIP.

**Recommended (single fix-up commit, ~30 min agent work):**

| # | Fix | From | Effort | Why now |
|---|---|---|---|---|
| **N1** | Add `role="img"` to the outer `<span>` in `dollar_tier.html`. Spec §6.1 matching edit. New test `test_outer_span_has_role_img`. | Sonnet 4.6 second-look | ~5 min | ARIA spec violation. Restores triple-redundancy claim to truth. The whole point of the second-look pattern. |
| **CQ-2** | Add `.sr-only` utility class to `styles.css`. New regression test asserting the rule exists. | Code-quality review | ~5 min | 4-line CSS. Without it, A8 launch makes citizens see ", Green tier" rendered visibly. Cheaper now than the design pass. |
| **CQ-1** | Update `README.md:481` docstring to describe the NamedTuple shape. | Code-quality review | ~2 min | Cosmetic doc rot. Trivial. |
| **CQ-3** | Cache `format_dollars` output via `{% set formatted = amount \| format_dollars %}` in `dollar_tier.html`. | Code-quality review + Sonnet N2 | ~3 min | Halves filter invocations per render. Trivial. |
| **CQ-4** | Pin `test_1_25m_rounds_to_one_decimal` to exact output (`$1.2M` under default Decimal context). | Code-quality review | ~3 min | Test rigor. Trivial. |
| **CQ-6** | Add `# When _TIER_GREEN/_YELLOW/_ORANGE in enrichment/dollars.py change, update prose here too.` cross-link comment to `_TIER_METADATA`. | Code-quality review | ~1 min | Audit-trail aid. |
| CQ-5 | `_facts_strip.html:25` doc note about future re-use | Code-quality review | n/a | **SKIP.** Speculation; cosmetic. |

**Skip CQ-5** (speculation about meeting-level totals re-use; cosmetic only).

**Optional addition:** `test_eq_returns_false_when_compared_to_color_string` — forcing test against the silent-False trap on `dollar_tier(amount) == 'green'` patterns. Documents the contract; cheap.

**Commit message proposal:**
```
fix(web): E5 review fix-up — role="img" for ARIA validity, .sr-only CSS, README + caching
```

---

## 10. Memory + branch state

**Branch:** `feat/impact-first-phase-2-track-3` (worktree: `~/docket-pub-pf2-track-3`)
**Status:** 12 commits ahead of `b4b9a88` (rebased parent on `main`)
**Push state:** **NOT pushed to origin.** Per Track 3 plan, branch stays local until full Track 3 finishes.

```
10f52c9 feat(web): WCAG-2.1-compliant dollar tier with symbols + sr-only labels  ← E5
5f65bc6 fix(web): E4 review fix-up — URL canonicalization, domain allowlist, 501 stub, drop bbox label
d0d0ee9 test(web): xfail-strict forcing tests for E4 TODO cleanups
e233b2c feat(web): adaptive source-anchor button (bbox → page → doc → OCR-needed)
f9c4c3b fix(web): E3 second-look — alias city in cards, stub item_detail+RSS routes
8ce83b2 fix(web): E3 review fixes — RFC 6068 mailto, target=_blank, format_date 3.10 compat
c94410e feat(web): engagement strip with 4 states + mailto fallback for missing data
198f6fb fix(web): E2 review fixes — link CSS, accent token, defensive confidence, _badge_row shared partial
575d898 feat(web): badge chip with Verification Spark + process-first ordering + mobile carousel
2bef322 fix(web): reject protocol-relative URLs in source-link stub
ce273e2 fix(web): E1 review fixes — v2 fallback fields, verification facts/source, scheme validation
1e4e211 feat(web): Smart Brevity Card 6-variant dispatcher + partials
b4b9a88 fix(test): ensure v3 trigger function is installed before each assertion  ← Track 3 base
```

**Track 3 progress:** 5 of 15 tasks complete (E1, E2, E3, E4, E5). Remaining: E6 (depends on A8), F1, F2, F3, F4, F5, G1, G2, G3, G4, plus **A8** (must precede E6).

**Next task per the plan:** E6 — Feature Flag the v3 UI (plan §E6, lines 1806-1838). **Blocked on A8** for the rendering path to actually do anything; the flag itself is independent.

---

## 11. Decisions for the lead engineer

1. **Approve the fix-up scope above (N1, CQ-1, CQ-2, CQ-3, CQ-4, CQ-6, skip CQ-5)?** Or pick a different combination.
2. **For N1, prefer Option (a) `role="img"` or Option (c) remove `aria-label`?** Recommendation: (a). Smallest diff; restores triple-redundancy claim to truth.
3. **For CQ-2, prefer adding the `.sr-only` rule to `styles.css` (the most-loaded stylesheet) or a new `accessibility.css` file?** Recommendation: `styles.css` — keeps one less file to load, matches the existing pattern of utility-class consolidation there.
4. **Add the optional `test_eq_returns_false_when_compared_to_color_string` forcing test?** Cheap, but the underlying trap may never bite. Defensible either way.
5. **Continue to E6 next, even though A8 hasn't landed?** E6 is the `SMART_BREVITY_UI` feature flag — independent of A8 in the sense that the flag can land empty; the dispatcher routing it controls only fires when A8 exposes the v3 columns. Reasonable to land E6 alongside A8 prep, OR pause Track 3 and pick up A8 first. Plan §E6 has E6 sequenced after E5, so following the plan keeps things clean.

---

## 12. Files reviewed (absolute paths)

- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/templates/partials/dollar_tier.html` (the partial under review)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/templates/partials/_facts_strip.html` (integration point)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/templates/partials/smart_brevity_card.html` (dispatcher — confirmed A8 wall)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/templates/partials/card_smart_brevity.html` (v3 card consuming `_facts_strip`)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/templates/partials/card_v2_fallback.html` (v2 card with legacy `dollar_tier` usage)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/templates/{city,topic_detail,search,base}.html` (all v2 callsites + base layout for CSS audit)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/filters.py` (new filters)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/public.py` (legacy filter removed)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/enrichment/dollars.py` (existing tier-classification reused)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/models/agenda.py` (AgendaItem dataclass — A8 wall confirmed)
- `/Users/darrellnance/docket-pub-pf2-track-3/src/docket/web/static/{styles,layout,councilmatic,tweaks,mobile}.css`, `static/css/smart_brevity.css` (`.sr-only` audit)
- `/Users/darrellnance/docket-pub-pf2-track-3/tests/unit/test_dollar_tier.py` (68 tests)
- `/Users/darrellnance/docket-pub-pf2-track-3/tests/unit/test_engagement_strip.py` (fixture mutation)
- `/Users/darrellnance/docket-pub-pf2-track-3/tests/unit/test_smart_brevity_card_dispatcher.py` (fixture mutation)
- `/Users/darrellnance/docket-pub-pf2-track-3/docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` (§6.1 + decisions #71/#75)
- `/Users/darrellnance/docket-pub-pf2-track-3/docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-2.md` (§E5)
- `/Users/darrellnance/docket-pub-pf2-track-3/README.md` (CQ-1)

---

## Appendix A — Reviewer prompts (for reproducibility)

Both first-pass reviews used the **default Opus model** (Sonnet 4.6 was held back for the second-look). Both were dispatched via the `Agent` tool with `run_in_background: true` and read-only access. The second-look used `model: "sonnet"` and ran in foreground.

The full briefs explicitly forbade these phrases:
- "out of scope"
- "downstream task territory"
- "spec gap not implementation gap"
- "track for follow-up"

…per the lesson from E3 second-look (memory: `feedback_reviewer_defer_verify.md`). The bar for `[REQUIRED]` was: "production crashes, mis-renders, leaks data, or fails the security model TODAY without the fix." Anything "would break when X lands" was demoted to `[FORCING TEST RECOMMENDED]`.

The second-look brief specifically attached both prior reviews verbatim and instructed Sonnet to: (a) trace the production code path on every "OK to ship — unreachable today" claim, and (b) consider WCAG conformance from a fresh perspective rather than just verifying spec match.

---

## Appendix B — Glossary

| Term | Meaning |
|---|---|
| **Decision #71** | Project decisions log. "Dollar-tier accessibility symbols" — green=`$`, yellow=`$$`, orange=`$$$`, red=`$$$$`. Color is no longer load-bearing for tier perception. |
| **Decision #75** | "ARIA labels for dollar tiers" — both visible symbols + sr-only label + parent aria-label. Triple-redundant signal: color + symbol + screen-reader text. WCAG 2.1 AA target. |
| **Path A / Path B / Path C** | Screen-reader traversal modes. A: AT reads aria-label, ignores children. B: AT reads children, ignores aria-label. C: AT reads both (some screen readers do this on `<span>` with explicit aria-label). |
| **A8** | Cross-track task: extend `AgendaItem` dataclass + `services/query.py:list_agenda_items()` SELECT to expose v3 columns. Blocks E6's `SMART_BREVITY_UI=true` flip. Same wall identified during E4 review. |
| **`_facts_strip.html`** | The v3 strip rendering structured facts + cost row. Now hosts the dollar-tier partial. Reachable only via `card_smart_brevity` and `card_verification_pending` (both A8-gated). |
| **NamedTuple `__str__` shim** | Custom `__str__` on `DollarTier(color, symbol, description)` returning `self.color` so v2 templates' `{{ amt \| dollar_tier }}` interpolation continues to render `green`/`yellow`/`orange`/`red`. |
| **Triple-redundancy contract** | The WCAG promise that tier perception works (a) without color (visual symbol), (b) without sight (sr-only + aria-label), (c) on monochrome printouts (symbol + visible text). |
| **Generic role / prohibited naming** | ARIA 1.2 §6.2.1. Roles where `aria-label`/`aria-labelledby` are explicitly disallowed. `<span>`'s implicit `generic` role is on this list. |
