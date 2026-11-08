# 0075 — The search page's lower list leaves out only the lines nested above it

## Decision

The lower list of the search page ("Also said at meetings") leaves out the transcript lines the page has nested under its results, by meeting and segment, in SQL ahead of its limit, and no others. A line that holds every typed word is therefore either nested under its result or eligible for the list.

## Rationale

Plan `search-finds-what-was-said` left out every line filed under one of the page's results, so that a much-discussed result could not use up the list's ten (review point C of its revision). But a result nests three moments at most, and only from the segments it owns in its range, so a matching line beyond the three, or filed under the result and outside its range, was on no page and nothing said so; the every-word list the plan replaced had shown them. The closing review found it on seeded rows.

The alternatives were a count under the result, which tells the reader that lines exist and gives no way to read them, and a count linked to a listing of that item's lines, which is a new state of the page. Leaving out only what is nested needs no new surface and makes the page's promise one sentence. Its cost is the one point C avoided: a result with many matching lines can take up the list on its page, pushing lines from elsewhere to the next page.

The trap is "fixing" a crowded lower list by excluding the page's items again, which makes lines unreachable.

## Date

2026-11-05, the operator, asked how the hidden lines should be made reachable, after the closing review of plan `search-finds-what-was-said` (`plans/completed/search-finds-what-was-said.md`, Decision Log); built by Claude on the plan's branch.

## Status

accepted
