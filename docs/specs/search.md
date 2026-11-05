# Search

What a reader gets at `/search` (`search()` in `src/docket/web/public.py`, rendering `src/docket/web/templates/search.html`): how the typed text is read, which agenda items it returns and in what order, the hidden search card that lets loose words find an item, the spoken moments shown under a result, the transcript lines listed below the results, and the two commands that measure all of it. Present tense. How a transcript reaches the site and what its stages write is `docs/specs/transcripts.md`; the operator's commands for the card stage are in `docs/runbooks/transcripts.md` and `docs/specs/operations.md`.

## What the page searches

The page takes `q`, `city` (a municipality slug, optional), `page`, and `order`, and shows twenty results a page. With a query it does three things in this order. It takes a `speaker:name` token out of the text (`parse_speaker_token` in `src/docket/services/transcripts.py`; `speaker:"Darrell O'Quinn"` for a name with a space), leaving the rest as the words searched. It asks `search_agenda_items` in `src/docket/services/query.py` for the page's agenda items, in the given city or in every active city, never from a hidden meeting. And it reads two kinds of transcript line: the spoken moments of the page's own results, nested under each result, and a lower list of up to ten other transcript lines that hold every typed word. With no query, a city, and `order=amount` the page lists that city's items by dollar amount instead, which `docs/specs/city-page.md` describes; no moment and no transcript line is computed there. A `speaker:` token with no other word returns no agenda items and lists that speaker's lines in the lower list.

Agenda items are searched for every city. Search cards, and so the words a card adds, exist only for Birmingham; spoken moments and the lower list exist wherever a meeting has a public transcript (`uploaded_at` set and status not `low_speech`), which today is Birmingham.

`search_meetings` in the same module is a separate function over meeting titles and is not called by this page; it still requires every word.

## How a query is read

`parse_query` in `src/docket/services/search_query.py` turns the typed text into a `SearchQuery`: a tuple of units, a tuple of excluded words, a recency preference, and the text as given. A unit is one word, one quoted phrase, or one identifier. The parser decides only what kind of unit a token is; stemming, case, and what a hyphen or an apostrophe splits are PostgreSQL's, applied when the statement runs.

The text is split on whitespace, and a run inside double quotes is one phrase unit, whatever it holds: nothing inside quotes is tested against the rules below, and a one-word phrase is still a phrase. A quote that is never closed is ignored and the words after it are ordinary tokens; empty quotes are nothing. Outside quotes, in this order:

- The characters `.,;:!?()[]{}` are removed from both ends of a token, and a token left with no letter or digit is dropped. A hyphen and an apostrophe are never removed. So `rules,` is the word `rules` and `(26-50).` is `26-50`.
- A token that, lowercased, is one of PostgreSQL's 127 English stop words is dropped. The server discards those words from every query, so dropping them changes no result; it keeps "what", "are", and "the" out of the unit slots below. The list is `STOP_WORDS`, a copy of the server's `tsearch_data/english.stop`; the server owns it, and `tests/integration/test_search_ranking.py` asks the test server about every member, so the copy never drops a word the server would have searched for.
- A token whose first character is `-` and whose second is a letter is an excluded word (`-zoning`): an item holding it is not returned. An excluded stop word is dropped, since it would exclude nothing.
- A token whose hyphen-separated parts number at least two and each hold a digit is an identifier: `26-50`, `12-10-46`, `ZAC2025-00012`. `24-hour` is a word, because its second part has no digit, and `-50` is a word.
- Anything else is a word.

Then the three recency words, `new`, `recent`, and `latest` (any case, outside quotes), are taken out of the units and set the recency preference: they ask for newer meetings first and are not searched for. When taking them out would leave no unit they stay as ordinary words and there is no preference, so `new` alone searches for "new". Duplicates of one kind are dropped whatever their case, and the first twelve units are kept (`MAX_UNITS`); words typed after the twelfth are ignored. Excluded words do not count toward the twelve; the first twelve of them are kept (`MAX_EXCLUDED`) and the ones typed after are ignored, because each is a predicate the item search evaluates for every candidate row. A unit's text is kept as typed.

