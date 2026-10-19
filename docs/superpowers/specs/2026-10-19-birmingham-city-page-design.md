# Birmingham city page as a briefing: design

> **Status:** Design, approved by the operator 2026-10-19 with the per-city flag option (see Open decision). Supersedes the initial suggestions in `2026-10-18-city-front-page-initial-suggestions.md`.
> **Scope:** the Birmingham city page at `/al/birmingham/` and the paths that leave it. The home page and the other three cities are out of scope by the operator's instruction; their pages continue to render from the same template and must not break, but nothing here is designed for them.

## Intent

A reader opens the Birmingham page and, without scrolling, learns what the council did at its last meeting and what comes next. Below that, a few doors, each opened by a real example rather than a count, lead to the deeper pages that already exist: the meeting, the item, the member record, the topic, the transcript. Every fact on the page keeps its link to the city's own document.

The operator's words for the problem: when you first go to Birmingham "there's a lot of stuff but you're not really directed or given much." The page should present, not inventory.

## Who the page is for

**My call, not the operator's:** the first reader is a Birmingham resident who heard something and wants to know what the council did about it. They do not follow the council week to week. The follower is served already by the Meetings list, the member records, and RSS, and loses nothing here.

## The review that produced this

The live page was read on 2026-10-18 against four lenses: gstack's seven design-review passes (information architecture, interaction states, user journey, AI-slop hard rules, design-system alignment, responsive and accessibility, unresolved decisions), the GOV.UK start-page pattern and writing rules, the cognitive-accessibility checklist (plain language, memory load, recognition over recall), and the journalism dev-toolkit's accessibility baseline. The findings that drive the design:

- First, second, third on the page today: a name and freshness chip; three large numbers; an empty state ("No agenda posted yet"). The first content with meaning, the notable items, is about five screens down.
- The same four meetings appear twice, in "Last week" cards and the "Recent meetings" table, all titled "Regular City Council Meeting", distinguishable only by date.
- "Flagged items 27" has no destination: the two vote sections are switched off in the route (`contested = []`, `recent_votes = []`, with a TODO about cold-load cost). Two oversight tiles are zero-count doors to empty pages.
- Twenty-two taxonomy doors (four policy tiles, seven oversight tiles, eleven topic chips) appear before any content.
- Headings name containers ("On the agenda", "What's on the docket", "Notable items"), so scanning headings teaches nothing.
- Vocabulary fails plain-words: "YTD", "Hidden on consent", "Sole-source / no-bid", "Provenance", "inferred", "CMS", "tsvector", an adapter class name and source path.
- "photo · placeholder" is shown to readers. Member cards lose their statistics on mobile. No skip link. No meta description. The h1 text repeats as an h2 in the source panel.
- Two hard rejections under the slop rules: a stat-card grid as first impression, and app UI made of stacked cards instead of layout.

## Goals

1. The first screen states, in sentences, what happened at the last meeting and what is next, with every clause linked to its source.
2. Each door below is opened by one real example (an item, a vote, a person, a topic, a quote) that links to a page that already exists.
3. Nothing on the page is a count with no destination, and no door leads to an empty page.
4. The page reads at a general-audience level: sentences of at most 25 words, no abbreviations a resident would not know, headings that say what is under them.
5. The page is at least as accessible as today and fixes the misses named above.

## Non-goals

- New data. Everything on the page is assembled from rows already in the database; the only new computation is precomputing what is too slow to compute on request.
- New routes or interior pages. Doors lead to existing pages. If no existing page fits as a door's "more" target, the door has no "more" link.
- Anything written by a language model for this page. The opening sentences are template text filled from counted rows. (Operator decision, 2026-10-18.)
- A redesign of the home page, the other city pages, or any interior page.
- A visual rebrand. The existing tokens, typefaces, and components stay.

## Anti-goals (what would make this a failure even if it ships)

- A sentence on the page whose number, name, or date does not link to the document it came from (`docs/PRINCIPLES.md`, source or silence).
- A clause filled with a default when the source has no value. The clause is dropped instead.
- A door that opens on an empty page or a zero.
- The page becoming slower on a cold load than it is today. The five-minute overview cache stays; anything heavier than the current queries is precomputed by the worker.
- Vote facts from video OCR and from minutes merged into one statement without their source label (`docs/PRINCIPLES.md`, keep the sources apart).

## Constraints

