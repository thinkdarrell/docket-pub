# City front page: initial suggestions

> **Status:** Initial suggestions, 2026-10-18. Not a design. Written during a brainstorm about the Birmingham city page (`/al/birmingham/`) before any decisions were made.

## The problem as stated

The operator's words: when you first go to a city (Birmingham), "there's a lot of stuff but you're not really directed or given much." The goal is a page that does not just let people find information but presents it, so a reader can go down whatever rabbit hole they choose.

## What the Birmingham page does today

Read from `src/docket/web/public.py` (`_city_overview_render`), `src/docket/web/templates/city.html`, and the live page on 2026-10-18.

- **An inventory, not a front page.** Thirteen stacked sections of roughly equal weight: stats strip, on the agenda, last week, four policy tiles, seven oversight tiles, eleven topic tags, notable dollars, a meetings table, nine member cards, blog, source of truth, about, colophon. Nothing comes first and nothing leads anywhere in particular.
- **The vote sections are switched off.** The route sets `contested` and `recent_votes` to empty lists with a TODO saying they are too heavy for cold loads, so "Contested votes" and "Recent votes" never render. The queries (`list_contested_votes`, `list_recent_votes` in `src/docket/services/query.py`) exist. The front page of a vote-tracking site shows no votes.
- **The rabbit holes exist one click down, unannounced.** The member page has attendance, alignment with majority, a Dissent filter, and item-level voting history. The city page's member cards show only a name and district.
- **Oversight tiles are counts, not stories.** "Hidden on consent 101" says nothing about which item or why it matters.
- **Birmingham rarely splits.** One member page showed 97% alignment with the majority and YEA on every visible row. Contested and Split vote both read zero for the last 30 days. The interesting hooks are the rare dissents, the big dollars, and what went through on consent.

Bugs noticed in passing, outside the redesign:

- The council page's source panel says "0 meetings indexed."
- A member page shows item #3 from 2026-09-15 twice with different outcomes (1 to 6 failed, 7 to 0 passed).
- The KultureCity notable item lists $39.5M while its title says $7M.
- The "contested votes YTD" sub-label on the stats strip renders with no number beside it (as read by the page fetcher; unconfirmed in a browser).

## Survey of civic sites

Loaded: Chicago Councilmatic (home, Divided Votes, Compare Alders), citymeetings.nyc (home), TheyWorkForYou (home). Blocked or unusable: GovTrack (403), Plural / Open States (empty render), Ballotpedia (empty render), LA Metro Councilmatic (DNS failure), TheyWorkForYou member votes page (503). ProPublica Represent is shut down.

- **Chicago Councilmatic.** Hero search, then person (find your ward, compare alders), topic (citywide vs local tag columns), date (upcoming meetings, latest meeting summary), and status (Passed / Active / Referred / Failed badges). Leads with a stat callout about the latest meeting: 1,015 items, 594 non-routine. Main feed is "Non-Routine Activity." Divided Votes lists every vote with a "No" but shows counts only, not who dissented. Compare Alders is a table of tenure, attendance, and non-routine bills sponsored.
- **citymeetings.nyc.** Pitch is "find the 3-minute Q&A or testimony you care about in a 12-hour hearing." Meeting cards carry type labels, plain-language summaries, bulleted topics, and "features testimony from" speaker roundups. Trust signals (press logos, testimonials) and a newsletter.
- **TheyWorkForYou.** Search and per-house entry, then nav by members, debates, votes, interests, upcoming. Recent divisions list on the home page. Email alerts pushed prominently.

## Patterns worth taking

1. **Lead with a sentence, not a stat strip.** Say what happened at the last meeting and what is coming at the next, in plain words.
2. **Separate signal from routine.** We already score items and flag consent, so a "non-routine" feed is within reach and can be better than Chicago's.
3. **Give disagreement its own door.** We have member-level roll calls, so unlike Chicago we can name the dissenters.
4. **Offer a person-first way in.** Show each councilor with one telling number (attendance, dissents, sponsored items) and link to their record.
5. **Make topic tags doors.** Tags on every item turn any row into a jumping-off point.
6. **Point at moments, not just meetings.** Birmingham has transcripts; a segment or quote can be a hook.
7. **Show a way to follow along.** RSS exists but is buried.

Not feasible with current data: find-your-district by address (no GIS), campaign finance.

## Initial direction

The city page works like a briefing rather than a directory.

- It opens with one plain sentence about the last meeting and the next one.
- Then four or five doors, each opened by one real example: the biggest dollar item, the latest vote where someone said no, each councilor with one telling number, the topics with the most activity, a moment from a transcript.
- The inventory of tiles, tag counts, and tables moves lower or onto interior pages.

Caveat: Birmingham rarely splits, so "where they disagreed" will be a short list. That rarity is itself a story; unanimity on a $39M item is news.

Every fact on the page keeps its link to the city's source document (`docs/PRINCIPLES.md`).

## Open questions

- Who lands on the city page first: a resident who just heard something on the news, or someone who already follows the council?
- Which door matters most if only one could be done well?
- Do other cities (no votes, no transcripts) get the same page with fewer doors, or a different page?
- How to make the vote sections cheap enough to render (the TODO in the route), whether precomputed by the worker or cached.