A word goes to the server as `plainto_tsquery('english', ...)`, and a phrase or an identifier as `phraseto_tsquery('english', ...)`, which requires its tokens side by side. Two consequences are the server's and not the parser's. The server reads `26-50` as the tokens `26` and `-50` in a row, which matches "Ordinance No. 26-50" and not an item that holds "26" and "50" apart. And a stop word inside a quoted phrase is not required: `"night out"` is the word "night", because "out" is a stop word.

A query with no unit (the empty string, `the of`, `-zoning` alone) returns no agenda items and runs no statement.

## Which items match, and in what order

An item matches when its `agenda_items.search_vector` matches any unit of the query and none of its excluded words, its meeting is not hidden, and its municipality is active (and is the given city, when one is given). No word is required: one word the item lacks no longer removes it.

The order is the constant `SEARCH_ORDER_SQL` in `src/docket/services/query.py`:

    ident_hits DESC, coverage DESC, [meeting date newest first,] rank DESC, meeting date newest first, item id DESC

`ident_hits` is how many of the typed identifiers the item carries, so an item with a typed ordinance or case number leads whatever else it matches. `coverage` is how many of the typed words and phrases the item matches, each counted once however often it occurs, so items matching all the words come first, then items matching most of them. The bracketed term is present only when the query held a recency word. `rank` is `ts_rank` over the any-unit query. `build_search_sql` writes the statement in two steps so that only the page's rows pay for the wide select: a CTE orders every matching item and keeps the page's twenty, and the outer select joins those back to their item, meeting, municipality, and badges in the same order. `search_agenda_items(query, municipality_slug=None, limit=20, offset=0)` parses the text itself and returns `AgendaItem` rows.

Because any unit is enough to match, a query of several common words ranks most of a city's archive before keeping twenty; the cost is in computing the three terms for each candidate, and it grows with the number of candidates and the size of their vectors. The scale check below is how that is measured.

The page's Next link appears when a page holds exactly twenty results, without a count, so a result set that is an exact multiple of twenty ends on an empty page (issue #66).

## What an item's search vector holds

The trigger function `agenda_items_search_update()` (last replaced by `src/docket/migrations/041_search_cards.py`) fills `agenda_items.search_vector` whenever the item row is written: the title and the headline at weight A; the description, `why_it_matters`, and the counterparty at weight B; the four location fields at weight C; the legacy `summary` at weight D (`D11` in `docs/DEBT.md`); and, when the item has a search card, the card's `search_b` at weight B and `search_c` at weight C. Titles and headlines stay alone at weight A, so a word in an item's own title outranks the same word in its card. One vector and one GIN index (`idx_agenda_items_search`) serve the whole item search.

## Search cards

A search card is one row of `agenda_item_search_cards` per agenda item: hidden text written by a model from the meeting's machine transcript, so that the item can be found by words that were said about it and are not in its agenda text. Nothing in a card is ever displayed. Its words reach search only through the item's vector, and its bounds only choose which of the transcript's own lines a page shows.

Which items have one. An item is placed when at least one non-silence segment of its meeting's transcript is filed under it (`transcript_segments.agenda_item_id`). The card stage writes a card for each placed item of a Birmingham meeting that is not hidden, has a numeric Granicus id, and has a public transcript at `events_extracted` or `compared`, the two statuses that mean the events stage has settled placement. An item nobody placed, an item of another city, and a meeting recorded only on YouTube (a `yt-` row, which has no agenda items, `D76`) have none.

What a card holds. The row carries `transcript_id`, `source_uploaded_at`, `prompt_version`, `model`, `discussed`, the snapped bounds `start_seq` and `end_seq` with their times `start_s` and `end_s` (both bounds or neither), the JSON `card`, and the two search texts. The JSON has six fields:

- `aliases`: up to eight lowercase phrases of one to eight words that a resident who does not know the official name might type.
- `spoken_details`: up to eight specifics said aloud about the item, each a one-line sentence (`text`), the segment it was said in (`seq`), and a `quote` copied from that segment.
- `identifiers`: up to twelve ordinance, resolution, case, contract, or file numbers, each with a `kind`, a `value` of at most 40 characters, and the segment where it was spoken or null when it comes from the agenda text.
- `names`: up to twelve people, organisations, places, or named laws, each with up to six `variants`, the transcript's other spellings of the name.
- `outcome`: one of `passed`, `failed`, `delayed`, `withdrawn`, `recalled`, `referred`, `no_action`, `unclear`, with the segment where it was stated or null.
- `refers_to`: one sentence, with its segment, when speakers tie the item to an earlier or later action on the same matter; otherwise null. No reader uses it yet; it is the input a later plan needs to link items across meetings.

`search_texts` in `src/docket/ai/transcripts/cards.py` builds the two texts from the stored JSON: `search_b` is the aliases, the identifier values, and the names with their variants; `search_c` is the spoken detail sentences, the `refers_to` sentence, and the outcome word unless it is `unclear`.

How a card is written. `run_cards` claims one transcript at a time, newest meeting first, and makes one model call for the whole meeting through `StructuredClient` with the prompt `CARDS_SYSTEM` and the schema `CARDS_SCHEMA` (model `AI_TRANSCRIPT_CARDS_MODEL`). The model reads the transcript one segment a line with a marker block before each placed item's first segment, holding the item's agenda text, description, headline, and summary, and is asked for one card per marker. `validate_cards` then decides what is stored, and counts what it drops:

- A card for an item that is not placed, and a second card for an item, are dropped. A placed item the reply gave no card is counted as missing.
- A spoken detail is kept only when the citation guard (`find_citation` in `src/docket/ai/transcripts/guard.py`, the guard every transcript stage uses) finds its quote in the cited segment or in the text of that segment and the two spoken segments on either side. A quote found beside its cited segment is re-pointed to the segment where the match starts; a quote found nowhere drops the detail and leaves the rest of the card.
- A `seq` counts only when it is a non-silence segment of this transcript; an identifier's, an outcome's, or a `refers_to`'s `seq` that is not becomes null. An identifier value over 40 characters and an alias of more than eight words are dropped, not cut.
- Bounds are kept only when the card says the item was discussed, both are spoken segments in order, the start segment begins no more than ten minutes (`CARD_SNAP_MAX_S`) before the placement's start or after its end, and the end segment ends no more than ten minutes after the placement's end. Otherwise both are null and the card keeps its text. Ranges that overlap are kept as they are: items voted as a block share an ending.

`write_cards` replaces a transcript's cards as a set in one transaction and then runs one `UPDATE agenda_items SET search_vector = search_vector` over the old and new item ids, which changes nothing itself and fires the trigger, so each vector is recomputed with or without its card. It refuses, writing nothing, when the transcript's `uploaded_at` no longer equals the upload the cards were written from.

When a card is current. A card is tied to its transcript by `(transcript_id, source_uploaded_at)` and is current when `source_uploaded_at` equals the transcript row's `uploaded_at`, the one value that changes exactly when a re-upload replaces the segments and the `seq` numbers stop meaning what they meant. After a re-upload a meeting's cards are not current until the card stage has run again: their bounds and cited segments are ignored by every reader, and the excerpt and the moments fall back to the placement. Their hidden search text stays in the item's vector until the stage replaces it, because it describes the same meeting and can only help a reader find the item. A re-run that ends without an upload leaves the old segments and the old `uploaded_at` in place, and the cards stay current.

## Card runs

The stage's bookkeeping is one row per transcript in `transcript_card_runs` (`claimed`, `done`, `failed`, `held`), and the stage never writes the `transcripts` table, so no reader of a transcript's status sees it. A transcript is claimed when it has no run row, or its row describes an earlier upload or an older `CARDS_PROMPT_VERSION`, or its last attempt ended `claimed` or `failed` with fewer than three attempts and 24 hours behind it. Each attempt opens an `ai_runs` row with the stage `transcript_cards`, so `AI_DAILY_BUDGET_USD` applies and `/admin/ai` lists the cost.

How an attempt ends:

