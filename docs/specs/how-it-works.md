# How it works: the path an item travels, and real items followed along it

The page at `/al/<slug>/how-it-works/` explains how an ordinance or resolution moves through a city's council, each rule in the words of its source with a citation and a link, and lays one real item onto that path with what the city's record shows at each stop. Only Birmingham has one. This file owns what the page shows, where its words come from, the two file formats, the quotation check, what a journey may state, and how its links degrade. Why the content is checked-in data is decision `0092`; why a journey states its facts in its file and takes only links from the database is `0093`; why quotations are checked by the loader is `0094`.

## Where the words come from

Every sentence on the page below the site's own chrome is checked-in content under `content/how-it-works/<slug>/`, and it changes only by a commit. Nothing writes or alters it at run time: no model is called, and no sentence, date, tally or name is read from a database row. Who wrote Birmingham's sentences, and where decision `0092` says more than this paragraph does, is `D127` in `docs/DEBT.md`.

A city's directory holds three things:

- `explainer.yaml`: the path (the stops and side routes), the rules at each stop, and the questions left open.
- `sources/`: plain-text copies of the documents the rules quote, with a `README.md` giving each copy's public address and the date it was read. They are working copies for checking quotations; the site does not serve them.
- `journeys/`: one YAML file per journey, named `<n>-<key>.yaml`. The number fixes the journey's place in the picker (file-name order); the journey's key is inside the file and is what its address carries.

`create_app` in `src/docket/web/__init__.py` reads every city directory under `HOW_IT_WORKS_ROOT` (`src/docket/config.py`; default `content/how-it-works`) once at start, through `load_explainers` in `src/docket/services/how_it_works.py`, and keeps the result in `app.config["HOW_IT_WORKS"]`, keyed by the directory's name, which is the city's slug. A directory is a city when it holds an `explainer.yaml`. A root that does not exist holds no cities. A file that fails validation raises `ExplainerError` and the application does not start; the message has the form `<path to the file>: <key path>: <problem>`.

## Terms

A **stop** is one step on the path. A **main stop** is one every item's path has; Birmingham's seven, in order, are Submitted, Committee, On the agenda, First reading, Final vote, Mayor, In effect (keys `submitted`, `committee`, `agenda`, `first_reading`, `final_vote`, `mayor`, `in_effect`). A **side route** is a stop only some items take, hung under a main stop; Birmingham's three are the consent agenda and a public hearing under On the agenda, and being held over under First reading (`consent`, `hearing`, `held_over`). A **rule** is one statement about a stop, with at most one quotation, a citation and a link. A **journey** is one real, finished item followed across the path. A **journey stop** is one event of a journey; it names one or more stops of the path, and a journey may have several events at one stop.

## The explainer file

    city: birmingham
    sources_read: 2026-11-12       # an unquoted YAML date
    stops:
      - key: committee
        name: Committee
        side_route_of: null        # or the key of the main stop it hangs under
        description: one sentence
        rules:
          - statement: plain words
            quote: exact words from the source, or omitted
            citation: General Code §2-2-14(b)
            url: https://…
            source_file: general-code-title-2-chapter-2.txt
    open_questions:
      - heading: short
        body: one paragraph

The loader refuses: a file with no stops; a stop with no key, name, description or rules; a repeated stop key; a `side_route_of` that does not name a main stop; a rule with no statement, citation or link; a link that does not begin `https://`; a `quote` with no `source_file`; a `source_file` that is not a bare file name of a file in the city's `sources/`; a quotation not found in its source (next section); an open question without both a heading and a body; and a `sources_read` that is not a date.

## The quotation check

A quotation is compared with the saved copy its `source_file` names after both are normalised: every run of whitespace becomes one space, and curly quotation marks and apostrophes become straight ones. The comparison is case-sensitive. A quotation may elide words with "…" or "..."; it is split there, and each piece must be found in the source after the end of the piece before it. The check runs every time the files are loaded, so a quotation the source does not hold stops the application from starting and fails `./tools/verify` in `tests/unit/test_how_it_works_content.py`.

The check covers every rule's quotation, because a rule's quotation must name a source file, and a journey stop's quotation when the stop names one. A journey stop's quotation with no `source_file`, and a journey's `title`, are not checked by the loader: they rest on records with no saved copy (`D126` in `docs/DEBT.md`). One title is checked by a unit test instead, the consent journey's against `committee-bf_min.txt`.

