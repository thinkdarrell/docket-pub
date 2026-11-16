# Give Birmingham a "What's coming up" page and a calendar feed of the same entries

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

Today a Birmingham resident who wants to know what is ahead has to read three places on the city's own sites: the council's video site for the next council meeting, the city calendar for committee meetings, and a three-page PDF for the hundred neighborhood associations. A public hearing's date is harder still: it is one sentence inside a resolution on an earlier agenda. docket.pub already stores the first two and the agenda text, and shows none of it as a list of what is ahead. `https://docket.pub/al/birmingham/coming-up/` answers 404 today and no calendar feed exists anywhere in `src/`.

After this work a reader opens `/al/birmingham/coming-up/` (linked from the Birmingham city page) and sees one list, in date order, of the next 60 days, in three kinds, every entry linked to the city document it came from:

1. Meetings: the council meetings the city's video site lists as upcoming and the council and committee meetings on the city's own calendar, shown together, a council meeting both sources list appearing once.
2. Scheduled public hearings: each hearing whose date a resolution on a Birmingham agenda set, read from the resolution's text by fixed rules with no language model, stored once however many agenda items set it, linked to every one of those items, and given a kind (zoning, weed lots, street or right-of-way, budget, other). A weed-lot resolution is one entry that says how many properties it lists.
3. Neighborhood association meetings: each dated meeting computed from the monthly rule in the Community Resource Services Division's published 2026 schedule, linked to that PDF, with the time, the meeting type, the place, and the call-in details as the schedule gives them and nothing where it gives nothing.

`/al/birmingham/coming-up.ics` returns the same entries as a calendar a phone or desktop calendar can subscribe to: one event per entry on the page.

How to see it working, once every milestone is done: `./tools/verify` passes with the new tests, among them one that asks for the page and the feed from one seeded database and finds the same number of entries in each; after the operator's deploy and backfill (Validation and Acceptance), `curl -s https://docket.pub/al/birmingham/coming-up.ics | head -3` prints `BEGIN:VCALENDAR` first, and the page lists the next council meeting once, with a link to the city's event page and one to the agenda.

## Progress

- [ ] M1: The hearing reader exists as a pure module, and its tests pin what it reads from twenty-five real Birmingham agenda titles.
- [ ] M2: Hearings are stored once per hearing with a link to every agenda item that set them, by a migration and a service whose tests pin the grouping.
- [ ] M3: Ingest keeps hearings current, the backfill script has a dry run, and the dry run's reading of production's rows is recorded and compared with the two earlier counts.
- [ ] M4: The 2026 neighborhood schedule is checked in as the saved PDF and a transcription, and a loader refuses a malformed file or one that disagrees with the PDF.
- [ ] M5: Each schedule rule expands to its 2026 dates, tested against dates worked by hand, and the reading sheet for the operator is generated.
- [ ] M6: One service returns the next 60 days of entries of all three kinds, with meetings from the two sources merged by a tested rule.
- [ ] M7: The page is served at the coming-up address for Birmingham alone and is linked from the city page and the sitemap.
- [ ] M8: The calendar feed is served beside the page, and a test finds one event per entry on the page.
- [ ] M9: The specs, the decision records, the debt rows, and the tour describe what was built and list the operator's steps after the merge.

## Surprises & Discoveries

As authored on 2026-11-16, nothing has been executed, so no session has discovered anything. What the authoring research found in production's rows, which shaped the design, is recorded in Context and Orientation under "What production's rows look like" and is not repeated here.

## Decision Log

