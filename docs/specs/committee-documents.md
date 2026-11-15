# Committee documents: what a council committee took up, and what it did

A city whose council committees post their agendas and minutes as PDFs on pages of the city's website has those documents listed, fetched, read by fixed rules, stored, and attached to the committee meeting each records; the meeting's page then links the city's PDFs and lists what the committee took up, in the minutes' own words. Only Birmingham has such pages configured. Present tense; the plan that built this is plan `committee-documents`. This file owns the source pages, how a document's committee, date and kind are decided, the item rules and the category list, storage, attaching and creating, what the meeting page shows, the daily task and the operator's script, and how a misread is corrected. Why the documents have tables of their own is decision `0095`; why a document's own first lines outrank its listing is `0096`; why items come from minutes only and only minutes create a meeting is `0097`; why an action is its own words and a category, never a vote, read by rule and by no language model, is `0098`. The rest are cited where they bind.

## Terms

A **committee page** is one page of the city's website listing one standing committee's agenda and minutes PDFs. A **listing** is one PDF link on such a page, with the date heading it sits under and the name the page shows for it. A **document** is one PDF. Its **header** is its first lines, which print the committee's name, the meeting's date and, for minutes, the single word MINUTES. A **heading line** inside a document begins with a number, Roman numeral or letter followed by a full stop or closing bracket (`VI.`, `4)`, `a.`). An **action** is the text after a line beginning "Action Taken". An **item** is one thing the committee took up: the lines before an action, and the action.

## The source pages

The pages are configured per city in `municipalities.metadata.committee_document_pages`, a JSON list of `{"committee": <canonical name>, "url": <page address>}`. Migration 045 sets it for Birmingham to eight entries, one per name in `BIRMINGHAM_COMMITTEES` (`src/docket/services/meeting_types.py`), at `https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/<slug>`; the slugs are `COMMITTEE_SLUGS` in `src/docket/adapters/committee_documents.py`. The address carries the council term and will change (`D135`). A city without the key is not read.

`src/docket/adapters/committee_documents.py` fetches and parses and never touches the database; `src/docket/services/committee_documents.py` owns every read and write. `fetch_page` and `fetch_pdf` share one gap of at least a second between requests, across the city's site and its Amazon bucket alike, with a browser user agent and a 60 second timeout. `fetch_page` raises on failure. `fetch_pdf` returns None when the request fails, when the body passes 40 MB, and when it does not begin `%PDF-`.

A page holds its listings in its `__NEXT_DATA__` JSON as strings of HTML. `parse_committee_page` reads each `<h4>` as a date heading and each `<article class="media--type-document">` as a listing (its `file` attribute the address, its `name` attribute the listed name, the nearest `<h4>` before it the heading), keeps an address once per page, and keeps only addresses that begin `https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/` or `https://www.birminghamal.gov/` and end `.pdf`. A page with no such block gives an empty list and a logged warning.

## What a document is

A document's committee, date and kind are read from its own header; the page it is listed on, the heading it is listed under and its listed name are the fallback, used only for a fact the header does not give (`0096`).

