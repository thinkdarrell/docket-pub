# What's coming up: meetings, scheduled hearings, and neighborhood meetings in one list

The page at `/al/<slug>/coming-up/` lists what a city has ahead of it in the next 60 days, in date order, in three kinds, each entry linked to the city document it came from or saying that docket.pub holds no link to one: the meetings the city's two sources list, the public hearings a resolution on a council agenda has set, and the neighborhood association meetings the city's published schedule gives a rule for. `/al/<slug>/coming-up.ics` returns the same entries as a calendar a program can subscribe to, one event per entry. Only Birmingham has either. This file owns the two addresses and their gate, the window, each kind's sources and rules and what an entry shows, the hearing reader and where hearings are stored, the schedule file and its loader, the feed, what `/al/<slug>/upcoming-hearings.rss` returns for a flagged city, and how each is checked. Why one hearing is told from another by its date, kind and subject is decision `0107`; why a hearing with no readable date is not shown is `0108`; why a meeting is merged, timed and marked cancelled as it is, `0109`; why a neighborhood date comes from the printed rule alone, `0110`; why hearings are read inside ingest, `0111`.

No language model reads anything here. A value a source does not give (a time, a place, call-in details, a hearing's date) is absent and never filled in (`docs/PRINCIPLES.md`, "Source or silence").

## Terms

An entry is one thing on the page: a meeting, a hearing, or one dated neighborhood meeting. A reading is what the hearing reader returns for one agenda item's title. The trigger is the phrase that makes a title a candidate. The subject is the text of a title after the hearing's date. An occurrence is one date a schedule rule produces. A flagged city is one whose metadata carries `"coming_up": true`.

## The gate and the window

A city has the page, the feed, the stored hearings and the new hearings feed when its `municipalities.metadata` carries the JSON value `true` under `coming_up`; migration 047 wrote it for Birmingham. `coming_up.is_coming_up_city(municipality)` in `src/docket/services/coming_up.py` owns the test for the web layer, and accepts the metadata as a dict or as JSON text; `hearings.refresh_recent` reads the same key with one SELECT of its own, because `coming_up.py` imports `hearings.py` and not the other way. For a city without the key the page and the feed answer 404, ingest's hearing step does nothing, the city page shows neither link, and the sitemap does not list the page. Removing the key turns all of it off without a deploy:

    UPDATE municipalities SET metadata = metadata - 'coming_up' WHERE slug = 'birmingham';

The window is today through today plus 60 days (`coming_up.WINDOW_DAYS`), both ends in America/Chicago, and it is the same for all three kinds. The page, the calendar feed and the flagged hearings feed are each built from one call of `coming_up.list_entries(municipality)`, so they cannot hold different entries. Every bound in that function's two statements and in its calls is computed from one `today` (the module function `_today()`, which a test replaces) and passed as a parameter; no statement reads the server's clock. Neither route accepts a date.

The result is ordered by date, then timed entries by their start before untimed ones, then kind in the order meeting, hearing, neighborhood, then title.

## An entry

`coming_up.Entry` is a frozen dataclass of sixteen fields: `kind` (`meeting`, `hearing` or `neighborhood`, the vocabulary `coming_up.KINDS`); `uid`; `on` (the date); `starts_at` and `ends_at` (datetimes in America/Chicago, or `None`); `title`; `detail` (a tuple of short lines); `links` (a tuple of `(label, url)` pairs, a city document's `url` its full address and a docket.pub page's a site path beginning `/`); `source_url` (the first city document, or `None`); `place`; `badge` and `badge_label` (the token and the words of its label); `cancelled` and `cancelled_by`; `attend` (a tuple of `(label, text)` pairs); and `association` (a neighborhood meeting's association slug, else `None`).

The labels, by token: `meeting` "Meeting"; for a hearing by its kind, `zoning` "Zoning", `weed-lots` "Weed lots", `vacation` "Street or right-of-way", `budget` "Budget", and `hearing` "Hearing" for the kind `other`; `neighborhood` "Neighborhood". An eighth token, `cancelled` "Cancelled", belongs to the page alone and is a second label on a cancelled entry. No kind's label is larger, bolder or placed differently from another's: which hearing matters is the reader's judgement.

## Meetings

Two sources. The council's video site: rows of `meetings` for the city with `external_id LIKE 'event-%'` (a meeting the site lists and has not yet recorded), `is_hidden = FALSE`, and `meeting_date` in the window. The city calendar: rows of `city_calendar_events` (`docs/specs/meeting-types.md`, "The city calendar", owns how the table is filled) whose `starts_at`, converted to America/Chicago, falls on a date in the window, kept only when `meeting_types.classify_event(title)` reads the title as a council or committee meeting, which drops the department's giveaways and anything else that is not a meeting.

Pairing. A row and an event are one meeting when the row's `calendar_event_id` is the event's id; when two rows name one event, the row with the lower id is merged and the other stands alone. Then, among what is left, a row whose `meeting_type` is `council` and an event that classifies as `council` on the same Chicago date are one meeting when each is the only such unpaired one that day. Everything else stands alone, so two council events and one council row on one day are three entries. A hidden row is absent, and its calendar event then stands alone.

What a meeting entry shows. The title is `adapters._helpers.label_for` over the row's `meeting_type`, `session_kind`, `body_name` and title, or over the event's classification for an event alone, always with `cancelled=False`, so a title never carries "(cancelled)"; a committee the calendar alone lists is titled by its body name ("Budget and Finance"). The day and the time are the calendar event's when there is an event (its `starts_at` and `ends_at`), and otherwise the row's `meeting_date` and `start_time`, with no time when `start_time` is NULL. The links are "City calendar" to the event's `source_url` when there is an event, "Agenda" to the row's `agenda_url` when there is a row with one, and "Meeting on docket.pub" to the meeting's page when there is a row. `source_url` is the event's page, else the row's `agenda_url`, else `None`. The UID is `calendar-<event id>@docket.pub` when there is an event and `meeting-<meeting id>@docket.pub` otherwise. `attend` is empty: no stored source gives call-in details for a council or committee meeting.

Cancellation. A meeting a source calls cancelled is shown, marked, with the source named; it is never left out. The row says cancelled when its title does (`query.is_cancelled_title`). The event says so when it is not live (`meeting_types._is_live`: a stored status other than NULL or `active`, or a title that says cancelled). `cancelled` is true when either says so, and `cancelled_by` names each that does, the row first: "the council's video site", "the city calendar". The entry's `detail` then opens with one sentence, "Cancelled, according to the city calendar." (or "the council's video site", or "the council's video site and the city calendar"). One exception: when the event is not live only because its stored status is a word other than `cancelled` or `canceled` (compared lower-cased) and neither title says cancelled, the sentence is `The city calendar marks this "<status>".` with the status as stored, since docket.pub does not know that the word means cancelled. When the entry is a pair and only one of its two sources says so, a second sentence follows: "The council's video site still lists it." or "The city calendar still lists it." Nothing else about a cancelled entry changes. A hearing and a neighborhood meeting are never `cancelled`.

## Scheduled hearings

### The reader

`src/docket/enrichment/hearings.py` imports the standard library only. `read_hearing(title)` reads an agenda item's `title` and never its `description`, and returns a `HearingReading` (`hearing_date`, `kind`, `subject`, `subject_key`, `property_count`) or `None`. Its rules, in order:

- The text is the title with every run of whitespace replaced by one space.
- The trigger is the first match, case ignored, of `\b(?:setting|to set|providing for) (?:a|the) public (?:show cause )?hearing\b`. No trigger, no reading. "resetting a public hearing" is not a trigger.
- A date is a month's full English name, a day of one or two digits, an optional comma, and a four-digit year; a date that is not a real day is no date. The hearing's date is found by the first of three forms that yields one: the date that follows the trigger at once, allowing a comma, spaces and the word "on" between; the first "on the <day><st|nd|rd|th> day of <Month>, <year>" after the trigger; the first date that follows the word "on" inside a clause that begins "to be held" after the trigger with no full stop or semicolon before the date. In the second and third forms only the first match is read.
- One correction: when the text holds "CHANGE HEARING DATE FROM <date> TO <date>" and the date found equals the first of the two, the hearing's date is the second.
- When no form yields a date, `hearing_date` is `None` and the reading is still returned, so a dry run can list it.
- The kind is the first that fits, on the whole text, case ignored: `weed_lots` when it contains "noxious or dangerous weeds"; `zoning` when it matches `zoning|zone district|rezon`; `vacation` when it matches `vacation of|closure of|right[- ]of[- ]way`; `budget` when it contains "budget"; otherwise `other`. `KINDS` in the reader owns the list, and the CHECK in migration 047 is its frozen copy.
- The property count is the integer in the first `(<digits>) properties`, or `None`.
- The subject is the text after the date when the date followed the trigger at once, and otherwise the text after the trigger. It is cut from where the first form matched, whatever the correction then did to the date.
- The subject key of a `weed_lots` reading with a count is `weeds:<count>`. Any other key is the subject with every `[...]` group removed, cut at the first "(Submitted by" or "(Recommended by", lower-cased, and reduced to the characters a to z and 0 to 9.

`same_hearing(key_a, key_b)` is true when the keys are equal, or when one begins with the other and the shorter is at least `PREFIX_MIN` (90) characters. The caller compares dates and kinds. `RULE_VERSION` is 1, and is stored on each hearing.

### What the reader does not read

A date that lies past the end of a stored title: titles ingested before about May 2026, and a few after, are cut at 255 or 256 characters and carry no description, so a weed-lot resolution of that period usually has no trigger in what is stored and eleven matched titles have no date. A hearing with no dated resolution setting it (a consent item marked as a hearing, a licence hearing). A hearing the council moved by a later resolution that does not carry the bracketed "CHANGE HEARING DATE" note, which stays on its first date. A reading with no date is not stored and not shown. `D158` in `docs/DEBT.md` lists these and the cases where two hearings are stored as one or one as two.

### Storage

Migration 047 creates `public_hearings` (`id`, `municipality_id`, `hearing_date`, `kind`, `subject`, `subject_key`, `property_count`, `rule_version`, `created_at`, `updated_at`; unique on city, date, kind and key) and `public_hearing_items` (`agenda_item_id` as the primary key, `hearing_id`), so an agenda item belongs to at most one hearing and a hearing has a link to every item that set it. `src/docket/services/hearings.py` owns every statement on the two tables.

- `find_readings(municipality_id, since, until=None)` runs one SELECT of the city's agenda items in meetings dated from `since` (to `until`) whose title matches `public\s+(show\s+cause\s+)?hearing`, and returns, in item-id order, `item_id`, `meeting_id`, `meeting_date`, `title` and `reading` for each item the reader reads. It reads neither hearings table.
- `group_readings(rows)` is pure. It takes the dated rows longest key first. A row joins the group of its date and kind whose key equals its own; failing that, the one group of its date and kind whose key begins with its own, when its own key is at least 90 characters and there is exactly one such group; otherwise it starts a group. Groups come back ordered by hearing date and then lowest item id.
- `refresh_hearings(municipality_id, since, until=None)` calls the two and then, in one transaction, matches groups to the stored hearings of the same date and kind (equal keys first, then the one stored hearing `same_hearing` accepts), inserts a hearing for each group left over, lengthens a matched hearing's subject and key when the group's is longer, upserts every link in one statement, deletes in one statement the link of every item of the run's range of meeting dates that was given no dated reading, and deletes in one statement the city's hearings left with no link. It returns a `HearingReport` (`matched`, `dated`, `undated`, `hearings`, `created`, `linked`); `created` is 0 on a repeated run and `linked` counts every dated item each time.
- `refresh_recent(municipality_id)` returns `None` for a city without the flag and otherwise refreshes the last 120 days of meetings (`RECENT_DAYS`).
- `list_upcoming(municipality_id, start, end)` returns the hearings dated in the range that have at least one visible link, each with its items oldest meeting first. A link is visible when its meeting is not hidden, its meeting's title does not say cancelled (`query.CANCELLED_PREDICATE_MT`), and the item's `processing_status` is not `withdrawn` (a NULL status counts as not withdrawn).

Hearings are kept current by stage 3c of `ingest_municipality` in `src/docket/services/ingest.py`, which calls `refresh_recent` after the meeting-type stage, logs `Hearings: matched=<n> dated=<n> undated=<n> hearings=<n> created=<n> linked=<n>` at INFO, and on a failure appends "Hearings: ..." to the ingest result's errors and stops nothing. There is no worker task for it. The backfill of older meetings is `scripts/backfill_hearings.py`; `docs/specs/operations.md`, "Railway specifics", says how it is run.

### What a hearing entry shows

The title is the kind's label and " hearing" ("Zoning hearing", "Weed lots hearing", "Street or right-of-way hearing", "Budget hearing"), and "Public hearing" for the kind `other`. The detail is "<count> properties" for a weed-lot hearing with a count and nothing for one without; for any other kind it is the subject, cut at 240 characters back to the end of the last whole word with "…" when cut. There is no time. The links are "City agenda", first, to the `agenda_url` of the newest item's meeting that has one, and then, for each item, "On the agenda of <Month D, YYYY>" to the item's page. The words are "on the agenda of" and never "set by" or "adopted": an item is stored when its agenda is posted, and nothing here checks that the resolution passed. `source_url` is the "City agenda" address or `None`. The UID is `hearing-<id>@docket.pub`.

## Neighborhood association meetings

### The schedule file

`content/coming-up/<slug>/neighborhood-schedule.yaml` is a hand transcription of the city's published schedule, and `content/coming-up/<slug>/sources/` holds the city's PDF as fetched, with a `README.md` row giving the file, what it is, its public address, the read date and its SHA-256. `config.COMING_UP_ROOT` names the directory (`content/coming-up` unless the environment says otherwise). Birmingham's is the Community Resource Services Division's 2026 schedule, revised February 3, 2026: 99 associations.

The file has three top-level keys. `source`: `title`, `revised`, `url`, `file` (the saved PDF, relative to the city's directory), `sha256`, `read`, `year`. `checked`: a list of `by`, `on` and `how`, one entry per reading of the transcription against the PDF. `associations`: one mapping per row of the PDF with `name`, `rule_text` and `type_text` (the PDF's cells as printed, misspellings included, a cell that wraps written on one line); `ordinal` (`first` to `fourth`) and `weekday` (a lower-case English weekday), or both null for a row given no dates; `time` (24-hour `"HH:MM"`, or null); `modes` (a list drawn from `in_person`, `phone`, `video`, empty for "No Meetings"); `place` and `remote` (the parts of the information cell that say where to go and how to call in, each as printed, each null when the cell has no such part or says "TBD"); optionally `months` (a list of month numbers; absent means all twelve); and `undated_reason`, required exactly when `ordinal` is null.

A rule is read as printed and no further. "Fourth Monday @ 6:00 p.m." is every month, as every other row is. "First Monday of this month @ 6:30 pm" (Glen Iris) and "No Meetings" (Bridlewood) are given no dates, and the page names both with the schedule's own words. Overton has its six named months. No date is moved for a holiday.

### The loader

`src/docket/services/neighborhood_schedule.py` reads files only. `load_schedule(city_dir)` raises `ScheduleError`, naming the file and the association, for: a missing or unknown key at any level; a value of the wrong shape (the file, `source` or an entry not a mapping, `associations`, `checked`, `modes` or `months` not a list, text that is empty or not text, a date that is not a date, a year that is not a whole number); an `ordinal`, `weekday`, `modes` or `months` value outside its vocabulary, or an empty `months`; one of `ordinal` and `weekday` null and the other not; a `time` that is not `HH:MM`; a duplicate `name`; `undated_reason` present with an ordinal or absent without one; an empty `checked` list; a `source.file` that does not exist or resolves outside the city's directory; and a saved file whose SHA-256 is not `source.sha256`. YAML reads a bare `on` as the boolean true, and the loader reads that key of a `checked` entry as `on`, so the file keeps `on:` unquoted. `get_schedule(slug)` returns `None` for a city with no schedule file and otherwise the loaded schedule, loaded on first use and kept for the life of the process.

`occurrences(schedule, start, end)` returns, for each association with an ordinal and each month of `schedule.year` in its `months`, the ordinal-th weekday of that month when it lies in the range, ordered by date, then time, then name. Nothing is produced for another year, so from January 1 after the schedule's year the neighborhood section of the page and the feed is empty until a new schedule is saved. The 2026 schedule gives 1,158 dates. `undated(schedule)` returns the associations with no ordinal.

`tests/unit/test_neighborhood_schedule.py` cross-checks the checked-in file against the saved PDF on every run: it reads the PDF's table with `pdfplumber` and requires, comparing letters and digits only, that every association's `name`, `rule_text` and `type_text` equal the first three cells of exactly one table row, that its `place` and `remote` are each contained in that row's fourth cell, and that no table row is left untranscribed. `TABLE_MISREADS` in that file lists the rows the table reading itself gets wrong (Highland Park's fourth cell, which is held to the page's text instead), and the test fails when a listed exception is no longer needed.

### What a neighborhood entry shows

The title is "<name> Neighborhood Association". The time is the date and `time`. The detail holds `type_text` as printed; then "Call-in details are not in the schedule" when `modes` contains `phone` or `video` and `remote` is null; and "The schedule gives no time" when `time` is null. `attend` holds `("Where", place)` when there is a place and then `("Call-in", remote)` when there are call-in details, each as transcribed, and `place` carries the same place. The one link is "City schedule (PDF)" to the schedule's public address, which is also `source_url`. `association` is `coming_up.association_slug(name)`: the name lower-cased, each run of other characters than a to z and 0 to 9 one hyphen, hyphens at the ends removed ("Forest Park/South Avondale" is `forest-park-south-avondale`). The UID is `na-<slug>-<YYYYMMDD>@docket.pub`.

### Saving a later revision or the next year's schedule

1. Fetch the city's PDF into `content/coming-up/<slug>/sources/` with one request, and record its SHA-256 (`sha256sum`).
2. Update the row in `sources/README.md`: the file, the revision date printed on it, the address, the read date, the digest.
3. Edit `neighborhood-schedule.yaml`: every changed row, and the `source` block (`revised`, `url`, `file`, `sha256`, `read`, `year`).
4. Add a `checked` entry with who read the rows against the PDF, the date, and how.
5. Regenerate the reading sheet: `venv/bin/python scripts/coming_up_reading_sheet.py <slug> > docs/runbooks/coming-up-reading-<slug>.md`, and read it against the PDF.
6. Run `./tools/verify`; the cross-check fails on any row that disagrees with the saved PDF's table.

The tests name the checked-in file's particulars, so a new file changes them too. `tests/unit/test_neighborhood_schedule.py` holds the saved PDF's name and digest (`PDF_NAME`, `PDF_SHA256`) and asserts the `source` block's dates and year, the first `checked` entry, the count of associations, the year's count of dates, and dates worked by hand for 2026. A schedule for another year also empties the neighborhood entries the page, feed and service tests expect on their fixed days in November 2026 (`D161`).

## The page

`public.coming_up_page` (`src/docket/web/public.py`) answers 404 for a slug that is no city or a city without the flag, and otherwise renders `coming_up.html` with its own stylesheet, `static/css/coming_up.css`. It executes no SQL and is not cached in the process. In order the page holds:

- An `<h1>` "What's coming up in <city>", and a sentence saying the list covers the next 60 days and each entry links to the city document it came from or says that docket.pub holds no link to one.
- The subscribe block (below).
- One `<section>` per date, headed by the date ("Tuesday, November 17, 2026"), holding that date's meetings and hearings and then, inside one `<details>` whose `<summary>` is "<n> neighborhood association meeting(s)", its neighborhood meetings.
- One `<article id="<the uid up to its @>" data-entry-uid="<uid>" data-entry-kind="<kind>">` per entry, holding the label (`<span class="cu-badge cu-badge--<badge>">`), the time when there is one ("9:30 a.m.", or "9:30 a.m. to 12:00 p.m." with an end; nothing in its place when there is none), the title, the detail lines, the "How to attend" block, and the links. An entry whose `source_url` is `None` (a meeting only the video site lists whose row has no `agenda_url`; a hearing none of whose setting meetings has one) then has `<p class="cu-nosource">` "docket.pub holds no link to a city document for this entry." A cancelled entry also has `data-entry-cancelled="true"` and a second label, `cu-badge--cancelled` "Cancelled".
- "How to attend" (`<div class="cu-attend">`), for an entry whose `attend` is not empty: one line per pair, the label and the text. Only neighborhood meetings have one, and the place is printed there and nowhere else in the article.
- "Nothing is listed for the next 60 days." when there is no entry.
- "Where these dates come from": meetings come from the council's video site and the city's calendar, one either calls cancelled is shown marked, and a calendar event docket.pub does not read as a council or committee meeting is left out; a hearing's date is read by docket.pub from the text of a resolution on a council agenda without a language model, a listed resolution may not yet have been adopted, and a hearing the council later moved may still show on its first date; the list of hearings can be incomplete, since a resolution whose hearing date could not be read from the agenda's text is left out and so are hearings held by city boards and commissions other than the council; neighborhood dates are computed from the monthly rule in the city's schedule (named, with its revision date, and linked), which covers its year only, and a meeting moved for a holiday is not reflected. Then one line per undated association: its name and its reason.

Each of the eight `cu-badge--` classes has its own dark text on a pale tint of the same hue, fixed hexadecimal pairs in `coming_up.css`; `tests/web/test_coming_up_page.py` computes each pair's contrast ratio and requires 4.5 or more (the lowest is 7.57). The label always has words, so colour is never the only signal. There is one pair per label and none for a dark theme, because no stylesheet the page sits on has one; a test fails when one gains it.

Links in: on a flagged city's page, "What's coming up →" beside "All meetings →" under "Recent meetings", and "calendar (.ics)" on the "Follow:" line (`docs/specs/city-page.md`); the city's meetings sitemap lists the page (`docs/specs/crawlers.md`).

## The calendar feed

`public.coming_up_ics` has the page's 404 rule and returns `text/calendar` with `Cache-Control: public, max-age=3600` and `Content-Disposition: inline; filename="<slug>-coming-up.ics"`. It is rebuilt on each request. `src/docket/web/ics.py`, which imports nothing from Flask or `docket`, writes it: `render_calendar(entries, *, name, now, absolute, page_url)`.

The text opens `BEGIN:VCALENDAR`, `VERSION:2.0`, `PRODID:-//docket.pub//Coming up//EN`, `CALSCALE:GREGORIAN`, `METHOD:PUBLISH`, `X-WR-CALNAME:<name>`, holds one `BEGIN:VEVENT` to `END:VEVENT` block per entry, and closes `END:VCALENDAR`. An event's lines, in order:

- `UID`: the entry's. It does not change between requests, so a calendar program knows an event it fetched again.
- `DTSTAMP`: the moment of the request in UTC.
- `DTSTART`: `YYYYMMDDTHHMMSSZ` in UTC for an entry with a start, `DTSTART;VALUE=DATE:YYYYMMDD` for one without.
- `DTEND`: in UTC when the entry has an end; `DTEND;VALUE=DATE:` of the next day for an entry without a start; none for a timed entry without an end, which is every neighborhood meeting, since the schedule gives no end and none is invented.
- `SUMMARY`: the title, with "Cancelled: " before it for a cancelled entry.
- `DESCRIPTION`: the detail lines, then each `attend` pair as "label: text", then each link as "label: absolute address", then "From docket.pub: " and the page's address.
- `LOCATION`: the place, when there is one.
- `URL`: the entry's `source_url`, or its first link made absolute when there is none.
- `CATEGORIES`: "Meeting", "Public hearing" or "Neighborhood association".

No event has a `STATUS` line, cancelled or not (`D163`). Text values escape backslash, semicolon and comma with a backslash and a line break as `\n`; `URL` is not escaped. Every line ends with CR LF, and a line longer than 75 bytes of UTF-8 is folded before the 76th byte, never inside a character, the continuation starting with one space; a long address is therefore broken across lines in the body, and a search of the feed for a link must unfold it first. `public._absolute_url` is the one function that makes a link absolute, for this feed and the hearings feed alike: it prefixes the request's root to a site path and returns a link that already begins `http://` or `https://` unchanged.

Two query parameters narrow the feed. `kind` must be one of `meeting`, `hearing`, `neighborhood`. `association` must be a slug `coming_up.association_feeds(slug)` returns, which is every association of the schedule that has dates (97 for Birmingham). Any other value of either, an empty value included, answers 404, so a mistyped address is not mistaken for an empty calendar; a value is matched as written, each parameter is checked on its own, and any other parameter is ignored. `coming_up.filter_entries` applies them. The calendar's name is "<City> coming up" with no parameter; "<City> meetings", "<City> public hearings" or "<City> neighborhood meetings" for a kind; and "<name> Neighborhood Association" for an association, whichever else is given. A narrowed feed with nothing in the window is a valid calendar with no event, answered 200.

The page's subscribe block (`<div class="cu-subscribe">`) offers three ways to take the feed, every address built by the route in `public._coming_up_feeds`: "Subscribe in your calendar", the address `webcal://<request host><the feed's path>`, the scheme calendar programs open as a subscription; "Add to Google Calendar", `https://calendar.google.com/calendar/render?cid=` followed by that `webcal` address percent-encoded with nothing left safe; and "Calendar file (.ics)", the feed's own path. Under them, "Only:" with a `webcal` link per kind, and a `<details>` headed "One neighborhood association (<year> schedule)" with a `webcal` link per association, the year being the schedule's so that a reader subscribing late in the year knows why the feed runs out.

## The upcoming-hearings feed, for a flagged city

`/al/<slug>/upcoming-hearings.rss` (`public.upcoming_hearings_rss`) returns, for a flagged city, the hearing entries of the coming-up page, `coming_up.filter_entries(coming_up.list_entries(municipality), kind="hearing")`, through `rss/scheduled_hearings.xml.j2`. For every other city it returns what it always has: the upcoming meetings whose title or item titles contain the word "hearing" (`query.list_upcoming_hearings`, `rss/upcoming_hearings.xml.j2`), which lists a resolution that only sets a hearing for a later date as if the hearing were at that meeting (`D155`). The cache key (`upcoming-hearings:<slug>`), the 60-minute cache in the process, the mimetype and the `Cache-Control` header are the same on both paths, and the gate is asked inside the cached render, so a city that gains or loses the flag changes feed within the hour.

The flagged feed has the older feed's `<channel>` envelope with the `<description>` "Public hearings the <city> council has scheduled, by the date of the hearing.", and one `<item>` per entry in the page's order: `<title>`, the entry's title, a comma and its date ("Zoning hearing, November 24, 2026"); `<link>` and `<guid isPermaLink="true">`, both the coming-up page's absolute address, `#`, and the entry's uid up to its `@` (the article's `id` on the page); `<description>`, a CDATA section holding the detail lines and then each link as "label: absolute address", one per line. There is no `<pubDate>`: the older template puts the meeting's date there, a date in the future, and an entry does not carry the day its hearing was first read, so a feed reader orders the items by when it first saw them. Two hearings of one kind on one day share a title and differ in description and guid.

## Checking

`./tools/verify` runs all of it. The test files, by what they pin: `tests/unit/test_hearing_reader.py` (the reader, on 25 real Birmingham titles in `tests/fixtures/hearings/birmingham_titles.json`); `tests/services/test_hearings_store.py` and `tests/integration/test_047_migration.py` (storage); `tests/integration/test_ingest_hearings.py` and `tests/unit/test_backfill_hearings_script.py` (the ingest stage and the script); `tests/unit/test_neighborhood_schedule.py` and `tests/unit/test_coming_up_reading_sheet.py` (the loader, the dates, the cross-check, the sheet); `tests/services/test_coming_up.py` (the entries); `tests/web/test_coming_up_page.py` (the page, with a test that its count of articles is the service's count of entries); `tests/unit/test_ics.py` and `tests/web/test_coming_up_feed.py` (the feed, with a test that it holds one event per article of the page and the same UIDs); `tests/web/test_hearings_rss_flagged.py` (the hearings feed on both paths). The web tests set `coming_up._today` to 2026-11-16, because the checked-in schedule gives no date after 2026-12-31.

On a running site:

    curl -s -o /dev/null -w '%{http_code}\n' https://docket.pub/al/birmingham/coming-up/        # 200
    curl -s -o /dev/null -w '%{http_code}\n' https://docket.pub/al/mobile/coming-up/            # 404
    curl -s https://docket.pub/al/birmingham/coming-up.ics | head -3                             # BEGIN:VCALENDAR first
    curl -s 'https://docket.pub/al/birmingham/coming-up.ics?kind=hearing' | grep -c BEGIN:VEVENT # the hearings on the page
    curl -s https://docket.pub/al/birmingham/upcoming-hearings.rss | grep -c '<item>'            # the same number, within the hour's cache

Which items the reader reads, without writing anything: `scripts/backfill_hearings.py --city birmingham --since <date> --dry-run`, which prints one line per matched item, one per hearing, and the totals.

## Not built

The city's other bodies that hold public hearings (`D157`); a note on a neighborhood meeting whose date is a city holiday (`D156`); a schedule for 2027 (`D161`); calendar events that are meetings and whose titles `classify_event` does not read, such as a work session (`D160`); a `STATUS` line on a cancelled event (`D163`); a hearing shown anywhere but this page and the two feeds (the item page, the meeting page, the city page's opener, search); past hearings as a list; any other city.
