# F2 Review — Route + Helpers + Security (Opus #1)
**Commit:** b2c93b0
**Reviewer scope:** Route correctness, helper SQL, security audit
**Verdict:** APPROVE WITH SUGGESTIONS

## Summary
The route, both shipped helpers, and the F3 stub are correct and safe. Werkzeug rule-specificity ordering means the new `<slug>/<badge_slug>/` greedy route does NOT swallow the literal `/meetings/`, `/items/`, `/council/`, or `_rail` paths — those bind to literal segments first. SQL is fully parameterized; user-controlled strings never concatenate. Two real correctness gaps surfaced (whitespace not stripped from `?and=` cross-filters; `category_kpis` confidence/significance floor disagrees with `list_items_by_badge` when admin toggles `min_confidence`/`include_low_significance`), neither severe enough to block — F4 is the natural cleanup window. Tests are honest (assert what their names claim).

## REQUIRED
_None._

## SUGGESTED
- [ ] **Cross-filter slugs not stripped** (`src/docket/web/public.py:218-219`) —
  `cross_filters = [s for s in raw.split(",") if s]` keeps leading/trailing
  whitespace verbatim. A bookmarked URL like `?and=blight,%20housing_stability`
  yields `["blight", " housing_stability"]`; the second token won't match any
  `agenda_item_badges.badge_slug` so the page silently shows zero items
  instead of the expected filtered set. Fix:
  ```python
  cross_filters = [s.strip() for s in raw.split(",") if s.strip()]
  ```
  No security risk (the value is parameterized into SQL via psycopg) — just a
  user-facing UX trap. Worth wrapping a unit test around it before F4 lands
  the HTMX dropdown that will start emitting these URLs in volume.

- [ ] **`category_kpis` hardcodes its own confidence + significance contract**
  (`src/docket/services/query.py:1070-1071`) — the SQL hard-codes
  `aib.confidence >= 0.6` and never applies the policy-significance gate.
  `list_items_by_badge` accepts `min_confidence` (default 0.6) AND
  `include_low_significance` (default False, applies the per-badge
  `min_significance` threshold). When admin tooling later renders this page
  with `?min_confidence=0` or `?include_low_significance=true` (decision #61
  contemplates both), the KPI strip ("23 items · $4.2M") will disagree with
  the rendered card count below it. Today the route never passes those, so
  this is latent. Two ways out, ranked: (a) thread `min_confidence` and the
  significance flag into `category_kpis(...)` so all three numbers stay
  consistent, or (b) pin a comment in both helpers stating "KPI strip is
  the *default* render contract; admin overrides intentionally diverge."
  Option (a) is cheap; (b) is acceptable v1.

- [ ] **`year=2026` hardcoded in route** (`src/docket/web/public.py:237`) —
  flagged by implementer. The KPI sub-label "tagged in 2026" is also
  hardcoded in `category_landing.html:36`. For a Phase 2 ship this is fine
  (single-year scope per spec §6.5). Add a `# TODO(post-launch):` and a
  `from datetime import date; date.today().year` follow-up so the page
  doesn't quietly stick to "2026" through January 2027. Same place is a
  good home for the `start_date`/`end_date` wiring in
  `badge_volume_series` (currently 2024-01-01..2026-12-31 hardcoded —
  acceptable for the F3 stub but should become "now() − 24mo" before F3
  ships its real implementation).

