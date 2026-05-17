# Granicus "Upcoming Meetings" Blind Spot

**Status:** Reviewed — design phase, not yet implemented
**Filed:** 2026-05-16
**Last revised:** 2026-05-16 (incorporates first review pass: processing_status guard, title-normalization helper, URL-builder concretization, alternative ruled out by evidence)
**Surface:** `src/docket/adapters/granicus.py` — Birmingham ingest path
**Severity:** High for citizen freshness; the platform is invisibly behind the city's own website by 3–10 days for every regular meeting cycle.

---

## TL;DR

The Birmingham city council typically posts the next Tuesday meeting's agenda the prior Friday (with possible Monday revisions). Our Granicus adapter cannot see these agendas — it scrapes only the archive (recorded) table, not the upcoming-events table. By the time a meeting gets a `clip_id` (i.e. is recorded), the agenda is no longer "upcoming" and has limited civic utility.

Confirmed today (2026-05-16): the 5/19 BHM council agenda is live on bhamal.granicus.com and has been since at least Friday 5/15. Our 06:00 CT cron tick ran successfully — it simply has no code path that would surface this agenda.

This is **not a freshness/cron-frequency issue**. Even hourly ingests would not fix it. The fix is in the adapter.

---

## Symptom

- 2026-05-16 06:00 CT: `ingest_all` cron tick fires successfully. Healthcheck green.
- Most recent BHM meeting in `meetings` table: `external_id=1980`, `meeting_date=2026-05-12`.
- bhamal.granicus.com publisher page (`view_id=2`) shows a 5/19 meeting in the "Upcoming Events" section with a live agenda link.
- User-visible result: docket.pub appears to have not noticed the new agenda.

The platform pattern (Birmingham council):
- Friday afternoon: agenda for next Tuesday's regular meeting is posted
- Sometimes Monday: a revised/final agenda is posted
- Tuesday morning: meeting happens, video begins recording, `clip_id` is assigned, row migrates from `#upcoming` to `#archive` on the publisher page

We currently surface a meeting only after step 3, missing the entire pre-meeting window (3–10 days depending on the cycle) when civic readers would benefit most from knowing what's coming.

---

## Investigation

### What we checked

1. **Cron health.** `meetings.updated_at` for BHM rows is `2026-05-16 11:00:02 UTC` (= 06:00:02 CT), exactly the scheduled tick. The worker ran.
2. **Adapter behavior live.** Invoking `GranicusAdapter('birmingham', {...}).list_meetings()` returns the same set of meetings that's in the DB — i.e., the adapter itself is silent about the upcoming meeting, not the ingest path downstream.
3. **Publisher page HTML.** `view_id=2` has both an "Upcoming Events" header and an "Archived Videos" header. The upcoming section contains:

   ```html
   <table id="upcoming" summary="...Upcoming and In Progress Events...">
     <tr class="odd">
       <td class="listItem" headers="EventName" scope="row">
         Regular City Council Meeting
       </td>
       <td class="listItem" headers="EventDate Regular-City-Council-Meeting">
         <span style="display:none;">1779206400</span>
         May 19, 2026 - 09:00 AM
       </td>
       <td class="listItem">
         <a href="//bhamal.granicus.com/AgendaViewer.php?view_id=2&event_id=2692">
           Agenda
         </a>
       </td>
       <td class="listItem" headers="EventLink Regular-City-Council-Meeting"></td>
     </tr>
   </table>
   ```

4. **Other view_ids.** `view_id=1` and `view_id=3` return 404. `view_id=4` exists ("New View") with the same row count as view_id=2 — a duplicate or test view, not a separate upcoming feed.

### What we found

The publisher page has **two structurally different tables**. Our adapter reads one and ignores the other.

| Field            | Archive row (`#archive`)            | Upcoming row (`#upcoming`)              |
|------------------|-------------------------------------|-----------------------------------------|
| Title cell       | `headers="Name"`                    | `headers="EventName"`                   |
| Date cell        | `headers="Date ..."`                | `headers="EventDate ..."`               |
| Date format      | "May 12, 2026" + hidden epoch       | "May 19, 2026 - 09:00 AM" + hidden epoch |
| Duration cell    | `headers="Duration ..."` ("01h 27m") | absent                                 |
| Agenda cell      | `headers="Agenda ..."` → `clip_id=N` | no headers attr → `event_id=N`         |
| Minutes cell     | `headers="Minutes ..."`             | absent                                  |
| Video cell       | `headers="VideoLink ..."`           | `headers="EventLink ..."` (empty)       |
| Identifier       | `clip_id` in agenda/video URLs      | `event_id` in agenda URL only           |

