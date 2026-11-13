# Explain how an item moves through the Birmingham City Council, on one page, with real items walked through it

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

docket.pub tells a reader what the Birmingham City Council voted on. It does not tell them how a thing reached that vote or what happens next. After this plan, a reader can open `https://docket.pub/al/birmingham/how-it-works/` and see the whole path an ordinance or resolution travels (submitted, committee, on the agenda, first reading, final vote, Mayor, in effect, with the side routes for the consent agenda, a public hearing, and being held over), each step explained in the words of the rule that governs it, with a citation and a link to that rule. Above the explanation the reader picks one of four real items and watches it travel the path: each stop shows the date, what the city's record says happened, and links to that day's meeting, the moment in the recording, the transcript, and the city's own document. A stop the rules say happens but the records do not show is drawn as "not in the record", never as done.

To see it working after the last milestone: start the dev server and open `/al/birmingham/how-it-works/`. The path is across the top. Choose "Parking fines ordinance". The journey shows a committee recommendation on 2026-05-11, a withdrawal on 2026-05-19, a first reading on 2026-05-26 that failed to get unanimous consent (three ayes, six nays), and adoption 8 to 0 on 2026-06-02, each with links. The Mayor and "in effect" stops say "not in the record".

This is the first of four phases described in the design document `docs/superpowers/specs/2026-11-12-how-it-works-design.md`. This plan builds only the first: the page and four hand-traced journeys. It reads no new source, adds no table, changes no stored value, and adds no progress strip to item pages; those are later plans.

## Progress

- [ ] M1: The explainer's content exists as data with its sources beside it, a loader reads it, and a test proves every quoted rule appears in its source.
- [ ] M2: `/al/birmingham/how-it-works/` renders the path, a section for each stop with its quoted rules and citations, and the open questions; other cities return 404; the city page and the meeting page link to it.
- [ ] M3: A journey file format and a resolver exist, and the parking-fines journey renders on the page with links that resolve, selectable by `?journey=`.
- [ ] M4: The three further journeys (the Huffman Road rezoning, the Legion Field liquor licence, the Friends of Avondale Park contract) are selectable, and switching between journeys swaps the journey without reloading the page.
- [ ] M5: The behaviour is written into `docs/specs/`, the Birmingham guide lists the page, the durable decisions are graduated, and the deferred work is recorded in `docs/DEBT.md`.

## Surprises & Discoveries

As authored on 2026-11-12, nothing has been executed and there are no discoveries from execution. Discoveries made while researching the plan are in Context and Orientation.

- Observation (M1, 2026-11-13): the starting state was green, and the verify command ran over its stated budget. `./tools/verify`, run before any edit at commit `0c190c4`, exited 0 in 195 seconds against the 180-second budget `AGENTS.md` gives.
  Evidence: `verify: unit+web+services ... ok (84s)`, `verify: integration ... ok (103s)`, `verify: transcriber ... ok (8s)`, `verify: all 6 checks passed in 195s.`

- Observation (M1, 2026-11-13): the design document names the old sources directory three times, not twice. Besides the full path in its section 3, the committee row of the parking-fines table in section 6 and the first sentence about minutes in section 8 each name a file as `2026-11-12-how-it-works-sources/committee-…`. All three now read `content/how-it-works/birmingham/sources/…`.
  Evidence: after the move, `grep -n how-it-works-sources docs/superpowers/specs/2026-11-12-how-it-works-design.md` prints nothing.

- Observation (M1, 2026-11-13): before the loader exists, every new test fails and the file still collects. The tests import `docket.services.how_it_works` inside each test function, so the before state is 28 failures in one file and not one collection error. The content file and the tests are committed in this state, ahead of the loader.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_how_it_works_content.py -q -p no:cacheprovider; tools/test-db --drop` printed `28 failed, 1 warning in 0.13s`.

- Observation (M1, 2026-11-13): with the loader written, the same 28 tests passed on their first run, so each rule of the loader was then taken out of an in-memory copy of `src/docket/services/how_it_works.py`, one at a time, and the tests run against each copy (a pytest plugin in the session scratchpad; the committed file was not edited). 22 removals were tried; 19 failed at least one test and 3 failed none: a stop's `description` being required, an open question needing both `heading` and `body`, and `sources_read` having to be a date. Three tests were added after the commit that holds the tests failing (`a1ad5f7`) to pin them: `test_a_stop_with_no_description_raises`, `test_an_open_question_needs_a_heading_and_a_body`, `test_the_date_the_sources_were_read_must_be_a_date`. With those, all 22 removals fail a test. The 19 that failed at once include every rule M1 states: a stop with no rules, a rule with no citation, no link, a quote with no source file, a source file that does not exist, a quotation not in its source, pieces out of order, a piece looked for from the start and not the end of the one before, whitespace collapsing, quote-mark straightening, and the case-sensitive comparison.
  Evidence: `28 passed, 1 warning in 0.30s` before the removals; after the three additions `31 passed, 1 warning in 0.31s`, and removals 19, 20 and 21 each printed `1 failed, 30 passed`.

- Observation (M1, 2026-11-13): the Birmingham content holds 10 stops (seven on the path, three side routes), 54 rules, and 54 quotations; every rule carries a quotation, so none relies on the exemption for unquoted rules. Rules per stop: submitted 6, committee 14, agenda 3, consent 4, hearing 7, first_reading 3, held_over 3, final_vote 5, mayor 5, in_effect 4. M2's acceptance counts `href="https://` against the number of rules; that number is 54.
  Evidence: `load_explainer(Path("content/how-it-works/birmingham"))` in a one-off script printed `10 54 54`.