## The journey file

    key: parking-fines
    label: Parking fines ordinance    # the picker's words
    note: one line on what this journey shows
    title: words a record prints for the item
    stops:
      - stops: [first_reading]        # one or more stop or side-route keys
        date: 2026-05-26
        record: minutes               # minutes | agenda | video | transcript | committee_minutes | none | not_on_route
        text: what the record shows, in plain words
        quote: exact words, or omitted
        source_file: committee-….txt  # optional; the quote is then checked against it
        meeting_id: 2237
        item_id: 58990                # optional
        seconds: 2506                 # optional; the cue on the meeting's own clock
        document:                     # optional; a city document the site holds no link to
          label: Committee minutes
          url: https://…
        gap: why there is no record

Five of the seven `record` kinds are records. The other two say there is none: `none` means the rules say the stop happens and no record read shows it; `not_on_route` means this item's route does not pass through the stop.

The loader refuses, in a journey file: a missing `key`, `label`, `note` or `title`; a key another journey file already has; a journey stop that names no stop, or a key that is not on the path; a `record` that is not one of the seven; a stop with no `text`; a recorded stop with no `date` or no `meeting_id`; a `none` or `not_on_route` stop with no `gap`, or with a `date` or a `meeting_id`; a `source_file` with no `quote`, or a quotation its source file does not hold; a `document` without a `label` and an `https://` address; a `meeting_id`, `item_id` or `seconds` that is not a whole number; and a journey in which one of the main stops is named by no journey stop. That last rule gives every journey the same path: each main stop is recorded, "not in the record", or "not on this item's route", and each blank is a statement someone wrote with its reason.

A city with no `journeys/` directory has no journeys, and its page shows the path unmarked with no picker, title or timeline.

## What a journey may state

A journey states what a record shows and names the kind of record. It states no motive: the page gives a tally, the names, the presiding officer's declaration and the rule beside it, and does not say why a member voted as they did. The `title` holds only words a record prints, because the page draws it as a quotation; a description of the item in the site's words goes in `note`. Words inside `quote` are the record's own. A fact read from a video is `record: video` and one read from the machine transcript is `record: transcript`, and the page labels each.

Every date, tally, name and quotation shown is the file's. A row that changes or vanishes cannot change a sentence; it can only remove a link.

## The route

`how_it_works(slug)` in `src/docket/web/public.py` answers 404 when the slug is no city, and when the city has no explainer; the city is looked up first, so a content directory named for no city serves nothing. `?journey=<key>` picks the journey; without the parameter the first journey in file-name order is shown; a key that names no journey of the city, an empty one included, is 404.

A request carrying the header `HX-Request` and not `HX-History-Restore-Request` is answered with the journey's container alone (`src/docket/web/templates/partials/how_it_works_journey.html`); any other request gets the whole page. Every 200 carries `Vary: HX-Request`. A journey that does not exist is 404 with or without the header.

The route resolves the chosen journey's links on each request with `resolve_journey(journey, municipality_id, city_slug)`, which reads through `query.get_meeting`, `query.get_agenda_item`, `video_links.for_meeting`, `video_links.link_for` and `transcripts.get_public_transcript`, and writes nothing.

## What the page shows

From the top (`src/docket/web/templates/how_it_works.html`, styled by `src/docket/web/static/css/how_it_works.css`):

1. **The hero**: the eyebrow "How it works", the heading "How an item becomes a decision in <city>", and a sentence saying every rule is cited to its source and links to it, with the date the sources were read.
2. **The journey's container**, `div#how-it-works-journey`, in a fixed order:
   - **The picker**, labelled "Follow a real item": one link per journey in file-name order, its words the journey's `label`, the one shown marked `aria-current="true"`. Each link is the address `?journey=<key>` and also asks for it through htmx, replacing the container (`hx-swap="outerHTML"`) and pushing the address; without JavaScript the link loads the page with that journey. Each link has the id `hiw-pick-<key>`, which lets htmx return keyboard focus to it after the swap.
   - **The item**: the eyebrow "This item", the journey's label, its note, and its title as a quotation.
   - **The path**: an ordered list of the main stops, each linking to its section below, with the side routes in a nested list under the stop they branch from. Each stop is marked from the journey, in words and not by colour alone: "in the record" when a recorded journey stop names it; otherwise "not in the record" when a `none` stop names it; otherwise "not on this item's route". A side route the journey does not name is muted and carries no words. The marks come from the journey file alone, so a stop the file records stays "in the record" when its meeting row can no longer be linked. No stop is drawn as the current one; every journey is a finished item.
   - **The timeline**: one card per journey stop, in file order. A card shows the name of each path stop it belongs to, linked to that stop's section; the date, or "not in the record", or "not on this item's route"; the file's text; the quotation, if any; the reason for a gap; the label "from the video" or "from the machine transcript" for those two kinds of record and no label for the others; and its links. A `none` stop is drawn with a dashed outline and a `not_on_route` stop as a slim, muted line.