---

## Root cause

Three contributing factors in `src/docket/adapters/granicus.py`:

### 1. Table scope is too narrow

```python
# granicus.py:71
archive_table = soup.find("table", id="archive")
if not archive_table:
    tables = soup.find_all("table")
    archive_table = tables[1] if len(tables) > 1 else tables[0]
```

The adapter explicitly targets `table#archive`. The `#upcoming` table is on the same page but never visited. The fallback path only fires if `#archive` is *missing*, which never happens.

### 2. Identifier extraction requires `clip_id`, with no event_id parser

```python
# granicus.py:277-288
@staticmethod
def _extract_clip_id(row) -> int | None:
    for link in row.find_all("a", href=True):
        match = re.search(r"clip_id=(\d+)", link["href"])
        if match:
            return int(match.group(1))
    for link in row.find_all("a", onclick=True):
        match = re.search(r"clip_id=(\d+)", link["onclick"])
        if match:
            return int(match.group(1))
    return None
```

Upcoming rows contain only `event_id=N`, never `clip_id=N`. There is no `_extract_event_id` counterpart. Even if the table-scope bug were fixed, every upcoming row would fail `_extract_clip_id` and be dropped at:

```python
# granicus.py:240-241
clip_id = self._extract_clip_id(row)
if not clip_id:
    return None
```

### 3. URL builders are clip_id-centric

```python
# granicus.py:46-59
def _player_url(self, clip_id): ...
def _agenda_url(self, clip_id): ...
def _minutes_url(self, clip_id): ...
def _download_url(self, clip_id): ...
def _source_url(self, clip_id): ...
```

All URL builders take a `clip_id`. For an upcoming meeting, the canonical agenda URL is `AgendaViewer.php?view_id=2&event_id=N` — a different shape. We'd need either parallel `_*_url_by_event_id` builders or a single builder that accepts an identifier dict.

### 4. Schema and downstream assumptions

`meetings.external_id` is currently the stringified `clip_id`. If we adopt `event_id` as the external identifier for upcoming meetings, two things must hold:

- **No collision** between event_id and clip_id namespaces. Granicus seems to use disjoint integer ranges (clip_ids ~1980, event_ids ~2692) but we should not bet on that — we should namespace.
- **Reconciliation on transition.** When the meeting is recorded, the same row migrates from `#upcoming` to `#archive`, and the identifier flips from `event_id=2692` to `clip_id=N`. We must detect this and not create a second `meetings` row.

`fetch_agenda_items` and `fetch_votes` both currently do `int(meeting.external_id)` and feed it into `_player_url` (clip_id-based). They will need a branch for the "no clip_id yet" case.

---

## Proposed solution

A two-part change. Part A is the adapter fix; Part B is the operational follow-up.

### Part A — Adapter: read both tables, reconcile on transition

**A1. Add `_extract_event_id` and namespace identifiers.** Mirror `_extract_clip_id` with a regex on `event_id=(\d+)`. Upcoming meetings get `external_id = f"event-{event_id}"`; archived meetings keep `external_id = str(clip_id)`. The `event-` prefix is the namespace boundary — anything starting with `event-` means "no clip_id yet."

**A2. Add `_parse_upcoming_row` alongside `_parse_archive_row`.** Extract the existing `_parse_meeting_row` into `_parse_archive_row` and add a sibling for the upcoming table. Both return `RawMeeting`. Differences:

- `external_id`: `event-N` (upcoming) vs `str(clip_id)` (archive).
- `agenda_url`: built with `event_id=N` (upcoming) vs `clip_id=N` (archive).
- `video_url`, `minutes_url`: `None` for upcoming.
- `meeting_date`: parsed from the hidden epoch span when present; both row types have one. Title format differs ("May 12, 2026" vs "May 19, 2026 - 09:00 AM") but both have the same epoch — prefer epoch and ignore the textual date.
- `source_url`: skip for upcoming, or build a publisher-page anchor.

**A3. URL builder strategy.** The existing builders (`_agenda_url`, `_player_url`, `_minutes_url`, etc.) all take an `int` clip_id. Two viable shapes:

- **(a) Parallel builders.** Add `_agenda_url_by_event_id(event_id: int)` next to `_agenda_url(clip_id)`. Pro: cleanest type signatures. Con: doubles surface area; callers must know which to call.
- **(b) Single builder taking a discriminated identifier.** Builders accept a `str` identifier and branch on prefix: if it starts with `event-`, build the event-id URL shape; otherwise build the clip-id shape. Pro: one entry point per URL; callers can pass `RawMeeting.external_id` directly. Con: type signatures lose precision.

Recommendation: **(a) parallel builders** for `_agenda_url` (the only URL builder that meaningfully has both shapes), single-shape for the rest (which only make sense post-clip_id). Keeps blast radius small and keeps the existing builders untouched. Upcoming meetings simply don't get `_player_url` / `_minutes_url` / `_download_url` called against them.

**A4. Read both tables in `list_meetings`.** Find `table#upcoming` and `table#archive` independently; iterate rows of each; return the union. The existing `since` filter applies uniformly.

**A5. Reconcile on `clip_id` assignment.** When a meeting moves from upcoming to archive, the same meeting will appear as two distinct rows on successive ingests: first as `event-2692`, then as `1980` (when recorded). Three reconciliation options:

| Option                          | Pro                                  | Con                                                  |
|---------------------------------|--------------------------------------|------------------------------------------------------|
| **B1. Match-and-upgrade**       | Single canonical row per meeting     | Requires reliable matching (date + title + city); silent bugs if heuristic fails |
| **B2. Keep both, prefer clip_id in UI** | Dead simple; never lose data | Two DB rows per meeting forever; reader complexity   |
| **B3. Hybrid: write event row, upgrade external_id in place** | Single row + zero dead data | Mutating `external_id` is unusual; FKs that reference `meetings.external_id` would need care |

Recommendation: **B1**. The match key is `(municipality_id, meeting_date, normalize_title(title))` which is already a de-facto identifier for BHM. On the first ingest where the same `(muni, date, title_normalized)` appears with a real `clip_id`, update the existing `event-*` row's `external_id` to the clip_id and refresh URLs. Treat this as a one-way upgrade — never downgrade.

The ingest service already does upserts keyed on `(municipality_id, external_id)`. The reconciliation step needs to happen *before* upsert: look for an existing `event-*` row matching `(muni, date, title_normalized)` and rewrite its `external_id` if found. This is a small addition to `services/ingest.py`, not a schema change.

**Match-key precision (defensive).** Dual-tier match with strict guards:

1. **Exact match** on `(muni, date, normalize_title(title))` — preferred path.
2. **Date-only fallback** when exact-match fails: permitted *only if exactly one `event-*` row exists for that municipality on that date*. If zero, nothing to upgrade — proceed as new insert. If more than one, do not guess — log a warning and proceed as new insert (creating a second row is recoverable; mis-mapping is not).

This rule keeps the upgrade path safe even if a meeting title is edited between Friday ingest and Tuesday ingest, but refuses to silently merge when ambiguity is real.

**A6. Add `normalize_title` to `adapters/_helpers.py`.** Lives next to the existing `classify_meeting` and `is_consent_item` helpers. Signature: `normalize_title(title: str) -> str`. Behavior: lowercase, strip common cancellation/rescheduling suffixes (e.g. `" - Cancelled"`, `" - Rescheduled"`, `" - Postponed"`), drop punctuation, collapse whitespace, return the result. Used by the reconciliation step and any future cross-row title-match logic. Unit tests cover: identity, case folding, suffix stripping, double-spaces, punctuation, unicode whitespace.

**A7. Branch the fetchers and preserve retry capability.** In `fetch_agenda_items` and `fetch_votes`, treat `external_id.startswith("event-")` as "no clip_id, no player page yet" → return `[]`. **Critically**, the ingest service must *not* mark `processing_status.agenda_items_scraped=TRUE` / `votes_scanned=TRUE` for these meetings, or they will be permanently skipped on the next tick when they become eligible.

Why this matters: `_ingest_agenda_items` (ingest.py:206-209) currently marks `agenda_items_scraped=TRUE` whenever the adapter returns an empty list, with the comment `"Mark as scraped even if empty so we don't re-try"`. That behavior is correct for genuine empty agendas. For deferred-because-upcoming meetings, it is a silent foot-gun: `processing_status` is keyed on the integer `meeting_id` (PK), so the flag persists through the eventual `external_id` upgrade from `event-N` → `clip_id`. The result would be a meeting that gains a clip_id but is never agenda-scraped.

