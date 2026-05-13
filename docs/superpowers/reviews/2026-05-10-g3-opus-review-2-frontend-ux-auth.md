# G3 Opus Review #2 — Frontend / UX / Auth

**Reviewer:** Opus 4.7
**Scope:** templates, HTMX, CSS, accessibility, auth coverage on routes
**Commits reviewed:** 76c526e..edd9260 (6 commits)
**Date:** 2026-05-10

## Summary

The G3 frontend is small, internally coherent, and matches the plan's architecture without surprises: one viewer template + one manage page + one HTMX-swap partial, three rendered routes plus two POST handlers, all under the existing admin blueprint's `before_request` auth hook. HTMX wiring is correct (single `#badges-manage-panel` swap target, `outerHTML` semantics intact, 307 form-bridge replacing the rejected `onsubmit` hack), and Jinja autoescape covers every user-controlled string with no `|safe` creep.

The findings are mostly polish: one real CSS-token drift (G3 invents `--surface-2` / `--border` / `--muted` tokens that don't exist in `styles.css`, where the established names are `--paper-2/3`, `--rule`, and `--ink-3`), one CSS class double-up (`manage-meta` is reused as both a `<section>` wrapper class and a chip's text-style class), and a handful of accessibility / consistency nits. Nothing blocks merge.

## REQUIRED

**R1 — None.**

No required changes. HTMX wiring is correct, auth coverage is complete, anti-XSS is clean, the 307 form-bridge replaces the JS hack as the reviewer demanded, and the swap-target id is unique across the rendered DOM.

For the avoidance of doubt, here are the things that could have been REQUIRED and aren't:

- **HTMX swap target uniqueness:** `<section id="badges-manage-panel">` appears exactly once on `badges_manage.html` (via `{% include %}` of the partial) and exactly once at the top of the partial (`_badges_manage_panel.html:8`). After `outerHTML` swap, the wrapper continues to exist with the same id. Verified.
- **Outermost element is the wrapper:** `_badges_manage_panel.html:8` IS `<section id="badges-manage-panel" class="manage-panel">` — first non-comment node, last `</section>` is line 51 closing the file. `hx-swap="outerHTML"` will replace the right thing.
- **Add-form dispatch (decision #11):** `_badges_manage_panel.html:36` is `hx-post="{{ url_for('admin.badge_add_via_form', item_id=item.id) }}"`. Slug is in the body via the `<select name="slug">` (line 42), not the path. Route handler at `admin.py:813-829` does the 307 redirect to `admin.badge_add` with slug-in-path. No `onsubmit` JavaScript anywhere in the templates — verified by `grep "onsubmit\|<script"` returning zero hits in `_badges_manage_panel.html` / `badges_manage.html` / `badges_audit.html`.
- **Auth coverage:** all five new routes (`badges_audit`, `badges_manage_item`, `badge_add`, `badge_add_via_form`, `badge_remove`) are bound to the `admin` blueprint (`bp.route("/badges/...")`), which means their endpoints all start with `admin.` and hit the `before_request` hook at `admin.py:27-35`. Tests `test_admin_badge_audit_route_redirects_anonymous`, `test_manage_page_redirects_anonymous`, `test_add_endpoint_requires_login`, and `test_remove_endpoint_requires_login` lock this in; the form-bridge route inherits the same hook (no separate test, but architecturally identical to the others).
- **GET-vs-POST hygiene:** mutating endpoints have `methods=["POST"]`; GET tests assert 405 (`test_add_endpoint_requires_post`, `test_remove_endpoint_requires_post`). Read-only endpoints accept GET only.
- **Anti-XSS:** zero `|safe` filters in any new template. Every user-controlled string (`r.actor`, `r.reason`, `r.badge_slug`, `r.item_title`, `item.title`, `filter_*`) flows through Jinja autoescape. The `<code>{{ r.badge_slug }}</code>` pattern is fine (the `<code>` element doesn't disable escaping; `{{ ... }}` is what controls escaping, and it's still escaped).
- **Filter form round-trip:** `filter_since[:10]` slice is a defensive no-op given that the route already echoes the raw `YYYY-MM-DD` string (`admin.py:644-645`). Not actively wrong.
- **Pagination URL hygiene:** `or none` correctly maps empty strings → Python `None` → Flask `url_for` omits the kwarg, so URLs with no filters set are `/admin/badges/audit?offset=50` rather than `/admin/badges/audit?badge_slug=&actor=&...&offset=50`. Edge case at `prev_offset=0`: `offset=none` → omitted entirely, URL collapses to bare `/admin/badges/audit`.

## SUGGESTED

**S1 — CSS variable names invented, not aligned with design tokens** (`tweaks.css:259, 272, 289, 294`).

`tweaks.css` introduces `var(--surface-2, #f6f6f4)`, `var(--border, #e6e6e0)`, `var(--muted, #6a6a60)` — none of these custom-property names are defined in `styles.css`. The actual design tokens are:

| Invented name        | Real token in `styles.css`                      |
|----------------------|-------------------------------------------------|
| `--surface-2`        | `--paper-2` or `--paper-3` (oklch warm paper)   |
| `--border`           | `--rule` (oklch 0.88 0.008 85)                  |
| `--muted`            | `--ink-3` (oklch 0.52 0.010 250)                |

Because the fallback is provided, the page renders correctly — but the CSS will *never* pick up the actual design tokens, only the hardcoded fallbacks. Compare the G2 admin queues at `tweaks.css:208-233` which correctly use `var(--rule, #ddd)` and `var(--paper-3, #f5f5f5)`. The pattern was established in G1/G2; G3 drifts off it.

Recommended: rename to `var(--paper-2, #f6f6f4)`, `var(--rule, #e6e6e0)`, `var(--ink-3, #6a6a60)` (or pick the closer existing token). Single-file find-and-replace; no template change needed.

**S2 — `manage-meta` class is overloaded across two semantically different uses** (`badges_manage.html:20`, `_badges_manage_panel.html:18`).

The same class name is applied in two distinct semantic roles:

1. `badges_manage.html:20`: `<section class="manage-meta">` — wrapper around the item title + city/date caption at the top of the manage page.
2. `_badges_manage_panel.html:18`: `<span class="manage-meta">(...source/confidence...)</span>` — secondary text inside a current-badge chip.

Both inherit the rule at `tweaks.css:294` (`font-size: 0.8rem; color: var(--muted, #6a6a60)`). The styling happens to be visually acceptable for both, but the class is doing double duty. If anyone later targets `.manage-meta` (e.g., `.manage-meta { display: block }`) to fix one site, they'll break the other.

Recommended: rename one. The chip-internal version could become `.manage-chip-meta`; the section wrapper could become `.manage-item-caption` or just drop the class and let `<section>` margins from base styles do the work.

**S3 — Empty-state heading inconsistent with G2 admin queues** (`badges_audit.html:57-58`).

The empty state for the audit viewer is `<p class="t-meta">No audit rows match these filters.</p>` — no `<h2>Empty</h2>` heading. That matches the calibration dashboard's empty-state pattern (`calibration.html` uses bare `<p>` for each panel's empty case), but diverges from the G2 admin queues:

- `data_debt.html:55-61`: wraps the empty state in `<section class="cal-panel"><h2>Empty</h2><p>...</p></section>`.
- `errors.html:58-61`: same `<section class="cal-panel"><h2>Empty</h2>...</section>` wrapper.

The G2 fix-up (R-S-NEW-2) explicitly established the `<h2>Empty</h2>` precedent for admin queue pages. The audit viewer is a queue-shaped page (filterable list of rows + pagination) and arguably should match the queues, not the calibration-panel pattern. Worth a small wrap to match.

**S4 — `.manage-remove` button color contrast is borderline for small text** (`tweaks.css:295-302`).

`.manage-remove` is `color: #c66; border: 1px solid #c66; background: none; font-size: 0.8rem` (≈12.8px). Against the `--paper` background (oklch 0.985), `#c66` lands around 3.3:1 contrast.

- WCAG AA for *normal* body text: 4.5:1 (FAIL).
- WCAG AA for *large* text or non-text UI components: 3:1 (PASS).

A 12.8px button is "normal" by WCAG's definition (large = 18pt/24px or 14pt bold). The button reads as light pink-red on near-white — fine for users with normal vision, but technically below AA for low-vision users.