3. **One section per stop and side route**, in the file's order, with the id `stop-<key>`: the eyebrow "Step N of 7" for a main stop or "Side route from <stop>" for a side route, the stop's description, and its rules, each as the statement, the quotation where there is one, and the citation as a link to the public source. When a journey is shown, each section links "Back to the journey".
4. **"What we could not establish"**: the open questions, each a heading and a paragraph.

At widths under 720 pixels the path stacks vertically; it does not scroll sideways.

## A card's links, and how they degrade

The links are small pills in a fixed order: "Meeting" and "Item" (the site's pages), "Recording" (naming the site, "on YouTube" or "on Granicus", when the link builder gives one, and ending ", at this moment" only when the link is timed; `docs/specs/video-links.md` owns when that is), "Transcript" (the site's transcript page), "Minutes" and "Agenda" (the city's documents), and the stop's own `document`, labelled with the file's label.

A stop keeps its text whatever the database holds, and loses only links:

- The meeting is missing, hidden, or another city's: no pills from the database at all, the city's minutes and agenda included.
- The item is missing, hidden with its meeting, or belongs to a different meeting than the stop names: no "Item" pill and no chapter id for the recording; the meeting's links remain.
- The item's `external_id` is not a chapter id (not all digits): the recording link is the plain player address, untimed.
- The meeting has no video: no "Recording" pill. No public transcript: no "Transcript" pill. No minutes or agenda address: that pill is absent.
- A stop with no meeting (`none`, `not_on_route`) has no pills from the database.

The stop's own `document` pill is the file's and is drawn whatever the database holds.

The first two losses are logged each time the journey is resolved, because they mean a row the journey cites has gone: `docket.services.how_it_works` writes one warning per affected stop, `how-it-works: journey '<key>' stop <n> (<stops>, <date>): meeting <id> is missing; the stop carries no links` (or `is hidden`, or `belongs to another city`), and `agenda item <id> is missing; the stop carries no item link` (or `belongs to another meeting than <meeting id>`). The warnings are in the `docket-web` service's log. The other losses are ordinary states of a meeting and are not logged.

## Links in

The shared footer partial `src/docket/web/templates/partials/page_sources.html` links the page as "How the council works" on every page rendered with a municipality that has an explainer (the Jinja global `has_how_it_works(slug)`); a city without one has no such link. The page is not in the sitemap, and item pages and item cards do not link to it.

## Adding a journey or correcting a rule

To correct a rule: re-read the public source; update the copy under the city's `sources/` and its read date in that directory's `README.md` (for Birmingham, `content/how-it-works/birmingham/sources/README.md`); edit the rule in `explainer.yaml`; run `./tools/verify`. A rule that makes several claims is several rules, each with the words that support it.

To add a journey: write `journeys/<n>-<key>.yaml` with the next number, accounting for every main stop. Where a quotation's source can be saved under `sources/`, save it, list it in the `README.md`, and give the stop its `source_file`. Check every quotation against the saved file before writing it down, and load the draft file before committing it; `./tools/verify` runs the loader on the real content. The ids a journey cites are production's, and the development database may hold none of them, so a new journey's pills are seen only on production.

A second city is a second directory under `content/how-it-works/` named for its slug.

## Not built

A progress strip on item pages, links from items to the page, journeys for items still in flight, any reading of a new source (the Mayor's signature, publication), and a sitemap entry. The design this page is the first phase of is `docs/superpowers/specs/2026-11-12-how-it-works-design.md`.