- `docs/PRINCIPLES.md`, all six rules. `GOALS.md` Constraints: worker memory, no second heavy process, deploy from `main` only.
- Flask and Jinja templates, HTMX, server-rendered, no build step, no new JavaScript library.
- The city template is shared by four cities. Every new section renders only when its data exists; a city without the data gets no section, not a zero.
- Routes call `docket.services.*`; services own transactions. Precomputation runs as a worker task on the existing scheduler and pings a Healthchecks check like every other task.

## The page, first to last

### 1. Lead (kept)

Eyebrow (council type, county, population), the h1 "Birmingham, AL", the freshness chip linking to source health. Unchanged except that the chip's date and the footer's "Updated" date must come from the same value; today they disagree.

### 2. The opener

Template sentences, filled from rows, replacing the KPI strip, in two visual beats so the links are not a wall of underlines on a phone. The shape:

> **Last meeting.** The council met on Tuesday, October 14 and acted on 63 items, including a **$10.1 million contract for citywide road resurfacing**. One vote split: the KultureCity campus item passed 6 to 1, with **Hunter Williams** voting no. **Read the October 14 meeting →**
>
> **Next meeting.** Tuesday, October 21, with **42 items on the agenda**. **See the agenda →**

Each beat carries at most three links, never two adjacent: the biggest item to its item page, the dissenting member to their record, and one action link at the end of the beat to the meeting page (the last-meeting link lands on its votes section when a vote split). The next-meeting beat says the item count only when the agenda has been ingested; otherwise it ends at the date. (Link limits and the agenda count: accepted from the operator's review of 2026-10-19.) The template chooses:

- The last meeting: the most recent Birmingham meeting of type `council` that is past under the existing upcoming predicate (`UPCOMING_PREDICATE_SQL` in `meeting_time.py`, which is date plus start time plus three hours, Chicago time) and that has at least one agenda item. Work sessions, planning, zoning board, and special meetings never become "the council met"; meetings with zero items are skipped so a placeholder record never does either. (My call after the builder check.)
- The biggest item: the agenda item of that meeting with the largest extracted dollar amount that passes the dollar check below. If none passes, the clause is dropped.

**The dollar check (accepted from the operator's review).** `agenda_items.dollars_amount` is the largest figure found in the item text (`enrichment.dollars.extract_dollars` keeps the maximum), so an item that mentions a $39.5 million campus and a $7 million city contribution stores $39.5 million. There is no verified flag on the column. An amount is promoted to prose on this page, in the opener or in section 3, only when one of two mechanical conditions holds: the item's text contains exactly one distinct dollar amount (`extract_dollar_amounts` in `src/docket/analysis/structured_facts.py` returns a set of size one), or the item's headline contains a dollar figure equal to `dollars_amount` within rounding to the headline's precision. An item that fails is skipped in favour of the next largest. The check costs nothing new: both inputs are already on the row. The meeting page and item page continue to show the stored amount with its source link as they do today; this rule governs only what this page asserts in a sentence.
- The split: votes of that meeting with nays or abstentions greater than zero. One split names the item, the tally, and the dissenters. Several splits say "**Three votes split**" linking to the meeting's votes section, naming none. Zero splits say "**Every vote was unanimous.**"
- The next meeting: the nearest Birmingham meeting of type `council` that is upcoming under the same predicate. If none is known, the sentence is "No agenda is posted yet for the next meeting; agendas usually appear a few days before." That copy already exists on the page.

**What a split vote names (my call after the builder check).** Votes attach to agenda items through `vote_agenda_items`, zero to many per vote, and most minutes votes have no linked item. The sentence and the list in section 4 therefore use one rule everywhere. Exactly one active link: name the item and link to its item page. Several active links: "a consent-agenda vote covering **14 items**", linking to the vote's anchor on the meeting page. No link: "a vote at the **October 14** meeting", linking to the same anchor. A vote is never excluded or dropped for lacking an item, so the opener and section 4 always agree. Provisional links do not count as links.

**Which source a vote comes from (my call after the builder check).** A meeting can carry a vote from the minutes and a vote from video OCR for the same roll call, and `docs/PRINCIPLES.md` forbids merging them. Every count on this page (the opener's split or unanimous sentence, section 4's list, the per-member dissent numbers) is taken from one source per meeting: the minutes votes when the meeting has any, otherwise the video votes. The sentence says which: "**from the minutes**" is omitted as the default; a video-sourced clause says "**from the video**". Votes with `needs_review` set are excluded from every count. Where the two sources disagree, this page does not adjudicate; the meeting page and the minutes-versus-video page show the disagreement, and that is where the reader is sent.

When the last qualifying meeting is more than 14 days old, the first sentence says so ("The council last met on ...") instead of implying recency. The opener is `aria`-plain prose, not a card, and its text also becomes the page's meta description, truncated at a sentence boundary.

### 2a. Search

One search field directly under the opener, scoped to Birmingham (the search route already takes a `city` parameter and searches transcripts as well as items). Label in plain words: "Search Birmingham's agendas, minutes, and transcripts for a street, a company, or a topic." This is the page's one primary action in the GOV.UK start-page sense: the reader who heard a name and wants to find it does not have to hope it appears in the doors below. The masthead search stays; this field is the same form, placed where the start-page reader is. (Accepted from the operator's review.)

### 3. Where the money went

Heading: "Where the money went". The three largest dollar items from Birmingham meetings in the last 90 days that pass the dollar check, each as one line: amount, headline, meeting date, consent flag in words ("passed on the consent agenda"), linking to the item page. No tier legend. A "more" link leads to the search page scoped to Birmingham with an `order=amount` parameter, which the search route gains for the empty-query case; a parameter on an existing route, as with the member route's date parameter. (Accepted from the operator's review; the earlier draft had no "more" link.)