Fix: in `_ingest_agenda_items` and `_ingest_votes`, short-circuit *before* calling the adapter when `raw_meeting.external_id.startswith("event-")`. Skip both the adapter call and the `_update_processing_status` write. This way, when the row is re-ingested post-recording with its upgraded external_id, the unchanged `agenda_items_scraped=FALSE` flag lets the normal scrape path run.

For the agenda items themselves: the Granicus AgendaViewer page (`AgendaViewer.php?event_id=N`) renders the posted agenda as HTML and is structurally similar to the post-recording AgendaViewer. There may be a path to parse agenda items directly from this page even before video exists — worth a follow-up investigation but not in scope for the first fix. v1 of this fix ships with meeting-row visibility only (title + date + agenda link), no item-level extraction.

### Part B — Operational

**B1. Ingest cadence.** Currently `ingest_all` runs daily at 06:00 CT. Once Part A ships, the Friday-evening agenda drop would surface Saturday 06:00 CT (worst case ~14h late). Acceptable for v1. A second daily tick (e.g. 14:00 CT) would catch same-day Friday drops within hours; cheap to add (one `sched.add_job` line in `worker/scheduler.py`). Decision can come after Part A ships and we see real-world drop timing.

**B2. Backfill.** Not needed. The fix is forward-only — once it deploys, the next ingest will pick up whatever upcoming meetings exist at that moment.

**B3. Citizen UI surfacing.** The current homepage and city pages prioritize *recent* meetings (180-day notable items, contested votes). An "Upcoming this week" rail or hero block would let upcoming meetings actually be seen by readers. This is a separate frontend ticket; Part A is the prerequisite (no data, nothing to show).

---

## Alternative considered: event_id as primary throughout

If archived rows on the Granicus publisher page exposed `event_id` (in addition to `clip_id`), we could side-step reconciliation entirely by using `event-N` as the canonical `external_id` for the whole meeting lifecycle. No upgrade step, no dual-tier match.

**Ruled out by evidence (2026-05-16).** Scanned all 1003 archive rows on bhamal.granicus.com — zero contain the substring `event_id` anywhere. Granicus appears to discard the `event_id` once a clip is assigned. The match-and-upgrade reconciliation in A5 is necessary.

If a future Granicus deployment surfaces `event_id` on archive rows, this design could be simplified — file as a follow-up to revisit annually.

## Risks and edge cases

1. **Cancelled meetings.** The archive table contains rows like "Regular City Council Meeting - Cancelled" (see 2026-03-17). The upcoming table may carry similar markers before the cancellation propagates. Title-based classification (`classify_meeting`) needs to handle "- Cancelled" suffix — already partially handled but worth a check.

2. **Special meetings.** BHM occasionally holds special/committee meetings. Upcoming-table parsing must not assume "Regular City Council Meeting" — use the title as-is.

3. **Title rewrites.** If the city edits the meeting title between the upcoming-row ingest and the archive-row ingest, the reconciliation match on `(date, title_normalized)` could miss. Mitigation: normalize aggressively (lowercase, strip punctuation, collapse whitespace) and consider matching on `(date,)` alone when there's exactly one BHM meeting that date. The dual-tier match (title-exact, then date-only-with-warning-log) is safer than a single brittle key.

4. **Multiple meetings same day.** Rare for BHM but possible (e.g. pre-council + regular). If the date-only fallback fires when there are 2 same-day meetings, we'd misjoin. Solution: title-exact required when same-day count > 1; log a warning and create a second row otherwise.

5. **Event_id reuse.** No evidence Granicus reuses `event_id` after the meeting transitions to having a clip_id. But the `event-` prefix means even if they did, we'd never re-ingest the same row twice (the upgraded row no longer has `event-N` as its external_id).

6. **Adapter test fixtures.** Existing tests in `tests/unit/test_granicus_adapter.py` use archive-row fixtures. New fixtures needed for upcoming rows; reconciliation logic needs its own integration-style test (ingest event row → second ingest with clip row → assert single meeting in DB with upgraded external_id).

7. **AgendaViewer-by-event_id behavior.** The agenda URL we emit for upcoming meetings (`AgendaViewer.php?event_id=N`) is the same one the city links to publicly. Worth confirming it works in an iframe / direct link from a docket.pub meeting page before shipping.

---

## Out of scope