## Decision Log

- Decision: The page lives at `/al/<slug>/how-it-works/` and returns 404 for any city that has no content directory.
  Rationale: Every city page lives under `/al/<slug>/`, and the content is Birmingham's rules only. A static segment wins over the variable route `/al/<slug>/<badge_slug>/` in Flask's router, as `/al/<slug>/council/` already does.
  Date/Author: 2026-11-12, plan author.

- Decision: The explainer's rules and journeys are checked-in YAML under `content/how-it-works/<slug>/`, read at application start, and no language model writes any sentence on the page.
  Rationale: Every sentence must trace to a source (`docs/PRINCIPLES.md`, "Source or silence"). Hand-written, reviewed text in the repository is the only way to hold that for rule text. `content/` is already deployed (`Dockerfile` copies the whole tree) and already holds the blog's markdown.
  Date/Author: 2026-11-12, plan author.

- Decision: A journey states its facts in its own file (dates, tallies, quotations) and names the record each fact rests on; the page resolves only links from the database, never facts.
  Rationale: Vote rows can be re-created by a re-parse and so their ids are not stable; a journey that printed a tally read live from `votes` could change under the reader, and one whose vote id vanished would lose its tally. A hand-checked fact with a link to the city's document is stable, and when the linked row is missing or hidden the stop keeps its text and loses only that link.
  Date/Author: 2026-11-12, plan author.

- Decision: A test asserts that every quotation in the content appears, after whitespace and quote-mark normalising, in the saved source text it cites.
  Rationale: The design document's first done-when is that a reviewer can find the quoted words in the source. A mechanical check makes that hold on every later edit.
  Date/Author: 2026-11-12, plan author.

- Decision: The page is not added to the sitemap service.
  Rationale: `src/docket/services/sitemap.py` lists cities, meetings and items only; no static page (`/about/` and its children) is in it. Adding static pages to the sitemap is a separate change.
  Date/Author: 2026-11-12, plan author.

- Decision: Phase 1 adds no link from item pages or item cards.
  Rationale: The progress strip on items is the design's Phase 3. A link on only the eleven items that appear in journeys would be a special case the strip later replaces.
  Date/Author: 2026-11-12, plan author.

- Decision: A journey stop names one or more path stops, and every journey accounts for each of the seven main stops as recorded, "not in the record", or "not on this item's route".
  Rationale: One event can be two stops (a public hearing and the final vote on the same call of the item), and a path stop a journey says nothing about would be drawn blank, which reads as "a rezoning is never submitted". Requiring every main stop to be accounted for, with a reason where there is no record, keeps the path the same shape for every journey and makes each blank an explicit statement. Raised by the external review of 2026-11-13.
  Date/Author: 2026-11-13, plan author.

- Decision: A quotation that elides words with "…" is checked piece by piece: each piece between ellipses must appear in the source, in order.
  Rationale: The design's own rule quotations elide (General Code §2-2-15(c)(2): "every ordinance or resolution … shall be submitted to a committee"), so a whole-string check would fail on the first run, and forbidding ellipses would force long quotations onto the page.
  Date/Author: 2026-11-13, plan author.

- Decision: The path is a compact map and the journey is a vertical timeline beneath it; the picker comes first, then the item's title, then the path, then the timeline. At phone width the path stacks vertically; it never scrolls sideways.
  Rationale: A journey has up to nine events with quotations and up to seven links each, which do not fit in seven columns. Picking an item above the path means the marks on the path change below the reader's click, not above it. A sideways-scrolling path at 375 pixels hides four of seven stops. This supersedes the design's "may scroll sideways or stack".
  Date/Author: 2026-11-13, plan author.

- Decision: The page states what the record shows and does not say why a councilmember voted as they did.
  Rationale: The external review proposed explaining the 3 to 6 first-reading vote as members deliberately forcing a week's review. The minutes record the motion, the roll and the Presiding Officer's declaration; no record read gives a motive. The page shows the tally, the names, the declaration and the rule beside it, and the 8 to 0 vote a week later, and leaves the inference to the reader.
  Date/Author: 2026-11-13, plan author.

## Outcomes & Retrospective

As authored on 2026-11-12, nothing has been executed and there are no outcomes.

## Context and Orientation

docket.pub is a Python 3.10 Flask application with HTMX, backed by PostgreSQL. `AGENTS.md` at the repository root is the map. Three rules from it govern this plan. Routes live in `src/docket/web/public.py` and never run SQL; they call functions in `src/docket/services/`. Services own every database read. And nothing shown to a reader may lose its link to the city's source (`docs/PRINCIPLES.md`).

The design this plan implements is `docs/superpowers/specs/2026-11-12-how-it-works-design.md`. Read it in full before M1. Its section 3 is the table of rules with their citations and its list of seven open questions; section 5 is the path; section 6 is the four journeys, stop by stop, with the record each fact rests on. Those three sections are the content this plan turns into data. Beside it, `docs/superpowers/specs/2026-11-12-how-it-works-sources/` held plain-text copies of every source the rules quote, with a `README.md` giving each one's public address and the date it was read; M1 moved that directory to `content/how-it-works/birmingham/sources/` on 2026-11-13, and that is where to read them now.

Terms used below. A **stop** is one step on the path, such as "Committee" or "First reading". A **side route** is a stop that only some items take: the consent agenda, a public hearing, being held over. A **rule** is one statement about a stop, with the words of its source, a citation, and a link. A **journey** is one real item followed across the stops, with what the record shows at each. A **journey stop** is one event in a journey; a journey may have several events at the same path stop (the parking-fines ordinance was at "First reading" twice) and may have none at a path stop.

