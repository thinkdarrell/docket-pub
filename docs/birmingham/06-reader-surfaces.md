# 6. What the reader sees, page by page

Every page below is served by the Flask app in `src/docket/web/` (routes in `public.py`, templates in `templates/`), which by rule never runs SQL itself: it calls `src/docket/services/` and renders what comes back. This chapter says what each Birmingham page shows and which chapter of this guide produced it. `docs/specs/city-page.md` and `docs/specs/search.md` own the exact rules for their two pages.

## The map of pages

| Page | URL | Built from |
| --- | --- | --- |
| City page (the front page) | `/al/birmingham/` | chapters 2, 3, 4, 5 |
| Meetings list | `/al/birmingham/meetings/` (`?type=` filter) | chapter 2 |
| Meeting page | `/al/birmingham/meetings/<id>/` | chapters 2, 3, 4, 5 |
| Transcript | `/al/birmingham/meetings/<id>/transcript/` | chapter 5 |
| Item page | `/al/birmingham/items/<id>/` | chapters 3, 4, 5 |
| Badge landing | `/al/birmingham/<badge_slug>/`, e.g. `/al/birmingham/split_vote/` | chapters 3, 4 |
| Council roster, member page | `/al/birmingham/council/`, `/al/birmingham/council/<id>/` | chapter 3 |
| Search | `/search` (`?city=birmingham`, `&order=amount`) | chapters 4, 5 |
| Topics | `/topics/`, `/topics/<topic>/` | chapter 3 |
| Minutes vs. video | `/al/birmingham/minutes-vs-video/` (behind a flag) | chapter 5 |
| Data debt | `/al/birmingham/data-debt`, `.rss` | chapter 4 |
| Source health | `/al/birmingham/source-health/` | chapter 7 |
| How the council works | `/al/birmingham/how-it-works/` (`?journey=` picks the real item followed) | checked-in rules and journeys under `content/how-it-works/birmingham/`, not meeting data; only a journey's links are read from chapters 2 and 5 (`docs/specs/how-it-works.md`) |
| Upcoming hearings feed | `/al/birmingham/upcoming-hearings.rss` | chapter 2 |
| Editorial coverage, blog | `/coverage/`, `/al/birmingham/blog` | markdown in `content/`, not meeting data |
| About, methodology, corrections | `/about/`, `/about/how-we-read-minutes/`, `/about/corrections/` | static |

Not public: `/login`, `/logout`, and everything under `/admin/`. There is no API, and no redirect route for source links: every link to an agenda, minutes PDF, or video is a plain link to the city's own URL (`GOALS.md` Non-goals).

Two things every page shares. A context processor fixes "today" to America/Chicago, so a 7 pm meeting does not become tomorrow's in UTC. The Jinja global `meeting_label` turns a meeting's classification into the name a reader sees ("City Council meeting", "Finance Committee", "… (cancelled)"), so the clip's raw title never appears as a heading (chapter 2).

## The city page

`/al/birmingham/` is the product; the memory note that it is the front page is literal. It is the only city page with the **briefing**, because only Birmingham's `metadata` carries `briefing: true` (`services/briefing.py`; `docs/specs/city-page.md`). It renders in this order, and is cached for five minutes:

1. **Lead**: the eyebrow (council type · county · population), the heading, and a freshness chip linking to source health.
2. **The opener**: two beats of plain prose that **no language model writes**. *Last meeting*: the newest council meeting (not a work session, not upcoming, not cancelled, with at least one item), the number of items it acted on, its largest item by amount if that amount passes the dollar check (chapter 4), and whether any vote split, naming the dissenter when exactly one vote did. *Next meeting*: the next council meeting that is not cancelled and how many items are on its agenda, or "No agenda is posted yet". Sentences are clipped to 25 words; the same text is the page's meta description.
3. A search box scoped to the city.
4. **Where the money went**: the three largest items of the last 90 days from meetings that happened, excluding cancelled meetings and withdrawn items, each with its key figure and whether it passed on consent. "More →" is the amount-ordered search.
5. **Where they disagreed**: up to five split votes of the last 180 days from the precomputed `city_briefing_facts`, each with its tally, "failed" or "tabled" where so, who voted against, and "from the video" when the count came from OCR; or, with no splits, the date of the last one. "More →" is the split-vote badge landing.
6. **The council**: one card per sitting member, "District N" largest, with roll calls attended and times "against the outcome" over the last twelve months, the latter linking to the member's dissent filter.
7. **What they keep dealing with**: the policy badges tracked in Birmingham with their 90-day counts, and the five busiest topics.
8. **Signals in the last 30 days**: counts of process badges such as passed-on-consent, sole-source, emergency action, and settlements; a zero has no row.
9. **Said at the meeting**: one quote, up to 60 words, from the newest public transcript, on that meeting's largest checked item, attributed only when the speaker was resolved; "Read the transcript →".
10. **Recent meetings**: the six newest meetings with an item or a document, each with its label, item count, dollar total, split count, and document links; an upcoming row says "upcoming", a cancelled row says "cancelled" in place of counts.
11. A footer that names the hosts the records came from and how many meetings are indexed.

Three decisions shape its prose: a tabled motion has no outcome, so "against the outcome" counts only a no on a motion that passed or a yes on one that failed (`0057`); a cancelled meeting is read from its title and is never the last or next meeting or a money line (`0058`); and a dollar amount reaches the prose only when the item's own text backs it (`0060`). One rule governs every count on the page: **one vote source per meeting**, the official minutes when the meeting has them, video OCR otherwise, never both (`0056`).

## The meetings list and the meeting page

The list shows twenty meetings a page with a filter row by body (Council, Committees, Planning, Boards, Other) whose counts come from the classification columns (chapter 2).

