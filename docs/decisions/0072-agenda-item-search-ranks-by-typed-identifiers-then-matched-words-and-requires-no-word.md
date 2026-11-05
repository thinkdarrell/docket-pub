# 0072 — Agenda-item search requires no word and ranks by typed identifiers, then by how many typed words match, with "new", "recent", and "latest" read as a preference for newer meetings

## Decision

`search_agenda_items` returns every visible item whose search vector matches any unit of the parsed query and orders them by `SEARCH_ORDER_SQL` in `src/docket/services/query.py`: how many typed identifiers the item carries, then how many typed words and phrases it matches, then the meeting date newest first when the query held a recency word, then `ts_rank`, the meeting date, and the item id. The recency words are taken out of the words searched and are never required. PostgreSQL full-text search stays the engine (decision `0003`); this replaces only that record's reliance on `websearch_to_tsquery`'s every-word rule for agenda items.

## Rationale

The rule this replaces required every typed word to be in the item's own text. A resident who remembers a matter in their own words types words the agenda never uses, and one missing word removed the item: on 2026-11-05 the golden check found 3 of 45 known items on the first page of production, and `new late night ordinance` returned one unrelated item from 2013 while the item it meant sat in the archive. A throwaway spike on 12 meetings measured the target in the top ten for 11 of 38 queries with every-word matching plus cards, 20 of 38 with ranked matching alone, and 30 of 38 with both.

Ranking by `ts_rank` alone over an any-word query is the obvious way to drop the requirement, and it is what the spike ran on 732 items. Against the full archive it lets an item that repeats one common word outrank an item that matches three different ones, so the first tiers are counts: the goal's own wording is "items matching all the words first, then items matching most of them", which a count of matched units states directly. Identifiers lead because a typed ordinance or case number is the most specific thing a reader can type and should not lose to an item that happens to match more ordinary words. The recency words are a preference and not words because "new", "recent", and "latest" are not stop words to the server, so under the old rule they were required, and a reader typing "new late night ordinance" means the newest such ordinance, not an item containing "new".

The cost is that a query of several common words makes most of a city's archive a candidate, and the three terms are computed for each before twenty are kept. At 60,000 synthetic rows with vectors of a few kilobytes the worst case took under half a second on the development machine (`scripts/search_scale_check.py`), against a limit of two seconds set before measuring; production's vector sizes and cold-cache time were not measurable from a factory session and are the operator's check after deploy. A candidate cap or a two-pass query was considered for a failing timing and not built, because none failed.

The constants and the order live in one constant and one parser (`src/docket/services/search_query.py`) so the operator can change them with one edit and re-measure with the golden check. The lower list of transcript lines and `search_meetings` keep every-word matching; that is deliberate for the first (a single segment either holds the words or does not) and untouched for the second.

The trap is restoring an every-word requirement because a ranked page shows weak matches below the strong ones: the weak matches are the price of finding the item at all, and the check that says whether the trade is right is the golden check's first-page count, not one query's tail.

## Date

2026-11-04, the operator (the goal's rule) and Claude, in plan `search-finds-what-was-said` (built in its M5 and M6; measured before in its M1; `plans/completed/search-finds-what-was-said.md`).

## Status

accepted