If fewer than three items pass in 90 days, show what there is. If none, the section does not render.

### 4. Where they disagreed

Heading: "Where they disagreed". The last five votes in Birmingham with nays or abstentions, newest first, each naming the item, the tally, the date, and the dissenting members by name linking to their records, with the vote's source label (minutes or OCR) kept. The queries exist (`list_contested_votes`, member breakdown in `list_recent_votes`); they are the ones the route switched off, so their results are precomputed (section "Precomputation" below).

A "more" link leads to the existing Split vote category landing, which lists every item with a dissenting vote.

If no vote in the last 180 days split, the section still renders, as one sentence: "Every recorded vote since **<date>** was unanimous. The last split was **<item>** on **<date>**, <tally>." Birmingham rarely splits, and unanimity on a $39 million item is the story. If the city has no votes at all, the section does not render.

### 5. Who voted how

Heading: "The council". The nine members as today's cards, ordered by district, with the district number as the card's first and largest text, because a resident who does not know their councilor's name does know their district. Under it the name, then two numbers that stay visible at every width: attendance in the last 12 months and votes against the outcome in the last 12 months. The card links to the member record. The second number links to the record's Dissent filter. The "photo · placeholder" tag is removed; the initials portrait stands on its own. "View record" appears once, not twice. A find-your-district-by-address door is not possible without district geometry, which the project does not have; the district number is the substitute. (District first, and the rolling window: accepted from the operator's review. A calendar-year window would show zeros every January.)

**What the second number counts (my call after the builder check).** It uses the Dissent filter's existing definition in `list_member_voting_history`: present and not aligned with the result, so an abstention counts and a no on a motion that failed does not. The label is "voted against the outcome", not "dissents" or "voted no", so the words match the definition. The destination must show the same count: the existing member route gains a `since` date query parameter that the Dissent filter honours, and the card links with the date 12 months back. That is a parameter on an existing route, not a new route. The source-per-meeting rule above applies to this count too.

The two numbers need a per-member query that does not exist on this page today (the member page computes them one member at a time); it is precomputed with the votes.

### 6. What they keep dealing with

Heading: "What they keep dealing with". Two groups in one section, same line shape for both: a name, the count in words ("41 items since July"), and one example headline from the last 90 days linking to its item page.

First, the four Birmingham policy priorities (Blight Accountability, Housing Stability, Property Recovery, Public-Safety Tech and Privacy), labelled "Tracked in Birmingham", each name linking to its category landing. They are the project's editorial priorities for this city and belong among the doors, not below the signals; the earlier draft demoted them and the operator's review objected. A priority with no item in 90 days still renders, with its latest item and the words "last item <date>", because a tracked issue going quiet is itself information.

Second, the five topics with the most Birmingham agenda items in the last 90 days, each name linking to the topic page filtered to Birmingham. The eleven all-time chips and their counts go. The "Routine & Procedural" topic is excluded; it is the opposite of a door.

### 7. Said at the meeting

Heading: "Said at the meeting". One transcript excerpt from the most recent Birmingham meeting that has a public transcript, chosen by the rule already used on item pages (`excerpt_for_item` in `src/docket/services/transcripts.py`) for that meeting's biggest-dollar item that passes the dollar check. Shown as a short quote, the meeting date, and a link to the transcript page at that segment. The speaker is named only when speaker resolution has attached a council member or a manual name; an unresolved cluster label such as `SPEAKER_04` never appears on this page, and the quote is then attributed as "during discussion of <item> at the <date> meeting". (Accepted from the operator's review; a cluster label fails this spec's own plain-words rule.) If no public transcript or no excerpt exists, the section does not render.

This section is last among the doors because its selection rule is the least settled; the builder may ship it in a later milestone.

### 8. Oversight signals, reduced

Heading: "Signals in the last 30 days". Only the process badges with a count above zero, as a short list, not tiles, each in plain words with its count and a link to its category landing:

| Badge slug today | Plain label |
|---|---|
| Hidden on consent | Passed without discussion, on the consent agenda |
| Legal settlement | Legal settlements |
| Sole-source / no-bid | Contracts awarded without competing bids |
| Emergency action | Emergency actions |
| Amends prior contract | Changes to earlier contracts |

The Split vote badge (one or more dissenters on a roll call) and the Contested badge (two or more dissenters and more than a fifth of those voting; both in `src/docket/ai/badges_process.py`) are not listed here. Section 4 is the page's one door for disagreement, and three differently named counts of non-unanimous votes on one page would confuse a reader. (Accepted from the operator's review.) Their category landings remain reachable from section 4's "more" link and from the meeting pages.