- Decision: The hearing reader reads an item's `title` alone, never its `description`.
  Rationale: Read from production on 2026-11-16: where a title is whole, it holds the entire resolution sentence (item 62830's title is 714 characters, its description the same sentence plus the "(Submitted by ...)" notes), and a description can run on into the agenda's boilerplate (item 58878's description continues into "CONSIDERATION OF CONSENT AGENDA ... interested in a public hearing so requests"), which holds the words the reader looks for. Where a title is cut at 255 or 256 characters, the description is NULL (49 of the 78 matching items), so it could not help.
  Date/Author: 2026-11-16, plan author.

- Decision: A hearing whose date the stored title does not hold is not stored and not shown. The dry run lists it as "matched, no date".
  Rationale: `docs/PRINCIPLES.md`, "Source or silence". Eleven of the 78 matching items are of this kind (a budget hearing "in the Council Chambers on the Mayor's proposed budgets", and titles cut before "on the 13th day of ..."). A date guessed from the next council meeting would be a default.
  Date/Author: 2026-11-16, plan author.

- Decision: Two agenda items set the same hearing when their dates and kinds are equal and their subjects, reduced to lower-case letters and digits, are equal or one opens the other and the shorter is at least 40 characters. A weed-lot hearing's subject is its property count.
  Rationale: Items 62830 and 62881 carry identical text. Items 3339 and 3297 set and then amend one hearing (June 10, 2025, 26,875 square feet), and 3297's title is cut after 101 letters of the subject that 3339 carries further. A case number cannot be the key: it sits at the end of the sentence and is cut from every 256-character title. Two zoning hearings of one day differ inside the first 100 letters (items 1680 and 1681, case numbers ZAC2025-00013 and -00022), and two vacations of one day differ at the square footage (items 1152 and 1153), so the opening-text rule keeps them apart. Each of these pairs is a test in M1.
  Date/Author: 2026-11-16, plan author.

- Decision: The page's sentence about an agenda item is "On the agenda of <date>", never "set by" or "adopted".
  Rationale: An item is stored when its agenda is posted, before the meeting, and nothing in the reader checks that the resolution passed. "On the agenda of" is true before and after the meeting, for an item on an agenda whose meeting row is a leftover (item 62881's meeting, `event-2713`), and whatever the vote was.
  Date/Author: 2026-11-16, plan author.

- Decision: Hearing extraction runs as a step inside `ingest_municipality` in `src/docket/services/ingest.py`, not as a new worker task.
  Rationale: New agenda items arrive only through ingest, so the step runs exactly when there is something new. A new task would trip three overdue debt rows at once (`D69`, the prose task counts; `D34`, the `os.environ` reads in `worker/tasks.py` and `worker/health.py`; and it would need its own Healthchecks variable, an operator step). The step is wrapped like the meeting-type step beside it, so a failure is logged in the ingest result and stops nothing.
  Date/Author: 2026-11-16, plan author.

- Decision: The gate is a new key in the city's metadata, `"coming_up": true`, written for Birmingham by this plan's migration. The page and the feed answer 404 for a city without it, and ingest's hearing step does nothing for one.
  Rationale: The same shape as the city briefing's `"briefing": true` (migration 037), so turning a city on is a metadata change. The goal is Birmingham only.
  Date/Author: 2026-11-16, plan author.

- Decision: The neighborhood schedule is loaded on first use and cached in the service, not at application start, and `src/docket/web/__init__.py` is not edited by this plan. The template global `has_coming_up` is registered in `src/docket/web/public.py`.
  Rationale: `D34` in `docs/DEBT.md` fires whenever a plan changes `src/docket/web/__init__.py` without routing its two `os.environ` reads through `config.py`; that is another plan's work. A malformed schedule file is refused by the loader's tests under `./tools/verify`, which is the required check on `main`, so a bad file cannot merge; what is given up is a refusal at start-up of a file changed by hand on the server, which nothing does.
  Date/Author: 2026-11-16, plan author.

- Decision: `src/docket/services/briefing.py` and `src/docket/services/meeting_types.py` are not edited. The city-page link goes in the template partial alone, and the new service calls `meeting_types.classify_event` and `meeting_types._is_live` as they stand.
  Rationale: `D60`, `D61` and `D62` are overdue on `briefing.py` and fire on any touch of it; `D119` fires on the next plan that touches the calendar rung in `meeting_types.py`. `_is_live` is the one owner of "this calendar event was not cancelled" and has a leading underscore; calling it from a second service is recorded as a debt row in M9 (the name should become public when `D119` is paid) rather than copied, because a second copy of the rule is what "One owner per fact" forbids.
  Date/Author: 2026-11-16, plan author.

- Decision: A merged council meeting prints the city calendar's time, and a meeting only the video site lists prints its stored `start_time`.
  Rationale: The stored `start_time` of an upcoming Granicus row is two hours late (GitHub issue #88; meeting 3207 stores 11:00 for a 9:30 meeting). The fix is pull request #181 (`fix/granicus-start-time-pacific`), open and not merged on 2026-11-16. The city's calendar gave 9:30 for the same meeting. In production the council meeting of the coming week was in both sources on 2026-11-16, so the calendar's time is what a reader will see; a row only Granicus lists would print the wrong time until #181 merges, which is why Validation asks the operator to merge #181 first.
  Date/Author: 2026-11-16, plan author.

- Decision: A cancelled meeting is left out of the page and the feed, on either source's word: a Granicus row whose title says cancelled, or a calendar event whose status is neither NULL nor `active` or whose title says cancelled, removes the entry, the merged one included.
  Rationale: The page is a list of things to attend. Showing a meeting one city source calls cancelled because the other has not caught up would send a reader to an empty room.
  Date/Author: 2026-11-16, plan author.

- Decision: All three kinds share one window, today through 60 days ahead in America/Chicago, and the page and the feed are built from one function call, so they cannot differ.
  Rationale: The schedule yields about 98 meetings a month; without a window the page in February would list over a thousand. Sixty days is long enough to hold every hearing a resolution sets (the observed lead is four to six weeks). One window for both is what makes "one event per entry on the page" checkable.
  Date/Author: 2026-11-16, plan author.

- Decision: A neighborhood association is given dates only by the rule the PDF prints. "Fourth Monday @ 6:00 p.m." (East Birmingham) is read as every month, as every other row of the monthly schedule is; "First Monday of this month @ 6:30 pm" (Glen Iris) and "No Meetings" (Bridlewood) are given no dates, and the page names both under the list with the schedule's own words. Overton is given its six named months. No date is moved for a holiday.
  Rationale: "Source or silence". "Of this month" names one month of a document revised on February 3 and does not say which rule holds after it; "No Meetings" beside a printed rule is the city saying the association is not meeting. Naming the two on the page tells a member of either why it is absent.
  Date/Author: 2026-11-16, plan author.

- Decision: The calendar feed is written by a small module of our own, `src/docket/web/ics.py`, with no new dependency.
  Rationale: The feed needs seven properties per event, line folding, and text escaping, about sixty lines. A library would mean a `requirements.txt` change and a regenerated `requirements.lock` for both images.
  Date/Author: 2026-11-16, plan author.

- Decision: `D131` (commit the test-removal runner under `tools/` in the first milestone of the next plan with two or more code milestones) is re-deferred by this plan, and M9 writes the re-deferral into the row.
  Rationale: The operator's goal is a reader's page. The runner is a tool with its own acceptance and belongs to a plan made for it through `skills/capability-build/SKILL.md`. The row has been passed over twice without a word; this time the row says who passed it and why.
  Date/Author: 2026-11-16, plan author.

- Decision: The existing feed `/al/<slug>/upcoming-hearings.rss` and `query.list_upcoming_hearings` are left as they are.
  Rationale: That feed serves every city from a title-contains-"hearing" test over upcoming meetings. Re-pointing it at the new table would change a published feed for cities this plan does not touch. M9 records a debt row for the two notions of an upcoming hearing living side by side.
  Date/Author: 2026-11-16, plan author.

## Outcomes & Retrospective

As authored on 2026-11-16, nothing has been executed and there is no outcome to report. Each milestone session adds its paragraph beneath this one; the closing retrospective is written by the retro stage after the last milestone, not by a milestone.

## Context and Orientation

docket.pub is a Flask application (`src/docket/web/`), an APScheduler worker (`src/docket/worker/`), and operator scripts (`scripts/`) over one PostgreSQL database. `AGENTS.md` at the repository root is the map. Three rules from `ARCHITECTURE.md` shape this plan: services (`src/docket/services/`) own every transaction, and routes, tasks and scripts call them; nothing under `src/docket/web/` executes SQL; and `src/docket/enrichment/` holds deterministic extraction from item text, imports nothing from `services/`, `web/` or `worker/`, and never calls a language model. `docs/PRINCIPLES.md` holds six rules that outrank convenience; read it before M1, because this plan produces and renders data. The two that bind hardest here are "Source or silence" (every data point links to the city's own document, and a value the source does not supply is shown as missing) and "Production is not a sandbox" (no per-row sweep of production; a backfill is bounded and has a dry run).

### What exists today

Upcoming council meetings. The Granicus adapter (`src/docket/adapters/granicus.py`, `_parse_upcoming_row`) reads the "upcoming" table of the council's video site and ingest stores each row in `meetings` with an `external_id` of the form `event-<n>`, `meeting_date`, `start_time`, and `agenda_url` and `source_url` both set to `https://bhamal.granicus.com/AgendaViewer.php?view_id=2&event_id=<n>`. When the meeting is recorded, ingest rewrites the row's `external_id` to the recording's number (`_try_upgrade_event_row` in `src/docket/services/ingest.py`), so an `event-` row is a meeting not yet recorded. A meeting is "upcoming" by `docket.services.meeting_time.is_upcoming` until three hours after its start. A cancelled meeting is an ordinary row whose title says so; `docket.services.query.is_cancelled_title` is the one owner of that test. A hidden meeting has `is_hidden = TRUE`.

The city calendar. Migrations 038 and 043 created `city_calendar_events` (`id`, `municipality_id`, `source_event_id`, `title`, `starts_at` and `ends_at` as `TIMESTAMPTZ`, `source_url`, `categories`, `event_status`, `fetched_at`), filled daily by the worker task `city_calendar` through `src/docket/services/city_calendar.py` from three readers of `www.birminghamal.gov`. `docs/specs/meeting-types.md`, "The city calendar", describes them. The table holds every event of the City Council department, which includes things that are not meetings: on 2026-11-16 production held "DISTRICT 4 200 HAMS GIVEAWAY ...", "COUNCIL PRO TEM LATONYA TATE HOLIDAY GIVEAWAY" and two more beside the council and committee meetings. `docket.services.meeting_types.classify_event(title)` returns a `Classification` (`meeting_type`, `session_kind`, `body_name`) for a title containing "CITY COUNCIL MEETING" or "COMMITTEE" and `None` for anything else, and `meeting_types._is_live(event_row)` is true when the stored status is NULL or `active` and the title does not say cancelled. `meetings.calendar_event_id` holds the calendar event the meeting-type resolver matched to a meeting row, when it matched one. No reader page shows `city_calendar_events` rows today; they are used only to name the body of a recording.

Agenda items. `agenda_items` rows (`id`, `meeting_id`, `title`, `description`, `processing_status`, and more) are inserted once per meeting by `_ingest_agenda_items` in `src/docket/services/ingest.py` with `ON CONFLICT DO NOTHING`; ingest never deletes or rewrites one, so an item id is stable. The item page is `/al/<slug>/items/<id>/` (`public.item_detail`), which answers 404 when the item's meeting is hidden.

Checked-in content with saved sources. `content/how-it-works/birmingham/` holds an explainer, and `content/how-it-works/birmingham/sources/` holds plain-text copies of the documents it quotes with a `README.md` table of file, what it is, public address, and read date. `src/docket/services/how_it_works.py` loads and validates it; `scripts/how_it_works_reading_sheet.py` prints a sheet a person reads against the sources, saved as `docs/runbooks/how-it-works-reading-birmingham.md`. This plan follows that shape for the neighborhood schedule; the difference is that the saved source is a PDF, the first binary under `content/`. The web and worker images are built with `COPY . .` (`Dockerfile`), so everything under `content/` is on both.

The existing hearings feed. `/al/<slug>/upcoming-hearings.rss` (`public.upcoming_hearings_rss`, `query.list_upcoming_hearings`, `src/docket/web/templates/rss/upcoming_hearings.xml.j2`) lists upcoming meetings whose title or item titles contain the word "hearing", for every city. It is linked from the city page's "Follow:" line in `src/docket/web/templates/partials/briefing/meetings.html`. This plan does not change it.

Routing. `public.py` has a catch-all `/al/<slug>/<badge_slug>/` (`category_landing`). A route with a fixed last segment, as `/al/<slug>/how-it-works/` already is, outranks it in Werkzeug's matching; `/al/<slug>/coming-up/` and `/al/<slug>/coming-up.ics` rely on the same thing, and M7 and M8 each assert a 200 to prove it. No badge slug and no route named `coming-up` exists in `src/`.

### What production's rows look like

The development database holds no Birmingham agenda items and no calendar events (observed 2026-11-16: `docket_db` has 0 of each and neither item 62830 nor 62881), so every number below was read from production, read-only, on 2026-11-16 by the plan's author through the Railway CLI from this worktree. The command form, which reached production and returned rows, is in Concrete Steps.

Seventy-eight Birmingham agenda items of meetings dated 2025-01-01 or later have a title matching the trigger (after whitespace is collapsed, case ignored): `(setting|to set|providing for) (a|the) public (show cause )?hearing`. All 78 are in meetings that are not hidden; 77 have `processing_status` `completed`, one `cross_stage_conflict`, none `withdrawn`. In 66 the date follows the trigger at once ("setting a public hearing November 17, 2026, to consider ..."). One more (item 730) gives it as "on the 7th day of April, 2026". Eleven give no date the stored title holds. Nine of the 66 were dated 2026-11-16 or later, which is the operator's figure; they are seven hearings: November 17, a street closure (item 62182), a right-of-way vacation (items 62830 and 62881), and 212 weed lots (items 62831 and 62882); November 24, a rezoning (63046); December 8, a zoning ordinance repeal (63108) and 136 weed lots (63109); December 15, 136 weed lots (63166). The operator's own scan of the same day counted 71 items; its query is not recorded, and M3 explains the difference between 71 and what the reader finds.

Titles come in two conditions. Meetings ingested before about May 2026, and a few after (all 87 items of meeting 2624, dated 2026-10-20), store each title cut at 255 or 256 characters, opening with the agenda's own item marker ("P", tabs, "ITEM 19.", a newline), and store no description. Later meetings store the whole sentence as the title with no marker. The cut is why a weed-lot resolution before May 2026 does not match (its "providing for a public hearing" lies past character 256; 269 "noxious" titles since 2025 have no "public hearing" in what is stored) and why eleven matches have no date. The reader works on what is stored and does not try to recover what was cut; M9 records that as a debt row.

Item 62881 belongs to meeting 2613, whose `external_id` is still `event-2713` though it is dated 2026-10-26: a row the video site listed and never recorded (GitHub issue #62; `D137` in `docs/DEBT.md` names this meeting). Its 51 items repeat the October 13 agenda. That is how one hearing came to be set by two items, and why the page says "On the agenda of" and no more.

On the meetings side, on 2026-11-16: meeting 3207 (`event-2718`, 2026-11-17, `start_time` 11:00, council, `calendar_event_id` 120) and calendar event 120 ("BIRMINGHAM CITY COUNCIL MEETING, November 17, 2026", starting 09:30 Chicago, status NULL) are the same meeting; calendar event 79 ("BUDGET AND FINANCE COMMITTEE MEETING, November 23, 2026", 15:30, `active`) has no meeting row; events 70, 71, 78 and 80 are giveaways. Of 37 stored calendar events, 14 have a NULL status and 23 `active`; none has another status and none says cancelled.

### The neighborhood schedule

The source is "CITY OF BIRMINGHAM COMMUNITY RESOURCE SERVICES DIVISION NEIGHBORHOOD ASSOCIATION MEETING SCHEDULE", "Revised February 3, 2026", at `https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/s3fs-public/2026-02/2026_NA_Meeting_Schedule_rev._2-3-2026.pdf`. The author fetched it on 2026-11-16 with `curl` from this machine (HTTP 200, `application/pdf`, 155,273 bytes, SHA-256 `f9987d63389a280b5333fb9675d090bcf76c3069ccce7f05ea1052fabda7333e`) into a scratch directory, not into the repository. It is three pages with a text layer. `pdfplumber` (already in `requirements.txt`) reads it two ways. `page.extract_text()` runs the columns together and interleaves a cell that wraps onto two lines with its neighbours ("Conference" on one line, the Industrial row on the next, "Call/In-Person" on a third). `page.extract_tables()` returns one table per page of four columns and 101 rows in all: two header rows and 99 associations, every name distinct. The four columns are the association, the meeting date and time, the meeting type, and the meeting information.

What the 99 rows hold, from the table reading: 94 rules are of the form "<First|Second|Third|Fourth> <weekday> of each month @ <h>:<mm> <a|p>.m."; the other five are "Fourth Tuesday of each month 6:00 p.m." (Dolomite, no "@"), "Fourth Monday @ 6:00 p.m." (East Birmingham), "Second Monday of each month @4 p.m." (Gate City), "First Monday of this month @ 6:30 pm" (Glen Iris), and "Meeting months: First Tuesday of each month on Feb, April, June, Aug, Oct & Dec. @ 6:00 p.m." (Overton). Every row has a time. The meeting type is spelled 21 ways ("In-Person", "In Person", "In-Persopn", "Conference Call", "Coference Call", "Teleconfernce", "Zoom", "Zoom/ In-Person", and so on); Bridlewood's type and information both read "No Meetings". The information cell holds a place, or dial-in or meeting-id details, or both separated by a slash; Gate City's ends "Conference Call TBD"; East Brownsville's reads "(Jan-Apr) Dial: ... / (May-Nov) Mary Dorsey Center ..."; the table reading returns Highland Park's information cell empty though the page prints "Visit highland-park.org for in-person meeting location / MI: 819 7094 5731". The table reading is therefore a good draft and not the transcription: the M4 session checks every row against the page by eye, and the operator reads the generated sheet before deploy.

### Terms

An entry is one thing on the page: a meeting, a hearing, or one dated neighborhood meeting. A reading is what the hearing reader returns for one title. The trigger is the phrase that makes a title a candidate. The subject is the text after the hearing's date. An occurrence is one date a schedule rule produces. The window is today through today plus 60 days, both in America/Chicago. A VEVENT is one event in the iCalendar text format (the `.ics` file a calendar program reads); a UID is the identifier a calendar program uses to tell that an event it fetched again is the same one.

### Debt rows this plan meets

`docs/DEBT.md` is the register of deliberate deferrals; a row's last column says what triggers it. This plan pays none. It is cut to avoid tripping these, and a session that finds itself about to edit one of the named files stops and records why first: `D69`, `D34` and `D65` (no worker task is added and `src/docket/worker/` is not edited); `D34` again (`src/docket/web/__init__.py` is not edited); `D60`, `D61`, `D62` (`src/docket/services/briefing.py` is not edited); `D119` (`src/docket/services/meeting_types.py` is not edited); `D122` (no test seeds a city carrying a calendar key: every test that needs a city uses Birmingham, which the migrations seed, with rows it prefixes and deletes, and the new migration test asserts about Birmingham's row only and says nothing about other cities). `D131` is tripped and re-deferred (Decision Log). `D117` is a dependency, not a trigger: the cause of issue #88 makes an upcoming Granicus row's `start_time` two hours late until pull request #181 merges. `D7` and `D138` are not touched.

Changing `src/docket/services/ingest.py` requires having read `docs/PRINCIPLES.md` (`AGENTS.md`, Working rules). `D102`, `D105` and `D106` name that file for its video-timestamp backfill, which this plan does not touch.

### Identifiers

A decision number in `docs/decisions/`, a debt id in `docs/DEBT.md`, and a migration number are each chosen by the session that writes the file: the lowest number above every one spent on `origin/main` and on any open pull request at that moment (`gh pr list --state open`, then the file lists of each). On 2026-11-16 the highest migration on `origin/main` was 046, the highest decision 0106, the highest debt id D153, and the one open pull request, #181, adds none of the three; those figures are a starting point to check, not numbers to use unchecked. This plan writes "the hearings migration" and never its number. A new migration is also added to the module list in `src/docket/migrations/runner.py` (the list that ends with `"docket.migrations.046_alignment_stretches"`), or the runner does not apply it.

## Plan of Work

### M1: the hearing reader

Create `src/docket/enrichment/hearings.py`, importing only the standard library. It defines `RULE_VERSION = 1`; `KINDS = ("zoning", "weed_lots", "vacation", "budget", "other")`; `KIND_LABELS`, mapping those to "Zoning", "Weed lots", "Street or right-of-way", "Budget", "Other"; the frozen dataclass `HearingReading` with `hearing_date: date | None`, `kind: str`, `subject: str`, `subject_key: str`, and `property_count: int | None`; `read_hearing(title: str | None) -> HearingReading | None`; and `same_hearing(key_a: str, key_b: str) -> bool`.

`read_hearing` applies these rules in order, and each is a contract a later milestone relies on.

The text is the title with every run of whitespace replaced by one space. The trigger is the first match, case ignored, of `\b(?:setting|to set|providing for) (?:a|the) public (?:show cause )?hearing\b`. No trigger, no reading: the function returns `None`.

A date is a month's full English name, a day of one or two digits, an optional comma, and a four-digit year (`November 17, 2026` or `July 15, 2025`), case ignored; a date that is not a real day is no date. The hearing's date is found by the first of these that yields one. First, the date that follows the trigger at once, allowing a comma, spaces, and the word "on" between. Second, the first "on the <day><st|nd|rd|th> day of <Month>, <year>" after the trigger. Third, the first date that follows the word "on" inside a clause that begins "to be held" after the trigger and contains no full stop or semicolon before the date. Then one correction: when the text anywhere holds "CHANGE HEARING DATE FROM <date> TO <date>" (case ignored) and the date found equals the first of the two, the hearing's date is the second. When none yields a date, `hearing_date` is `None` and the reading is still returned, so a dry run can list it.

The kind is the first that fits, tested on the whole text, case ignored: `weed_lots` when it contains "noxious or dangerous weeds"; `zoning` when it matches `zoning|zone district|rezon`; `vacation` when it matches `vacation of|closure of|right[- ]of[- ]way`; `budget` when it contains "budget"; otherwise `other`.

The property count is the integer in the first `(<digits>) properties`, or `None`.

The subject is the text after the date when the date followed the trigger at once (leading commas and spaces removed), and otherwise the text after the trigger. The subject key of a `weed_lots` reading with a count is `weeds:<count>`. Any other key is the subject with every `[...]` group removed, cut at the first "(Submitted by" or "(Recommended by" (case ignored), lower-cased, and reduced to the characters a to z and 0 to 9. `same_hearing` is true when the keys are equal, or when one begins with the other and the shorter is at least 40 characters long. (Dates and kinds are compared by the caller; `same_hearing` compares keys alone.)

Create the fixture `tests/fixtures/hearings/birmingham_titles.json`, a JSON list of the 25 objects in Artifacts and Notes ("The fixture titles"), copied exactly: each has `id` (the production item id), `len` (the stored title's full length), and `title` (the stored title, or its first 420 characters where `len` is greater than 420). Create `tests/unit/test_hearing_reader.py`, which loads the fixture and asserts, for each id, the reading in the table of expected readings in Artifacts and Notes, and the four pair cases stated there (same and different hearings). Add tests for the rules the fixture cannot reach: the third date form on a constructed sentence ("... setting a public hearing to consider a moratorium to be held at the regular meeting of the Council in the Council Chambers on March 3, 2026" reads 2026-03-03), an impossible date ("February 30, 2026" reads no date), `read_hearing(None)` and `read_hearing("")` returning `None`, and a test that reads the module's source and fails if it contains `import docket` or `from docket` (the layer rule, since no mechanical boundary check exists: `boundary-lint` is only `specced` in `docs/capabilities/index.md`).

Result: a pure function later milestones call. Proof: the acceptance in Validation.

### M2: storage

Write the hearings migration under `src/docket/migrations/` (number by the rule in Identifiers; file name `<number>_public_hearings.py`, in the shape of `043_calendar_sources.py`: a module docstring, `SQL_UP`, `SQL_DOWN`) and register it in `runner.py`. Up creates two tables and sets Birmingham's flag:

    CREATE TABLE IF NOT EXISTS public_hearings (
        id              SERIAL PRIMARY KEY,
        municipality_id INTEGER NOT NULL REFERENCES municipalities(id) ON DELETE CASCADE,
        hearing_date    DATE NOT NULL,
        kind            TEXT NOT NULL CHECK (kind IN ('zoning', 'weed_lots', 'vacation', 'budget', 'other')),
        subject         TEXT NOT NULL,
        subject_key     TEXT NOT NULL,
        property_count  INTEGER NULL,
        rule_version    INTEGER NOT NULL,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (municipality_id, hearing_date, kind, subject_key)
    );
    CREATE INDEX IF NOT EXISTS idx_public_hearings_city_date ON public_hearings (municipality_id, hearing_date);
    CREATE TABLE IF NOT EXISTS public_hearing_items (
        agenda_item_id INTEGER PRIMARY KEY REFERENCES agenda_items(id) ON DELETE CASCADE,
        hearing_id     INTEGER NOT NULL REFERENCES public_hearings(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_public_hearing_items_hearing ON public_hearing_items (hearing_id);
    UPDATE municipalities SET metadata = metadata || '{"coming_up": true}'::jsonb WHERE slug = 'birmingham';

The link table's primary key is the item, because one title yields one reading, so an item belongs to at most one hearing and a second run moves it rather than doubling it. Down removes the key (`metadata - 'coming_up'`) and drops both tables. The kind list in the CHECK is frozen text, as migration 038's vocabularies are; its owner is `KINDS` in the reader.

Create `src/docket/services/hearings.py`. It owns every statement on the two tables.

`find_readings(municipality_id, since, until=None) -> list[dict]` runs one SELECT of `agenda_items` joined to `meetings` for the city where `meetings.meeting_date >= since` (and `<= until` when given) and `agenda_items.title ~* 'public\s+(show\s+cause\s+)?hearing'`, ordered by item id, and returns one dict per item whose `read_hearing` is not `None`: `item_id`, `meeting_id`, `meeting_date`, `reading`. It reads neither new table, so it runs against a database that does not have them.

`group_readings(rows) -> list[dict]` is pure: taking the dated rows in item-id order, it puts each into the first group with the same date and kind whose key `same_hearing` accepts, or starts a group; a group keeps the longest key seen and the subject that came with it, the first property count seen, and its item ids.

`refresh_hearings(municipality_id, since, until=None) -> HearingReport` calls the two and then, in one transaction: loads the city's stored hearings whose date is among the groups' dates; for each group, finds the stored hearing of the same date and kind whose key `same_hearing` accepts, and inserts one if none (updating `subject`, `subject_key` and `updated_at` of a stored one when the group's key is longer); writes every link in one statement (`INSERT INTO public_hearing_items (agenda_item_id, hearing_id) VALUES ... ON CONFLICT (agenda_item_id) DO UPDATE SET hearing_id = EXCLUDED.hearing_id`, through `psycopg2.extras.execute_values`); deletes, in one statement, the links of items the SELECT returned that now have no dated reading; and deletes, in one statement scoped to the city, hearings left with no link. `HearingReport` is a frozen dataclass of `matched`, `dated`, `undated`, `hearings`, `created`, `linked`. Nothing here loops a write over existing rows: the inserts are of new rows in a new table, a few a week after the first run and about sixty in the backfill, which is the scale `services/city_calendar._upsert` already accepts, and both deletes are one statement each (decision `0026`).

`refresh_recent(municipality_id) -> HearingReport | None` reads the city's metadata, returns `None` unless it carries `"coming_up": true`, and otherwise calls `refresh_hearings` with `since` 120 days before today (`RECENT_DAYS = 120`).

`list_upcoming(municipality_id, start, end) -> list[dict]` returns the hearings dated from `start` to `end` that have at least one visible link, each with `id`, `hearing_date`, `kind`, `subject`, `property_count`, and `items`: a list, oldest meeting first, of `item_id`, `meeting_id`, `meeting_date`, `agenda_url`. A link is visible when its meeting is not hidden, its meeting's title does not say cancelled (`query.CANCELLED_PREDICATE_MT`), and the item's `processing_status` is not `withdrawn`. A withdrawn resolution set no hearing, an agenda for a cancelled meeting was not acted on, and a hidden meeting's item page answers 404; a hearing with no visible link is not returned.

Tests. `tests/integration/test_<number>_migration.py`, in the pattern of `tests/integration/test_043_migration.py`: up creates both tables and gives Birmingham's metadata `coming_up` true; down removes the key and both tables; nothing is asserted about any other city. `tests/services/test_hearings_store.py`: seeds, under Birmingham's id, meetings and items whose titles come from the M1 fixture, every seeded meeting title prefixed `HEARINGS_TEST_`, and deletes them (the cascade removes links; the test also deletes the city's `public_hearings` rows it made) before and after. Its cases: fixture titles 62830 twice (two items, two meetings) make one hearing with two links; 62182, 62830 and 62882 on one date make three hearings; a second `refresh_hearings` changes no count; 3339 then 3297 make one hearing whose stored key is 3339's longer one; an item whose title is edited to lose its trigger loses its link on the next run and its hearing is deleted; an undated reading (3238) stores nothing; `list_upcoming` leaves out a hearing whose only item is `withdrawn`, whose only meeting is hidden, or whose only meeting's title says "CANCELLED", and returns a hearing with one visible and one hidden link with the visible one alone; `refresh_recent` returns `None` for a seeded city without the flag (`mobile`).

### M3: the ingest step, the script, and the dry run on real rows

In `ingest_municipality` (`src/docket/services/ingest.py`), after the block commented "Stage 3b" and before "Stage 4", add a stage "3c" in the same shape: inside `try`, call `hearings.refresh_recent(municipality_id)` and, when it returns a report, log its counts; on any exception append `f"Hearings: {e}"` to `errors` and log it. Import `hearings` beside `meeting_types`. Add `tests/integration/test_ingest_hearings.py`. No existing test runs `ingest_municipality` from end to end (the ingest tests call `_upsert_meetings` and its neighbours directly), so this one supplies its own adapter: it monkeypatches `docket.services.ingest.get_adapter` to return an object whose `list_meetings(since=None)` returns one `RawMeeting` (the dataclass in `src/docket/models/protocol.py`; an `external_id` of the form `event-99xxxx`, a title prefixed `HEARINGS_TEST_`, a date five days back, no minutes link) and whose `fetch_agenda_items(meeting)` returns one raw item whose title is fixture title 63108. It runs `ingest_municipality("birmingham")` and asserts a `public_hearings` row dated 2026-12-08 of kind `zoning` linked to the stored item; then, in a second test, that an exception raised by a monkeypatched `hearings.refresh_recent` appears in `IngestResult.errors` as a string beginning "Hearings:" while the meeting and its item are stored. It deletes its meeting (by the title prefix) and the hearings it made, before and after.

Create `scripts/backfill_hearings.py`, in the shape of `scripts/hide_non_meetings.py`: `--city <slug>` (required), `--since YYYY-MM-DD` (required: the script refuses to run without a bound), `--until YYYY-MM-DD` (optional), `--dry-run`. With `--dry-run` it calls `find_readings` and `group_readings` only, so it issues one SELECT and reads neither new table, and prints one line per matched item, in item-id order,

    <item id>  <meeting date>  <hearing date or "no date">  <kind>  <property count or "-">  <first 70 characters of the collapsed title>

then one line per hearing (`hearing <date> <kind> items=<ids>`), then `matched=<n> dated=<n> undated=<n> hearings=<n>`. Without `--dry-run` it prints the same and then calls `refresh_hearings` and prints `created=<n> linked=<n>`. Its docstring says the order (dry run first), that against production `DATABASE_URL` is set to `DATABASE_PUBLIC_URL`, and that a second run creates nothing. `tests/unit/test_backfill_hearings_script.py` (pattern: `tests/unit/test_backfill_committee_documents_script.py`) asserts the refusal without `--since` and that `--dry-run` calls neither `refresh_hearings` nor any write.

Then the session runs the dry run against production, read-only, with the command in Concrete Steps, saves the output outside the repository, and records in this plan's Artifacts and Notes: the totals line; the hearing lines dated on or after the day of the run; the line for items 62830 and 62881; and a paragraph comparing the run restricted by `--until 2026-11-16` with the two earlier counts (the author's 78 matched, 67 dated, 11 undated; the operator's 71 items and 9 dated on or after 2026-11-16), naming every item on which the reader and the author's SQL differ and saying why. This output is the comparison on real rows that `docs/PRINCIPLES.md` "Evidence or silence" requires of a pipeline change before it ships; there is no older pipeline to compare with, so the two earlier counts stand in for "old". If the harness refuses the Railway command, the session does not tick M3: it records the refusal in Surprises & Discoveries, commits, and stops, and the operator runs the command in the WSL checkout and pastes the output for the next session.

### M4: the schedule, saved and transcribed

Add to `src/docket/config.py`, beside `HOW_IT_WORKS_ROOT`: `COMING_UP_ROOT = os.environ.get("COMING_UP_ROOT", "content/coming-up")`.

Create `content/coming-up/birmingham/sources/2026_NA_Meeting_Schedule_rev._2-3-2026.pdf` by fetching the address in Context with `curl` (one request; the session checks the SHA-256 against the one in Context and, if the city has replaced the file, records the new digest and the date as a Surprises entry and carries on with the file it fetched). Create `content/coming-up/birmingham/sources/README.md` in the shape of `content/how-it-works/birmingham/sources/README.md`: one table row with the file, what it is (title, the revision date printed on it, three pages), the public address, the read date, and the SHA-256; and a paragraph saying the PDF is kept so a reviewer can check every transcribed row, that the page links the public address, and how a later revision is saved (M9's spec owns the procedure; the README points there).

Create `content/coming-up/birmingham/neighborhood-schedule.yaml`:

    source:
      title: "City of Birmingham Community Resource Services Division Neighborhood Association Meeting Schedule"
      revised: 2026-02-03
      url: "https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/s3fs-public/2026-02/2026_NA_Meeting_Schedule_rev._2-3-2026.pdf"
      file: "sources/2026_NA_Meeting_Schedule_rev._2-3-2026.pdf"
      sha256: "<the digest of the saved file>"
      read: <the date the file was fetched>
      year: 2026
    checked:
      - by: "<who>"
        on: <date>
        how: "<one sentence>"
    associations:
      - name: "Acipco-Finley"
        rule_text: "First Wednesday of each month @ 5:30 p.m."
        ordinal: first
        weekday: wednesday
        time: "17:30"
        type_text: "In-Person"
        modes: [in_person]
        place: "Acipco Finley Community Room, 453 38th Ave W, Birmingham, AL 35207"
        remote: null

`name`, `rule_text` and `type_text` are the PDF's cells, character for character, misspellings included ("In-Persopn" stays). `ordinal` is `first`, `second`, `third` or `fourth`, and `weekday` a lower-case English weekday, or both are `null` for a row given no dates; `months` is an optional list of month numbers (absent means all twelve; Overton's is `[2, 4, 6, 8, 10, 12]`). `time` is 24-hour `"HH:MM"` or `null`. `modes` is a list drawn from `in_person`, `phone` (any spelling of conference call or teleconference), and `video` (Zoom), in the order the type cell names them, and is empty for "No Meetings". `place` is the part of the information cell that names where to go in person and `remote` the part that gives dial-in or meeting-id details, each copied as printed, each `null` when the cell has no such part or says "TBD" (Gate City's `remote` is `null`); a cell whose parts cannot be told apart goes whole into the one field it mostly is. `undated_reason` is required exactly when `ordinal` is `null`: for Bridlewood `"The schedule says: No Meetings"`, for Glen Iris `"The schedule says: First Monday of this month @ 6:30 pm"`. The first `checked` entry is the session's own ("Claude, plan birmingham-coming-up M4", the date, "each row compared with the saved PDF's page"); the operator's reading adds a second after the merge.

The session drafts the 99 rows from `pdfplumber`'s `extract_tables()` with a script kept in its scratch directory, then renders each PDF page to an image or reads the page text and compares every row, correcting the draft; Highland Park's information cell, empty in the table reading, is taken from the page.

Create `src/docket/services/neighborhood_schedule.py`, which reads files only and imports nothing from `docket.web`. It defines `ScheduleError(ValueError)`; frozen dataclasses `Association` (the fields above) and `Schedule` (`title`, `revised`, `url`, `file`, `sha256`, `read`, `year`, `checked`, `associations`); `load_schedule(city_dir: Path) -> Schedule`; and `get_schedule(slug: str) -> Schedule | None`, which returns `None` when `COMING_UP_ROOT/<slug>/neighborhood-schedule.yaml` does not exist and otherwise the loaded schedule, cached per slug for the life of the process. `load_schedule` raises `ScheduleError`, naming the file and the association, for: a missing or unknown key; an `ordinal`, `weekday`, `modes` or `months` value outside its vocabulary; one of `ordinal` and `weekday` null and the other not; a `time` that is not `HH:MM`; a duplicate `name`; an empty `rule_text` or `type_text`; `undated_reason` present with an ordinal or absent without one; an empty `checked` list; a `source.file` that does not exist; and a saved file whose SHA-256 is not `source.sha256`.

Tests, `tests/unit/test_neighborhood_schedule.py`: the checked-in file loads and holds 99 associations; each refusal above, on a copy of a three-association file written to `tmp_path`; and the cross-check against the PDF, which opens the saved PDF with `pdfplumber`, collects the table rows of all pages, and asserts, comparing lower-cased letters and digits only, that every association's `name`, `rule_text` and `type_text` equal the first three cells of exactly one table row, and that its `place` and `remote`, when not null, are each contained in that row's fourth cell. Rows where the table reading itself is wrong are listed in the test in a dict of name to the reason (Highland Park's empty cell is the one known), and for those the comparison is against the page's `extract_text()`; the session records each exception it adds in the Decision Log.

### M5: dates and the reading sheet

Add to `src/docket/services/neighborhood_schedule.py`: `occurrences(schedule, start: date, end: date) -> list[Occurrence]`, where `Occurrence` is a frozen dataclass of `association` and `on: date`. For each association with an ordinal, for each month of `schedule.year` in its `months` (all twelve when absent), the date is the ordinal-th `weekday` of that month; it is returned when it lies in `start` to `end` inclusive. Nothing is produced for a year other than `schedule.year`, so after 2026-12-31 the list is empty. The result is ordered by date, then time with `null` last, then name. Add `undated(schedule) -> list[Association]`.

Tests, in the same file as M4's: the dates in Artifacts and Notes ("Dates worked by hand"), each asserted; the count for the whole of 2026 is 1,158 (96 associations with a rule for every month, 96 × 12 = 1,152, plus Overton's 6; Bridlewood and Glen Iris give none); `occurrences` for 2027-01-01 to 2027-12-31 is empty; `undated` returns Bridlewood and Glen Iris. If the M4 transcription found a row the author's table reading misread, so that the count differs, the session records the row and the corrected arithmetic in Surprises & Discoveries and asserts the corrected figure.

Create `scripts/coming_up_reading_sheet.py` in the shape of `scripts/how_it_works_reading_sheet.py`: it prints, as Markdown, the source's title, address, revision date and digest, the commit that last changed `content/coming-up/<city>/`, and one tick-box line per association with its name, `rule_text`, what the loader made of it ("first Wednesday, every month, 5:30 p.m." or the undated reason), `type_text`, `modes`, `place`, `remote`, and the association's next three dates of the schedule year. Run it and save the output as `docs/runbooks/coming-up-reading-birmingham.md`, and add that file to the runbook index at the end of `docs/specs/operations.md` (the "Runbooks" section) in one line.

### M6: the entries

Create `src/docket/services/coming_up.py`. It reads through `services/hearings.py` and `services/neighborhood_schedule.py` and runs two SELECTs of its own, on `meetings` and on `city_calendar_events`. It defines `WINDOW_DAYS = 60`; `is_coming_up_city(municipality: dict | None) -> bool` (the metadata carries `"coming_up": true`; written like `briefing.is_briefing_city`, which accepts the metadata as a dict or a JSON string); the frozen dataclass `Entry`; and `list_entries(municipality: dict, *, today: date | None = None) -> list[Entry]`, where `today` defaults to `_today()`, a module-level function returning the current date in America/Chicago. Every bound in the function's SQL and in its calls is computed from that one `today` and passed as a parameter (no `NOW()` or `CURRENT_DATE` in its statements), so a test that fixes the day fixes the whole result.

`Entry` has: `kind` (`meeting`, `hearing`, `neighborhood`); `uid` (text); `on` (date); `starts_at` and `ends_at` (timezone-aware datetimes or `None`); `title`; `detail` (a tuple of short strings the page prints as lines); `links` (a tuple of `(label, url)` pairs, the first being the city's own document where one exists); `source_url` (that first city document, or `None`); and `place` (text or `None`).

Meetings. Granicus rows: `meetings` of the city with `external_id LIKE 'event-%'`, `is_hidden = FALSE`, and `meeting_date` in the window. Calendar events: `city_calendar_events` of the city whose `starts_at`, converted to America/Chicago, falls on a date in the window, kept only when `meeting_types.classify_event(title)` is not `None` (which drops the giveaways). Pairing: first, a row and an event are one meeting when the row's `calendar_event_id` is the event's id; then, among what is left, a row whose `meeting_type` is `council` and an event that classifies as `council` on the same Chicago date are one meeting when each is the only such unpaired one that day. Everything else stands alone. Then an entry is dropped when its row's title says cancelled (`query.is_cancelled_title`) or its event is not live (`meeting_types._is_live`), on either side of a pair. The title is `adapters._helpers.label_for` over the row's `meeting_type`, `session_kind`, `body_name` and title (as the `meeting_label` template global does), or, for an event alone, over the event's classification. The time is the event's `starts_at` and `ends_at` when there is an event; otherwise the row's `meeting_date` and `start_time` in America/Chicago, or none when `start_time` is NULL. Links: "City calendar" to the event's `source_url` when there is an event; "Agenda" to the row's `agenda_url` when there is a row with one; "Meeting on docket.pub" to the meeting's page path when there is a row. The UID is `calendar-<event id>@docket.pub` when there is an event, else `meeting-<meeting id>@docket.pub`.

Worked on production's rows of 2026-11-16 with `today` 2026-11-16: meeting 3207 and event 120 pair by the first rule and give one entry, titled with what `label_for` returns for a regular council meeting (the session reads the function and asserts that text), on 2026-11-17 at 9:30 a.m., UID `calendar-120@docket.pub`, with all three links; event 79 gives one entry for the Budget and Finance committee on 2026-11-23 at 3:30 p.m. with the calendar link alone; events 78 and 80 give nothing; events 66, 67, 70 and 71 are before the window.

Hearings: `hearings.list_upcoming(municipality_id, today, today + 60 days)`. The title is `KIND_LABELS[kind]` followed by " hearing" ("Zoning hearing", "Weed lots hearing", "Street or right-of-way hearing", "Budget hearing"), except that kind `other` is titled "Public hearing". The detail is, for `weed_lots` with a count, "<count> properties" (and for one without a count nothing: no number is invented); for any other kind, the subject cut to 240 characters at a word boundary with an ellipsis when cut. No time. Links: for each item, "On the agenda of <Month D, YYYY>" to the item's page path, and for the newest item whose meeting has an `agenda_url`, "City agenda" to it, placed first. UID `hearing-<id>@docket.pub`.

Neighborhood meetings: `neighborhood_schedule.get_schedule(slug)`, and when it is not `None`, `occurrences(schedule, today, today + 60 days)`. The title is "<name> Neighborhood Association". The time is the date and `time` in America/Chicago, or none. The detail holds `type_text` as printed; then `remote` when not null, or, when `modes` contains `phone` or `video` and `remote` is null, "Call-in details are not in the schedule"; and when `time` is null, "The schedule gives no time". `place` is the place or `None`. One link, "City schedule (PDF)", to `schedule.url`. UID `na-<name lower-cased, runs of other characters made one hyphen>-<YYYYMMDD>@docket.pub`.

The result is ordered by date, then timed entries by start before untimed ones, then kind in the order meeting, hearing, neighborhood, then title.

Also `undated_associations(slug) -> list[tuple[str, str]]` (name and `undated_reason`), and `schedule_source(slug)` returning the schedule's title, address, revision date and year for the page's footer, or `None`.

Tests, `tests/services/test_coming_up.py`, seeding under Birmingham's id with meeting titles prefixed `COMINGUP_TEST_` and calendar `source_event_id` values prefixed the same, cleaned before and after, with `today` passed in: the production case above reproduced with seeded rows (one merged entry with the calendar's time and three links; a committee event alone; a giveaway dropped); a council row and a council event on one day with no `calendar_event_id` merge by the second rule; two council events and one council row on one day are three entries; a pair whose event has status `cancelled` gives no entry, and so does a pair whose row's title says "CANCELLED"; a hidden row is absent and its calendar event stands alone; a row with NULL `start_time` and no event has `starts_at` `None`; a row dated 61 days ahead is absent; a hearing dated today is present and one dated yesterday absent; a neighborhood occurrence carries the PDF link; Gate City's entry carries "Call-in details are not in the schedule"; with `today` 2027-01-05 there is no neighborhood entry; a city without the flag gives `is_coming_up_city` false. The file's cleanup also deletes the `public_hearings` rows it seeded.

### M7: the page

In `src/docket/web/public.py`: import `coming_up`; register `@bp.app_template_global("has_coming_up")` returning `coming_up.is_coming_up_city(municipality)`; add `@bp.route("/al/<slug>/coming-up/")`, `coming_up_page(slug)`: 404 when the city does not exist or is not a coming-up city; otherwise render `coming_up.html` with the municipality, the entries grouped by date, the undated associations, the schedule source, and the feed's address. The route executes no SQL.

Create `src/docket/web/templates/coming_up.html`, extending `base.html` as `how_it_works.html` does, with its own stylesheet `src/docket/web/static/css/coming_up.css` linked the way `how_it_works.html` links `css/how_it_works.css` (`layout.css` and `mobile.css` are not edited). The page has: an `<h1>` "What's coming up in Birmingham" (the city's name from the row); one sentence saying the list covers the next 60 days and every entry links to the city document it came from; a link "Subscribe to this calendar" to the feed's address (the route M8 adds; until then the template builds the path from the slug, `/al/<slug>/coming-up.ics`, as plain text in an `href`, which M8 replaces with `url_for`); then one `<section>` per date with the date as its heading ("Tuesday, November 17, 2026"), and inside it one `<article data-entry-uid="<uid>" data-entry-kind="<kind>">` per entry holding the kind as a short label, the time when there is one (the page prints nothing in its place when there is none, except the detail line M6 supplies for a neighborhood meeting), the title, the detail lines, the place, and the links. The neighborhood entries of a date sit together inside one `<details>` whose `<summary>` is "<n> neighborhood association meeting(s)", after that date's meetings and hearings, so a date with twelve of them stays short; they are still in the page's HTML, each with its `data-entry-uid`. When there are no entries at all the page says "Nothing is listed for the next 60 days." Under the list, a section "Where these dates come from" says, in sentences: meetings come from the council's video site and the city's calendar, and a meeting the city has cancelled is left out; a hearing's date is read by docket.pub from the text of a resolution on a council agenda, without a language model, an agenda is posted before its meeting so a listed resolution may not yet have been adopted, and a hearing the council later moved may still show on its first date; neighborhood dates are computed by docket.pub from the monthly rule in the city's schedule (title, revision date, linked), which covers <year> only, and a meeting moved for a holiday is not reflected. Then, when there are undated associations, a line for each: its name and its reason.

In `src/docket/web/templates/partials/briefing/meetings.html`, inside `{% if has_coming_up(municipality) %}`, add a link "What's coming up →" to the page beside "All meetings →". The "Follow:" line is not changed in this milestone.

In `src/docket/web/crawlers.py`, `sitemap_city_meetings` adds `/al/<slug>/coming-up/` to its first entries when the city is a coming-up city, asked through a new `sitemap_svc.has_coming_up(slug)` in `src/docket/services/sitemap.py`, which loads the municipality row and calls `coming_up.is_coming_up_city`.

Tests, `tests/web/test_coming_up_page.py`, with the `client` fixture of `tests/web/conftest.py` and rows seeded as M6's tests seed them (the seeding helper moves to `tests/support/coming_up_seed.py` so M6's, M7's and M8's tests share it): `GET /al/birmingham/coming-up/` is 200 and `GET /al/mobile/coming-up/` and `GET /al/nowhere/coming-up/` are 404; the number of `data-entry-uid="` in the body equals `len(coming_up.list_entries(...))` for the same day; a seeded hearing's article contains its item's page address and "On the agenda of"; a weed-lot hearing's article contains "212 properties" and not its subject text; a neighborhood article contains the PDF address; an entry with no time has no `<time` element; the undated line names Bridlewood with "No Meetings"; the Birmingham city page (`GET /al/birmingham/`, after clearing `public._overview_cache`) contains the page's address and `/al/mobile/` does not; `/sitemaps/birmingham/meetings.xml` (after `crawlers.clear_cache()`) lists the page and `/sitemaps/mobile/meetings.xml` does not. The route accepts no date parameter. Every test in this file, and in M8's feed test, monkeypatches `coming_up._today` to return 2026-11-16 and seeds its meetings, events and hearings on fixed dates after it, because the checked-in schedule yields no neighborhood meeting after 2026-12-31 and these tests must still pass when run in 2027.

What a factory session can observe here is the markup and the status codes. How the page looks at phone and desktop width is the operator's look, in Validation.

### M8: the feed

Create `src/docket/web/ics.py` with `render_calendar(entries, *, name: str, now: datetime, absolute) -> str`, where `absolute` turns a site path into an absolute address. The text opens `BEGIN:VCALENDAR`, `VERSION:2.0`, `PRODID:-//docket.pub//Coming up//EN`, `CALSCALE:GREGORIAN`, `METHOD:PUBLISH`, `X-WR-CALNAME:<name>`, holds one `BEGIN:VEVENT` to `END:VEVENT` block per entry, and closes `END:VCALENDAR`. Each event has `UID` (the entry's); `DTSTAMP` (`now` in UTC, `YYYYMMDDTHHMMSSZ`); `DTSTART`, as `YYYYMMDDTHHMMSSZ` in UTC when the entry has a start, and as `DTSTART;VALUE=DATE:YYYYMMDD` when it has none; `DTEND` in UTC when the entry has an end, `DTEND;VALUE=DATE:` of the next day for an entry without a start, and none for a timed entry without an end; `SUMMARY` (the title); `DESCRIPTION` (the detail lines, then each link as "label: absolute address", then "From docket.pub: " and the page's address, joined by newlines); `LOCATION` when the entry has a place; `URL` (the entry's `source_url`, or the first link made absolute when there is none); and `CATEGORIES` ("Meeting", "Public hearing", or "Neighborhood association"). Text values escape backslash, semicolon and comma with a backslash and a newline as `\n`. Every line ends with CR LF, and a line longer than 75 bytes of UTF-8 is folded: broken before the 76th byte, never inside a multi-byte character, the continuation starting with one space.

In `public.py` add `@bp.route("/al/<slug>/coming-up.ics")`, `coming_up_ics(slug)`, with the page's 404 rule, returning the text with `mimetype="text/calendar"` (Flask adds `charset=utf-8`), `Cache-Control: public, max-age=3600`, and `Content-Disposition: inline; filename="<slug>-coming-up.ics"`. The page's subscribe link becomes `url_for("public.coming_up_ics", slug=...)`, and the city page's "Follow:" line gains, inside the `has_coming_up` test, "calendar (.ics)" linking to it.

Tests. `tests/unit/test_ics.py`: an entry with a start and end; one with a start alone; one with neither, whose `DTEND` is the next day; a title containing a comma, a semicolon, a backslash and a newline, escaped; a 200-character summary with a multi-byte character at the fold, which unfolds to the original; every line ending CR LF; no line over 75 bytes. `tests/web/test_coming_up_feed.py`: `GET /al/birmingham/coming-up.ics` is 200 with a `Content-Type` beginning `text/calendar` and `GET /al/mobile/coming-up.ics` is 404; the test unfolds the body, counts `BEGIN:VEVENT`, and asserts the count equals the number of `data-entry-uid="` in the page fetched in the same test from the same seeded rows, and that the set of `UID` values equals the set of `data-entry-uid` values; the seeded hearing's event has `DTSTART;VALUE=DATE:` and a `URL`; the merged meeting's event has `DTSTART` equal to the calendar event's start in UTC.

### M9: the record

Create `docs/specs/coming-up.md`, in the present tense, owning: the two addresses and the gate; the window; each kind's sources, inclusion rules and what an entry shows; the merge rule and the cancelled rule; the hearing reader's rules (trigger, the three date forms and the correction, the kinds, the subject key, `same_hearing`), what it does not read (a date cut from a stored title, a hearing with no dated resolution, a hearing moved by a later resolution without the bracketed note), and where they are stored; the schedule file's format, the loader's refusals, the PDF cross-check, how a later revision or a 2027 schedule is saved (fetch the PDF into `sources/`, update the README row, edit the YAML and its `source` block, add a `checked` entry, regenerate the reading sheet, run `./tools/verify`) and that after the schedule's year the neighborhood section is empty until that is done; the feed's properties and UIDs; and how to check each. Add its row to the index in `docs/specs/index.md`.

Edit the specs whose behaviour changed, each where it already owns the fact: `docs/specs/city-page.md`, the "Recent meetings" paragraph (the link to the page and the feed link on the "Follow:" line, both on a flagged city only, with the gate's owner named as the new spec); `docs/specs/crawlers.md`, the sitemap paragraph (the per-city meetings file lists the coming-up page for a city that has one); `docs/specs/meeting-types.md`, "The city calendar" (one sentence: the table's rows are also read by the coming-up page, which keeps only titles `classify_event` reads, and the new spec owns how); `docs/specs/operations.md`, "Railway specifics" (the hearings paragraph: ingest's step keeps them current with no task of its own, and the backfill is `scripts/backfill_hearings.py --city birmingham --since 2025-01-01`, dry run first, from a laptop with `DATABASE_URL` set to `DATABASE_PUBLIC_URL`).

Add to `ARCHITECTURE.md`: in Enrichment's "Owns", the hearing reader; in Services' "Owns", the hearings store, the neighborhood schedule loader, and the coming-up entries, each with its spec. Add one map line to `AGENTS.md` for `content/coming-up/` pointing at the new spec, keeping the file within its length rule. Add a row to the surfaces table of `docs/birmingham/06-reader-surfaces.md` for the page and the feed, linking the spec rather than restating it, and a line in `docs/birmingham/01-sources.md` for the schedule PDF as a source.

Graduate the durable decisions to `docs/decisions/`, numbered by the rule in Identifiers, in the format of `docs/decisions/DECISION_FORMAT.md`: how one hearing is told from another and why not by case number; why a hearing with no readable date is not shown; the merge and cancelled rules for meetings and whose time is printed; that neighborhood dates are computed from the printed rule alone with the two undated associations named; and that extraction is a step of ingest.

Add debt rows to `docs/DEBT.md`, ids by the same rule: the operator's steps after the merge, in the order Validation gives them, with "the pull request merges" as the trigger; the two notions of an upcoming hearing (the RSS feed's title test and the new table), trigger "the next change to either feed"; hearings the reader cannot date or follow (dates cut from 256-character titles, weed-lot resolutions before May 2026, a hearing moved by a later resolution, a hearing set on an agenda whose meeting row is a leftover `event-` row), trigger "a reader or the operator reports a missing, stale, or doubled hearing"; `meeting_types._is_live` called from a second service under a private name, trigger `D119`'s; calendar events that are meetings and whose titles `classify_event` does not read (a work session), trigger "such an event is seen on the city's calendar"; the schedule's year ending 2026-12-31 with no 2027 file, trigger "the city publishes a 2027 schedule, or 2027-01-01"; the schedule loaded on first use rather than at start, trigger `D34`'s payment for `web/__init__.py`. Append to the `D131` row that this plan re-deferred it and why (Decision Log). Do not move this plan to `plans/completed/` and do not write the closing retrospective: the retro stage does both.

## Concrete Steps

Every command is run from the worktree root, `/home/thinkdarrell/docket-pub/.claude/worktrees/birmingham-coming-up`, with its own `venv/`.

Each session begins and ends with the full check:

    ./tools/verify

As observed by the author on 2026-11-16 on the branch as cut from `origin/main` (commit 608e912), it ended:

    verify: test-db ... ok (0s) postgresql://docket:docket_dev@localhost:5432/docket_test_1126d0ec
    verify: unit+web+services ... ok (125s)
    verify: integration ... ok (113s)
    verify: judge-fixtures ... ok (0s)
    verify: workflows ... ok (0s)
    verify: transcriber ... ok (11s)
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 249s.

and the fast tiers' own summary line read `2888 passed, 5 skipped, 4 xfailed, 2 warnings in 122.20s`. That run shared the machine with the author's other commands, so 249 seconds is not the usual time. The plan file did not exist yet, so the `plans` check had no active plan to read.

To run one test file by hand (bare `pytest` is refused by `tests/conftest.py` in this worktree, whose `.env` names `docket_db`):

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_hearing_reader.py -q -p no:cacheprovider
    tools/test-db --drop

This form is the one `docs/specs/operations.md` gives; the author ran `./tools/verify`, which uses the same pieces, and did not run this line itself, since the file it names does not exist yet.

The production dry run of M3, read-only. The first two lines are the form the author ran on 2026-11-16 from this worktree; it reached production and returned rows (`railway status` printed the project, and the `psql` statements returned the counts in Context). `PGOPTIONS` makes every transaction of the session read-only on the server's side, so a mistake in the script cannot write:

    export PGURL="$(railway variables --service docket-web --kv 2>/dev/null | grep '^DATABASE_PUBLIC_URL=' | cut -d= -f2-)"
    PGOPTIONS='-c default_transaction_read_only=on' psql "$PGURL" -X -A -t -c "SELECT count(*) FROM agenda_items"
    DATABASE_URL="$PGURL" PGOPTIONS='-c default_transaction_read_only=on' venv/bin/python scripts/backfill_hearings.py --city birmingham --since 2025-01-01 --dry-run
    DATABASE_URL="$PGURL" PGOPTIONS='-c default_transaction_read_only=on' venv/bin/python scripts/backfill_hearings.py --city birmingham --since 2025-01-01 --until 2026-11-16 --dry-run

The third and fourth lines have not been run: the script does not exist. Never print `$PGURL`, never write it to a file, and never run the script against it without `--dry-run`; the backfill itself is the operator's step. Expected, as a design assumption to be checked and not as evidence: the fourth line's totals near `matched=78 dated=67 undated=11`, a hearing line `hearing 2026-11-17 vacation items=62830,62881`, and a hearing line `hearing 2026-11-17 weed_lots items=62831,62882`.

The author's SQL for the 78, 66 and 9, so the comparison in M3 can name its terms: over Birmingham items of meetings dated 2025-01-01 or later, with `t` the title after `regexp_replace(title, E'[\n\t ]+', ' ', 'g')`, "matched" is `t ~* '(setting|to set|providing for) (a|the) public (show cause )?hearing'`, and "dated" is a non-null `regexp_match(t, '(?:setting|to set|providing for) (?:a|the) public (?:show cause )?hearing,? (?:on |for )?((?:January|February|March|April|May|June|July|August|September|October|November|December) [0-9]{1,2},? [0-9]{4})', 'i')`. That SQL knows only the first date form, which is why it dates 66 and the reader should date 67 (item 730).

Fetching the PDF in M4 (one request):

    mkdir -p content/coming-up/birmingham/sources
    curl -sS -o 'content/coming-up/birmingham/sources/2026_NA_Meeting_Schedule_rev._2-3-2026.pdf' -w '%{http_code} %{content_type} %{size_download}\n' 'https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/s3fs-public/2026-02/2026_NA_Meeting_Schedule_rev._2-3-2026.pdf'
    sha256sum content/coming-up/birmingham/sources/*.pdf

The author ran the `curl` line with a scratch path in place of the repository path and it printed `200 application/pdf 155273`.

The reading sheet in M5:

    venv/bin/python scripts/coming_up_reading_sheet.py birmingham > docs/runbooks/coming-up-reading-birmingham.md

Commits: every commit of a milestone session also changes this plan file (decision `0037`), hooks are never bypassed, and a Progress line is ticked by changing `- [ ]` to `- [x] (YYYY-MM-DD HH:MMZ)` and nothing else on the line.

## Validation and Acceptance

Each milestone's acceptance is what its session observes in this worktree. In every milestone, `./tools/verify` ends with `verify: all 6 checks passed in <N>s.`, its `plans` line reads `ok`, and the fast tiers or the integration tier report more tests passed than the session's own first run of the day did, with none failed; the session records both summary lines. A count of tests is not promised here, because a parametrized test collects one test per case.

M1. The single-file command in Concrete Steps, on `tests/unit/test_hearing_reader.py`, ends with a line of the form `<n> passed` and no failure, and the file asserts every row of the table of expected readings and the four pair cases. `grep -c "docket" src/docket/enrichment/hearings.py` may print any number; what must hold is the test that the module imports nothing from `docket`. Before the reader was written the session ran the test file and saw it fail on import; it records that line.

M2. `DATABASE_URL=$(tools/test-db) venv/bin/python -m docket.migrations.runner --status` lists the hearings migration as applied, and `tools/test-db --drop` follows. The migration test passes up, down, and up again. `tests/services/test_hearings_store.py` passes, and the session records, from a run of it with `-v`, the names of the test for two items making one hearing and the test for the withdrawn, hidden, and cancelled links.

M3. `tests/integration/test_ingest_hearings.py` and `tests/unit/test_backfill_hearings_script.py` pass. `venv/bin/python scripts/backfill_hearings.py --city birmingham` (no `--since`) exits non-zero and names the missing bound. The two production dry-run lines of Concrete Steps ran, and Artifacts and Notes holds their totals lines, the hearing lines for items 62830 with 62881 (one hearing dated 2026-11-17, two items) and 62831 with 62882 (one `weed_lots` hearing, 212), and the paragraph of differences against 78, 67, 11 and against the operator's 71 and 9, with no difference left unexplained. `git status --porcelain` prints nothing: the dry run's output was saved outside the repository.

M4. `sha256sum` of the saved PDF prints the digest the YAML and the README record. `tests/unit/test_neighborhood_schedule.py` passes, including the 99-association count and the cross-check against the PDF's table; the session records how many exceptions the cross-check's dict holds and each one's reason. Changing one association's `rule_text` by a letter in a scratch copy makes the cross-check fail, and changing the YAML's `sha256` by a digit makes the loader raise `ScheduleError`; the session records both failures' messages and restores the file.

M5. The hand-worked dates pass; the 2026 count is asserted (1,158, or the corrected figure with its arithmetic recorded); `docs/runbooks/coming-up-reading-birmingham.md` exists, names the content's commit, and has one tick-box line per association (`grep -c '^- \[ \]' docs/runbooks/coming-up-reading-birmingham.md` prints the association count, 99 unless M4 recorded otherwise).

M6. `tests/services/test_coming_up.py` passes; the session records, from `-v`, the names of the merged-meeting test, the cancelled-pair test, and the giveaway test.

M7. `tests/web/test_coming_up_page.py` passes; the session records the three status codes it asserts (200 for Birmingham, 404 for `mobile`, 404 for an unknown city) and the entry count the page and the service agreed on in the count test. `grep -n "db_cursor\|db()" src/docket/web/public.py` prints nothing new against `origin/main` (the route executes no SQL): `git diff origin/main -- src/docket/web/public.py | grep -c "^+.*db_cursor\|^+.*db()"` prints `0`.

M8. `tests/unit/test_ics.py` and `tests/web/test_coming_up_feed.py` pass; the session records the event count and the entry count the feed test found equal, and the first three lines of the feed body from that test's seeded rows (`BEGIN:VCALENDAR`, `VERSION:2.0`, the `PRODID` line).

M9. `docs/specs/coming-up.md` exists and `docs/specs/index.md` lists it; each of the four edited specs names what it gained (`grep -l "coming-up" docs/specs/city-page.md docs/specs/crawlers.md docs/specs/meeting-types.md` prints three paths, and `grep -c "backfill_hearings" docs/specs/operations.md` prints at least 1); `docs/DEBT.md` holds a row whose trigger is "the pull request merges" listing the operator's steps below in order, and the `D131` row names this plan; the milestone edits documents only: `git diff --stat <the commit the session started on> -- src/ tests/ scripts/ content/` prints nothing; `wc -l AGENTS.md` stays at or under 100. This plan file is still under `plans/active/`.

The operator's steps, none of which a milestone session takes and none of which is part of a Progress line. Machine: the Legion. Folder: the WSL checkout. They go into the M9 debt row in this order.

1. Before merging: read `docs/runbooks/coming-up-reading-birmingham.md` against the PDF (in the pull request, or the saved file), tick the rows, correct any row in the YAML through a commit on the branch, and add a `checked` entry with your name and the date.
2. Merge pull request #181 (Granicus start times) first if it is still open, so that a council meeting only the video site lists does not print a time two hours late.
3. Merge this plan's pull request; deploy `docket-web` and `worker` from a clean `main` with `scripts/deploy.sh`. The web service applies the hearings migration at start.
4. Dry run, then the backfill, with `DATABASE_URL` set to `DATABASE_PUBLIC_URL`: `venv/bin/python scripts/backfill_hearings.py --city birmingham --since 2025-01-01 --dry-run`, read the output against M3's record, then the same line without `--dry-run`. Expect `created=` near the dry run's `hearings=` and, on a second run, `created=0`.
5. Check, read-only: `SELECT h.id, h.hearing_date, h.kind, array_agg(i.agenda_item_id ORDER BY i.agenda_item_id) FROM public_hearings h JOIN public_hearing_items i ON i.hearing_id = h.id WHERE i.agenda_item_id IN (62830, 62881) GROUP BY 1, 2, 3;` prints one row dated 2026-11-17 with both items.
6. Open `https://docket.pub/al/birmingham/coming-up/` in a browser at about 390 and 1280 pixels wide: the next council meeting appears once with the city calendar's time; a day's neighborhood meetings open and close under their summary; nothing overflows sideways. `curl -sI https://docket.pub/al/birmingham/coming-up.ics` shows `content-type: text/calendar`, and subscribing to that address in a calendar program shows the entries on their days. `https://docket.pub/al/mobile/coming-up/` is 404.

## Idempotence and Recovery

The migration is additive and written with `IF NOT EXISTS`; its down drops only what it made and removes only its own metadata key. `refresh_hearings` can be run any number of times: links are upserted on the item, a stored hearing is found again by the same rule that made it, and a hearing with no link is deleted, so a second run changes nothing and a run after a rule change moves links rather than doubling them. If the backfill is interrupted, running it again completes it. To undo the backfill entirely: `DELETE FROM public_hearings WHERE municipality_id = (SELECT id FROM municipalities WHERE slug = 'birmingham')`, one statement, whose cascade removes the links; the page then shows no hearings and ingest refills the last 120 days on its next run. To turn the page, the feed, and ingest's step off without a deploy: `UPDATE municipalities SET metadata = metadata - 'coming_up' WHERE slug = 'birmingham'`; the page and feed then answer 404 and the city page's link disappears within its five-minute cache.

Every test that seeds rows prefixes them and deletes them before and after, so a killed run is tidied by the next. Fetching the PDF again overwrites the same file; if the bytes differ from the recorded digest the loader refuses until the YAML and the README are updated, which is the intended alarm. If a session runs short of context, it splits its Progress line in place (completed and remaining), records the split in the Decision Log, commits, and stops.

## Artifacts and Notes

### The fixture titles

The 25 objects of `tests/fixtures/hearings/birmingham_titles.json`, one per line here, exactly as production returned them on 2026-11-16 (`title` is the first 420 characters of the stored title; `len` is the stored title's length, so `len` over 420 means the title is cut here, and `len` of 254 to 256 with a marker at the start means production itself stores it cut). In the file they form one JSON list.

    {"id": 730, "len": 256, "title": "P\t\tITEM 27. \nA Resolution to set a public hearing on the application of Harvest Solutions, LLC to site a new solid waste treatment facility at 4400 7th Avenue North, Birmingham, AL 35212, on the 7th day of April, 2026, in the Council Chambers, Third Floor,"}
    {"id": 746, "len": 256, "title": "P\t\tITEM 43.\nA Resolution setting a public hearing to consider a temporary suspension on data centers within the City to be held at the regular meeting of City Council to be held in the Council Chambers in the City Hall in Birmingham, Alabama on March 3, 20"}
    {"id": 1152, "len": 256, "title": "ITEM 30. A Resolution setting a public hearing February 10, 2026, to consider the adoption of a resolution assenting to the vacation of 36,000 square feet of the right of way that is located parallel to and between 28th Street N. and 30th Street N. and  pe"}
    {"id": 1153, "len": 255, "title": "ITEM 31.\nA Resolution setting a public hearing February 10, 2026, to consider the adoption of a resolution assenting to the vacation of 1,185 square feet of the right of way that is located parallel to and between 22nd Street S. and Arlington Crescent and"}
    {"id": 1680, "len": 256, "title": "P\t\tITEM 25.\nA Resolution setting a public hearing December 9, 2025, to consider the adoption of an Ordinance \"TO AMEND THE ZONING DISTRICT MAP OF THE CITY OF BIRMINGHAM\" (Case No. ZAC2025-00013) from D-5 (Multiple Dwelling District) to I-1 (Light Manufactu"}
    {"id": 1681, "len": 255, "title": "P      ITEM 26.  \nA Resolution setting a public hearing December 9, 2025, to consider the adoption of an Ordinance \"TO AMEND THE ZONING DISTRICT MAP OF THE CITY OF BIRMINGHAM\" (Case No. ZAC2025-00022) to pre-zone territory proposed for annexation from B-2"}
    {"id": 2116, "len": 256, "title": "P\t\tITEM 35. [CHANGE HEARING DATE FROM OCTOBER 28, 2025 TO NOVEMBER 4, 2025]\nA Resolution setting a public hearing October 28, 2025 to consider the adoption of an Ordinance \"TO AMEND THE ZONING DISTRICT MAP OF THE CITY OF BIRMINGHAM\" (Case No. ZAC2025-00019"}
    {"id": 3131, "len": 256, "title": "P\t\tITEM 38.\nA Resolution setting a public hearing July 15, 2025 to consider the adoption of an Ordinance on a proposed text amendment to the City's Zoning Ordinance, Ordinance No. 15-133, as amended, to include the addition of several terms that were previ"}
    {"id": 3167, "len": 256, "title": "ITEM 22.\nA Resolution to set a public hearing to consider the closure of 20thAvenue South near its intersection with Richard Arrington, Jr. Boulevard South to vehicular traffic to control traffic flow from neighboring businesses. (Submitted by the City Att"}
    {"id": 3238, "len": 102, "title": "ITEM 1.\nA Resolution setting a public hearing in the Council Chambers on the Mayor's proposed budgets."}
    {"id": 3296, "len": 255, "title": "(ph)\tITEM 51.\nA Resolution setting a public show cause hearing to consider the matter of revoking the business license issued to Happy Hour Hangout at 2417 Avenue C, Birmingham, Alabama 35218. Said hearing shall be held at the Council's regular meeting in"}
    {"id": 3297, "len": 256, "title": "P ITEM 52. \nA Resolution, amending Resolution No. 796-25, adopted by Council May 13, 2025, setting a public hearing June 10, 2025, to consider the adoption of a resolution assenting to the vacation of the following: 26,875 square feet of the right of way t"}
    {"id": 3339, "len": 254, "title": "P\t\tITEM 24.\nA Resolution setting a public hearing June 10, 2025, to consider the adoption of a resolution assenting to the vacation of the following: 26,875 square feet of the right of way that is located parallel to and between 10th Court North and 10th"}
    {"id": 4412, "len": 256, "title": "CONSENT\t\tITEM 20.\nA Resolution finding that the following ninety-nine (99) properties have noxious or dangerous weeds growing thereon declaring said properties to be a public nuisance and providing that notice shall be posted on each of said properties and"}
    {"id": 4425, "len": 256, "title": "P\t\tITEM 19. \nA Resolution setting a public hearing February 4, 2025, to consider the adoption of an Ordinance \"TO AMEND THE ZONING DISTRICT MAP OF THE CITY OF BIRMINGHAM\" (Case No. ZAC2024-00011) to change zone district boundaries from MU-H, Mixed-Use High"}
    {"id": 58869, "len": 256, "title": "P ITEM 32\nA Resolution setting a public hearing June 9, 2026, to amend the City of Birmingham Zoning Ordinance, Title 1 \"General Provisions\" (Ord No. 15-133, as amended); filed by the Department of Planning, Engineering and Permits (Case No. ZAC2026-00001)"}
    {"id": 58878, "len": 94, "title": "A Resolution setting a public hearing in the Council Chambers on the Mayor’s proposed budgets."}
    {"id": 59096, "len": 64, "title": "PUBLIC HEARING ON THE PROPOSED 2026-2027 FISCAL YEAR CITY BUDGET"}
    {"id": 62182, "len": 303, "title": "A Resolution setting a public hearing November 17, 2026, to consider the closure of approximately 900 feet of Woodcrest Road South and Warick Court South to the intersection of 21st Way South and 15th Avenue South, Birmingham, due to the hazardous deterioration condition of the roadway. [First Reading]"}
    {"id": 62830, "len": 714, "title": "A Resolution setting a public hearing November 17, 2026, to consider the adoption of a resolution assenting to the vacation of 23,277 square feet of the right of way that is located parallel to and between 1st Avenue South and 2nd Avenue South and perpendicular to and between 28th Street South and 32nd Street South, and located at 3100 2nd Avenue South, Birmingham, on behalf of Marx Management, Sloss #2 Shaw, LLC, Sl"}
    {"id": 62882, "len": 502, "title": "A Resolution finding that the following two hundred twelve (212) properties have noxious or dangerous weeds growing thereon declaring said properties to be a public nuisance and providing that notice shall be posted on each of said properties and notice sent by certified mail to the last person assessing these properties for state taxes and further providing for a public hearing November 17, 2026, to hear and conside"}
    {"id": 63046, "len": 591, "title": "A Resolution setting a public hearing November 24, 2026, to consider the adoption of an Ordinance “TO AMEND THE ZONING DISTRICT MAP OF THE CITY OF BIRMINGHAM” (Case No. ZAC2026-08005) to change zone district boundaries from QMU-H (Qualified Mixed-Use High District) to QC-2 (Qualified General Commercial District), in order to allow for a new church campus, filed by C. Randall Minor, applicant, on behalf of the propert"}
    {"id": 63108, "len": 374, "title": "A Resolution setting a public hearing December 8, 2026, to consider the adoption of an Ordinance repealing Title 2 and Title 3 of the Zoning Ordinance of the City of Birmingham, Ordinance No. 15-133, as amended, removing obsolete provisions that no longer apply to properties within the corporate boundaries of the City of Birmingham. Case No. ZAC2026-08010. [First Reading]"}
    {"id": 63109, "len": 505, "title": "A Resolution finding that the following one hundred thirty-six (136) properties have noxious or dangerous weeds growing thereon declaring said properties to be a public nuisance and providing that notice shall be posted on each of said properties and notice sent by certified mail to the last person assessing these properties for state taxes and further providing for a public hearing December 8, 2026, to hear and cons"}
    {"id": 63166, "len": 506, "title": "A Resolution finding that the following one hundred thirty-six (136) properties have noxious or dangerous weeds growing thereon declaring said properties to be a public nuisance and providing that notice shall be posted on each of said properties and notice sent by certified mail to the last person assessing these properties for state taxes and further providing for a public hearing December 15, 2026, to hear and con"}

### Expected readings

For each fixture id: the hearing date (or "no date"), the kind, and the property count where there is one. "None" means `read_hearing` returns `None`.

    730     2026-04-07   other
    746     no date      other
    1152    2026-02-10   vacation
    1153    2026-02-10   vacation
    1680    2025-12-09   zoning
    1681    2025-12-09   zoning
    2116    2025-11-04   zoning
    3131    2025-07-15   zoning
    3167    no date      vacation
    3238    no date      budget
    3296    no date      other
    3297    2025-06-10   vacation
    3339    2025-06-10   vacation
    4412    None
    4425    2025-02-04   zoning
    58869   2026-06-09   zoning
    58878   no date      budget
    59096   None
    62182   2026-11-17   vacation
    62830   2026-11-17   vacation
    62882   2026-11-17   weed_lots   212
    63046   2026-11-24   zoning
    63108   2026-12-08   zoning
    63109   2026-12-08   weed_lots   136
    63166   2026-12-15   weed_lots   136

How the less obvious rows come out under the rules of M1, worked by the author. 730: the trigger is "to set a public hearing"; what follows is "on the application of", so the first form finds nothing; the second finds "on the 7th day of April, 2026"; no kind word fits, so `other`. 746: the first two forms find nothing and the third finds "to be held ... on March 3, 20", whose year is cut to two digits, so no date. 2116: the first form reads October 28, 2025, the text holds "CHANGE HEARING DATE FROM OCTOBER 28, 2025 TO NOVEMBER 4, 2025", and the date read equals the first, so the date is November 4, 2025. 3297: "amending Resolution No. 796-25, adopted by Council May 13, 2025" comes before the trigger, so May 13 is never considered; the date after the trigger is June 10, 2025. 3167: "closure of" makes it `vacation`, and it has no date. 4412: a weed-lot title cut before "providing for a public hearing", so no trigger. 59096: the words "PUBLIC HEARING" with no trigger before them. 63108: "Zoning Ordinance" makes it `zoning`.

The pair cases, with keys taken from the readings. 3297 and 3339 are the same hearing: 3297's key is 101 characters and 3339's begins with it. 1152 and 1153 are different: both keys begin `toconsidertheadoptionofaresolutionassentingtothevacationof` and continue `36000` and `1185`. 1680 and 1681 are different: the keys part at the case numbers, `zac202500013` and `zac202500022`. 62182 and 62830 are different: `toconsidertheclosureof...` and `toconsidertheadoptionof...`. Under the other rule one might have chosen, equal case numbers, 3297 and 3339 would be two hearings, since neither stored title reaches its case number; the test asserts that neither title contains "Case No".

### Dates worked by hand

Counted on a 2026 calendar by the author and checked with Python's `calendar` module on 2026-11-16 (November 1, 2026 is a Sunday; December 1, 2026 is a Tuesday).

    Acipco-Finley      first Wednesday     November 4 and December 2, 2026
    Brown Springs      third Thursday      November 19 and December 17, 2026
    Huffman            fourth Monday       November 23 and December 28, 2026
    Gate City          second Monday       December 14, 2026
    Jones Valley       first Friday        January 2 and May 1, 2026
    East Birmingham    fourth Monday       February 23, 2026
    Overton            first Tuesday, even months only: October 6 and December 1, 2026, and no date in November 2026
    Glen Iris          no dates
    Bridlewood         no dates

The times that go with them, from the schedule: Acipco-Finley 17:30, Brown Springs 18:00, Huffman 19:00, Gate City 16:00 ("@4 p.m."), Jones Valley 16:00, East Birmingham 18:00, Overton 18:00. West Brownsville's "@ 10: 00 a.m." is 10:00.

### What M3 will add here

The production dry run's totals lines, hearing lines, and the comparison paragraph. As authored, none exists.

## Interfaces and Dependencies

No new package. `pdfplumber` and `pyyaml` (through `python-frontmatter`; `src/docket/services/how_it_works.py` already imports `yaml`) are in the environment; `requirements.txt` and `requirements.lock` are not changed.

At the end of M1, in `src/docket/enrichment/hearings.py`:

    RULE_VERSION: int
    KINDS: tuple[str, ...]
    KIND_LABELS: dict[str, str]
    @dataclass(frozen=True)
    class HearingReading: hearing_date: date | None; kind: str; subject: str; subject_key: str; property_count: int | None
    def read_hearing(title: str | None) -> HearingReading | None
    def same_hearing(key_a: str, key_b: str) -> bool

At the end of M2 and M3, in `src/docket/services/hearings.py`:

    RECENT_DAYS: int
    @dataclass(frozen=True)
    class HearingReport: matched: int; dated: int; undated: int; hearings: int; created: int; linked: int
    def find_readings(municipality_id: int, since: date, until: date | None = None) -> list[dict]
    def group_readings(rows: list[dict]) -> list[dict]
    def refresh_hearings(municipality_id: int, since: date, until: date | None = None) -> HearingReport
    def refresh_recent(municipality_id: int) -> HearingReport | None
    def list_upcoming(municipality_id: int, start: date, end: date) -> list[dict]

At the end of M4 and M5, in `src/docket/services/neighborhood_schedule.py`:

    class ScheduleError(ValueError)
    @dataclass(frozen=True) class Association
    @dataclass(frozen=True) class Schedule
    @dataclass(frozen=True) class Occurrence: association: Association; on: date
    def load_schedule(city_dir: Path) -> Schedule
    def get_schedule(slug: str) -> Schedule | None
    def occurrences(schedule: Schedule, start: date, end: date) -> list[Occurrence]
    def undated(schedule: Schedule) -> list[Association]

At the end of M6, in `src/docket/services/coming_up.py`:

    WINDOW_DAYS: int
    @dataclass(frozen=True) class Entry
    def is_coming_up_city(municipality: dict | None) -> bool
    def list_entries(municipality: dict, *, today: date | None = None) -> list[Entry]
    def undated_associations(slug: str) -> list[tuple[str, str]]
    def schedule_source(slug: str) -> dict | None

At the end of M7 and M8, in `src/docket/web/public.py`, the routes `public.coming_up_page` and `public.coming_up_ics` and the template global `has_coming_up`; in `src/docket/web/ics.py`, `render_calendar(entries, *, name, now, absolute) -> str`; in `src/docket/services/sitemap.py`, `has_coming_up(slug: str) -> bool`.

Allowed imports, by the layer map in `ARCHITECTURE.md`: the reader imports the standard library only; the three services import `docket.db`, `docket.config`, `docket.enrichment.hearings`, `docket.adapters._helpers`, and other services; nothing under `services/` imports `docket.web`; `public.py` and `ics.py` call services and execute no SQL.

Files this plan does not edit, and a session that needs to edit one stops and records why first: `src/docket/web/__init__.py`, everything under `src/docket/worker/`, `src/docket/services/briefing.py`, `src/docket/services/meeting_types.py`, `src/docket/services/query.py`, `src/docket/web/static/layout.css`, `src/docket/web/static/mobile.css`, `requirements.txt`, `Dockerfile`.

## Revision note

2026-11-16, authored by the `cycle-plan` workflow from the operator's goal and a scope brief written by a read-only agent; the brief is folded into Purpose and Context and is not committed as a file. Deliberately left out of this plan, and why: the existing `/al/<slug>/upcoming-hearings.rss` and `query.list_upcoming_hearings` (re-pointing them changes a published feed for every city; M9 records the two notions as debt); fixing Granicus start times (issue #88, pull request #181, a branch already in flight; the operator merges it first); retiring leftover `event-` rows (issue #62; the page lists only future dates, so one disappears when its date passes); reading committee agendas into items (`D132`; an upcoming committee meeting links its event page and nothing about what it will take up); showing a hearing on the item page, the meeting page, the city-page opener, or in search (the goal names one page and one feed); past hearings as a browsable archive (the backfill stores them, the page shows the window); hearings held without a dated resolution setting them (consent "ph" items, licence hearings); a 2027 neighborhood schedule and any automatic re-fetch of the PDF; holiday or one-off changes the PDF does not state; the README's worker counts (`D138`) and SQL in web modules (`D7`); the test-removal runner of `D131` (re-deferred); other cities, events submitted by users or groups, board term ends and vacancies, elections, contract end dates, and deferred-item tracking (excluded by the goal); and deploy, the production migration, and the production backfill, which are the operator's steps after the merge.