- `done`: every placed item has a card. A meeting with no placed item is `done` without a model call.
- `failed` with a `last_error` beginning `incomplete:`: the reply left a placed item without a card. The cards that did validate are written, and the run is retried by the claim's rule, each retry replacing the cards the last one wrote. A reply that carded nothing writes nothing, so the cards already there are not wiped.
- `failed` otherwise: a transient API error, a bug, or `transcript changed during the run` when a re-upload landed during the call.
- `held`: a refusal, a truncated or malformed reply, or a meeting over `TRANSCRIPT_TOKEN_CEILING`. Not retried until a new upload or a prompt bump. A held or failed run raises no alert; it is logged at WARNING and counted by the command below.
- A 429 hands the attempt back and stops the run's loop.

Each validated reply logs one report line, `cards: meeting N transcript N: P placed, C cards (D discussed, M missing, E extra), details K kept R re-pointed X dropped, bounds K kept X dropped, S starts moved 20 s or more, I in O out, $cost`. The worker builds cards for up to `TRANSCRIPT_CARDS_PER_TICK` meetings at the end of each daily `transcript_pipeline` tick, unless the tick's stage loop stopped on the budget or a rate limit, and `scripts/build_search_cards.py` does the same by hand. The tick's card counts are in the pipeline's own summary line, `transcript_pipeline PipelineSummary(... cards_built=N, cards_failed=N)`, where `cards_failed` is failed plus held; the worker task's shorter `transcript_pipeline processed=...` line does not carry them. Its `--count` line is a partition of the public Birmingham transcripts past the events stage: `with current cards` (a run for this upload and prompt that ended `done`), `held`, `failed` (out of attempts), and `waiting` (everything the claim will take, now or once its 24 hours are up).

## Spoken moments

Under a result card the page nests up to three spoken moments: single transcript segments, in the order they were said, each a link to `/al/<slug>/meetings/<id>/transcript/#t-<seq>` with its time, the speaker's name when the site is confident of it, and the transcript's own words with the matched words marked. `moments_for_items` in `src/docket/services/transcripts.py` chooses them for the page's items in one statement.

An item's range is the segments it owns inside the snapped bounds of its current card, when it has one with bounds, and otherwise the segments filed under it that no current card's bounds cover, so a placed item shows moments before any card exists. A moment is a non-silence segment in that range matching at least one unit of the query; a segment matching more of the query's words and phrases leads, then `ts_rank`, then the earlier segment, and the best three are shown. The moments are chosen by matching the transcript's words, never from the card's own sentences, so what is shown is always what the transcript holds. An item with no matching segment has no nested list. A `speaker:` token narrows the moments to that speaker. An excluded word does not affect them.

Where snapped ranges overlap, a segment belongs to one item, the one opened latest: an item's range leaves out any segment inside the range of another current card of the same transcript whose start is later (`SNAPPED_OWNER_SQL`, the one statement of the rule, used by the moments and by the item page's excerpt). Of a block of items read one after another and voted together, each owns its own reading and the last owns the shared vote; an item always owns its own start segment. An item without bounds of its own (its card has none, is not current, or does not exist) gives up any segment filed under it that lies inside the bounds of a current card of the same transcript, and that card's item keeps it (`PLACED_OWNER_SQL`, beside the other statement; decision `0074`). When a neighbour's bounds cover every segment filed under such an item, it shows no moment and no excerpt.

A speaker is named only when the resolved name's confidence is absent or at least `SPEAKER_CONFIDENCE_FLOOR` (0.6); a cluster label such as `SPEAKER_04` never reaches the page. Transcript text is entity-escaped before the server marks it, so markup in a transcript is shown as text.

The item page's "From the video" excerpt (`excerpt_for_item`) reads the same range: its first four speaker turns are taken from the segments the item owns inside the snapped bounds of a current card, so it begins where the item is taken up, and from the segments filed under the item that no current card's bounds cover when there is no such card or the snapped range holds no spoken segment; `docs/specs/transcripts.md` says so where it names the function.

## The lower list

Below the results and their pagination the page lists up to ten more transcript lines under the eyebrow "From transcripts" and the heading "Also said at meetings" (`search_transcripts`, rendered by `partials/search_transcript_hit.html`). These are what the nesting cannot show: public comment, talk before the meeting is called to order, every line of a meeting that has no agenda items, the lines of a `speaker:`-only query, lines inside an item the item search did not return, and the lines of a result that are not among its three moments or lie outside its range.

