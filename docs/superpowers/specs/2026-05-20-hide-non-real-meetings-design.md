# Hide non-real meetings

**Status:** Design — awaiting user review
**Filed:** 2026-05-20
**Surface:** `meetings` table + service-layer reads + admin web routes
**Severity:** Medium — recurring data-quality noise from operator-published Granicus "test" clips that surface as empty meeting cards on the citizen site.

---

## TL;DR

Birmingham's Granicus operators publish short test/procedural clips with some frequency. These appear in the `#archive` table alongside real meetings, get ingested by our normal pipeline, and surface on docket.pub as empty meeting cards (e.g., meeting id `2233`, BHM 2026-05-18, 11-minute clip, zero index-points, zero agenda items).

There is currently no mechanism to suppress them. This spec adds a soft `is_hidden` flag on `meetings`, a service-layer filter at every public read-path, a logged-in-admin toggle on the meeting detail page, and a small `/admin/meetings/hidden` index for audit and reversal.

---

## Symptom (the trigger case)

- **Meeting id 2233** (BHM 2026-05-18, Granicus `clip_id=1981`): 11-minute clip, 0 agenda items, 0 votes, 0 `<div class="index-point">` chapter markers.
- The clip's `AgendaViewer` redirects to **the same PDF** as the Tuesday 5/19 meeting (`bhamal_9aaa36264b4b8d8e9a52e9138b836fd8.pdf`), so it looks superficially like it has an agenda — but the operator did not actually hold a meeting against those items.
- User-visible result: docket.pub's Birmingham landing renders a "Regular City Council Meeting" card for 5/18 that has nothing in it.
- This pattern recurs ("they do tests with some frequency and do not comment on them well") — so a one-off SQL hack is insufficient.

A title-based hack would not survive the daily ingest cycle: `_upsert_meetings` (`src/docket/services/ingest.py:159`) overwrites `title` on every run. A dedicated column is required.

---

## Out of scope

These are deliberately deferred:

- **Heuristic auto-flagging.** A future task could mark suspicious archived clip-id rows (0 items + 0 index-points + agenda_url shared with another meeting within ±2 days) as `is_hidden_suggested=TRUE` and route them through an admin review queue, similar to refactor #2's `agenda_item_badges.status='flagged'` pattern. Not built in v1; operator flags meetings manually.
- **Bulk hide / bulk unhide.** v1 is one-at-a-time. If frequency increases meaningfully, revisit.
- **Public "this meeting was hidden by admin" indicator.** Hidden meetings are simply absent from public surfaces. No "[Hidden]" placeholder shown to anonymous users.
- **Hiding individual agenda items.** v1 hides whole meetings. Items inside a hidden meeting are filtered transitively via the JOIN; there is no per-item `is_hidden`.

---

## Design

### 1. Data model — migration 033

```sql
ALTER TABLE meetings
    ADD COLUMN is_hidden  BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN hidden_at  TIMESTAMPTZ NULL,
    ADD COLUMN hidden_by  INTEGER NULL REFERENCES admin_users(id) ON DELETE SET NULL;

CREATE INDEX idx_meetings_public_visible
    ON meetings (municipality_id, meeting_date DESC)
    WHERE is_hidden = FALSE;
```

The partial index covers the hot path (public meeting lists, ordered by date within a city) without paying for hidden rows.

`hidden_at` and `hidden_by` provide an audit trail and feed the admin index (§5). They are cleared on unhide.

Migration is reversible: `--down` drops the index and the three columns.

### 2. Filter scope — anywhere-hidden

Every public read-path that returns meetings (or items joined to meetings) must filter `mt.is_hidden = FALSE` (or the equivalent `m.is_hidden = FALSE` join predicate).

**Call-sites to patch** (to be confirmed during implementation by grep — this list is the inventory I plan to inspect and either patch or explicitly justify skipping):

| Call-site | File | Purpose |
|---|---|---|
| `list_meetings()` | `services/query.py:65` | Citizen meetings list per city |
| Dashboard count | `services/query.py:437` | Total meeting count on landing KPIs |
| City-landing "recent meetings" | `services/query.py:~860–960` block | Hero / feed strips |
| Item lookups joined to meeting | `services/query.py` (multiple) | Item detail + lists must hide items whose parent meeting is hidden |
| Search (FTS) | `services/query.py` | Meeting and item search results |
| Member detail "items voted on" | `services/query.py` | Member rail |
| Coverage entries linking to meeting | `services/query.py` | Editorial coverage surfaces |
| Category landing volume MV | `mv_badge_volume_monthly` consumers | Must exclude hidden meetings — see note below |
| RSS | `web/public.py` RSS routes | Feed output |

**MV note:** `mv_badge_volume_monthly` is a precomputed materialized view. The cleanest approach is to add the `is_hidden=FALSE` filter to the MV's defining query (migration 033 includes a `CREATE OR REPLACE MATERIALIZED VIEW` step) and refresh it as part of the deploy. This avoids per-read filtering against the MV.

**What does NOT get patched:**
- Admin routes (`web/admin.py`) — admins must see everything, including hidden rows.
- Ingest pipeline — must still see hidden meetings to upsert them (avoids re-INSERT duplicates).
- The internal `agenda_items` table itself — items are filtered transitively via their parent meeting's `is_hidden`.

### 3. Meeting detail page behavior

`/al/<city>/meetings/<id>/` (`web/public.py` `meeting_detail` route):

| Case | Behavior |
|---|---|
| `is_hidden=FALSE` | Render normally. No change. |
| `is_hidden=TRUE`, anonymous user | **404.** Treated as if the meeting doesn't exist. |
| `is_hidden=TRUE`, logged-in admin | Render normally, with a yellow banner at the top: *"This meeting is hidden from the public site. [Unhide]"* |