Recommended: darken to oklch(~0.45 0.16 25) or use a token like `var(--bad, #c33)`. Easy fix.

**S5 — No-JS form fallback for the add form is broken** (`_badges_manage_panel.html:35-49`).

The add form has `method="post"` and `hx-post="..."` but no `action="..."` attribute. If HTMX fails to load (CDN block, dev-tools-with-network-disabled, etc.), browsers submit forms with no action to the page's current URL — `/admin/badges/items/<id>` — which is GET-only, and the user gets a 405.

The remove form (line 20) is even worse: no `method=`, no `action=`, only `hx-post`. Without HTMX, clicking "× Remove" does nothing.

This is a known project-wide tradeoff (the project assumes HTMX is loaded; `base.html` includes it via CDN), but worth flagging because HTMX-via-CDN is the one external dependency that can fail. If you ever care about graceful degradation, the add form should at minimum get `action="{{ url_for('admin.badge_add_via_form', item_id=item.id) }}"`. The remove form would need `<form method="post" action="{{ url_for('admin.badge_remove', ...) }}">`.

Acceptable for v1; flagging.

**S6 — No user-facing confirmation after add/remove** (referenced by reviewer's "HTMX UX" bullet).

After a successful add or remove, the panel swaps and the only visual feedback is "the slug is now / no longer in the current-badges list." No flash banner, no toast, no "Badge removed" message. Compare the G2 retry/escalate handlers in `data_debt.html:46-52` which render `get_flashed_messages()` into a `.queue-flash` list.

For an admin-only surface, this is borderline acceptable — the admin probably wants to do many adds/removes in a row and each banner is friction. But on a slow connection where the swap takes 800ms, the lack of any "saved" affordance is unsettling. Consider an `hx-indicator` or a flash-via-HX-Trigger banner in a follow-up.

**S7 — `<th>` cells lack explicit `scope="col"`** (`badges_audit.html:62-71`).

The audit table's column headers are bare `<th>...</th>`. The HTML5 spec says `<th>` inside `<thead>` is implicitly `scope="col"`, and modern screen-readers handle this correctly. Adding `scope="col"` explicitly is belt-and-suspenders best practice.

Compare `data_debt.html:67-75` and `errors.html:67-76` — they also omit `scope=`, so this isn't a G3-introduced regression. But if you want one of these queues to be the "good example" for accessibility, add `scope="col"` to all five admin tables in a follow-up sweep.

## NICE-TO-HAVE

**N1 — Nav strip ordering across admin templates is inconsistent.**

The cross-link bullet ordering varies:

| Template            | Nav strip                                                                      |
|---------------------|--------------------------------------------------------------------------------|
| `members.html`      | `+ Add Member · Badge audit · AI Pipeline →` (3 links)                         |
| `ai_panel.html`     | `← Council Members · Badge audit` (2 links)                                    |
| `calibration.html`  | `← Council Members · Badge audit · AI Pipeline →` (3 links)                    |
| `data_debt.html`    | `← Council Members · Badge audit · Calibration · Errors queue → · AI Pipeline` |
| `errors.html`       | `← Council Members · Badge audit · Calibration · ← OCR queue · AI Pipeline`    |
| `badges_audit.html` | `← Council Members · Calibration · OCR queue · Errors queue · AI Pipeline`     |

Three templates have a 5-link strip, two have a 3-link strip, one has a 2-link strip. "Badge audit" position varies (2nd in most, but absent in the audit's own strip — by design — which is fine).

This was already drift before G3; the implementer correctly preserved each template's existing pattern when inserting "Badge audit" rather than mass-rewriting. A future cleanup task could pick a canonical 5-link order and apply it everywhere.

**N2 — `<form style="display: inline;">` is redundant inside a flex container** (`_badges_manage_panel.html:23`).

The remove form has `style="display: inline;"` to keep the X button on the same line as the chip. But its parent `<li>` is `display: flex; align-items: center; gap: 0.75rem` (`tweaks.css:284-290`), which already lays children out horizontally. The inline override has no effect inside a flex container — flex items use the flex algorithm regardless of their own `display: inline`. Harmless, but cargo-culted.

Could be dropped. Or, if you want the form to truly behave inline (e.g., outside flex contexts in some future template re-use), `style="display: inline;"` is fine to leave.

**N3 — No 405 / requires_login test for `badge_add_via_form` (the 307 form-bridge).**

The four canonical routes have explicit auth + method-not-allowed tests. The form-bridge does not. Architecturally it inherits both behaviors (same blueprint, same `methods=["POST"]`), so this is belt-and-suspenders. If future refactoring moves the bridge out of the blueprint, the test would be the safety net.

```python
def test_add_via_form_requires_login(client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m)
    resp = client.post(f"/admin/badges/{iid}/add", data={"slug": "contested"})
    assert resp.status_code in (302, 303)
    assert "/admin/login" in resp.headers.get("Location", "")

def test_add_via_form_requires_post(admin_client, bag):
    m = bag.add_meeting()
    iid = bag.add_item(m)
    resp = admin_client.get(f"/admin/badges/{iid}/add")
    assert resp.status_code == 405
```

**N4 — The audit table renders one row across multiple HTML lines, which the implementer's deviation #2 confirmed via `body.count("g3-test") == 1`.**

The implementer flagged that the original test (single-line "actor and slug appear together") didn't work because Jinja `{% for %}` emits cells on separate lines. That's a Jinja-rendering quirk, not a layout bug — the rendered DOM has each `<tr>` correctly hosting its `<td>` cells; the source HTML just has linebreaks between them. The deviation's resolution (count occurrences of unique actor name) is sound. No template change needed; flagging because the reviewer asked.

**N5 — No `hx-indicator` for slow swaps.**

Per the spec, the implementer noted "Loading indicators: HTMX defaults work, but no `hx-indicator` is set. v1-acceptable." Agreed. On a slow connection or during DB lock contention, the swap can take 1-2 seconds and the user has no spinner. v2 polish.

**N6 — Date input labels stack vertically; mobile may want horizontal labels.**

`.audit-filter label { display: flex; flex-direction: column; }` (`tweaks.css:262-266`) stacks the "Since" / "Until" labels above the date inputs. The filter row uses `flex-wrap: wrap` so on narrow viewports the inputs flow to subsequent rows. Acceptable. If you're aiming for a more compact filter UI on mobile, `flex-direction: row; gap: 0.4rem;` with the label-text and input on the same line would tighten it. Not a blocker.

**N7 — The "Remove" button uses `× Remove` text where G2 conventions might have used `Remove` alone.**

Minor readability point. The `×` glyph in `× Remove` is decorative and SR-skipped (the `aria-label="Remove {{ b.name }}"` carries the meaning). If the visible text is also "Remove", consider whether the leading `×` adds enough utility to justify the visual weight. Either way works.

## Decisions to escalate to user

**None.** This G3 frontend is mergeable as-is. Every finding above is polish or future-cleanup territory.

The one item worth a shrug-and-decide is **S1 (CSS token drift)**. It would take 5 minutes to fix and would bring G3 in line with G2's CSS-token discipline. Up to the user whether to fix-up before merge or carry it forward as cleanup.

---

## Verification notes

Files actually inspected:

- `src/docket/web/templates/admin/badges_audit.html` (113 lines)
- `src/docket/web/templates/admin/badges_manage.html` (28 lines)
- `src/docket/web/templates/admin/_badges_manage_panel.html` (51 lines)
- `src/docket/web/static/tweaks.css:251-304` (G3 additions)
- `src/docket/web/static/styles.css:1-90` (token reference)
- `src/docket/web/templates/admin/data_debt.html`, `errors.html`, `calibration.html`, `ai_panel.html`, `members.html` (cross-link diffs + tone reference)
- `src/docket/web/templates/base.html` (HTMX include, CSS load order)
- `src/docket/web/templates/partials/badge_chip.html` (visual-consistency baseline)
- `src/docket/web/admin.py:25-35, 537-885` (auth hook + G3 route decorators + redirect/abort calls in handlers — read for endpoint name + method verification, not for SQL review)
- `tests/integration/test_admin_badge_audit.py:380-815` (HTML-rendering assertions: 200s, login redirects, 405s, body substrings, swap-target id presence)

Total review time scoped to ~30 minutes of reading + cross-referencing. No tests run.