This list keeps the stricter rule: a line is listed only when one segment holds every typed word (`websearch_to_tsquery`), while the items and the moments match any of them. A `speaker:` token narrows it to that speaker's lines, as it narrows the moments; the filter matches a resolved name whatever its confidence (a trigram match, or the name with its punctuation removed containing the typed text, so `oquinn` finds "Darrell O'Quinn"), and a line found through a name the site is not confident of is printed without the name. The lines nested above are left out in SQL, ahead of the limit of ten, and nothing else is, so a line that holds every typed word is either nested under its result or eligible for this list (decision `0075`). A result with many such lines can therefore take up the list on its page. Each line says where it was said: `during <item title>`, linked to the item and cut to 90 characters, or `outside any agenda item`, then the meeting's title and date and the words "machine transcript".

"During" names the item the segment is filed under, and a segment is filed whole under the item it starts in. A segment that runs across the end of one item into the clerk reading the next can therefore show words about the second item beside the name of the first; the link goes to the transcript at that segment, where both are visible.

## The page's labels

The hero eyebrow reads "Search · agenda items and what was said", and the field's placeholder "Search agenda items and what was said…". Under a result the nested list ends with "What was said at the meeting · machine transcript". The states that could make that sentence false are excluded before the page renders: a hidden meeting never reaches the results, a transcript that is not public yields no range, a card that is not current contributes no bounds, and the amount list computes no moments. "No results" is shown only when there are neither item results nor transcript lines.

## Measuring

The golden check, `scripts/golden_search.py`, asks a deployment of the site 42 loose queries, in 45 query-and-item pairs aimed at 20 known Birmingham items (`tests/fixtures/golden_search/queries.json`; the summary's "targets" are the pairs), and prints one line per pair and a summary:

    venv/bin/python scripts/golden_search.py --base-url https://docket.pub
    golden: 3 of 45 targets on the first page (top 3: 3, top 10: 3, top 20: 3); 0 with spoken moments; 42 queries

That line is the measurement of 2026-11-05 against the site as it was before ranked matching, the cards, and the nested moments were deployed. The check only reads: one request a second at the least (`--delay`, a smaller value is refused), a failed or unreadable page ends it with `golden: fetch failed for <url>` and exit 1, and otherwise it exits 0 whatever the score, because it is a measurement and not a gate. It reads the page's markup: an item is a result when it is linked from a result card after the heading "Refine search", a moment is an `<li class="search-moment" data-item-id="<id>">` holding a link that ends `/transcript/#t-<seq>`, and an item named beside "during" in the lower list is not counted as a result. A change to that heading, those classes, or that attribute changes what the check reads. "With spoken moments" can be above zero before any card is built, since a placed item's filed lines are nested; the first-page count is the one that says what cards added.

The scale check, `scripts/search_scale_check.py --rows 60000`, times the ranked statement on synthetic rows inside a transaction it rolls back, on a disposable database (it refuses a Railway host), and prints one line: the row count, the median and 95th-percentile stored size of the synthetic search vectors, and the slowest of three runs for a rare word, for `late night ordinance`, for four common words, and for those four words with twelve excluded words, the most a query keeps. At 60,000 rows on the development machine the four timings were 2, 358, 449, and 418 ms with a median vector of 3.2 kB (2026-11-05). The line is only as good as the rows it timed: if production's vectors are much larger than its median, it is re-run with a wider `--desc-words`.

## Not built

Facets and sorts other than the amount list (`D22`). Linking items across meetings into one matter with a timeline: a query that names a matter by words said at one meeting does not find the item that acted on it at another, and `refers_to` is stored for the plan that builds this. Embeddings, vector search, and phonetic matching: a name is found under a spelling other than the agenda's only when the transcript itself used that spelling and the card recorded it as a variant. Moments chosen from a card's cited segments when no segment matches the query's words. Cards for other cities and for meetings recorded only on YouTube. The follow-ups are one row of `docs/DEBT.md`.