- Agenda item extraction from upcoming AgendaViewer pages (file for follow-up).
- Detecting and surfacing the Friday → Monday agenda *revision* explicitly. The reconciliation logic already overwrites the row on each tick, so a Monday revision would replace the Friday version; but no audit trail is preserved. Could be a v2 feature.
- Other Granicus cities. Birmingham is currently the only city using `GranicusAdapter`; the fix will naturally benefit any future Granicus city we add.
- Hourly-or-faster ingest cadence. Treat as a separate decision after this lands.

---

## Verification plan

Pre-merge:
1. New unit tests for `normalize_title` (case folding, suffix stripping, punctuation, whitespace, unicode).
2. New unit tests for `_extract_event_id` (regex match, no-match returns None) and `_parse_upcoming_row` fixture (title, date from epoch, agenda URL with `event_id=`, `external_id=event-N`, no minutes/video URLs).
3. New integration test simulating the lifecycle:
   - Tick 1: ingest with upcoming row only → DB has one meeting with `external_id=event-2692`, `processing_status.agenda_items_scraped=FALSE` (not set, since fetcher was skipped).
   - Tick 2: ingest where same `(muni, date, normalize_title)` appears in archive with `clip_id=1981` → DB has single meeting row with `external_id=1981`, agenda items scraped, no orphan `event-` row remaining.
4. New unit test for the dual-tier match guard: two upcoming meetings same date with different titles → archive-row arrival with title that fuzzy-matches one of them via exact-match wins; with a title that matches neither exactly → both `event-` rows preserved, new `clip_id` row created, warning logged.
5. New test that `_ingest_agenda_items` is a no-op (no DB writes, no `processing_status` change) when `raw_meeting.external_id.startswith("event-")`.
6. Live smoke against `bhamal.granicus.com`: run `GranicusAdapter('birmingham', {...}).list_meetings()` in a shell, assert the 5/19 meeting appears (or whatever upcoming meeting exists at that moment) with `external_id` prefixed `event-`.

Post-deploy on Railway:
1. `railway ssh --service worker` → `python -m docket.worker.scheduler --run-once ingest_all`.
2. SQL: `SELECT external_id, title, meeting_date, agenda_url FROM meetings WHERE municipality_id = 1 AND meeting_date > CURRENT_DATE ORDER BY meeting_date LIMIT 5;` — expect at least one row with `external_id` prefixed `event-`.
3. Hit the meeting detail page for the new row in a browser and confirm the agenda link works.
4. On the Tuesday after deploy (when the meeting is recorded), verify the row's `external_id` upgrades from `event-N` to a numeric clip_id, and that no duplicate row appears.

---

## Implementation sketch (rough sizing)

- `adapters/_helpers.py`: ~25 lines (`normalize_title` + suffix list).
- `adapters/granicus.py`: ~100 lines added (`_extract_event_id`, `_parse_upcoming_row`, `_agenda_url_by_event_id`, `list_meetings` reads both tables).
- `services/ingest.py`: ~50 lines added (pre-upsert reconciliation lookup with dual-tier match guard + external_id upgrade; short-circuit in `_ingest_agenda_items` and `_ingest_votes` for `event-*` external_ids before any `processing_status` write).
- Tests: ~200 lines (2 new HTML fixtures, ~8 new unit tests, 1 lifecycle integration test).
- Schema: no migration needed. `external_id` is already `TEXT`.
- Single PR. Estimated ~half a day with tests and live verification.

## Change checklist

- [ ] `normalize_title` helper added to `adapters/_helpers.py` with unit tests
- [ ] `_extract_event_id` helper on `GranicusAdapter` with unit tests
- [ ] `_agenda_url_by_event_id` builder on `GranicusAdapter`
- [ ] `_parse_archive_row` (renamed from `_parse_meeting_row`) + new `_parse_upcoming_row`
- [ ] `list_meetings` reads `table#upcoming` and `table#archive`, returns union
- [ ] `services/ingest.py` reconciliation step: lookup by `(muni, date, normalize_title)` with date-only fallback guarded by single-event-row precondition
- [ ] `_ingest_agenda_items` and `_ingest_votes` short-circuit for `event-*` external_ids *before* any `processing_status` write
- [ ] Live smoke against bhamal.granicus.com confirms the next BHM meeting appears with `event-` prefix
- [ ] Post-deploy: verify Tuesday-after-deploy that the row upgrades from `event-N` to a clip_id without creating a duplicate