Zero-count badges are omitted. If every badge is zero, the section does not render. The four Birmingham policy priorities moved up into section 6.

### 9. Meetings

Heading: "Recent meetings". One list, six rows, replacing both today's "Last week" strip and the "Recent meetings" table. Each row: date with weekday, title, item count, total dollars where any item has an amount, number of split votes where votes exist, and the document links (agenda, minutes, video) as today. "All meetings" links to the meetings list. The "On the agenda" strip is replaced by the opener's next-meeting sentence.

A meeting appears in this list only if it has at least one agenda item or at least one document link. Today's six "Regular City Council Meeting" records in five days would otherwise fill the list with ghosts. The adapter defect behind those records is still filed separately; this filter is the page's defence, not the fix. (Accepted from the operator's review.)

Under the list, one line of follow links in plain words: the Birmingham upcoming-meetings RSS feed, the city blog feed, and the editorial coverage feed, all existing routes. No newsletter exists, so none is offered. This is the page's only "come back" prompt and it is a line of links, not a banner. (Accepted from the operator's review.)

### 10. Blog, source panel, footer

"From the blog" stays. The source panel keeps its purpose and loses its developer vocabulary: it says which city website the records come from, how many meetings are indexed, when the last one was indexed, and links to source health and the methodology page. The adapter class name, source path, schema, database version, and search-index detail are removed from the public page; they belong on source health or the colophon. The duplicate h2 "Birmingham, AL" is removed.

**The source panel and footer are site-wide partials (my call after the builder check).** `base.html` includes `partials/page_sources.html` and `partials/footer.html` on every page. They are edited once, in place, and every page inherits the change; forking a city-page copy would make two owners of one fact (`docs/PRINCIPLES.md`). The footer's "Updated" date becomes the municipality's last-ingest value where a municipality is in context and is omitted otherwise, instead of today's render time or "N/A". The existing web tests that assert the panel's markup on interior pages are updated to the new markup. This is the one place the work touches pages other than the Birmingham city page, and it is a wording and provenance fix, not a design change to them.

## Interaction states

| Section | Empty | Partial | Error or stale |
|---|---|---|---|
| Opener | No qualifying meeting: "docket.pub has not indexed a Birmingham meeting yet." (never expected on Birmingham) | Missing clause dropped, sentence still grammatical | Last meeting more than 14 days old: "last met" phrasing |
| Money | Section absent | Fewer than three rows shown | n/a |
| Disagreed | One-sentence unanimity form with last split | Dissenters unknown (tally only): tally shown, no names | OCR-sourced vote carries OCR label |
| Council | Section absent (no roster) | Member with no votes this year: attendance shown, dissent omitted | n/a |
| Topics | Section absent | Fewer than five topics shown | n/a |
| Said | Section absent | n/a | Transcript hidden (low speech, re-run): section absent, as the predicate decides |
| Signals | Section absent | Only nonzero rows | n/a |
| Search | n/a (always renders) | n/a | Empty query submits to the search page as today |
| Meetings | Existing "no meetings" copy; ghost records (no items, no documents) excluded | Row without documents but with items: "no documents linked", as today | n/a |