Admin-detection reuses the existing session-based auth (`session['admin_user']` is populated on login — see `web/auth.py:51`). The page itself is not `@login_required` — anonymous users still get 404 for hidden, 200 for visible. Only the admin-banner branch is conditional on `session.get('admin_user')` being set.

### 4. Admin toggle on meeting_detail

For any logged-in admin viewing `meeting_detail.html`, render a small action near the meeting header:

- If currently visible → `<form method="post" action="/admin/meetings/<id>/hide">` with a "Hide this meeting" button and a brief confirm prompt.
- If currently hidden → "Unhide" button inside the yellow banner from §3.

Two new admin routes in `web/admin.py`:

```python
@admin_bp.post("/meetings/<int:meeting_id>/hide")
@login_required
def hide_meeting(meeting_id):
    # Resolve admin_user_id from session['admin_user'] (username string)
    # UPDATE meetings SET is_hidden=TRUE, hidden_at=NOW(), hidden_by=<resolved id>
    # Redirect back to meeting_detail with flash
    ...

@admin_bp.post("/meetings/<int:meeting_id>/unhide")
@login_required
def unhide_meeting(meeting_id):
    # UPDATE meetings SET is_hidden=FALSE, hidden_at=NULL, hidden_by=NULL
    # Redirect back to meeting_detail with flash
    ...
```

Username-to-id resolution is a single `SELECT id FROM admin_users WHERE username = %s` against the session value. Both routes are POST-only (no GET). The existing admin routes (e.g., `add_member`, coverage) do not use Flask-WTF CSRF tokens; v1 follows the same convention (re-evaluate codebase-wide if/when CSRF is added).

### 5. Admin index of hidden meetings

`/admin/meetings/hidden` (new route in `web/admin.py`, login-required). Renders a table:

| City | Date | Title | Hidden at | Hidden by | Action |
|---|---|---|---|---|---|
| Birmingham | 2026-05-18 | Regular City Council Meeting | 2026-05-20 14:32 CT | darrell | [Unhide] |

Linked from the existing admin nav (header link). Query joins `meetings → municipalities → admin_users`, ordered by `hidden_at DESC`.

Each row's "Unhide" button posts to the same `/admin/meetings/<id>/unhide` endpoint used by the meeting-detail banner.

### 6. Ingest preservation

`_upsert_meetings` (`services/ingest.py:158-172`) explicitly enumerates the columns it updates:

```sql
UPDATE meetings SET
    title = %s, meeting_date = %s, meeting_type = %s,
    agenda_url = %s, minutes_url = %s, video_url = %s,
    source_url = %s,
    start_time = COALESCE(%s, start_time)
WHERE municipality_id = %s AND external_id = %s
```

`is_hidden`, `hidden_at`, `hidden_by` are **not** in this list, so daily Granicus ingest will preserve them. A regression test pins this contract: ingest a meeting → set `is_hidden=TRUE` → re-ingest → assert `is_hidden` is still TRUE.

No change to `_upsert_meetings` is required.

### 7. Tests

| Test | Type | Asserts |
|---|---|---|
| Migration up + down | unit | Columns + index exist after up; absent after down |
| `list_meetings` excludes hidden | service | A `is_hidden=TRUE` meeting does not appear |
| Search excludes hidden | service | FTS query that would otherwise match a hidden meeting/item returns 0 hits |
| Member-detail excludes hidden items | service | Items in hidden meetings don't surface on member rail |
| City landing recent feed excludes hidden | service | The "this week" / "recent meetings" query excludes hidden rows |
| RSS excludes hidden | web | RSS feed doesn't include hidden meetings |
| `meeting_detail` 404 anonymous | web | GET `/al/.../meetings/<hidden_id>/` returns 404 for anon |
| `meeting_detail` 200 admin | web | Same URL returns 200 for logged-in admin with banner content |
| Hide POST flips flag + audit | web | `POST /admin/meetings/<id>/hide` sets is_hidden, hidden_at, hidden_by |
| Unhide POST clears flag + audit | web | `POST /admin/meetings/<id>/unhide` clears all three |
| Re-ingest preserves is_hidden | integration | Set flag → run ingest → flag still set |
| Admin index lists hidden meetings | web | `/admin/meetings/hidden` shows the row, ordered by hidden_at DESC |

### 8. Backfill / apply

After deploy, hide the known trigger case:

```sql
UPDATE meetings
   SET is_hidden = TRUE,
       hidden_at = NOW(),
       hidden_by = (SELECT id FROM admin_users WHERE username = 'darrell' LIMIT 1)
 WHERE id = 2233;
```

Run via `railway ssh --service docket-web` (or any psql against `DATABASE_PUBLIC_URL`). One row.

---

## Non-goals revisited (sanity check)

- **Not a hard delete.** Rows stay so daily ingest doesn't loop-create them (idempotent on `external_id`). Hard delete would require also blocklisting the `external_id` to prevent re-ingest.
- **Not affecting analytics.** Umami pageview data for hidden meetings (if anyone visited before hide) stays as-is; we don't retroactively purge it. The `umami_reader` queries don't touch `meetings.is_hidden`.
- **Not a "removed from search index" rebuild.** PostgreSQL FTS reads `search_vector` live; the filter at query time suffices. No re-indexing required.

---

## Estimated cost

~1–1.5 hours including the migration, full filter sweep across `services/query.py`, the admin button + routes + index page, tests, and deploy. Deploys via `railway up --service docket-web --detach` (and a follow-up MV refresh if the category-landing volume MV gets a filter added).