- **Text.** `extract_text_from_pdf` (`src/docket/analysis/minutes_parser.py`) extracts it. Fewer than 200 non-space characters (`MIN_TEXT_CHARS`) is a scanned image: status `no_text`, no text stored, facts from the listing alone.
- **Header** (`read_header`). The non-empty lines before the first heading line, at most the first 20. A header containing `REGULAR MEETING OF THE COUNCIL` is not a committee document: status `not_committee`, the text stored, no facts. A text with no header line at all, because its first non-empty line is a heading line, is stored the same way and takes nothing from its listing (`D144`).
- **Committee** (`committees_named`). One pattern per committee, tested against upper-cased text: `ARTS`; `BUDGET`; `COMMITTEE OF THE WHOLE` or `GOVERNMENTAL AFFAIRS`; `COMMUNITY DEVELOPMENT`; `ECONOMIC`; `PLANNING`; `PUBLIC SAFETY`; `TRANSPORTATION`. A header may name several (a joint meeting), in the order found. When it names none, the committee is the page's. The same function, through `committee_of`, reads a meeting row's `body_name`, and gives a committee only when exactly one is named; `same_committee` in `meeting_types.py` is not used here (`0099`). The bare `ARTS` is found inside other words (`D141`).
- **Date** (`read_date`). The first month word (3 to 12 letters, known by its first three, so "SEPTEBMBER" is September, and beginning at a word's beginning), a day from 1 to 31 that may carry `st`, `nd`, `rd` or `th`, may follow the month with no space, and is not the start of a longer number, and an optional year: four characters, each a digit or the letter O, that with O read as zero begin `19` or `20`. The header is read line by line. A header date with a year is the date (`date_source` `header`). A header month and day with no year take the heading's year when the heading's month and day are the same, else there is no date. A header with no date takes the heading's date when it has a year. A date that is no day of the calendar is no date.
- **Kind.** `minutes` when some header line is exactly `MINUTES`; otherwise `agenda` when there is a header; with no text, `minutes` or `agenda` by which word the listed name contains, else none.
- **Flags.** `special` and `work_session` when the header contains `SPECIAL CALLED` or `WORK SESSION`. `listing_disagrees` when the header and the heading both give a full date and they differ, or the header names a committee and none it names is the page's.

## Items

Items come from minutes only; an agenda is stored and linked and its items are not read (`0097`, `D132`). `parse_minutes_items` reads minutes text as follows.

The lines after the header lose every line that is `Page N of M`, is "FULL TRANSCRIPTION AVAILABLE UPON REQUEST" (either in any case), or repeats a header line. `present` is what follows "Councilor(s) Present" on the first header line that begins with it, in any case.

An action begins at a line matching `^Action Taken\s*:?` in any case. Its stretch runs to the next heading line or "Action Taken" line. The action ends at the first line after which the joined text ends with an outcome ending, extended by one or two further lines when the joined text still ends with an outcome ending that begins at the same word. The outcome endings are `_OUTCOME_ENDINGS` in the adapter: an item recommended to the city council (with its consent, lack-of-quorum, no-recommendation, deny and approval forms), forwarded to the council agenda with or without a recommendation, "No Action – Information Only", "Item Withdrawn", "Item Tabled", "Item Delayed", "Minutes were Approved", "Meeting Adjourned", in the minutes' own spellings. With no ending in the stretch, the action is the whole stretch when a heading line or the end follows, and the lines through the first that ends with a full stop (or the first line) when another action follows. Lines after the action's end begin the next item; lines after the last action belong to no item and are counted as `trailing_lines`.

An item is the lines since the previous action's end and the action. Its heading is the last heading line among its lines (`owns_heading` true) or the most recent one before it. A heading that one action answers names its item, with no group; a heading that several actions share is each item's `group`, and each item is named by its first body line. The body is the item's lines that are not heading lines. An item with no line and no heading has the empty name; an "Action Taken" with no words is an item with an empty action and the category `other`.

`moved_by` and `seconded_by` are the surname in `Councilor[ Pro Tem| President] <Surname> Motioned` and `... Seconded`, matched in that case, each absent when the minutes do not print it. `action_category` is the first of these found anywhere in the action's text, in any case, in this order:

| Category | Pattern |
| --- | --- |
| `minutes_approved` | `minutes were approved` |
| `recommended_no_quorum` | `recomm\w*.*lack of quorum` |
| `recommended_deny` | `recommendation to deny` |
| `no_recommendation` | `(?:with\s+(?:a\s+)?no\|without\s+a)\s+recommendation` |
| `recommended_consent` | `recomm\w*\s+to\s+the\s+city\s+council\s+consent` |
| `recommended` | `recomm\w*\s+(?:item\s+)?to\s+the\s+city\s+council` |
| `information_only` | `no\s+action\s*[–-]\s*information` |
| `withdrawn` | `\bwithdrawn\b` |
| `tabled` | `\btabled\b` |
| `delayed` | `\bdelayed\b` |
| `adjourned` | `\badjourned\b` |
| `other` | none of the above; the words are kept |

A committee's minutes record a motion and a second, not a roll call, so nothing here is stored or shown as a vote, a tally, "passed" or "failed" (`0098`).

## Storage

Migration 045 creates two tables. `committee_documents` holds one row per listed PDF, unique by `(municipality_id, url)`: the listing (`page_url`, `page_committee`, `listed_name`, `listed_heading`, `first_seen_at`, `last_seen_at`), the fetch (`status`, `fetched_at`, `fetch_attempts`, `pdf_sha256`), the text, the facts (`kind`, `committees`, `meeting_date`, `date_source`, `listing_disagrees`, `special`, `work_session`, `present`, `trailing_lines`, `parser_version`), and the meeting (`meeting_id`, set to NULL when its meeting is deleted, and `attached_by`, `matched` or `created`). `status` is `listed`, `read`, `no_text`, `not_committee` or `fetch_failed`. `committee_items` holds a minutes document's items, unique by `(document_id, position)`, numbered from 1, deleted with their document, with `action_category` held to the list above by a CHECK. The PDF itself is not kept; its sha256 is.

Nothing is written to `agenda_items`, `votes`, `meetings.agenda_url` or `meetings.minutes_url`, so the AI stages, the money list, item search, member pages and vote counts do not see a committee item (`0095`). Committee items are therefore not in search and have no page of their own (`D134`).

- `sync_listings(municipality_id, pages)` inserts a new address with status `listed` and, for a known one, updates `last_seen_at`, `listed_name` and `listed_heading` only. A page that cannot be fetched, or that yields no listing, is logged and skipped; the call raises `RuntimeError` only when every configured page failed (`0102`).
- `read_pending(municipality_id, limit)` takes rows that are `listed`, or `fetch_failed` with fewer than three attempts (`MAX_FETCH_ATTEMPTS`), oldest first, up to `limit` rows tried. A PDF that does not arrive, cannot be opened, or cannot be stored is logged, marked `fetch_failed` and counted as an attempt, and the rows after it are still read. One transaction per document.
- `reparse(municipality_id)` reads stored text again, with no fetch, for every row whose `parser_version` is below `PARSER_VERSION`. Every reading writes every fact column and replaces the document's items.

## Attaching, and creating a meeting

`attach(municipality_id, today)` considers each document that is `read` or `no_text`, has a kind, a date and a committee, and has no meeting, minutes before agendas and the lowest id first. Its candidates are the city's visible meetings of that date typed `committee` whose `body_name` names, alone, one of the document's committees. One candidate: attached, `matched`. Several: those for the document's first-named committee if any, then a row with a `video_url`, then the lowest id; counted as ambiguous. None: minutes whose date came from their own header and is not after `today` create a meeting and attach as `created`; anything else waits and is tried on every later run, so an agenda attaches once its meeting exists. An agenda alone never creates a meeting (`0097`).

A created meeting has `external_id` `cdoc-<slug>-<yyyy-mm-dd>`, the slug being the first-named committee's page slug without its trailing `-committee` (`cdoc-budget-finance-2026-10-12`); a title of the committee's canonical name and " Committee Meeting", or " Committee Work Session", with "Special Called " in front when the header says so; the classification `classify_title` gives that title, with `type_source = 'title'`; `source_url` the committee's page; and no agenda, minutes or video address. When a row already holds that `external_id`, nothing is made and the document attaches to it as `matched`. What the YouTube pass does with a `cdoc-` row when the meeting's recording arrives later is not tested: its `_is_granicus` (`src/docket/services/youtube_meetings.py`) takes every row whose `external_id` does not begin `yt-` for a Granicus clip, a `cdoc-` row among them (`D136`). A `yt-` row that already names the committee on that day is an ordinary candidate, so minutes posted after the recording attach to it and make no `cdoc-` row.

A document that has a meeting is never moved or detached by `attach`, whatever a later reading makes of it (`0100`); to re-attach on purpose, set `meeting_id` to NULL on the rows concerned and run `attach`. `primary_documents(meeting_id)` names a meeting's one document of each kind: those whose listing does not disagree first, then the lowest id. `AttachReport` counts the call's own work (`matched`, `created`, `ambiguous`, `unattached_agendas`, `unattached_minutes`) and lists `crowded_days`: a created meeting's date on which the city also has more than one visible Granicus meeting typed `council`, the sign of a committee clip mislabelled as the council's.

## What the meeting page shows

`meeting_detail` in `src/docket/web/public.py` calls `for_meeting(meeting_id)`, which is None for a meeting with no attached document that has a kind. Otherwise `partials/committee_record.html` is rendered as its own section directly after the hero, in this order:

- "From the committee's own documents" and one link per document, primaries first, then agenda before minutes: "Agenda (PDF)" or "Minutes (PDF)", opening the city's address in a new tab. A further document of a kind is marked "another copy"; one with no text, "scanned image; not read" (`D133`).
- When the meeting has minutes: "Councilors present: " and the minutes' list, when they give one; then, when the minutes hold an item, "What the committee took up" and the items as an ordered list in the minutes' order. An item shows its group once, before the first item of the list that has it; its name; its body, unaltered, inside a closed "What the minutes say" (left out when empty or only the name again); "Moved by X, seconded by Y", or the one the minutes give; the category's label; and the action's words in a quotation introduced by "The minutes record:", whose `cite` is the minutes' address. Items that are `minutes_approved` or `adjourned` come last under a closed "Procedural", with no label. Scanned minutes have their link and its note and nothing else.
- When there are no minutes: "docket.pub has no minutes for this meeting. The agenda shows what was planned; it does not show what the committee did."
- Always: "A committee recommends; it does not decide. No committee action is final without a vote of the full council."

The labels: `recommended` "Recommended to the council"; `recommended_consent` "Recommended to the council's consent agenda"; `recommended_no_quorum` "Sent to the council by the chair; no quorum"; `no_recommendation` "Sent to the council with no recommendation"; `recommended_deny` "Sent to the council with a recommendation to deny"; `information_only` "Information only; no action"; `withdrawn` "Withdrawn"; `tabled` "Tabled"; `delayed` "Delayed"; `other` has no label and shows its quoted words only.

The body is printed as the minutes give it (`0101`): a meeting's first item opens with the call to order, and an item named by its first line repeats that line.

In the hero's strip, when the record has an item and the meeting has no `agenda_items`, the first figure reads "Items in the minutes" with the count of items that are not procedural, and the "Votes" figure's second line reads "committees record motions, not roll calls". The third figure is unchanged and reads "$0" (`D140`). A meeting with no committee document, and every council meeting, is as it was. The page reads the tables on each request and caches nothing.

## The daily task and the operator's script

`refresh_city(municipality_id, metadata, today, read_limit)` runs `sync_listings`, `read_pending`, `reparse` and `attach` in that order. `refresh_all(today)` runs it, with `DAILY_READ_LIMIT` (25) documents, for every active city that names its pages; a city that fails is logged, the next is run, and the call raises after the last so the task reports a failure (`0102`). The worker task `committee_documents` calls it daily, scheduled in `src/docket/worker/scheduler.py` after `youtube_ingest`, so a new document finds the day's recording; its health variable is `HEALTHCHECK_COMMITTEE_DOCUMENTS_UUID`. `docs/runbooks/cron-worker.md` is how it is operated.

`scripts/backfill_committee_documents.py --city <slug> [--dry-run] [--limit N]` is the one-time fill: the same four steps with no read limit unless `--limit` is given, through `backfill` in the service, which also reads what the script prints: documents by status and kind; how many dates came from the header and from the heading, and how many listings disagree; items by category; the attach report; the meetings created; and, per committee, for visible committee meetings dated 2026-01-01 or later whose `body_name` names that committee alone, how many there are and how many have an agenda, minutes, items, a document and no video, and a video and no document.

With `--dry-run` everything is fetched and read on one connection that is rolled back at the end, so the output is what a real run would do and nothing is written (`0103`). A dry run is for a script only: its switch is a module global, and neither the web process nor the worker calls `backfill`. On a database migration 045 has not reached, a dry run makes the two tables inside its transaction and says so; until it ends, writes to `meetings` and `municipalities` wait, so it is run before 04:00 or after 11:15 America/Chicago. A real run on such a database, an unknown city, and a city that names no pages each print an error and exit 1.

## Correcting a misread

Fix the rule in `src/docket/adapters/committee_documents.py` with a test on a fixture under `tests/fixtures/committee_documents/`, raise `PARSER_VERSION` in the service, and deploy. The next daily run's `reparse` reads every stored text again without fetching, rewrites each document's facts and replaces its items. It does not move a document already attached (`0100`). A document that is `no_text` has no stored text and is not read again.

To remove the source: `DELETE FROM meetings WHERE external_id LIKE 'cdoc-%'` for the city, then roll migration 045 back, which drops both tables and the metadata key.

## Not built

Agenda items are not read (`D132`). Scanned documents are linked and not read (`D133`). Committee items are not in search and have no page (`D134`). No amount is read from a committee item (`D140`). A meeting row that has a `minutes_url` of its own and committee minutes shows two links, "Official minutes" in the source rail and "Minutes (PDF)" in the record.