The meeting page opens with a hero (the label, a chip for the body and one for a special sitting, "upcoming" when so), a strip of three figures (agenda items split consent/regular; votes, with the first vote's source or "none recorded"; total dollars), and, when the label differs from the clip's title, a **provenance line** saying who titled the recording and which rung named the body. Then:

- **Executive summary** (chapter 4), marked "Provisional · minutes not yet adopted" or "Adopted", and "Auto summary — under review" at low confidence. An upcoming meeting says the meeting has not happened yet and shows no summary of decisions.
- **Votes** (chapter 3). When any vote came from video OCR, a callout says so and asks the reader to verify against the video. Each vote block shows the result, a "provisional" or "adopted" chip, its source and confidence ("official minutes · 0.9", "video OCR · 0.7"), the item it is linked to and how (match method and score, "No agenda item linked", or, for a consent vote, the items it covers and the ones pulled for a separate vote), the tally, each member's position, and a "Needs review" callout with the reason when flagged.
- **Minutes vs. video** (chapter 5), behind the `MINUTES_VS_VIDEO_UI` flag.
- **Regular agenda, then consent agenda**, each item as a card (next section). The consent heading says these items passed as a group ("expected to pass" when upcoming).
- **The source rail**: Agenda (primary source), Official minutes, Watch video (naming "Granicus player" or "YouTube (council channel)"), a second "Watch on YouTube" when both exist, Transcript (machine-generated; loaded into the page by HTMX), Original source, and "Other recordings of this meeting".

## The item card and the item page

With `SMART_BREVITY_UI` on (production since 2026-05), every item renders through `partials/smart_brevity_card.html`, which picks a face by the item's state (chapter 4): a **full card** when the AI rewrite is at version 3 or later; a **degraded card** naming what is missing ("OCR needed", "no agenda text", "source empty"); a one-line **procedural row**; "Verification in progress" when the two AI stages disagree; "summary updating" while the item is queued; and a plain title with "processing error" when the pipeline gave up. The full card's shell carries the item number, the primary badge chip, the **dollar chip** coloured by tier (green under $50K, yellow to $250K, orange to $1M, red above; "undisclosed" when the item has financial facts but no amount), the coverage count, the AI headline, and a facts strip. For an upcoming meeting the headline is the raw title and "why it matters" is hidden, because nothing has been decided.

The item page repeats the card's hero, then "why it matters" or the summary with the facts strip, then **From the video** (the transcript excerpt for this item, with timestamps and a link into the full transcript), then the **vote result block**: the result and tally, a "provisional · consent" or "adopted · consent" chip, "manually linked" when an admin linked it, and one source link in order of preference: "Watch this vote on YouTube ↗" or "on Granicus ↗" (the timed link of chapter 5), else "Read minutes ↗", else the vote in meeting context. When there is no vote, the copy says why: the meeting has not happened, the item was withdrawn or procedural, no vote in the minutes could be matched to it, or no vote was recorded. Then related items by topic and sponsor.

## Members and the council

The roster page lists the sitting council. A member page shows attendance, alignment with the majority, and items sponsored, counted through the same one-source-per-meeting rule as the city page (`0066`), with a note saying so and that a vote flagged for review is listed but not counted. Chips switch between all votes, dissent (`AGAINST_OUTCOME_PREDICATE`), and sponsored items; `?since=` narrows the window. Each history row shows the date, the item (or "Consent block — N items"), the tally and result, the source, and the member's position.

## Search, topics, badges

`/search` (chapter 5, `docs/specs/search.md`) returns item cards with spoken moments nested under them, then transcript lines. `?order=amount` with a city and no query is the money page: "Where the money went in Birmingham, last 90 days", checked amounts only. `/topics/` indexes the keyword topics (chapter 3). A badge landing such as `/al/birmingham/split_vote/` shows the badge's description, a tally, a five-year volume timeline whose bars filter by month, a cross-filter by a second badge, and the items, 25 a page.

## Honesty labels, and where their words live

| Label | Where | Means |
| --- | --- | --- |
| provisional / adopted | votes, summaries, item vote block | the minutes these came from have (not) been adopted by the council (chapter 3) |
| official minutes · conf / video OCR · conf | each vote | which document the vote was read from, and the parser's confidence |
| from the video | city page, member page | the count came from OCR because the meeting has no minutes |
| Auto summary — under review | cards, summaries | the AI text's confidence is low |
| Verification in progress | cards | the two AI stages disagree |
| Needs review | votes | the OCR reader flagged this vote, with one of five reasons (`docs/specs/votes.md`) |
| Machine-generated transcript | transcript page, excerpts | ASR output; names assigned by software may be wrong |
| Speaker N / Unknown speaker | transcripts | the speaker was not resolved with enough confidence |
| provisional · minutes not yet adopted | executive summary | as above |

Three pages state the policy in words a reader can quote: `/about/how-we-read-minutes/` (sources, pipeline, the honesty protocol, transcripts, limits), `/about/corrections/` (what counts as an error, that a discrepancy is preserved and annotated rather than rewritten), and `/al/birmingham/data-debt` (every item not yet machine-readable, grouped by priority, and every meeting with video but no usable transcript, "listed publicly so the gap stays honest"). The footer colophon on every page: every figure is hyperlinked to its original document, and where automated extraction disagrees with the minutes, both readings are preserved.

## Behind the page

- **Analytics**: a self-hosted Umami tracker, cookieless, with two custom events (`outbound_source_click`, `search_submit`) and a guard that drops long string properties; the operator reads it only through the `v_*` views (`0024`, `docs/runbooks/analytics.md`).
- **Security**: HSTS without subdomains (`0025`); Secure, HttpOnly, SameSite cookies outside development; CSRF on every admin form. `source_security.py` is an allowlist for source-anchor URLs (Granicus, CivicClerk, CivicPlus, YouTube, Vimeo, and each city's own host) whose one calling partial no current template includes.
- **Styling**: `styles.css` (tokens), `layout.css`, `councilmatic.css`, `tweaks.css`, `css/smart_brevity.css`, and `mobile.css` last with one 768 px breakpoint; IBM Plex Sans, JetBrains Mono, Source Serif 4; HTMX 2 for the transcript tab and the badge-landing filters.

Next: [7. Where it runs, and the daily rhythm](07-operations.md).