- [ ] **Pagination boundary at exactly 25 items** (`src/docket/web/public.py:250`) —
  flagged by implementer. `next_offset = offset + 25 if len(items) == 25
  else None` will paint a "Load more" button when 25 items exist *total*;
  clicking it returns 0 items, which renders the empty-state copy ("No
  items match this badge yet"). Not a crash, but disorienting. Two clean
  options: (a) `LIMIT 26` in `list_items_by_badge`, slice off the
  sentinel, set `next_offset` only when 26 came back (the standard
  cheap-introspection pattern); or (b) accept the spurious empty page —
  it is documented behavior in many large sites. Prefer (a) when F4
  touches this code; not worth a dedicated commit.

- [ ] **Reserved badge slugs**
  (`src/docket/web/public.py:179` vs `:109,:140,:296,:416,:265`) —
  Werkzeug correctly prefers literal-suffix routes over the `<slug>/<badge_slug>/`
  greedy match, so `/al/birmingham/meetings/` keeps hitting `city_meetings`
  and never `category_landing`. The corollary is that any future badge
  whose slug equals `meetings`, `items`, `council`, `_rail`, or
  `hearings.rss` would be **unreachable**. Today's 11 seeded templates
  don't collide, but Phase 4 onboarding scripts should reject these
  reserved slugs. Add a CHECK constraint or seeded-template validator
  (not a route-level fix). Track 1 / D2's matcher tests are the natural
  place to register this.

## NIT
- [ ] **`get_resolved_badge` returns `dict` not a dataclass** — consistent
  with the rest of `query.py` (`get_municipality`, `get_council_member`
  etc. all return `dict`). Mark as decision: keep dicts for read-only
  template payloads; reserve dataclasses for entities flowing through
  the ingest pipeline (Meeting, AgendaItem, Vote). No change requested.

- [ ] **`category_kpis` returns `total_dollars` as `Decimal | int`** — the
  COALESCE returns 0 (Python `int`) when no rows match, but `SUM` returns
  `Decimal` when rows exist. The template's `{% if kpis.total_dollars %}`
  short-circuits cleanly on both, and `format_dollars` handles both. Worth
  a one-line docstring note that callers comparing types should use
  `Decimal(str(value))` or arithmetic (not `isinstance`). Pure NIT.

- [ ] **F3-stub signature parity with plan §F3.1**
  (`src/docket/services/query.py:1084`) — `(city_id, badge_slug, start_date,
  end_date, bucket="month")`. Plan only specifies the return shape; this
  signature is consistent with the spec §6.6 description ("monthly bar
  chart … with mayoral-term overlay"). Approved.

- [ ] **Empty-state copy mentions matchers haven't shipped**
  (`category_landing.html:158-161`) — accurate now (no items have badges
  populated until Track 1 / D2 ships). Add a TODO so the copy gets
  updated when matchers go live; otherwise the page will say "matchers
  haven't shipped" forever. Out of F2 scope.

## Audit notes
The following came back clean:

- **SQL injection surface** — every user-controllable value (`badge_slug`
  from URL, `cross_filter_slugs` from `?and=`, `offset` post-int-cast)
  flows through psycopg `%s` parameters. No `f"…{slug}…"` interpolation
  anywhere in F2's added code. The `EXISTS` subquery in
  `list_items_by_badge` (F1, audited there) takes each cross-slug as a
  positional `%s`. ✓

- **`?offset=…` parsing** — implementer's claim of try/except + clamp
  matches actual code (`src/docket/web/public.py:224-228`). Both
  `offset=notanumber` and `offset=-99` integration tests assert 200, not
  500. ✓

- **`?and=…` parsing** — `request.args.get("and", "")` defaults to empty
  string; `.split(",")` of "" yields `[""]`; `[s for s in … if s]` drops
  empty tokens. The `test_route_empty_cross_filter_string_ignored` test
  verifies the empty-string default does not produce a phantom
  filter. ✓ (See SUGGESTED #1 for the whitespace gap.)

- **Jinja autoescape** — Flask defaults autoescape to True for `.html`
  templates. `category_landing.html` carries no `|safe` filters and no
  `{% autoescape false %}` blocks. `cf | replace('_', ' ') | title` and
  `data-cross-filter="{{ cf }}"` are escaped (attribute and text both).
  `badge.name` / `badge.description` come from
  `priority_badge_templates` / `priority_badges_config` — admin-curated,
  not user-input — so even unescaped they wouldn't be a public XSS
  surface. ✓

- **Helper SQL — `get_resolved_badge`** — `INNER JOIN` on
  `priority_badges_config` correctly enforces the implementer's stated
  contract (template + opted-in city + enabled). Migration 013 declares
  `enabled BOOLEAN NOT NULL DEFAULT TRUE`, so `c.enabled = TRUE` is
  precise (no NULL comparison hazard). The three "not active" cases
  collapsing to a single `None` (and thence 404) is the safer default
  per spec §6.5: rendering a category page for a badge a city hasn't
  opted into would be a silent UX bug. The implementer's flag is
  acknowledged but the chosen behavior is correct. ✓

- **Helper SQL — `category_kpis` year filter on `meeting_date`** — the
  TIMESTAMPTZ concern is moot. Migration 001 declares
  `meetings.meeting_date DATE` (line 49), so `BETWEEN '2026-01-01' AND
  '2026-12-31'` is an inclusive DATE-vs-DATE comparison. December 31
  meetings are captured cleanly; no TZ truncation. ✓

- **N+1 / template iteration** — `list_items_by_badge` returns 25
  `AgendaItem` instances with all v3 fields and lifted facts already
  populated by `from_row`. The template's `{% for item in items %}` loop
  invokes `smart_brevity_card` (dispatcher only) and the chosen variant
  reads only attributes already on the dataclass. No per-item DB
  callback. ✓ (The card variants do NOT receive `item.badges` because
  `list_items_by_badge` doesn't aggregate badges — but per the F1
  docstring's stated contract, badge chips are intentionally omitted on
  the badge-scoped listing. The smart-brevity card dispatcher handles
  empty `badges` cleanly via `default_factory=list`.) ✓

- **Test fidelity** — every test name in `test_category_landing.py`
  matches its assertion shape:
  - `test_route_404_disabled_badge` actually flips
    `priority_badges_config.enabled = FALSE` via `bag.set_enabled` and
    asserts the route returns 404. ✓
  - `test_route_cross_filter_filters_items` adds two items, one with
    both badges and one with only the primary, and asserts the
    cross-filtered response contains the dual-badged item title and
    NOT the primary-only item title. Verifies the helper actually
    received and applied the slug. ✓
  - `test_route_pagination_offset` adds 26 items and asserts
    `"offset=25"` in the first response body and `"offset=50"` NOT in
    the second. Verifies offset flows through and `next_offset`
    sentinels correctly. ✓
  - Test pollution resistance: `_Bag.cleanup()` restores `enabled`
    flags, restores `name_override`/`description_override` to original
    values, and deletes inserted items / badges / meetings in
    dependency order. The teardown handles the case where the test
    inserted nothing (empty lists are safe). ✓