No loading states: the page is server-rendered and cached. No success states: nothing is submitted.

## Precomputation

The split votes, the unanimity fallback, and the per-member attendance and dissent counts are the queries the route switched off for cold-load cost. They are computed by a worker task after the daily ingest and stored in one small table (one row per city per computed fact set, JSON payload, computed-at timestamp), read by the city route in one query. Payload rows carry the ids they came from so every rendered fact still links to its meeting, vote, item, or member. The table is rebuilt in place per city with one statement; it is never swept row by row. The task pings its own Healthchecks check. If the row is older than 48 hours the sections render from it anyway with the freshness chip's date unchanged, because the chip reports ingest, not this table; the staleness is surfaced on source health, not hidden.

The builder chooses the table name, the payload shape, and whether the opener's facts also come from this table or from the existing per-request queries, which are cheap.

## Navigation out of the page

Masthead and tab bar are unchanged. Every door on the page targets an existing route: meeting detail, item detail, member detail (with the `filter=dissent` query where named), topic detail with the city parameter, category landing, transcript, meetings list, source health. Each link's text is unique on the page or made unique by context in an `aria-label`. A skip link to the main landmark is added in the base layout.

## Accessibility and writing rules

- Sentences at most 25 words. No abbreviations: "this year" not "YTD"; "video" not "OCR" in reader-facing copy, except the source label where the distinction is the point, which reads "from video" and "from minutes".
- Headings say what is under them and are unique on the page. One h1.
- Touch targets at least 44 pixels on member cards and list rows.
- Nothing hidden on mobile that carries the section's meaning: the member numbers stay; the meetings list may drop document links behind the row link but keeps date, title, and item count.
- Horizontal scroll strips are not used for content a reader must see; the meetings list is vertical at every width.
- Colour is never the only carrier of pass/fail or source; the words are present.
- Emoji icons on badges are removed from this page; the plain label carries the meaning.

## Measurement

Umami is live with referrer and pageview views. Before the change merges, the operator records a 30-day baseline of pageviews for the city page and outbound-source clicks from it, by hand, following `docs/runbooks/analytics.md`; agent sessions have no Umami credentials. After, the operator compares the same two. This is an operator step outside the plan and does not gate any milestone or the merge. Readers are few before launch, so the numbers are a sanity check, not a verdict.

## Open decision for the operator

The template is shared by four cities. The redesign removes the KPI strip, the tile grids, the topic chips, and the "Last week" strip that the other three city pages render today. Two ways to build it:

- **One template, opener gated per city (recommended after the operator's review).** Every city gets the new layout, and every section already renders only where data exists. The opener's prose and the precompute task run only for cities whose municipality metadata carries a `briefing` flag, set for Birmingham alone. A city without the flag shows the lead, the search field, and whatever lists its data supports, with no generated sentences. Turning a city on later is a metadata change, not a template change. One page shape to test; no unreviewed prose on the other cities.
- **One template, data-driven everywhere.** As above but with the opener on for all four. Rejected: the other cities' meeting-type and dollar data has not been reviewed for this copy, and a false first sentence is the one failure this design cannot afford.
- **Birmingham-conditional branch.** The other cities keep today's page behind a template branch. Two page shapes to test and maintain. Not recommended, since the gate above achieves the same protection at lower cost.

The operator approved the first option on 2026-10-19.

## Out of scope but found, to be filed separately

- Six distinct Birmingham records titled "Regular City Council Meeting" in five days (Oct 13 to 18, 2026), including Sunday Oct 18. Birmingham holds one regular meeting a week. These are probably Granicus events mislabelled by the adapter; the opener's "at least one agenda item" rule protects the sentence but the records need fixing.
- The KultureCity item (Jun 23, 2026, #10) reads $7M in its headline and $39.5M in its amount.
- The freshness chip (synced Oct 16) and footer (updated Oct 18) disagree.

## Left to the builder

- Exact copy of each heading and sentence form, within the writing rules.
- Query shapes, indexes, the precompute table, and the worker task's place on the schedule.
- CSS for the opener and the lists, using the existing tokens; the inline styles on today's tiles are replaced by classes.
- Milestone cut. A plausible order: precompute table and task; opener and meetings list; money and disagreed; council and topics; signals and source panel; said at the meeting; accessibility sweep. Each milestone leaves the page rendering for all four cities.
- Tests: a web-tier test per section for its empty, partial, and full states against the throwaway database, and one for the opener's clause-dropping.