What exists today that this plan uses:

- `src/docket/web/public.py` holds the public routes on the blueprint `bp`. `city_overview` serves `/al/<slug>/`, `meeting_detail` serves `/al/<slug>/meetings/<int:meeting_id>/`, `meeting_transcript` serves `/al/<slug>/meetings/<int:meeting_id>/transcript/`, `item_detail` serves `/al/<slug>/items/<int:item_id>/`, and `about_methodology` serves `/about/how-we-read-minutes/` from the static template `src/docket/web/templates/about_methodology.html`, which is the model for this page's hero and section markup (`section.hero.hero--detail`, `section.feed`, `t-eyebrow`, `t-display`, `hero-sub`).
- `src/docket/services/query.py` has `get_municipality(slug) -> dict | None`, `get_meeting(meeting_id) -> Meeting | None` and `get_agenda_item(item_id) -> AgendaItem | None`. `Meeting` (`src/docket/models/meeting.py`) carries `municipality_id`, `meeting_date`, `agenda_url`, `minutes_url`, `video_url`, `is_hidden`. `AgendaItem` (`src/docket/models/agenda.py`) carries `meeting_id` and `external_id`, which for a Granicus item is the chapter id its video link needs.
- `src/docket/services/video_links.py` builds links into a meeting's recording. `for_meeting(meeting_id) -> MeetingVideo | None` loads what a link is built from, and `link_for(video, *, seconds=None, chapter_id=None) -> VideoLink | None` returns a `VideoLink` with `url`, `label` ("YouTube", "Granicus" or None) and `timed`. A Granicus player can only jump to a chapter, so a link is "timed" on Granicus only when a chapter id is passed; when the meeting has an aligned YouTube recording the link opens YouTube at the second. A committee meeting's own video is a YouTube address, and `link_for` with no seconds returns its plain watch address.
- `src/docket/services/transcripts.py` has `get_public_transcript(meeting_id) -> Transcript | None`, which returns a transcript only when it is public.
- `src/docket/blog/loader.py` and `src/docket/web/__init__.py` show how checked-in content is loaded once in `create_app` and kept in `app.config` (`BLOG_STATE`, from `BLOG_CONTENT_ROOT` in `src/docket/config.py`). This plan follows the same shape. PyYAML is already installed (it arrives with `python-frontmatter` in `requirements.txt`, and `config/blog_authors.yaml` is read with it).
- Tests: `tests/unit/` for pure functions, `tests/services/` for services against the test database, `tests/web/` for routes and templates. `tests/web/conftest.py` provides `client` (a Flask test client) and `render_partial`. `tests/web/test_meeting_recordings.py` shows how a web test inserts a municipality's meeting rows and removes them. `./tools/verify` runs every tier against a throwaway database and is the only test command to run; never run bare `pytest` against a database you care about (`AGENTS.md`, Commands).

Facts established while researching, which the milestones rely on:

- The local development database holds no Birmingham agenda items, so nothing here can be checked against local rows. Every id in the journeys was read from production on 2026-11-12 and is recorded in section 6 of the design document. A milestone session has no production connection; it writes the ids the design gives and proves the resolver on rows its own test inserts. The operator's check after deploy is in Validation and Acceptance.
- The states that would make a journey's sentence or link wrong, and what the page does for each. A meeting row that is hidden (`is_hidden`) or missing: the stop keeps its text and shows no link to that meeting, its recording or its transcript. An item row that is missing, or belongs to a different meeting than the stop names: no item link and no chapter id; the meeting links remain. A meeting with no `video_url`: no recording link. A meeting with no public transcript: no transcript link. A meeting with no `minutes_url` or no `agenda_url`: that document link is absent. A stop that names no meeting (the Mayor's signature, publication): the words "not in the record" and the reason the journey file gives. The page never prints a date, a tally or a name that is not written in the journey file.
- Two journey facts come from a video reading, not from adopted minutes (the 8 to 0 votes of 2026-09-29 and 2026-10-13). The journey file marks them, and the page labels them "from the video", as the rest of the site does.
- Item 58990 (the 2026-05-26 first reading) has no video cue stored, and its `external_id` is `event-2693-11`, which is not a chapter id; its stop links the meeting, the minutes and the transcript, and the recording untimed.
- `video_links.link_for` already refuses a chapter id that is not all digits: it returns the plain player address with `timed` false (`_is_chapter_id` in `src/docket/services/video_links.py`). The resolver passes `external_id` through unchanged and adds no guard of its own; a test pins the behaviour.
- Which journeys have a first reading, read from production on 2026-11-13. Item 61883 (the rezoning's hearing-setting resolution of 2026-09-15) ends `[First Reading]` in its own text, so that event is both "On the agenda" and "First reading". Items 62035 (the liquor licence) and 62911 (the consent contract) are resolutions whose text carries no reading marker; their journeys mark "First reading" as not on the item's route, with the reason "The agenda does not mark this resolution as a first reading."
- The web tests run against a database with no Birmingham meetings, and so does the local preview. Without seeded rows no test would ever run the template's link markup, and a mistyped attribute there would first fail in production. M3's web test therefore seeds a meeting and an item under the ids a journey cites.
- The page writes no sentence from a database row, so no reader of any column changes, and no existing prose rule changes.

## Plan of Work

### M1: Content as data, with a check that quotations are real

Scope: turn the design's rules, path and open questions into one YAML file per city, move the saved source texts beside it, write the loader, and prove by test that every quotation is in its source. Nothing is rendered yet.

Create the directory `content/how-it-works/birmingham/`. Move the whole of `docs/superpowers/specs/2026-11-12-how-it-works-sources/` to `content/how-it-works/birmingham/sources/` (with `git mv`, so the design document's two references to the old path must be edited to the new one in the same commit). Write `content/how-it-works/birmingham/explainer.yaml` from sections 3 and 5 of the design, in the shape given in Interfaces and Dependencies: the seven stops and three side routes in path order, each with a one-sentence plain description; under each, its rules, each with the statement in plain words, the quotation where the design gives one, the citation, the public link, and the name of the source file under `sources/` that holds the quotation; and the seven open questions, each as a short heading and a paragraph. Use the design's wording for the rules. A rule the design states without quotation marks has no `quote` and is exempt from the quotation check, but still needs its citation and link. Where the design names a source with no saved copy (the Statement of Conduct of Business is in `council-agenda-2026-11-10.txt`; the committee outcome wordings are in the `committee-*.txt` files), use the file that holds the words.

Create `src/docket/services/how_it_works.py` with the dataclasses and `load_explainer` given in Interfaces. It parses and validates; it does not touch the database. Validation failures raise `ExplainerError` naming the file and the key: a stop with no rules, a rule with no citation or no link, a `quote` whose `source_file` is missing, a `source_file` that does not exist, a rule whose stop key is not one of the path's.

Add `HOW_IT_WORKS_ROOT = os.environ.get("HOW_IT_WORKS_ROOT", "content/how-it-works")` to `src/docket/config.py`.

Tests in `tests/unit/test_how_it_works_content.py`: the Birmingham explainer loads; its stop keys, in order, are `submitted`, `committee`, `agenda`, `first_reading`, `final_vote`, `mayor`, `in_effect`, and its side routes are `consent`, `hearing`, `held_over`; every rule has a citation and an `https://` link; every `quote` is found in its source file after normalising (collapse all whitespace to single spaces, replace curly quotes and apostrophes with straight ones, compare case-sensitively); there are exactly seven open questions; and a loader given a file with a quotation that is not in its source raises `ExplainerError`. A quotation containing "…" or "..." is split there, and each piece must be found in the source, each after the end of the one before; test that a quotation whose pieces are both present but in the wrong order raises `ExplainerError`, and that one with a piece absent does too. These three tests use a temporary directory, not the real content.

### M2: The page, without journeys

Scope: the route, the template, the styles, the links in. At the end the page explains the whole path with cited rules and nothing about any particular item.

In `src/docket/web/__init__.py`, inside `create_app`, load every city's explainer once: for each directory under `HOW_IT_WORKS_ROOT` that holds an `explainer.yaml`, call `load_explainer` and store the results in `app.config["HOW_IT_WORKS"]` as a dict keyed by city slug. A load failure must fail application start with the `ExplainerError` message, as a broken template would; do not catch it into an empty page.

In `src/docket/web/public.py` add the route `/al/<slug>/how-it-works/` as `how_it_works(slug)`. It returns 404 when the city does not exist or has no entry in `app.config["HOW_IT_WORKS"]`, and otherwise renders `how_it_works.html` with the municipality and the explainer.

Create `src/docket/web/templates/how_it_works.html`, extending `base.html`. In order: a hero in the manner of `about_methodology.html`, with the eyebrow "How it works", the title "How an item becomes a decision in <city name>", and one sentence saying that every rule below is quoted from the city's code, state law, or the council's own agenda, with the date the sources were read; the path, an ordered list of the seven stops drawn as a horizontal line of numbered stops with the three side routes hung beneath the stop they branch from (consent and hearing under "On the agenda", held over under "First reading"), each stop linking to its section below; then one `section.feed` per stop and side route, with the stop's description and its rules, each rule as the plain statement, the quotation in a `blockquote` where there is one, and the citation as a link that opens the public source; then a section "What we could not establish" with the seven open questions. The path must be an `<ol>` of exactly seven `<li>`, so it reads and numbers one to seven without styles. `Explainer.stops` is a flat tuple of ten, so do not loop it straight into the `<ol>`: loop the stops whose `side_route_of` is null, and inside each `<li>` render a `<ul>` of the side routes whose `side_route_of` is that stop's key. Keep the words inside the path to the number, the stop's name, and (from M3) its mark. At widths under 720 pixels the path stacks vertically, the line becoming a spine down the left; it never scrolls sideways.

Put the page's styles in a new file `src/docket/web/static/css/how_it_works.css`, linked from the template's `{% block head %}` (which `src/docket/web/templates/base.html` leaves empty for pages to fill) with the same `url_for('static', filename=...)` form `base.html` uses for `css/smart_brevity.css`, using the colour and spacing custom properties already defined in `src/docket/web/static/styles.css`; define no new colours.

Add the links in. The footer that names the hosts the records came from is the shared partial `src/docket/web/templates/partials/page_sources.html`; its `nav.page-sources-links` already holds "Source health" and "How we read minutes". Add a third link there, "How the council works", to the page, rendered only when a `municipality` is in the template's context and the city has an explainer. That one edit puts the link on the city page and on every other page that includes the partial with a municipality, the meeting page among them; confirm which pages those are with `grep -rn page_sources.html src/docket/web/templates` and record the list in Surprises & Discoveries. Expose the condition to templates as a Jinja global `has_how_it_works(slug)` registered in `create_app` beside `meeting_label`.

Tests in `tests/web/test_how_it_works_page.py`: `GET /al/birmingham/how-it-works/` returns 200; the response contains each of the seven stop names in path order; it contains the text of one known quotation ("No action of any committee including the committee of the city council as a whole shall be considered final") and the citation "§2-2-14(b)"; the path's `<ol>` has exactly seven direct `<li>` children and the three side-route names sit inside nested `<ul>`s; it contains the heading "What we could not establish"; `GET /al/mobile/how-it-works/` returns 404 and so does a slug that is not a city; and the city page for Birmingham contains a link to the page while a city without an explainer does not. These tests need a Birmingham and a Mobile row in `municipalities`; migration `001` seeds Birmingham and migration `002` seeds Mobile in the test database.

### M3: Journeys, and the parking-fines ordinance on the page

Scope: the journey file format, the resolver that turns a journey's record references into links, and the first journey rendered above the explanation.

Write `content/how-it-works/birmingham/journeys/parking-fines.yaml` from the first table in section 6 of the design, in the shape given in Interfaces: the journey's key, the short label for the picker ("Parking fines ordinance"), a one-line note of what it shows ("held over a week for lack of unanimous consent"), the item's title, and its journey stops in date order. The stops are: submitted (no date, "not in the record": the submission date is not published); committee, 2026-05-11, meeting 3142, with the committee's action quoted, the committee minutes address as its document, and `source_file: committee-transportation-minutes-2026-05-11.txt` so the quotation is checked; first reading listed and withdrawn, 2026-05-19, meeting 2232, item 58893, cue 2506 seconds, marked as read from the machine transcript, naming both `agenda` and `first_reading` in `stops`; first reading voted, 2026-05-26, meeting 2237, item 58990, with both roll calls (the names and the tally, three ayes and six nays, in the text) and the Presiding Officer's declaration quoted from the minutes; held over, 2026-05-26 to 2026-06-02, with the agenda's own note quoted; final vote, 2026-06-02, meeting 2238, item 59026, cue 5313 seconds, adopted as amended as Ordinance No. 26-61 with the eight ayes named; Mayor ("not in the record": the ten-day window ran to 2026-06-12 and the site holds no record of signature or veto); in effect ("not in the record": effective on publication, and the site holds no publication record). Mention the sibling ordinance (Title 8, Chapter 3, Section 8) in the journey's note, as the design does. Copy quotations exactly from the design.

Extend `src/docket/services/how_it_works.py`: `load_explainer` also reads every `journeys/*.yaml` beside the explainer into `Explainer.journeys`, validating that every key in a journey stop's `stops` is one of the path's stops or side routes, that a stop with `record: none` or `record: not_on_route` has a `gap` reason and no meeting, that every one of the seven main stops is named by at least one journey stop, that a quotation with a `source_file` is found in that file by the M1 check, and that journey keys are unique. Add `resolve_journey(journey, municipality_id, city_slug) -> ResolvedJourney`, which for each journey stop that names a meeting looks the meeting up with `query.get_meeting`, and builds the links listed in Interfaces under the rules in Context ("The states that would make a journey's sentence or link wrong"). A meeting that is missing, hidden, or whose `municipality_id` is not the one passed in is treated the same way: no links. The three sets on `ResolvedJourney` do not overlap: `reached` is every key named by a recorded stop; `not_in_record` is every key named by a `record: none` stop, less `reached`; `not_on_route` is every key named by a `record: not_on_route` stop, less the other two. It reads through existing services only (`query.get_meeting`, `query.get_agenda_item`, `video_links.for_meeting`, `video_links.link_for`, `transcripts.get_public_transcript`) and writes nothing.

In the route, read `?journey=<key>`; when it names a journey of this city, resolve it and pass it to the template; when it is absent, resolve the first journey in file-name order; when it names nothing, return 404. In the template, the order from the hero down becomes: the journey's label, note and quoted title; the path; the journey's stops; then the stop sections. (M2 put the path directly under the hero; move it.) Wrap the first three in one container with the id `how-it-works-journey`, which M4 turns into the swapped partial. Render the journey's stops as a vertical timeline, one card per stop in file order, each showing the name of every path stop it belongs to as a link to that stop's section below (`#stop-<key>`), the date (or "not in the record"), the journey file's text, any quotation, a provenance label, and its links. Each stop section below gains a "Back to the journey" link to `#how-it-works-journey`. The provenance label is fixed by `record`: `video` shows "from the video", `transcript` shows "from the machine transcript", and `minutes`, `agenda`, `committee_minutes`, `none` and `not_on_route` show no label. The links are drawn as small pills in a fixed order: "Meeting", "Item", "Recording" (with the site name `link_for` returns, and "at this moment" only when the link is timed), "Transcript", "Minutes", "Agenda", and the stop's own document link when the file gives one (labelled with the file's label, for example "Committee minutes"). A stop with `record: none` is drawn with a dashed outline and the gap reason; one with `record: not_on_route` is drawn as a slim, muted line with its reason. On the path itself, mark each stop and side route from the resolved journey's three sets: in `reached`, filled, with the words "in the record"; in `not_in_record`, dashed, with "not in the record"; in `not_on_route`, muted, with "not on this item's route". A side route in none of the sets is muted with no words. Every mark carries its words as text, not colour alone. No stop is drawn as "now" or "current": every journey is a finished item, and the page shows what was recorded, not where an item stands.

Tests. `tests/unit/test_how_it_works_content.py` gains: the parking-fines journey loads with eight journey stops; its stops with `record: none` are exactly submitted, mayor and in_effect; a journey file whose stop key is not on the path raises `ExplainerError`; a journey file that names no stop for one of the seven main stops raises `ExplainerError` naming that stop; a journey quotation with a `source_file` that does not hold it raises `ExplainerError`. `tests/services/test_how_it_works_resolve.py` inserts, for a test municipality, one visible meeting with an agenda address, a minutes address and a Granicus `video_url`, one agenda item in it with a numeric `external_id`, one hidden meeting, and one meeting with a YouTube `video_url`, and asserts on a journey built in the test: a stop on the visible meeting with the item and `seconds` gets a meeting link, an item link, a recording link whose `timed` is true, a minutes link and an agenda link, and no transcript link; the same stop with an item id that does not exist gets no item link and a recording link whose `timed` is false; a stop on the hidden meeting gets no links at all and keeps its text; a stop on a meeting id that does not exist gets no links; a stop on the YouTube meeting gets a recording link whose address is the meeting's own; a `record: none` stop gets no links and carries its gap reason; a stop on a visible meeting that belongs to a different municipality gets no links; a stop whose item has the `external_id` `event-2693-11` gets a recording link whose `timed` is false and whose address carries no `meta_id`; and a journey with a recorded stop and a `record: none` stop at the same path stop has that key in `reached` and not in `not_in_record`. `tests/web/test_how_it_works_page.py` gains: the page contains "Parking fines ordinance", the words "Did Not Receive Unanimous Consent", the text "not in the record" at least three times, and `?journey=nope` returns 404. It also gains the one test that runs the link markup: insert under Birmingham a meeting with the explicit id 2238 (date 2026-06-02, an agenda address, a minutes address, and a Granicus `MediaPlayer.php` `video_url`) and an agenda item with the explicit id 59026 in it whose `external_id` is `371088`, in the manner of `tests/web/test_meeting_recordings.py`, and delete both afterwards; assert the response contains links to `/al/birmingham/meetings/2238/` and `/al/birmingham/items/59026/`, a recording link containing `meta_id=371088` with the words "at this moment", the minutes address and the agenda address. If the throwaway database already holds either id, the insert fails loudly; use the ids the journey file cites, not others, because the page reads them from the file.

### M4: Three further journeys, and switching between them

Scope: the remaining journeys from section 6 of the design, and a picker that swaps the journey in place.

Write three more files under `content/how-it-works/birmingham/journeys/`, from the three further tables in section 6: `rezoning-huffman-road.yaml` (label "A rezoning with a split recommendation", six stops: `submitted` as `record: none`, the submission date not being published; the Zoning Advisory Committee stop as `record: none` attached to `committee`; the Planning and Zoning Committee on 2026-09-08, attached to `committee`; the hearing set on 2026-09-15, attached to `[agenda, first_reading]` because the item is marked `[First Reading]`; the public hearing and final vote on 2026-10-13, attached to `[hearing, final_vote]`, `record: video`; and one `record: none` stop attached to `[mayor, in_effect]`); `liquor-licence-legion-field.yaml` (label "A liquor licence with a hearing", five stops: `submitted` as `record: none`, saying the agenda names Councilor Tate, Chairman of the Public Safety Committee, as submitter and gives no date; the committee on 2026-09-22; `first_reading` as `record: not_on_route`; the hearing and vote on 2026-09-29, attached to `[agenda, hearing, final_vote]`, `record: video`; and one `record: none` stop attached to `[mayor, in_effect]`); and `consent-avondale-park.yaml` (label "A routine contract on consent", six stops: `submitted` as `record: none`; the committee on 2026-10-12; `first_reading` as `record: not_on_route`; the consent agenda on 2026-10-20, attached to `[agenda, consent]`, saying in the design's words that consent items pass on one motion for the group; `final_vote` as `record: none`, because no vote is linked to the item and the minutes are not published; and one `record: none` stop attached to `[mayor, in_effect]`). The `not_on_route` reason in both files is "The agenda does not mark this resolution as a first reading." Where `content/how-it-works/birmingham/sources/` holds the text of the committee minutes a stop quotes, give the stop that `source_file`; where it does not, the quotation is copied from the design and is not machine-checked. Do not cite item 62832 or meeting 2613 anywhere; the design explains why. File-name order decides the picker's order, so prefix the four files `1-` to `4-` with parking fines first; the journey key inside each file does not carry the prefix.

Move the `how-it-works-journey` container into `src/docket/web/templates/partials/how_it_works_journey.html`, included by the page. Inside the partial the order is fixed: the picker, the selected journey's label, note and title, the path, the timeline. The picker is one link per journey, each to `?journey=<key>`, the current one marked with `aria-current="true"`. Give each link `hx-get` of the same address, `hx-target` of the journey's container, `hx-swap="outerHTML"` and `hx-push-url="true"`, and have the route return only the partial when the request carries the `HX-Request` header and not `HX-History-Restore-Request`, setting `Vary: HX-Request` on the response, exactly as `meeting_transcript` in `src/docket/web/public.py` does. The partial includes the picker and the path, so the path's reached marks change with the journey. Without JavaScript the links load the full page with the journey selected.

Tests in `tests/web/test_how_it_works_page.py` gain: the page lists four picker links in the order parking fines, rezoning, liquor licence, consent; `?journey=rezoning-huffman-road` returns 200 and contains "NOT Recommended by the ZAC" and "from the video"; `?journey=liquor-licence-legion-field` contains "Lack of Quorum"; `?journey=consent-avondale-park` contains "Consent Agenda"; in every journey's response the picker comes before the path's `<ol>` and the path before the first timeline card; the liquor-licence and consent responses contain "not on this item's route" and the parking-fines response does not; for every journey, each of the seven main stops carries one of the three marks; a request with the header `HX-Request: true` returns a body that does not contain `<html` and does contain the journey's label; and no response contains "62832".

### M5: Write it down

Scope: the documents that describe the behaviour, and the record of what was deferred. No code changes.

Write `docs/specs/how-it-works.md` in the present tense: what the page shows, where its content lives, the content and journey formats, the quotation check, what a journey may and may not state, how links degrade, and how to add a journey or correct a rule (edit the YAML, re-read the source, update the source copy and its read date in `content/how-it-works/birmingham/sources/README.md`, run `./tools/verify`). Add it to `docs/specs/index.md`. Add a row for the page to the table in `docs/birmingham/06-reader-surfaces.md` and a line to the Map in `AGENTS.md` only if it stays under the length that file sets for itself. Graduate to `docs/decisions/` the Decision Log entries that outlive this plan (content as checked-in data with no language model; a journey states facts and resolves only links; the quotation check), each numbered by the rule in force: the lowest number above every one spent on `origin/main` and on any open pull request at that moment. Add rows to `docs/DEBT.md`, numbered by the same rule for debt ids: the seven open questions of the design's section 3 that need the City Clerk or a browser, with "an answer is obtained" as trigger; the two video-read tallies to be re-checked against the minutes, with "the minutes for 2026-09-29 and 2026-10-13 are published" as trigger; and the operator's post-merge steps listed in Validation and Acceptance, with "the pull request merges" as trigger. Do not move this plan to `plans/completed/` and do not write the closing retrospective; the retro stage does both.

## Concrete Steps

Work from the root of the checkout the plan is executed in, with that checkout's own `venv/`. The only test command is the verify command; it builds its own throwaway database.

    ./tools/verify

At authoring, `tools/check-plans plans/active/how-it-works-explainer.md` was run on this file and printed:

    plans: plans/active/how-it-works-explainer.md ... ok (Progress, Surprises & Discoveries, Decision Log, Outcomes & Retrospective)
    plans: 1 of 1 ok

To look at the page while building (M2 onward), with a local database that has the migrations applied:

    venv/bin/flask --app docket.web:create_app run

and open `http://127.0.0.1:5000/al/birmingham/how-it-works/`. The local database has no Birmingham meetings, so journey stops render their text with no links; that is the degraded state working, not a failure. Links are proved by the service test in M3.

Each milestone ends with `./tools/verify` passing, the plan's living sections updated with what was observed, and a commit.

## Validation and Acceptance

M1 is accepted when `./tools/verify` exits zero and its summary line for `unit+web+services` reports passed; when the same run, with the quotation of one rule in `content/how-it-works/birmingham/explainer.yaml` temporarily altered by one word, fails in `tests/unit/test_how_it_works_content.py` naming that rule (restore the file afterwards and record both observations); and when `ls docs/superpowers/specs/2026-11-12-how-it-works-sources` reports no such directory while `ls content/how-it-works/birmingham/sources/README.md` finds the file.

M2 is accepted when `./tools/verify` exits zero, and when, with the dev server running, `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5000/al/birmingham/how-it-works/` prints `200`, the same for `/al/mobile/how-it-works/` prints `404`, and `curl -s http://127.0.0.1:5000/al/birmingham/how-it-works/ | grep -c 'href="https://'` prints a number at least as large as the number of rules in the explainer file (every rule's citation is a link).

M3 is accepted when `./tools/verify` exits zero; when `curl -s 'http://127.0.0.1:5000/al/birmingham/how-it-works/?journey=parking-fines' | grep -c 'not in the record'` prints 3 or more; and when `?journey=nope` returns `404`.

M4 is accepted when `./tools/verify` exits zero; when each of the four journey addresses returns `200`; when `curl -s -H 'HX-Request: true' 'http://127.0.0.1:5000/al/birmingham/how-it-works/?journey=consent-avondale-park' | grep -c '<html'` prints `0`; and when `grep -rn 62832 content/how-it-works` prints nothing.

M5 is accepted when `./tools/verify` exits zero, `docs/specs/how-it-works.md` exists and is listed in `docs/specs/index.md`, `docs/birmingham/06-reader-surfaces.md` has the page's row, and `docs/DEBT.md` has the rows named in M5.

After the pull request merges, the operator, not a milestone session: deploys the `docket-web` service from a clean `main` with `scripts/deploy.sh --service docket-web`; opens `https://docket.pub/al/birmingham/how-it-works/` and each of the four journeys; and confirms on each that every pill opens the city's document, the meeting page, the item page, or the recording, and that the 2026-06-02 "Recording" pill for the parking-fines journey opens at the item (chapter id 371088, or YouTube at the converted second). A pill that is missing where section 6 of the design names a record means a row has changed since 2026-11-12; record it as an issue with the journey and stop names.

## Idempotence and Recovery

Every step adds files or edits templates and can be repeated. The move of the sources directory in M1 is a `git mv`; if it is interrupted, `git status` shows which files moved, and repeating the command for the rest completes it. Nothing in this plan writes to any database outside the tests' throwaway one, and nothing calls an external service. If application start fails with an `ExplainerError` after a content edit, the message names the file and key; fix the YAML and restart. To back the whole change out, revert the branch; no data migration exists to undo.

## Artifacts and Notes

Production rows the journeys cite, read on 2026-11-12 (read-only), for the operator's post-deploy check. Meetings, all visible: 3142 (2026-05-11, Transportation and Infrastructure Committee, YouTube `MiL1mYay0eQ`), 2232 (2026-05-19), 2237 (2026-05-26), 2238 (2026-06-02), 3172 (2026-09-08, Planning and Zoning Committee, YouTube `Gcis1bbt6RI`), 2487 (2026-09-15), 3179 (2026-09-22, Public Safety Committee, YouTube `w2VWq71DYqY`), 2536 (2026-09-29), 3183 (2026-10-12, Budget and Finance Committee, YouTube `8k-12tMVeHk`), 2609 (2026-10-13), 2624 (2026-10-20). Council meetings 2232, 2237 and 2238 have minutes addresses; 2487, 2536, 2609 and 2624 did not yet. Public transcripts existed for 2232, 2237, 2238, 2487, 2536 and 2624, and not for 2609 or any committee meeting. Items, with chapter id and cue second: 58893 (370353, 2506), 58990 (`event-2693-11`, no cue), 59026 (371088, 5313), 61883 (376794, 3320), 62781 (378506, 2662), 62035 (377825, 872), 62911 (379037, 1714).

## Interfaces and Dependencies

No new dependency. YAML is read with `yaml.safe_load`.

`content/how-it-works/<slug>/explainer.yaml`:

    city: birmingham
    sources_read: 2026-11-12
    stops:
      - key: committee
        name: Committee
        side_route_of: null        # or the key of the stop it hangs under
        description: one sentence
        rules:
          - statement: plain words
            quote: exact words from the source, or omitted
            citation: General Code §2-2-14(b)
            url: https://…
            source_file: general-code-title-2-chapter-2.txt   # required when quote is present
    open_questions:
      - heading: short
        body: one paragraph

`content/how-it-works/<slug>/journeys/<n>-<key>.yaml`:

    key: parking-fines
    label: Parking fines ordinance
    note: one line
    title: the item's title, quoted from the agenda
    stops:
      - stops: [first_reading]     # one or more stop or side-route keys from explainer.yaml
        date: 2026-05-26           # omitted when record is none or not_on_route
        record: minutes            # minutes | agenda | video | transcript | committee_minutes | none | not_on_route
        text: what the record shows, in plain words
        quote: exact words, or omitted
        source_file: committee-….txt   # optional; when present the quote is checked against it
        meeting_id: 2237           # omitted when record is none or not_on_route
        item_id: 58990             # optional
        seconds: 2506              # optional; the cue on the meeting's own clock
        document:                  # optional; a city document the site does not hold a link to
          label: Committee minutes
          url: https://…
        gap: why there is no record   # required when record is none or not_on_route

Every one of the seven main stops must appear in at least one journey stop's `stops`.

In `src/docket/services/how_it_works.py`:

    class ExplainerError(ValueError): ...

    @dataclass(frozen=True)
    class Rule:
        statement: str
        quote: str | None
        citation: str
        url: str
        source_file: str | None

    @dataclass(frozen=True)
    class Stop:
        key: str
        name: str
        side_route_of: str | None
        description: str
        rules: tuple[Rule, ...]

    @dataclass(frozen=True)
    class JourneyStop:
        stops: tuple[str, ...]       # at least one
        date: date | None
        record: str
        text: str
        quote: str | None
        source_file: str | None
        meeting_id: int | None
        item_id: int | None
        seconds: int | None
        document_label: str | None
        document_url: str | None
        gap: str | None

    @dataclass(frozen=True)
    class Journey:
        key: str
        label: str
        note: str
        title: str
        stops: tuple[JourneyStop, ...]

    @dataclass(frozen=True)
    class Explainer:
        city: str
        sources_read: date
        stops: tuple[Stop, ...]
        open_questions: tuple[tuple[str, str], ...]
        journeys: tuple[Journey, ...]      # empty until M3

    def load_explainer(city_dir: Path) -> Explainer: ...
    def normalise_for_quote_check(text: str) -> str: ...

    @dataclass(frozen=True)
    class StopLinks:
        meeting_url: str | None      # the site's meeting page
        item_url: str | None         # the site's item page
        recording: VideoLink | None  # docket.services.video_links.VideoLink
        transcript_url: str | None   # the site's transcript page
        minutes_url: str | None      # the city's document
        agenda_url: str | None       # the city's document

    @dataclass(frozen=True)
    class ResolvedStop:
        stop: JourneyStop
        links: StopLinks

    @dataclass(frozen=True)
    class ResolvedJourney:
        journey: Journey
        stops: tuple[ResolvedStop, ...]
        reached: frozenset[str]          # path stop keys with a recorded event
        not_in_record: frozenset[str]    # keys named by a record-none stop, less reached
        not_on_route: frozenset[str]     # keys named by a not_on_route stop, less the two above

    def resolve_journey(journey: Journey, municipality_id: int, city_slug: str) -> ResolvedJourney: ...

`resolve_journey` builds site addresses as plain paths (`/al/<city_slug>/meetings/<id>/`, `/al/<city_slug>/items/<id>/`, `/al/<city_slug>/meetings/<id>/transcript/`) so that the service does not import Flask; a service may not import from `src/docket/web/` (`ARCHITECTURE.md`, layer map). The recording link is `video_links.link_for(video_links.for_meeting(meeting_id), seconds=stop.seconds, chapter_id=item.external_id if the item resolved else None)`. `link_for` itself ignores a chapter id that is not all digits.

In `src/docket/web/public.py`:

    @bp.route("/al/<slug>/how-it-works/")
    def how_it_works(slug): ...

Templates: `src/docket/web/templates/how_it_works.html`, and from M4 `src/docket/web/templates/partials/how_it_works_journey.html`. Styles: `src/docket/web/static/css/how_it_works.css`. Jinja global: `has_how_it_works(slug) -> bool`.

Revision note, 2026-11-13 (M1 session): the sentence in Context and Orientation that locates the saved source texts now gives their new directory, because M1 moved them and a later session reading the old path would find nothing there.
