# City page less narrow, less dense: two-tier door rows with a mono key figure, two two-column bands from 900px, and trimmed topics and council copy

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

The Birmingham city page, `https://docket.pub/al/birmingham/` (the route `city_overview` in `src/docket/web/public.py`, the template `src/docket/web/templates/city.html`, the service `src/docket/services/briefing.py`, described in the present tense by `docs/specs/city-page.md`), is ten stacked sections of one-line list items. The operator's review measured the live page at ten stacked sections, about 5,200 visible characters, and 76 links, with disagreement rows of up to 184 characters that wrap to three lines inside the lists' 68-character cap on a desktop and to five or six lines on a phone. Every list sits in a column 68 characters wide while the page's main column is 1,200 pixels, so on a desktop the page reads as a narrow strip down the left; and every row packs its amount, headline, date, names, and labels into one run of text, so it reads dense at every width.

After this plan a reader opening the same page sees the same ten sections and every link the page carries today (one deliberate exception, the example headline each topic line carries, which the operator's own goal drops), laid out so that it is wider on a desktop and lighter everywhere. Three changes, each shipped on its own and each visible on its own. (A) Every row of "Where the money went", "Where they disagreed", "What they keep dealing with", and "Signals in the last 30 days" becomes two-tier: a key figure at the left in the monospace face (the dollar amount in a compact form, "$10.1M"; the vote tally, "8–1", with "1–6 failed" in the page's bad tone and "5–4 tabled" plain; the count, "3 items"), the linked headline beside it, and a muted 13-pixel second line under the headline holding the date, then the dissenters' names, then "from the video" or "passed on the consent agenda" where today's line says them; on a phone the money and disagreement rows put the key figure and the date on one small line above the headline, while the count rows of topics and signals keep the key beside the name. The "Recent meetings" list already has this shape and does not change. (B) From 900 pixels of viewport width, money and disagreed share one two-column band and topics shares a second band with signals over the "Said at the meeting" quote; below that width they stack as today. The opener, the search label, and the quote keep their 68-character cap because they are prose; the lists lose it. (C) The topics door shows each tracked priority and each busiest topic as its count and its linked name, with the window stated once in the sub-label and no example headline; the council card's two stats shorten to "Attended 121 of 121 roll calls" and "Against the outcome 2 times" with "Roll calls counted over the last 12 months." stated once under the grid; and on a phone the city page's council renders as nine rows (initials square, district, name, the two numbers) instead of nine three-column tiles. Section order stays as it is except that signals moves up beside topics, so the order becomes money, disagreed, council, topics, signals, said, meetings, blog.

How to see it working: `./tools/verify` passes at the end of every milestone with the city page's tests rewritten to the new markup; `venv/bin/flask --app docket.web:create_app run` against a database seeded by `tests/support/briefing_seed.py` plus `briefing.recompute_city_facts` renders `http://127.0.0.1:5000/al/birmingham/` with the rows, bands, and copy this plan describes; and the operator, who alone has a browser in this workflow, records in Surprises & Discoveries what the page looks like at 1,200, 900, and 375 pixels after each milestone merges.

## Progress

- [x] (2026-10-21 14:02Z) M1: `compact_dollars` in `src/docket/web/filters.py` with its unit tests, "Where the money went" and "Where they disagreed" rows in the two-tier shape (mono key figure, linked headline, muted second line; key and date on one line at phone width) with their CSS in `layout.css` and `mobile.css` and the `--space-5` token in `styles.css`, the money and disagreement assertions of `tests/web/test_city_briefing.py` rewritten with one new failed-and-abstained test, the vacuous `upcoming` assertion replaced and the `D62` row shortened, and `docs/specs/city-page.md` describing the two doors' rows
- [ ] M2: "What they keep dealing with" and "Signals in the last 30 days" rows in the two-tier shape with the example headline dropped and the window in the sub-labels, `city.html` wrapping money with disagreed and topics with signals-over-said in two bands that sit side by side from 900px with signals moved beside topics, the `.brf-door` 68ch cap removed with the quote keeping its own, one new band-order test, `DESIGN_HEADINGS` and the topics, signals, and integration assertions rewritten, and `docs/specs/city-page.md` describing the order, the bands, and the two doors' rows
- [ ] M3: the council card's two stats reading "Attended <a> of <r> roll calls" and "Against the outcome <n> times" with "Roll calls counted over the last 12 months." once under the city page's grid, the city page's council rendering as nine rows at phone width in `mobile.css` while `/al/<slug>/council/` keeps its tiles, the council assertions of `tests/web/test_city_briefing.py` and `tests/web/test_partials_visual_refactor.py` rewritten, and `docs/specs/city-page.md` describing the card

## Surprises & Discoveries

- Observation: nothing has been executed yet; this section holds what the authoring research found that the goal and the brief did not say.
  Evidence: authoring session, 2026-10-21 03:00Z by the machine's clock, in the worktree `.claude/worktrees/city-page-less-narrow-less-dense` cut from `origin/main` at `6225346` (the merge of pull request #131).
- Observation: the worktree was cut without the gitignored `.env` that `D57` in `docs/DEBT.md` says every worktree on this machine needs, so the first `./tools/verify` printed `test-db: building docket_test_63e81421 on postgresql://docket:docket_dev@localhost:5432`, `ERROR:  permission denied to create database`, and `verify: 6 of 6 checks failed in 0s`. The author wrote `.env` with the one line `DATABASE_URL=postgresql://thinkdarrell@/docket_db`, after which `git status --porcelain` still printed nothing (`.gitignore` line 8 is `.env`) and the second run passed. Every milestone session depends on that file; Concrete Steps says how to recreate it.
  Evidence: the two verify runs, 2026-10-21; the second printed `verify: test-db ... ok (1s) postgresql://thinkdarrell@/docket_test_63e81421`, `verify: unit+web+services ... ok (56s)`, `verify: integration ... ok (46s)`, `verify: judge-fixtures ... ok (1s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (1s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 105s.`, with the tier lines `1987 passed, 5 skipped, 4 xfailed, 1 warning in 55.32s`, `631 passed, 1 warning in 46.20s`, `judge fixtures: 12 of 12 passed`, `84 passed in 0.94s`, and `plans: no active plans`.
- Observation: the token `--space-5` that `layout.css` uses twice on this page (`.brf-head { margin: var(--space-5) 0 var(--space-3); }` at line 1388 and `.brf-search { margin: 0 0 var(--space-5); }` at line 1360) is defined nowhere: `styles.css` declares `--space-1` (4px), `-2` (8px), `-3` (12px), `-4` (16px), `-6` (24px), `-8`, `-12`, `-16` and no `-5`, and no other stylesheet declares it. A `var()` of an undefined custom property with no fallback makes the declaration invalid at computed-value time, and `margin` is not inherited, so both margins compute to zero: every section heading on the page sits with no space above it, and the search field has none below. That is part of why the page reads dense, and it is paid in M1 by declaring the token.
  Evidence: `grep -rn 'space-5' src/docket/web/static/` printed only the two `layout.css` lines; `grep -n 'space-5' src/docket/web/static/styles.css` printed nothing.
- Observation: the brief's file list misses `tests/integration/test_f4_browse_by_priority.py`, whose `test_city_page_links_four_priorities_under_topics_door` (line 441) asserts each priority's example headline (`Priority-<slug>`) and `door.count("1 item since") >= 4`, and whose `test_city_page_signal_line_shows_count` (line 488) matches the label and the count inside one `<a>`. Both are rewritten in M2 with the signals and topics markup; the integration tier runs inside `./tools/verify`.
  Evidence: `grep -n 'brf-' tests/integration/test_f4_browse_by_priority.py` printed lines 427, 437, 457, 475, 498.
- Observation: the baselines the acceptance counts from, against the throwaway database `docket_test_63e81421` built with `tools/test-db` and dropped afterwards: `tests/web/test_city_briefing.py` printed `58 passed in 8.35s`; `tests/web/test_city_briefing_a11y.py` `8 passed`; `tests/web/test_partials_visual_refactor.py` `42 passed`; `tests/unit/test_dollar_tier.py` `71 passed`; `tests/integration/test_f4_browse_by_priority.py` `35 passed`; `tests/web/test_city_overview_render.py` `10 passed, 1 skipped`; `tests/web/test_card_navigation.py` `12 passed`; the five files the milestones edit together (`test_city_briefing.py`, `test_city_briefing_a11y.py`, `test_f4_browse_by_priority.py`, `test_partials_visual_refactor.py`, `test_dollar_tier.py`) printed `214 passed in 12.83s`.
  Evidence: the runs above, 2026-10-21, with `DATABASE_URL` exported at the throwaway database.
- Observation: the seeded page's link inventory, the list every milestone's acceptance diffs against (Artifacts and Notes holds the script): 55 `href` values between `<main` and `<aside class="page-sources"`, ids normalised to `N`, among them ten `/al/birmingham/items/N/` (the opener's largest item, the money door's one line, the disagreement door's clause, the topics door's six example headlines, and the transcript door's item), eleven `<section ` tags, and 3,490 visible characters. The seed is smaller than the live page (one past meeting of four items), so these numbers are a local baseline, not the review's 5,200 and 76.
  Evidence: the script's output, 2026-10-21, reproduced in full under Artifacts and Notes.
- Observation: the existing `format_dollars` filter cannot serve as the key figure: it prints `$50.0M` for 50,000,000 and `$1200.0M` for 1,200,000,000, and its docstring says the `.0` is deliberate; `briefing.amount_in_words` prints `$50 million`, which is the prose form the opener needs, not a key figure, and rounds 999,950,000 to `$1000 million` (`D62`, second item). So a third formatter is written, `compact_dollars`, that chooses the unit after rounding.
  Evidence: `venv/bin/python -c` over both functions printed `50000000 $50.0M $50 million`, `1200000000 $1200.0M $1.2 billion`, `999950000 $1000.0M $1000 million`, `1050000 $1.0M $1.1 million`; the arithmetic the plan prescribes printed `$50M`, `$10.1M`, `$850,000`, `$1.2B`, `$1B`, `$1M`, `$1.1M`, `$2.3M`, `$10M` for the inputs Interfaces and Dependencies lists.
- Observation: the approved mockup at `.superpowers/brainstorm/1841146-1792550756/content/layout.html` is gitignored (`.gitignore` line 30, `.superpowers/`) and absent from this worktree, so no session can open it; this plan embeds the measurements, forms, and markup shapes it relies on and names the file nowhere else.
  Evidence: `ls .superpowers/brainstorm/1841146-1792550756/content/` in the worktree printed nothing.
- Observation: on this machine `grep -c <pattern> <file1> <file2>` prints one `<file>:<count>` line per file, and recursive `grep -rn` prints paths without a `./` prefix (the development machine's grep is ugrep), so every count in Validation and Acceptance names one file per command or reads the per-file lines.
  Evidence: `grep -c 'brf-key' src/docket/web/templates/partials/briefing/door_money.html ...` printed four `<path>:0` lines.
- Observation: M1 session, 2026-10-21 13:55Z by the machine's clock, on `86b0573`. The starting `./tools/verify` printed `verify: all 6 checks passed in 102s.` (tier lines `1987 passed, 5 skipped, 4 xfailed, 1 warning in 53.79s`, `631 passed, 1 warning in 45.72s`, `judge fixtures: 12 of 12 passed`, `84 passed in 0.70s`, `verify: plans ... ok (0s)`); `.env` was already present with the one `DATABASE_URL` line and `git status --porcelain` printed nothing. The new tests were committed failing before any template or filter change: `pytest tests/web/test_city_briefing.py -k failed_tone` printed `1 failed, 58 deselected in 0.66s`, the row count of three passing and the first failing assertion being `'<span class="brf-key t-mono brf-key--bad">1–6 failed</span>' in door` (line 889); `pytest tests/unit/test_dollar_tier.py -k TestCompactDollars` printed `12 failed, 71 deselected`, every case with `ImportError: cannot import name 'compact_dollars' from 'docket.web.filters'`. The unit test imports the function inside the test method, as every other test in that file does, so the module still collects while the filter is absent.
  Evidence: the runs above against `docket_test_63e81421`, 2026-10-21 14:0xZ.
- Observation: M1 acceptance, observed after the code change (commit after `9b5a532`): `pytest tests/web/test_city_briefing.py tests/unit/test_dollar_tier.py -q -p no:cacheprovider` printed `142 passed in 9.32s`; the filter one-liner printed `$50M $10.1M $850,000 $1.2B $1B ` (the trailing empty string for `None`); `grep -c 'brf-key t-mono'` printed `1` on `door_money.html` and `1` on `door_disagreed.html`; `grep -n 'space-5' styles.css` printed `66:  --space-5:  20px;`; the `brf-amount` grep over `layout.css` and `door_money.html` printed nothing (exit 1); the `D62` grep printed one line containing `Two small defects` and none containing `cannot fail`; `git diff --stat origin/main -- src/docket/services` printed nothing; the link inventory script printed the authoring list unchanged, `links: 55 sections: 11 chars: 3476` (chars down from 3,490, the dropped "million" words and " — " separators). A render with the new test's two extra votes printed, by eye, `<span class="brf-key t-mono">8–0–1</span>` with the rest span `<a href="/al/birmingham/council/8/">Sonja Q. Smith</a> abstained`, `<span class="brf-key t-mono brf-key--bad">1–6 failed</span>` with `against: ` and six linked names, and `<span class="brf-key t-mono">8–1</span>` with `against: <a ...>Hunter Williams</a>`; the rest span opens and closes with no stray whitespace, so the Jinja trimming in the partial holds.
  Evidence: the runs above against `docket_test_63e81421`, 2026-10-21 14:1xZ.
- Observation: the closing `./tools/verify` of M1, after `a0d8171` with the database dropped first, printed `verify: all 6 checks passed in 102s.`, with `2000 passed, 5 skipped, 4 xfailed, 1 warning in 53.45s` (1,987 at the start plus the twelve `compact_dollars` cases and the one disagreement test), `631 passed, 1 warning in 46.46s`, `judge fixtures: 12 of 12 passed`, `84 passed in 0.70s`, and `verify: plans ... ok (0s)`.
  Evidence: the run, 2026-10-21, logged at the session's scratchpad `verify-end.log`.
- Observation: correction to the two M1 entries above: the times written as `14:0xZ` and `14:1xZ` were estimates; the machine's clock printed `13:55Z` at the session's start and `14:02Z` at the tick, so every run between them, the acceptance runs included, happened between 13:57Z and 14:02Z.
  Evidence: `date -u` at the start (`2026-10-21 13:55Z`) and at the tick (`2026-10-21 14:02Z`).

## Decision Log

- Decision: the plan is cut into three milestones that follow the operator's (A), (B), (C) only loosely: M1 is (A) for the money and disagreement doors with the new filter; M2 is (A) for the topics and signals doors together with (C)'s topics trim and all of (B); M3 is (C)'s council copy and phone list.
  Rationale: (A) and (C) both rewrite the topics door's rows (first into the two-tier shape with the example on the second line, then dropping the example), so an (A)-then-(C) cut edits the same template and the same six assertions twice; cutting at the door instead edits each once. (B) is small (two wrapper `<div>`s, one `@media` block, one reordered list in the accessibility test) and shares `city.html` with the signals move, so it rides with M2. Each milestone still ships on its own: after M1 two doors are two-tier and the rest unchanged; after M2 every list is two-tier and banded; after M3 the council is trimmed.
  Date/Author: 2026-10-21, plan author (Claude, under `cycle-plan`), from the operator's goal.
- Decision: the key figure is a `<span class="brf-key t-mono">` placed first inside each `<li class="brf-door-line">`, the headline an `<a class="brf-row-link">`, the date a `<span class="brf-row-date">`, and whatever follows the date a `<span class="brf-row-rest">` rendered only when it has content; the row is a CSS grid on the `<li>`, with the areas `"key head head" / "key date rest"` on a desktop and `"key date" / "head head" / "rest rest"` at phone width, and the separator between the date and the rest is CSS-generated (`::before`), while the separators inside the rest are literal ` · ` in the markup.
  Rationale: the phone layout has to pull the date up beside the key and leave the dissenters under the headline, which needs the date and the rest to be separate elements; a grid on the row does that with no change to the markup between widths, which is why the separator between them cannot be literal (it would print on the phone's date line and again at the start of the rest). The test assertions therefore match the pieces, never the dot between them. The `t-mono` utility already exists in `styles.css` (line 121, with tabular numerals), so the mono face comes from it and `brf-key` carries only the layout.
  Date/Author: 2026-10-21, plan author.
- Decision: the key column is a fixed width per door, a custom property `--brf-key-w` set on the row (default `11ch`, `9ch` on the money, topics, and signals doors), not a per-row `max-content` column and not a subgrid.
  Rationale: rows are separate `<li>` grids, so only a fixed width aligns the headlines down a list; `max-content` would stagger them and a subgrid on the `<ul>` would size the column to the list's longest key, which the disagreement door's "10–0 failed" style keys make ten characters anyway. The widths are the longest key each door prints plus one character: `$850,000` and `128 items` are eight and nine characters, `5–4 tabled` and `1–6 failed` ten.
  Date/Author: 2026-10-21, plan author.
- Decision: the tally is written `<y>–<n>` with en dashes, `–<a>` appended when abstentions are above zero, and the stored result appended as a word only when it is not `passed` (`1–6 failed` in the bad tone through the extra class `brf-key--bad`, `5–4 tabled` plain); a passed vote's key carries no word.
  Rationale: the operator's goal gives the forms ("vote tally for disagreements with a failed vote in the bad tone"), and the section's heading already says these are the votes where the council disagreed, so "passed" is the default a reader assumes and the two exceptions are what the key must say; decision `0057` (a tabled motion has no outcome) is kept by printing the stored word and never substituting another, exactly as `briefing._result_verb` does today. The unanimity sentence of the same door ("The last split was ... 7 to 2") is prose, not a row, and keeps its words.
  Date/Author: 2026-10-21, plan author.
- Decision: the second line of a disagreement row writes nays as `against: <names>` and abstainers as `<names> abstained`, each resolved name still a link, in that order, then `from the video`; a split with no roll call has a date and nothing else.
  Rationale: the brief's forms; "against:" reads as the row's own label where today's bare comma list needs the sentence around it, and an abstainer named after the word "against" would be misread, so abstainers get their own clause.
  Date/Author: 2026-10-21, plan author.
- Decision: the count keys of the topics and signals doors carry their unit, `<n> item` or `<n> items`, and the topics sub-labels read `Tracked in <City> · since <Month D>` and `Busiest topics · since <Month D>`; a quiet priority (no item in the window) prints `0 items` as its key and `last item <Month D, YYYY>` in the date slot of its second line, with its name still linked to its landing page.
  Rationale: the signals door has no sub-label to carry the unit, so a bare `3` beside "Legal settlements" would leave the reader to guess what is counted, and the two doors sit side by side in one band from M2, so their keys take one form. The brief read the mockup as putting "last item <date>" in the count's place; a twelve-to-twenty-four character date in the key column would widen every row of the list, and the council card already prints a zero ("Against the outcome 0 times"), so the zero is printed as a count and the date goes where dates go on every other row. The existing test `test_topics_door_quiet_priority_shows_last_item` still finds `last item <Month> <D>, <YYYY>` in the row.
  Date/Author: 2026-10-21, plan author.
- Decision: the bands are two `<div class="brf-band">` wrappers in `city.html`, laid out from 900px by `grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr)`, so one child takes the full width and two children split it; the second band's right column is a `<div class="brf-band-col">` holding signals then the quote, rendered only when `signals or said` is set, so an absent pair leaves no empty column.
  Rationale: any door may be absent (a section with nothing to show renders nothing, `docs/specs/city-page.md`), and a fixed `1fr 1fr` template would leave a lone money door in the left half; implicit columns size to whatever children exist. `repeat(auto-fit, minmax(0, 1fr))` does not do this, because a zero minimum resolves to one repetition. The threshold is `min-width: 900px` in `layout.css`, separate from the phone layer's `max-width: 768px` in `mobile.css`, because the goal says "about 900px" for the bands and "on phones" for the rows; between 769 and 899 pixels the rows are desktop two-tier and the bands stack.
  Date/Author: 2026-10-21, plan author.
- Decision: `compact_dollars` is a new filter in `src/docket/web/filters.py`, registered in `filters.register`, that formats through `_coerce_amount` like `format_dollars` and chooses the unit after rounding to one decimal (`$1B`, not `$1000M`, for 999,950,000); `format_dollars` and `briefing.amount_in_words` are not changed, and `src/docket/services/briefing.py` is not edited.
  Rationale: `format_dollars` is depended on by the dollar-tier partial and item cards with a documented `.0`; `amount_in_words` is the opener's prose form and the meta description's; neither prints the approved `$50M`. Keeping `briefing.py` untouched keeps `D60` (five sentences to take in one milestone) and `D61` (the NULL-date guard) from tripping, which would turn a template-and-CSS plan into a service change; every value the new markup needs is already in the template context (`amount`, `yeas`, `nays`, `abstentions`, `verb`, `dissenters`, `from_video`, `count`, `latest.date_long`, `briefing.attended`, `roll_calls`, `against`, `dissent_href`).
  Date/Author: 2026-10-21, plan author.
- Decision: the `--space-5` token is declared in `styles.css` as `20px` in M1 rather than the two `layout.css` rules being rewritten to `--space-6`.
  Rationale: the rules were written to a 20-pixel step between `--space-4` (16px) and `--space-6` (24px) that the scale skipped; declaring it gives the author's intended spacing and leaves the rules alone, and the fix belongs to the milestone that first edits the page's CSS.
  Date/Author: 2026-10-21, plan author.
- Decision: the council's phone list is scoped to `.brf-council` (the city page's section) in `mobile.css`, so `/al/<slug>/council/`, whose section carries only `council`, keeps its three-column tiles; the dissent link in a phone row is an inline block with four pixels of vertical padding, and the 44-pixel `min-height` of `.cc-stat` is dropped inside the list.
  Rationale: the goal names the city page only. The row's whole area is already the member link (stretched over the card by `.cc-link::after`), so the tap target the 44-pixel rule protected survives; the dissent link is the row's one secondary target and keeps a padded hit area without forcing two 44-pixel lines into each of nine rows.
  Date/Author: 2026-10-21, plan author.
- Decision: the "Roll calls counted over the last 12 months." sentence is one `<p class="brf-council-note">` under the grid in `city.html`, rendered when any member carries counts, with no link.
  Rationale: the mockup's "How these are counted →" link has no destination page (the member page holds only an inline counting note); a link to nowhere is out of scope by the brief, and a sentence with no counts under it would say nothing, so the facts-row-absent state omits it.
  Date/Author: 2026-10-21, plan author.
- Decision: the third item of `D62` (the assertion that cannot fail) is paid in M1 by replacing `assert "upcoming" in section` with `assert "<span>upcoming</span>" in section`, the row keeps its other two items, and no debt row is added by this plan; no decision record is planned for `docs/decisions/` at completion.
  Rationale: `D62`'s trigger is the next touch of `tests/web/test_city_briefing.py`, which M1 is, and the replacement is the markup the upcoming row prints (`<span>upcoming</span>`, already asserted at line 748), which the follow line's "upcoming hearings (RSS)" cannot satisfy. The layout choices here are described by `docs/specs/city-page.md` in the present tense and bind nothing an agent would confidently revert; the retro may disagree. The last spent ids on `origin/main` are `D73` and `0066`, and `gh pr list --state open` printed nothing on 2026-10-21 (the check `D70` asks for), recorded here in case a later revision needs a number.
  Date/Author: 2026-10-21, plan author.
- Decision: the operator's visual check at three widths is an operator step after each milestone merges and deploys, recorded in Surprises & Discoveries, not an acceptance clause a session runs.
  Rationale: a factory session has no browser; the acceptance it can run is the rendered markup, the stylesheet text, and the tests, and a plan that names a command the session cannot run costs a divergence instead of a check (`skills/plan-author/SKILL.md`, step 8).
  Date/Author: 2026-10-21, plan author.

- Decision: the desktop row has `column-gap: 0`; the key column is `calc(var(--brf-key-w) + var(--space-3))` with that `--space-3` as the key's right padding, and the separator before the rest span is `"\00a0· "` (a no-break space, then the dot). The default `--brf-key-w` is `12ch`, not `11ch`.
  Rationale: the operator's external review of this plan (2026-10-21) found that with `column-gap: var(--space-3)` the gap falls between the date (column 2) and the rest (column 3) as well as after the key, so a second line printed as "October 14", twelve pixels of nothing, then "· against: ...": a chasm before the dot and a normal space after it. Moving the gap into the key column keeps the headline where it was and lets the date and the rest sit flush, with the no-break space giving the dot its own even spacing. The review also noted that a failed or tabled vote can carry an abstention ("4–4–1 failed", twelve characters), which an eleven-character column would overflow; one character more costs about nine pixels in each list. Two of the review's other suggestions were not taken: `align-items: baseline` (the key spans both grid rows, and a multi-row item's part in baseline alignment is not something to rely on, so the hand-set one-pixel top padding stays), and its claim that single-line rows lose twelve pixels to the gap between columns 2 and 3 (the headline spans both tracks, and a spanning item's width includes the gap it crosses, so nothing is lost; the only cost on a single-line row is the two-pixel row gap before an empty second row, which is left as it is).
  Date/Author: 2026-10-21, the operator (Darrell Nance) by external review; applied by Claude.
- Decision: the phone stacking (`"key date" / "head head" / "rest rest"`) applies to the rows of `.brf-door-money` and `.brf-door-disagreed` only; the rows of the topics and signals doors keep the desktop grid at phone width, the key column beside the name, and a quiet priority's "last item <date>" sits under its name in the date slot.
  Rationale: the same review found that a row with no date (every active priority, every busiest topic, every signal) would put its key alone on the first line and the name on the second under the unscoped phone rule, doubling the height of two lists whose rows are one short name each. The review offered `.brf-door-line:has(.brf-row-date)`; scoping by door is chosen instead because it needs no `:has()` support, reads as the doors' own rule, and gives the topics door one shape at phone width whether or not a priority is quiet. The phone `.brf-key` rule keeps only the 13-pixel size; the stacked doors zero the key's padding, since their phone grid carries its own `column-gap`.
  Date/Author: 2026-10-21, the operator by external review; applied by Claude.
- Decision: each `<div class="brf-band">` in `city.html` is guarded by the condition under which at least one of its sections renders: `{% if money or disagreed %}` and `{% if (topics_door and (topics_door.priorities or topics_door.topics)) or signals or said %}`.
  Rationale: the review noted that an unguarded wrapper renders an empty `<div>` for a city with nothing in either door (the `tests/web/test_card_navigation.py` fixtures, a newly onboarded city). Today that div has no height, but `docs/specs/city-page.md` says a section with nothing to show renders nothing, and the guard keeps that true of the wrappers too; the `facts` fixture renders every door, so the band-order test and the `grep -c` of two bands are unchanged.
  Date/Author: 2026-10-21, the operator by external review; applied by Claude.
- Decision: `compact_dollars` drops a trailing `.0` with `str.removesuffix(".0")` rather than `.rstrip("0").rstrip(".")`.
  Rationale: the review observed that the `rstrip` form is correct only because the quantized value always carries a decimal point; fed an integer string it would turn `"50"` into `"5"`. The suffix form prints the same nine strings on the plan's cases (checked 2026-10-21) and cannot do that, and Python 3.10 has it.
  Date/Author: 2026-10-21, the operator by external review; applied by Claude.
- Decision: `TestCompactDollarsFilter` imports `compact_dollars` inside its one test method rather than at the top of `tests/unit/test_dollar_tier.py`.
  Rationale: Plan of Work says "importing the function directly"; a module-level import would have made the whole file fail collection (71 existing tests) while the filter was absent, so the before state could not have been committed as "12 failed" beside the rest passing. Every other test in the file imports its filter inside the method, so this follows the file's convention and the plan's intent (the function, not the Jinja environment, is what is tested).
  Date/Author: 2026-10-21, M1 session (Claude, under `cycle-run`).

## Outcomes & Retrospective

M1 (2026-10-21 14:02Z): the money and disagreement doors are two-tier on the seeded page, every acceptance clause of M1 under Validation and Acceptance was run and printed what it says, and no carve-out was needed. What exists now that did not: `compact_dollars` in `src/docket/web/filters.py` with its twelve-case unit test; the money rows as `$10.1M` key, linked headline, and a dated second line; the disagreement rows as `8–1`, `1–6 failed` (bad tone), `5–4 tabled`, or `8–0–1` keys with `against: <names>`, `<names> abstained`, and `from the video` on the second line; the row grid in `layout.css` and the phone stacking for those two doors in `mobile.css`; the `--space-5` token the section headings were silently missing; `D62` reduced to two items; and `docs/specs/city-page.md` describing the rows. Still to come: M2 (topics and signals rows, the two bands, the section order) and M3 (council copy and phone list), and the operator's visual check at 1,200, 900, and 375 pixels after this milestone deploys. Lesson: committing the new tests failing before the change cost one extra commit and gave a before state readable from `9b5a532`; a module-level import of the new filter would have hidden that state behind a collection error, which is why the test imports inside the method.

The closing entry, written when M3 completes, compares the page against the purpose above: the same sections and links, two-tier rows, two bands from 900 pixels, and the trimmed topics and council copy.

## Context and Orientation

The repository is a Python 3.10 Flask application; `AGENTS.md` is its map. The city page is served by `city_overview` in `src/docket/web/public.py`, which calls `src/docket/services/briefing.py` for every list and passes the results to `src/docket/web/templates/city.html` as `opener`, `money`, `disagreed`, `members` (each with a `briefing` key from `briefing.council_cards`), `topics_door`, `signals`, `said`, `briefing_meetings`, and `blog_posts_for_city`. `city.html` includes the partials under `src/docket/web/templates/partials/briefing/` (`opener.html`, `search.html`, `door_money.html`, `door_disagreed.html`, `door_topics.html`, `door_said.html`, `signals.html`, `meetings.html`) and, for the council, `partials/council_card.html`, which `templates/council.html` (the page `/al/<slug>/council/`) also includes. The page's CSS is the `brf-` block of `src/docket/web/static/layout.css` (lines 1345 to 1447 today) and its phone rules in `src/docket/web/static/mobile.css` inside the `@media (max-width: 768px)` block that starts at line 609; the council card's CSS is `layout.css` lines 388 to 438 (`.council-grid`, `.cc`, `.cc-portrait`, `.cc-body`, `.cc-stats`, `.cc-stat`, `.cc-dissent`) with its phone tile rules at `mobile.css` lines 157 to 208. The design tokens (`--ink`, `--ink-2`, `--ink-3`, `--rule`, `--accent`, `--bad`, `--font-mono`, the `--space-*` scale) and the utility `.t-mono` are in `src/docket/web/static/styles.css`. `base.html` loads `styles.css`, then `layout.css`, `councilmatic.css`, `tweaks.css`, `css/smart_brevity.css`, and `mobile.css` last; none of the later sheets names a `brf-` or `cc-` class, so a rule in `layout.css` or `mobile.css` is the last word. The main column is `.app-main { max-width: 1200px; padding: 0 56px }` (`layout.css` line 5), `0 32px` under 1,280 pixels.

Today's rows, as the partials print them. Money (`door_money.html`): one `<a>` holding `<span class="brf-amount">$10.1 million</span> — <headline> · October 14[ · passed on the consent agenda]`, from `money` rows of `item_id, amount, amount_text, headline, date_text, is_consent` (`briefing.money_items`; `headline` has its leading dollar figure stripped, `amount` is the stored `NUMERIC(15, 2)`). Disagreed (`door_disagreed.html`, the `splits` branch): `<a>clause</a> · passed 8 to 1[ to 1 abstaining] · October 14 · <a>Hunter Williams</a>[ (abstained)][, ...][ · from the video]`, from `disagreed.splits` rows of `clause, clause_href, verb, yeas, nays, abstentions, date_text, dissenters [{name, href, abstained}], from_video` (`briefing._disagreement_line`; `verb` is the stored `votes.result`, one of `passed`, `failed`, `tabled`); the door's `unanimous` and `unanimous_only` branches are prose paragraphs (`brf-door-text`) and are not rows. Topics (`door_topics.html`): under the sub-label `Tracked in Birmingham`, each priority `<a>name</a> · 1 item since July 22 · <a>example headline</a>`, or for a quiet priority `<a>name</a> · last item March 14, 2026 · <a>headline</a>`, from `topics_door.priorities` rows of `slug, name, count, example | None, latest | None` where `example` and `latest` are `{item_id, headline, meeting_date, date_text, date_long}` and exactly one of them is set (`example` when `count` is above zero); under `Busiest topics`, each `<a>name</a> · 12 items since July 22 · <a>example</a>` from `topics_door.topics` rows of `slug, name, count, example`; `topics_door.since_text` is the window's start as `Month D`. Signals (`signals.html`): one `<a>` holding `<label> — 1 item`, from `signals` rows of `slug, label, count`. The council card prints `Attended 2 of 2 roll calls in the last 12 months` and `Voted against the outcome 1 time` (a link with class `cc-dissent` to `m.briefing.dissent_href` when `against` is above zero, plain text when it is zero) from `m.briefing = {roll_calls, attended, against, since, since_iso, dissent_href}`, or nothing when `m.briefing` is None. Every row is a `<li class="brf-door-line">` in a `<ul class="brf-door-list">`, and the tests slice a door out of the page by the exact string `<section class="brf-door brf-door-money"` (the helper `_section` in `tests/web/test_city_briefing.py` line 271), so the section elements keep their class attributes exactly as they are.

The tests. `tests/web/test_city_briefing.py` (58 tests) renders `/al/birmingham/` through the Flask test client after `tests/support/briefing_seed.py` seeds the real Birmingham with one past council meeting of four items (A, a $10.1 million road contract that passes the dollar check; B, a $39.5 million KultureCity item that fails it; C, a grant with the `hidden_on_consent` badge; D, routine), a split minutes vote (8 to 1, Hunter Williams no, Clinton P. Woods absent) on item A, a unanimous vote, a review-flagged video vote, an upcoming meeting, a placeholder meeting, a public transcript, and the badges; `seed(conn, **options)` returns ids (`items`, `members` as name to id, `nay_member_id`, `past_meeting_id`, ...), the `facts` fixture adds the precomputed `city_briefing_facts` row by `briefing.recompute_city_facts`, and `_insert_vote(cur, meeting_id, *, result, yeas, nays, abstentions=0, item_ids=(), roster=None, positions=None)` adds a vote whose unnamed members vote yea. `tests/web/test_city_briefing_a11y.py` renders the full page once and checks the eight `<h2>` texts in `DESIGN_HEADINGS` order, among other rules. `tests/web/test_partials_visual_refactor.py` renders `partials/council_card.html` alone through the `render_partial` fixture. `tests/unit/test_dollar_tier.py` holds `TestFormatDollarsFilter`, the unit tests of the existing dollar filter. `tests/integration/test_f4_browse_by_priority.py` renders the page with its own `bag` fixture and asserts the topics and signals markup (lines 441 to 465 and 488 to 507). `tests/web/test_card_navigation.py` renders `city.html` with a bare context (`members=[]`, `money=[]`, `disagreed=None`, no `signals`, `said`, or `topics_door`), which a Jinja `Undefined` keeps falsy. All of these run under `./tools/verify`.

The spec. `docs/specs/city-page.md` describes the page in the present tense; its paragraphs "The page, first to last" (the section order and the CSS prefix), "The doors" (one paragraph per door, the council's among them), and "Tests" are the ones this plan rewrites, each in the milestone whose change they describe, so the spec is true at every merge point. `docs/superpowers/specs/2026-10-19-birmingham-city-page-design.md` is the design the page was built from and is history (`GOALS.md`, Scope); it is not edited. `docs/DEBT.md` rows that this plan touches: `D62` (third item paid in M1); rows it must not trip: `D60` and `D61` (both fire on a touch of `briefing.py`, which is not touched). `D59` (cancelled-meeting items counted by the topics and signals queries) is unchanged by a layout plan.

Terms. A door is one of the page's sections with a heading and a list, so called because each line opens onto a deeper page. The dollar check is `briefing.passes_dollar_check`, which admits an amount to prose only when the item's own text backs it; nothing here changes it. The chosen source is one vote source per meeting (minutes first; decision `0056`); the tallies and names the rows print come from the precomputed `split_votes` payload under that rule, unchanged. The bad tone is the token `--bad` in `styles.css` (line 37), the red the vote chips use for a failed result. The mono face is `--font-mono` (JetBrains Mono), reached through the `.t-mono` utility. A key figure is the number a row leads with. A band is a wrapper that lays two sections side by side above a viewport width. `ch` is the CSS unit equal to the width of the digit zero in the element's font, so `9ch` in a monospace face fits nine characters. The throwaway database is the `docket_test_<hash>` database `tools/test-db` builds from the migrations; `tests/conftest.py` refuses any other database name with exit 2 before collection.

The brief's deliberate exclusions, which this plan keeps out: the "0 items" rows of "Recent meetings" and the opener headline that clips mid-word (excluded by the goal); the mockup's "How these are counted →" link (no destination exists); any change to `/al/<slug>/council/` beyond what the shared card's copy implies; the dissenter name form (the stored `member_name` prints as today); the five `D60` sentences and the `D61` guard; reusing `format_dollars`; folding the 768px and 900px thresholds into one; the blog rail and the search field; and the open issues #107 and #73, which concern other pages.

## Plan of Work

### M1: the filter, the money and disagreement rows, the row CSS

In `src/docket/web/filters.py`, after `format_dollars`, add `compact_dollars(value)` with the contract under Interfaces and Dependencies, add the bullet to the module docstring beside the `format_dollars` one, and register it in `register` as `app.jinja_env.filters["compact_dollars"] = compact_dollars`. In `tests/unit/test_dollar_tier.py`, after `TestFormatDollarsFilter`, add `TestCompactDollarsFilter` with one parametrized test over the twelve cases listed under Interfaces and Dependencies, importing the function directly (`from docket.web.filters import compact_dollars`).

In `src/docket/web/static/styles.css`, add `--space-5:  20px;` to `:root` between the `--space-4` and `--space-6` lines.

In `src/docket/web/static/layout.css`, replace the block from the comment `/* The doors (plan birmingham-city-briefing, M3): one list of linked lines each */` through the `.brf-amount` rule (lines 1409 to 1415 today) with the row rules given verbatim under Artifacts and Notes, and delete the line `.brf-signals .brf-door-line a { display: inline-block; }` (line 1440), which served the one-link line. Keep `.brf-door { max-width: 68ch; }` in M1 (M2 removes it with the bands) and keep `.brf-door-text` and its link rule. In `src/docket/web/static/mobile.css`, inside the `@media (max-width: 768px)` block that begins at line 609, after the `.brf-meeting` rule that closes the block, add the phone row rules given under Artifacts and Notes.

Rewrite `partials/briefing/door_money.html` and `partials/briefing/door_disagreed.html` as given verbatim under Artifacts and Notes: the `<li>` keeps its exact class, the key span comes first, then the headline link, then the date span, then the rest span only when there is content. Update each partial's header comment to describe the row. The disagreement partial's `unanimous` branches are untouched.

In `tests/web/test_city_briefing.py`: line 237, `assert "upcoming" in section` becomes `assert "<span>upcoming</span>" in section`. Lines 314 and 332 to 334 (the money door): assert each of `$10.1M`, `$2.3M`, `$850,000` as `<span class="brf-key t-mono">{key}</span>` in the door, assert `"$10.1 million" not in door`, and in the partial test assert `door.count("$10.1M") == 1`. Line 353: `"passed 8 to 1" in door` becomes `'<span class="brf-key t-mono">8–1</span>' in door` plus `"passed 8 to 1" not in door`, and line 354's dissenter assertion becomes `f'against: <a href="/al/birmingham/council/{facts["nay_member_id"]}/">Hunter Williams</a>' in door`. Lines 839 to 841 (tally only): the key assertion as above, `"abstained" not in door`, and `'class="brf-row-rest"' not in door`. Line 860: `"· from the video" in door` becomes `'· from the video</span>' in door` (the rest span ends with the label; the dot before it is literal because the dissenter precedes it inside the span). Line 988: `"· tabled 5 to 4" in door` becomes `'<span class="brf-key t-mono">5–4 tabled</span>' in door` plus `"brf-key--bad" not in door`. Add one test after `test_disagreed_video_sourced_vote_carries_label`, `test_disagreed_failed_tone_and_abstainer_clause`, on the `facts` fixture: with `names = list(facts["members"])`, insert through `briefing_seed._insert_vote` a `failed` vote of `yeas=1, nays=6` linked to item B with `positions` nay for `names[1:7]` and absent for `names[7:9]`, and a `passed` vote of `yeas=8, nays=0, abstentions=1` with `positions={names[7]: "abstain"}`, commit, call `briefing.recompute_city_facts` and `briefing_seed.clear_caches`, render, and assert the door has three `<li class="brf-door-line">`, contains `<span class="brf-key t-mono brf-key--bad">1–6 failed</span>`, contains `<span class="brf-key t-mono">8–0–1</span>`, contains `f'<a href="/al/birmingham/council/{facts["members"][names[7]]}/">{escape(names[7])}</a> abstained'`, and does not contain `failed 1 to 6` or `(abstained)`. The money assertions on lines 743 and 925 (hrefs and line counts) are unchanged.

In `docs/DEBT.md`, the `D62` row becomes: Item "Two small defects the first and second closing reviews of plan `birmingham-city-briefing` rated minor: source health prints the briefing row's `computed_at` through `strftime` followed by a literal "UTC" while psycopg2 delivers it in the session's time zone (`America/Chicago` locally), so the operator reads a wall-clock time mislabelled; and `briefing.amount_in_words` rounds to one decimal before choosing the unit, so 999,950,000 to 999,999,999 print "$1000 million" (the third item, the assertion in `tests/web/test_city_briefing.py` that could not fail, was paid by plan `city-page-less-narrow-less-dense` M1)"; Where "`src/docket/web/templates/source_health.html` (stage 5), `src/docket/services/briefing.py` `amount_in_words`"; Why deferred unchanged; Trigger "The next touch of each file".

In `docs/specs/city-page.md`, in "The doors": the money sentence `each line "<$ amount> — <headline> · <Month D>[ · passed on the consent agenda]" linking to the item page` becomes `each row two-tier: the amount as the key figure at the left in the mono face, in its compact form (`compact_dollars` in `src/docket/web/filters.py`: "$50M", "$10.1M", "$1.2B", and "$850,000" below a million), the headline linked to the item page beside it, and a muted second line "<Month D>[ · passed on the consent agenda]"; at phone width the key figure and the date share one small line above the headline`; the disagreement sentence `each "<item clause linked> · <passed, failed, or tabled, the stored result> <y> to <n>[ to <a> abstaining] · <Month D> · <dissenters>[ · from the video]"` becomes `each row two-tier: the tally "<y>–<n>[–<a>]" as the key figure, followed by " failed" in the bad tone or " tabled" plain when the stored result is not passed and by nothing when it is, the item clause linked beside it, and a muted second line "<Month D>[ · against: <names>][ · <names> abstained][ · from the video]"`, with the clause about where the item clause links and how a resolved dissenter links kept, and `with "(abstained)" after an abstainer` dropped. In "The page, first to last", after the sentence naming the `brf-` prefix, add: `A door row (`.brf-door-line`) is a grid of a key figure, a headline link, a date, and the rest of its second line, with the phone layer of `mobile.css` moving the key and the date onto one line above the headline in "Where the money went" and "Where they disagreed".`

### M2: the topics and signals rows, the bands, the order

Rewrite `partials/briefing/door_topics.html` and `partials/briefing/signals.html` as given under Artifacts and Notes: the topics sub-labels become `Tracked in {{ municipality.name }} · since {{ topics_door.since_text }}` and `Busiest topics · since {{ topics_door.since_text }}`; each priority and topic row is the key `<n> item(s)` and the linked name, with a quiet priority's row (its `latest` set, `example` None) adding `<span class="brf-row-date">last item {{ p.latest.date_long }}</span>` and the key `0 items`; no example headline and no item link remain in the door. Each signal row is the key `<n> item(s)` and the label linked to its category landing.

In `city.html`, wrap the two includes of `door_money.html` and `door_disagreed.html` in `<div class="brf-band">` inside `{% if money or disagreed %}`; move the include of `signals.html` above `door_said.html`; wrap the include of `door_topics.html` and, inside `{% if signals or said %}`, a `<div class="brf-band-col">` holding the `signals.html` and `door_said.html` includes, in a second `<div class="brf-band">` inside `{% if (topics_door and (topics_door.priorities or topics_door.topics)) or signals or said %}` (the topics partial's own condition, so a band renders only when it will hold a section); the council section stays between the bands and the meetings and blog sections follow the second band. The resulting order of `<h2>` texts is money, disagreed, council, topics, signals, said, meetings, blog.

In `layout.css`, delete `.brf-door { max-width: 68ch; }`, add `.brf-door-said { max-width: 68ch; }` beside the quote rules, add `.brf-door-topics .brf-door-line, .brf-signals .brf-door-line { --brf-key-w: 9ch; }` beside the money door's width rule, and add the band block given under Artifacts and Notes (`.brf-band-col { min-width: 0; }` and the `@media (min-width: 900px)` rule).

In `tests/web/test_city_briefing_a11y.py`, `DESIGN_HEADINGS` becomes the order above and its comment says the order follows plan `city-page-less-narrow-less-dense`. In `tests/web/test_city_briefing.py`: lines 513 to 514, `"1 item since" in door` becomes `'<span class="brf-key t-mono">1 item</span>' in door` plus `"Tracked in Birmingham · since " in door` and `"Busiest topics · since " in door`, and the item A href assertion becomes `"/al/birmingham/items/" not in door`; line 529 is deleted (the item C example) and the count at line 528 stays 6; lines 551 to 554, the item E href becomes `"/items/" not in line`, `"since" not in line` stays, add `'<span class="brf-key t-mono">0 items</span>' in line`, and `"1 item since" in door` becomes the key assertion; lines 586 to 588, the regex becomes `r'<li class="brf-door-line">\s*<span class="brf-key t-mono">([^<]+)</span>\s*<a class="brf-row-link" href="([^"]+)">([^<]+)</a>'` and the expected list `[("1 item", "/al/birmingham/hidden_on_consent/", "Passed without discussion, on the consent agenda")]`. Add one test after `test_signals_absent_when_all_zero`, `test_bands_hold_the_doors_in_order`, on the `facts` fixture: render, and assert by `html.index` that the first `<div class="brf-band">` precedes `brf-door-money`, which precedes `brf-door-disagreed`, which precedes `class="council brf-council"`, which precedes the second `<div class="brf-band">` (searched from the council's index), which precedes `brf-door-topics`, then `<div class="brf-band-col">`, then `brf-signals`, then `brf-door-said`, then `brf-meetings-section`; and that `html.count('<div class="brf-band">') == 2`. In `tests/integration/test_f4_browse_by_priority.py`: lines 461 to 465, `assert f"Priority-{slug}" in door` becomes `not in door` and `door.count("1 item since") >= 4` becomes `door.count('<span class="brf-key t-mono">1 item</span>') >= 4`, with the docstring saying each priority is its count and its linked name; lines 498 to 505, the regex becomes `r'<span class="brf-key t-mono">2 items</span>\s*<a class="brf-row-link" href="/al/birmingham/hidden_on_consent/">Passed without discussion, on the consent agenda</a>'`, with the docstring following.

In `docs/specs/city-page.md`: in "The page, first to last", the door order becomes `"Where the money went", "Where they disagreed", "The council", "What they keep dealing with", "Signals in the last 30 days", "Said at the meeting"`, and after the sentence about the row grid add: `From 900 pixels of viewport width, "Where the money went" and "Where they disagreed" share one two-column band, and "What they keep dealing with" shares a second with "Signals in the last 30 days" over "Said at the meeting" (`.brf-band` in `layout.css`, a column per section present); below that width they stack in the order above. The opener, the search label, and the quote are capped at 68 characters of measure (`max-width: 68ch`); the lists are not.` In "The doors", the topics paragraph's row forms become `"<n> item(s)" as the key figure and "<name linked to /al/<slug>/<badge>/>"` under the sub-label `"Tracked in <City> · since <Month D>"`, with `a priority with no item in the window shows "0 items" and, on its second line, "last item <Month D, YYYY>"`, and the topics list `"<n> item(s)" and "<name linked to /topics/<slug>/?city=<slug>>"` under `"Busiest topics · since <Month D>"`; drop every mention of an example headline. The signals sentence `each one line "<label> — <n> items" linking to its category landing` becomes `each row "<n> item(s)" as the key figure and the label linked to its category landing`. In "Tests", `the eight headings above in order` stays true as written.

### M3: the council copy, the note, the phone list

In `partials/council_card.html`, the first stat becomes `Attended {{ m.briefing.attended }} of {{ m.briefing.roll_calls }} roll call{{ 's' if m.briefing.roll_calls != 1 else '' }}` and both branches of the second become `Against the outcome {{ m.briefing.against }} time{{ 's' if m.briefing.against != 1 else '' }}` (the plain branch prints `times`, since it only renders for zero); the header comment says the window is stated once under the city page's grid. In `city.html`, after the council `<div class="council-grid">...</div>`, add `{% if members | selectattr('briefing') | list %}<p class="brf-council-note">Roll calls counted over the last 12 months.</p>{% endif %}`. In `layout.css`, add `.brf-council-note { font-size: 13px; color: var(--ink-3); margin: var(--space-3) 0 0; }` after `.brf-council .council-grid`. In `mobile.css`, inside the `@media (max-width: 768px)` block, after the phone row rules M1 added, add the `.brf-council` list rules given under Artifacts and Notes.

In `tests/web/test_city_briefing.py`: lines 429 to 432, 451, 802 to 804, and 906 replace `Attended <a> of <r> roll calls in the last 12 months` with `Attended <a> of <r> roll calls</div>` and `Voted against the outcome <n> time(s)` with `Against the outcome <n> time(s)` (line 431's `Voted against the outcome 1 time<` becomes `Against the outcome 1 time<`, and line 906's `roll calls in the last 12 months` becomes `roll calls</div>`); line 443's `"Voted against" not in section` becomes `"Against the outcome" not in section` plus `"Roll calls counted" not in section`; in `test_council_door_nine_cards_in_district_order_with_numbers` add `section.count("Roll calls counted over the last 12 months.") == 1` and `"in the last 12 months</div>" not in section`; in `test_council_door_absent_without_roster` nothing changes; and in `test_council_card_links_dissent_since_and_member_page_matches_count`, after the card assertions, add `resp = client.get("/al/birmingham/council/")`, `assert resp.status_code == 200`, and that its body contains neither `Roll calls counted` nor `brf-council`. In `tests/web/test_partials_visual_refactor.py` lines 563 to 565: `'Attended 37 of 40 roll calls' in html`, `'in the last 12 months' not in html`, and the dissent anchor's text `Against the outcome 4 times`.

In `docs/specs/city-page.md`, the council sentence `"Attended <a> of <r> roll calls in the last 12 months" and "Voted against the outcome <n> times", the second a link ... when `n` is above zero and plain text when it is zero` becomes `"Attended <a> of <r> roll calls" and "Against the outcome <n> times", the second a link to ... when `n` is above zero and plain text when it is zero, with "Roll calls counted over the last 12 months." stated once under the grid when any card carries counts`, and after `A member with no chosen-source roll call in the window shows the name alone; a city with no active members has no section.` add `At phone width the city page's council is a list of rows, each the initials square, the district, the name, and the two numbers (`.brf-council` in `mobile.css`); `/al/<slug>/council/` renders the same card without the numbers and keeps its three-column tiles at every width.`

## Concrete Steps

Every command runs from the worktree root, `/home/thinkdarrell/docket-pub/.claude/worktrees/city-page-less-narrow-less-dense`, with that checkout's `venv/`. The branch is `plan/city-page-less-narrow-less-dense`; the base is `origin/main` at `6225346`, and no check compares against bare `main`.

Before anything, the gitignored `.env` (`D57`): `test -f .env || printf 'DATABASE_URL=postgresql://thinkdarrell@/docket_db\n' > .env`, then `git status --porcelain` prints nothing. Without it `./tools/verify` prints `ERROR:  permission denied to create database` and `verify: 6 of 6 checks failed in 0s`.

Each session starts and ends with `./tools/verify` (about 105 seconds here; budget 180). It builds `docket_test_63e81421`, runs the tiers, and drops it; the final line of a passing run is `verify: all 6 checks passed in <n>s.` To run one file against a throwaway database between those two runs: `URL=$(tools/test-db)`, then `DATABASE_URL="$URL" venv/bin/python -m pytest <file> -q -p no:cacheprovider`, then `tools/test-db --drop`; a bare `pytest` without the variable is refused before collection with exit 2, because the worktree's `.env` names `docket_db`. The link inventory script under Artifacts and Notes runs the same way with `PYTHONPATH=.` in front of `venv/bin/python`, because it imports `tests.support`.

To look at the markup by eye: `URL=$(tools/test-db)`, then in one Python session seed and recompute as the script does, and `DATABASE_URL="$URL" venv/bin/flask --app docket.web:create_app run` serves `http://127.0.0.1:5000/al/birmingham/`; `curl -s http://127.0.0.1:5000/al/birmingham/ | sed -n '/brf-door-money/,/<\/section>/p'` prints one door. Stop the server and `tools/test-db --drop` afterwards (the seed cleans up by its `BRIEFING_TEST_` prefix only when `briefing_seed.cleanup` runs, so drop the database rather than leave rows).

M1 ran, 2026-10-21, as two commits after the starting verify: the failing tests first (`9b5a532`), then the filter, the token, the two stylesheets, the two partials, the test rewrites, `D62`, and the spec together; the throwaway database `docket_test_63e81421` stayed up between the single-file runs and was dropped before the closing verify, which rebuilds it.

Every commit in a milestone session changes the plan file (decision `0037`); the pre-commit hook in `tools/hooks/` runs `tools/check-plans --staged` and is never bypassed. A milestone's tick is `- [x] (YYYY-MM-DD HH:MMZ)` in place of `- [ ]` with the line's text otherwise unchanged.

Operator step, after each milestone's pull request merges and a human deploys from `main` (`scripts/deploy.sh --service docket-web`, never from a session): open `https://docket.pub/al/birmingham/` at about 1,200, 900, and 375 pixels wide (a desktop window, a narrowed window, a phone or the browser's device mode) and record under Surprises & Discoveries what the rows, bands, and council look like, in particular whether the key figures align down each list, whether the two bands sit side by side at 900 and stack at 899, and whether the phone council reads as nine rows. A finding that the approved layout does not hold is a Surprises entry and a decision, not a silent fix.

## Validation and Acceptance

M1. `./tools/verify` prints `verify: all 6 checks passed in <n>s.` `DATABASE_URL="$URL" venv/bin/python -m pytest tests/web/test_city_briefing.py tests/unit/test_dollar_tier.py -q -p no:cacheprovider` prints `142 passed` (58 plus the new test, and 71 plus twelve parametrized cases). `venv/bin/python -c "from docket.web.filters import compact_dollars as c; print(c(50_000_000), c(10_125_000), c(850_000), c(1_200_000_000), c(999_950_000), c(None))"` prints `$50M $10.1M $850,000 $1.2B $1B ` (at authoring it printed `ImportError: cannot import name 'compact_dollars'`). `grep -c 'brf-key t-mono' src/docket/web/templates/partials/briefing/door_money.html` prints `1` and the same on `door_disagreed.html` prints `1` (both printed `0` at authoring). `grep -n 'space-5' src/docket/web/static/styles.css` prints one line. `grep -n 'brf-amount' src/docket/web/static/layout.css src/docket/web/templates/partials/briefing/door_money.html` prints nothing. `grep -n '^| D62 ' docs/DEBT.md` prints one line containing `Two small defects` and not containing `cannot fail`. The link inventory script prints the list under Artifacts and Notes unchanged, `links: 55`. `git diff --stat origin/main -- src/docket/services` prints nothing. The new test fails before the template change: with the test added and the partials as they were, `pytest tests/web/test_city_briefing.py -k failed_tone` prints `1 failed`; the session records the first assertion it failed on.

M2. `./tools/verify` passes. `DATABASE_URL="$URL" venv/bin/python -m pytest tests/web/test_city_briefing.py tests/web/test_city_briefing_a11y.py tests/integration/test_f4_browse_by_priority.py -q -p no:cacheprovider` prints `103 passed` (59 plus the band test, 8, and 35). `grep -c '<div class="brf-band">' src/docket/web/templates/city.html` prints `2` (it printed `0` at authoring) and `grep -c 'brf-band-col' src/docket/web/templates/city.html` prints `1`. `grep -n '^\.brf-door {' src/docket/web/static/layout.css` prints nothing (it printed `1410:.brf-door { max-width: 68ch; }` at authoring) and `grep -c 'max-width: 68ch' src/docket/web/static/layout.css` prints `4` (the opener, the search label, the quote, the member note). `grep -c 'brf-key t-mono' src/docket/web/templates/partials/briefing/door_topics.html` prints `2` and on `signals.html` prints `1`. `grep -c 'item_detail' src/docket/web/templates/partials/briefing/door_topics.html` prints `0` (it printed `3` at authoring). The link inventory script prints the list under Artifacts and Notes with the one difference that `10 /al/birmingham/items/N/` reads `4 /al/birmingham/items/N/`, and `links: 49` (the six example links the operator's goal drops; every other line is identical). `git diff --stat origin/main -- src/docket/services` prints nothing.

M3. `./tools/verify` passes. `DATABASE_URL="$URL" venv/bin/python -m pytest tests/web/test_city_briefing.py tests/web/test_partials_visual_refactor.py tests/web/test_city_overview_render.py -q -p no:cacheprovider` prints `112 passed, 1 skipped` (60, 42, and 10 plus the skip that file already carries). `grep -rn 'the last 12 months' src/docket/web/templates` prints only the `city.html` note line, "Roll calls counted over the last 12 months." (at authoring it printed the one `council_card.html` line). `grep -rn 'Voted against the outcome' src tests docs/specs` prints nothing (at authoring it printed thirteen lines across `council_card.html`, `test_city_briefing.py`, `test_partials_visual_refactor.py`, and `docs/specs/city-page.md`, counted with the `Attended` lines). `grep -c 'brf-council' src/docket/web/static/mobile.css` prints at least `8`. The link inventory script prints `links: 49` with the M2 list unchanged. `git diff --stat origin/main -- src/docket/services` prints nothing. Rendering `/al/birmingham/council/` through the test client contains no `Roll calls counted` and no `brf-council`.

## Idempotence and Recovery

Every step edits files in the worktree and is safe to repeat; a half-finished edit is recovered by `git checkout -- <file>` for the files under `src/` and `tests/` and by re-reading this plan for the plan file itself, which is never reverted. The throwaway database is rebuilt by `tools/test-db` and dropped by `tools/test-db --drop`; a build that finds the database already present (a session interrupted between build and drop) is reported by the tool and resolved by dropping first. No migration, no production connection, and no write outside the worktree is involved. If a session cannot finish its milestone, it splits the Progress line in place (completed: X; remaining: Y), logs the split in the Decision Log, commits with the plan file in the commit, and exits with `git status --porcelain` printing nothing.

## Artifacts and Notes

The link inventory script. Save it outside the checkout (the session's scratchpad directory) as `city_links.py` and run `URL=$(tools/test-db) && DATABASE_URL="$URL" PYTHONPATH=. venv/bin/python <path>/city_links.py; tools/test-db --drop` from the worktree root:

    """Render the seeded Birmingham page and list its links, ids normalised to N."""
    import re
    from collections import Counter

    from docket.db import db
    from docket.services import briefing
    from docket.web import create_app
    from tests.support import briefing_seed

    app = create_app()
    app.config["TESTING"] = True
    with db() as conn:
        ids = briefing_seed.seed(conn)
    briefing.recompute_city_facts(ids["municipality_id"])
    briefing_seed.clear_caches()
    try:
        with app.test_client() as c:
            html = c.get("/al/birmingham/").get_data(as_text=True)
    finally:
        with db() as conn:
            briefing_seed.cleanup(conn)
        briefing_seed.clear_caches()
    body = html[html.index("<main"): html.index('<aside class="page-sources"')]
    hrefs = [re.sub(r"\d+", "N", h) for h in re.findall(r'href="([^"]+)"', body)]
    for h, n in sorted(Counter(hrefs).items()):
        print(n, h)
    text = " ".join(re.sub(r"<[^>]+>", " ", body).split())
    print("links:", len(hrefs), "sections:", len(re.findall(r"<section ", body)), "chars:", len(text))

Its output at authoring, 2026-10-21, on `origin/main` at `6225346`:

    2 /
    3 /al/birmingham/
    1 /al/birmingham/blight_accountability/
    2 /al/birmingham/blog
    1 /al/birmingham/blog/feed.xml
    1 /al/birmingham/blog/fyN-budget-message-vs-ledger
    1 /al/birmingham/council/
    12 /al/birmingham/council/N/
    1 /al/birmingham/council/N/?filter=dissent&amp;since=N-N-N
    1 /al/birmingham/hidden_on_consent/
    10 /al/birmingham/items/N/
    2 /al/birmingham/meetings/
    3 /al/birmingham/meetings/N/
    1 /al/birmingham/meetings/N/#vote-N
    1 /al/birmingham/meetings/N/transcript/#t-N
    1 /al/birmingham/source-health/
    1 /al/birmingham/split_vote/
    1 /al/birmingham/upcoming-hearings.rss
    1 /blog/hello-docket
    1 /coverage.rss
    1 /search
    1 /search?city=birmingham
    1 /search?city=birmingham&amp;order=amount
    1 /topics/budget/?city=birmingham
    1 /topics/contracts/?city=birmingham
    1 /topics/grants/?city=birmingham
    1 /topics/public_works/?city=birmingham
    1 /topics/zoning/?city=birmingham
    links: 55 sections: 11 chars: 3490

The `chars` figure is reported, not asserted: it falls with the dropped examples and the shortened council copy.

The money partial after M1 (the list only; the section, header, and "More →" lines stay as they are):

    <ul class="brf-door-list">
      {% for it in money %}
      <li class="brf-door-line">
        <span class="brf-key t-mono">{{ it.amount | compact_dollars }}</span>
        <a class="brf-row-link" href="{{ url_for('public.item_detail', slug=municipality.slug, item_id=it.item_id) }}">{{ it.headline }}</a>
        <span class="brf-row-date">{{ it.date_text }}</span>
        {%- if it.is_consent %}
        <span class="brf-row-rest">passed on the consent agenda</span>
        {%- endif %}
      </li>
      {% endfor %}
    </ul>

The disagreement partial's `splits` list after M1:

    <ul class="brf-door-list">
      {% for s in disagreed.splits %}
      {%- set nays = s.dissenters | rejectattr('abstained') | list %}
      {%- set abstainers = s.dissenters | selectattr('abstained') | list %}
      <li class="brf-door-line">
        <span class="brf-key t-mono{% if s.verb == 'failed' %} brf-key--bad{% endif %}">{{ s.yeas }}–{{ s.nays }}{% if s.abstentions %}–{{ s.abstentions }}{% endif %}{% if s.verb != 'passed' %} {{ s.verb }}{% endif %}</span>
        <a class="brf-row-link" href="{{ s.clause_href }}">{{ s.clause }}</a>
        <span class="brf-row-date">{{ s.date_text }}</span>
        {%- if s.dissenters or s.from_video %}
        <span class="brf-row-rest">
          {%- if nays %}against: {% for d in nays %}{% if d.href %}<a href="{{ d.href }}">{{ d.name }}</a>{% else %}{{ d.name }}{% endif %}{% if not loop.last %}, {% endif %}{% endfor %}{% endif %}
          {%- if abstainers %}{% if nays %} · {% endif %}{% for d in abstainers %}{% if d.href %}<a href="{{ d.href }}">{{ d.name }}</a>{% else %}{{ d.name }}{% endif %}{% if not loop.last %}, {% endif %}{% endfor %} abstained{% endif %}
          {%- if s.from_video %}{% if s.dissenters %} · {% endif %}from the video{% endif -%}
        </span>
        {%- endif %}
      </li>
      {% endfor %}
    </ul>

(`rejectattr('abstained')` and `selectattr('abstained')` work on the dicts the service passes; checked at authoring with a two-row list, which printed `1/1`.) For the seed's split this prints `<span class="brf-key t-mono">8–1</span>`, the clause link, `<span class="brf-row-date">October 14</span>` (the seed's date), and `<span class="brf-row-rest">against: <a href="/al/birmingham/council/2/">Hunter Williams</a></span>`; a video-sourced split ends `... Hunter Williams</a> · from the video</span>`.

The topics partial's two lists after M2:

    <p class="brf-sublabel">Tracked in {{ municipality.name }} · since {{ topics_door.since_text }}</p>
    <ul class="brf-door-list brf-priorities">
      {% for p in topics_door.priorities %}
      <li class="brf-door-line">
        <span class="brf-key t-mono">{{ p.count }} item{{ 's' if p.count != 1 else '' }}</span>
        <a class="brf-row-link" href="{{ url_for('public.category_landing', slug=municipality.slug, badge_slug=p.slug) }}">{{ p.name }}</a>
        {%- if p.latest %}
        <span class="brf-row-date">last item {{ p.latest.date_long }}</span>
        {%- endif %}
      </li>
      {% endfor %}
    </ul>

    <p class="brf-sublabel">Busiest topics · since {{ topics_door.since_text }}</p>
    <ul class="brf-door-list brf-topics">
      {% for t in topics_door.topics %}
      <li class="brf-door-line">
        <span class="brf-key t-mono">{{ t.count }} item{{ 's' if t.count != 1 else '' }}</span>
        <a class="brf-row-link" href="{{ url_for('public.topic_detail', topic=t.slug, city=municipality.slug) }}">{{ t.name }}</a>
      </li>
      {% endfor %}
    </ul>

The signals partial's list after M2:

    <ul class="brf-door-list">
      {% for s in signals %}
      <li class="brf-door-line">
        <span class="brf-key t-mono">{{ s.count }} item{{ 's' if s.count != 1 else '' }}</span>
        <a class="brf-row-link" href="{{ url_for('public.category_landing', slug=municipality.slug, badge_slug=s.slug) }}">{{ s.label }}</a>
      </li>
      {% endfor %}
    </ul>

`city.html`'s content block after M2 (the lead, opener, search, meetings, and blog includes as today):

    {% include 'partials/city_lead.html' %}
    {% if opener %}{% include 'partials/briefing/opener.html' %}{% endif %}
    {% include 'partials/briefing/search.html' %}

    {# Band one (plan city-page-less-narrow-less-dense, M2): money beside disagreed from 900px #}
    {% if money or disagreed %}
    <div class="brf-band">
    {% include 'partials/briefing/door_money.html' %}
    {% include 'partials/briefing/door_disagreed.html' %}
    </div>
    {% endif %}

    {# The council: the roster by district with the twelve-month counts #}
    {% if members %}
    <section class="council brf-council" aria-labelledby="brf-council-h">
        ... unchanged header and grid ...
        {% if members | selectattr('briefing') | list %}
        <p class="brf-council-note">Roll calls counted over the last 12 months.</p>
        {% endif %}
    </section>
    {% endif %}

    {# Band two: topics beside signals over the quote #}
    {% if (topics_door and (topics_door.priorities or topics_door.topics)) or signals or said %}
    <div class="brf-band">
    {% include 'partials/briefing/door_topics.html' %}
    {% if signals or said %}
    <div class="brf-band-col">
    {% include 'partials/briefing/signals.html' %}
    {% include 'partials/briefing/door_said.html' %}
    </div>
    {% endif %}
    </div>
    {% endif %}

    {% include 'partials/briefing/meetings.html' %}
    ... the blog rail as today ...

(The note `<p>` is M3's; M2 leaves the council section as it is.)

The row rules in `layout.css` after M1, replacing lines 1409 to 1415:

    /* The doors (plan city-page-less-narrow-less-dense, M1): two-tier rows. The key
       figure sits in a fixed mono column, the linked headline beside it, and the
       muted second line (the date, then the rest) under the headline. The phone
       layer in mobile.css moves the key and the date onto one line above it. */
    .brf-door-list { list-style: none; margin: 0; padding: 0; border-top: 1px solid var(--rule); }
    .brf-door-line {
      --brf-key-w: 12ch;
      display: grid;
      grid-template-columns: calc(var(--brf-key-w) + var(--space-3)) max-content 1fr;
      grid-template-areas: "key head head" "key date rest";
      align-items: start;
      column-gap: 0;
      row-gap: 2px;
      padding: var(--space-3) 0;
      border-bottom: 1px solid var(--rule);
      line-height: 1.5;
      min-height: 44px;
    }
    .brf-door-money .brf-door-line { --brf-key-w: 9ch; }
    .brf-key { grid-area: key; font-size: 14px; line-height: 1.5; padding: 1px var(--space-3) 0 0; font-weight: 500; color: var(--ink); white-space: nowrap; }
    .brf-key--bad { color: var(--bad); }
    .brf-row-link { grid-area: head; }
    .brf-door-line a { color: var(--ink); text-decoration: underline; text-decoration-color: var(--accent); text-underline-offset: 3px; }
    .brf-door-line a:hover { color: var(--accent-ink); }
    .brf-row-date, .brf-row-rest { font-size: 13px; line-height: 1.5; color: var(--ink-3); }
    .brf-row-date { grid-area: date; white-space: nowrap; }
    .brf-row-rest { grid-area: rest; min-width: 0; }
    .brf-row-date + .brf-row-rest::before { content: "\00a0· "; }
    .brf-row-rest a { color: var(--ink-2); }
    .brf-door-text { line-height: 1.5; margin: 0; }
    .brf-door-text a { color: var(--ink); text-decoration: underline; text-decoration-color: var(--accent); text-underline-offset: 3px; }

The phone row rules in `mobile.css` after M1, at the end of the `@media (max-width: 768px)` block that holds `.brf-meeting`:

      /* City briefing door rows (plan city-page-less-narrow-less-dense, M1): in the
         money and disagreement doors the key figure and the date share one small
         line above the headline. The count rows of the topics and signals doors
         (M2) keep the desktop shape, the key beside the name. */
      .brf-key { font-size: 13px; }
      .brf-door-money .brf-door-line, .brf-door-disagreed .brf-door-line {
        grid-template-columns: max-content 1fr;
        grid-template-areas: "key date" "head head" "rest rest";
        column-gap: var(--space-2);
      }
      .brf-door-money .brf-key, .brf-door-disagreed .brf-key { padding: 0; }
      .brf-door-money .brf-row-date, .brf-door-disagreed .brf-row-date { white-space: normal; }
      .brf-door-money .brf-row-date::before, .brf-door-disagreed .brf-row-date::before { content: "· "; }
      .brf-door-money .brf-row-date + .brf-row-rest::before, .brf-door-disagreed .brf-row-date + .brf-row-rest::before { content: none; }

The band rules in `layout.css` after M2, after `.brf-more a:hover`:

    /* Two bands (plan city-page-less-narrow-less-dense, M2): from 900px, money sits
       beside disagreed and topics beside signals over the quote; a column per
       section present, so a lone section takes the width. Below 900px they stack. */
    .brf-band-col { min-width: 0; }
    @media (min-width: 900px) {
      .brf-band {
        display: grid;
        grid-auto-flow: column;
        grid-auto-columns: minmax(0, 1fr);
        column-gap: var(--space-8);
        align-items: start;
      }
    }
    .brf-door-topics .brf-door-line, .brf-signals .brf-door-line { --brf-key-w: 9ch; }
    .brf-door-said { max-width: 68ch; }

The council list rules in `mobile.css` after M3, after the phone row rules:

      /* The city page's council as nine rows (plan city-page-less-narrow-less-dense,
         M3): initials square, district, name, the two numbers. /al/<slug>/council/
         carries no brf-council and keeps the three-column tiles above. */
      .brf-council .council-grid { grid-template-columns: 1fr; gap: 0; border-top: 1px solid var(--rule); }
      .brf-council .cc {
        display: grid;
        grid-template-columns: 40px 1fr;
        column-gap: var(--space-3);
        align-items: center;
        border: 0;
        border-bottom: 1px solid var(--rule);
        border-radius: 0;
        padding: var(--space-2) 0;
      }
      .brf-council .cc-portrait { width: 40px; aspect-ratio: 1; border-radius: 6px; }
      .brf-council .cc-initials { font-size: 14px; text-shadow: none; }
      .brf-council .cc-body { padding: 0; gap: 2px; }
      .brf-council .cc-district-num { font-size: 12px; color: var(--ink-3); }
      .brf-council .cc-name { font-size: 15px; display: block; -webkit-line-clamp: none; overflow: visible; }
      .brf-council .cc-stats { flex-direction: row; flex-wrap: wrap; gap: 0 var(--space-3); font-size: 12px; }
      .brf-council .cc-stat { min-height: 0; }
      .brf-council .cc-dissent { display: inline-block; padding: 4px 0; }

## Interfaces and Dependencies

In `src/docket/web/filters.py`, define and register:

    def compact_dollars(value: Decimal | float | int | str | None) -> str:
        """``50_000_000`` → ``"$50M"``; ``10_125_000`` → ``"$10.1M"``; ``850_000`` → ``"$850,000"``;
        ``1_200_000_000`` → ``"$1.2B"``. The key figure of the city page's money door.

        Coerces through ``_coerce_amount`` (None, zero, negative, bool, NaN, and
        non-numeric input give ``""``). Below one million the integer with
        thousands separators, cents dropped. From one million, the amount in
        millions rounded half up to one decimal with a trailing ``.0`` dropped;
        when that rounds to 1000 or more, the amount in billions the same way,
        so 999,950,000 prints ``$1B``, never ``$1000M``.
        """

Its twelve unit cases and what each prints: `50_000_000` → `$50M`; `10_125_000` → `$10.1M`; `850_000` → `$850,000`; `1_200_000_000` → `$1.2B`; `999_950_000` → `$1B`; `1_000_000` → `$1M`; `1_050_000` → `$1.1M`; `Decimal("2300000.00")` → `$2.3M`; `850_000.42` → `$850,000`; `None` → `""`; `0` → `""`; `"abc"` → `""`. Rounding is `decimal.ROUND_HALF_UP` on `Decimal` arithmetic (`(amount / Decimal(1_000_000)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)`), and the text is `format(scaled, "f").removesuffix(".0")` (the quantized value always carries one decimal, so this drops exactly a trailing `.0` and can never shorten an integer the way `rstrip("0")` would turn `"50"` into `"5"`); the arithmetic was checked at authoring and printed exactly these values, and the suffix form was checked on 2026-10-21 to print the same nine strings as the `rstrip` form it replaced.

The template context is unchanged: `money` rows carry `amount` (the stored `Decimal`), `headline`, `date_text`, `is_consent`, `item_id`; `disagreed.splits` rows carry `clause`, `clause_href`, `verb`, `yeas`, `nays`, `abstentions`, `date_text`, `dissenters` (`name`, `href`, `abstained`), `from_video`; `topics_door` carries `since_text`, `priorities` (`slug`, `name`, `count`, `example`, `latest`), `topics` (`slug`, `name`, `count`); `signals` rows carry `slug`, `label`, `count`; each member's `briefing` carries `roll_calls`, `attended`, `against`, `dissent_href`. `src/docket/services/briefing.py` and `src/docket/web/public.py` are not edited by any milestone, and `git diff --stat origin/main -- src/docket/services` printing nothing is part of every milestone's acceptance.

CSS classes this plan introduces, all on the city page: `brf-key`, `brf-key--bad`, `brf-row-link`, `brf-row-date`, `brf-row-rest` (M1); `brf-band`, `brf-band-col` (M2); `brf-council-note` (M3). Classes it retires: `brf-amount` (M1); the `.brf-door` width rule (M2; the class itself stays on the sections because the tests slice by it). The custom property `--brf-key-w` (the key's text width; the column adds `--space-3` of padding on the key's right, and the row has no column gap) is set on `.brf-door-line` and overridden per door. The thresholds are `max-width: 768px` (phone, `mobile.css`) and `min-width: 900px` (bands, `layout.css`).

Debt and specs: `D62` is edited in M1 as Plan of Work gives it; `D60` and `D61` must not trip, which the untouched `briefing.py` guarantees; `docs/specs/city-page.md` is edited in every milestone. Identifiers already spent on `origin/main`: debt rows through `D73`, decisions through `0066`.

## Revision note

Authored 2026-10-21 from the operator's goal and the read-only scope brief, with the brief folded into Purpose and Context as prose. The plan deliberately leaves out: the "0 items" rows of "Recent meetings" and the opener headline that clips mid-word (the goal excludes them); the mockup's "How these are counted →" link (no destination page exists, so the window sentence ships without a link); any change to `/al/<slug>/council/` beyond the shared card's copy (the phone list is scoped to `.brf-council`); the dissenter name form (the stored name prints as today); the five `D60` sentences and the `D61` guard (the layout needs no `briefing.py` edit, and taking them would make this a service change); reusing `format_dollars` (it prints `$50.0M`); folding the 768px and 900px thresholds into one; the blog rail and the search field; and the open issues #107 and #73. It adds, beyond the brief, the `--space-5` token and the `tests/integration/test_f4_browse_by_priority.py` edits that the research found.

Revised 2026-10-21, before any milestone ran, from the operator's external review of the plan. Four changes, each with a Decision Log entry: the desktop row's gap moves from `column-gap` into the key column so no gap falls between the date and the rest, with a no-break space before the dot and a default key width of `12ch`; the phone stacking is scoped to the money and disagreement doors so date-less count rows stay one line; the two band wrappers are guarded by their sections' own conditions; and `compact_dollars` drops its trailing `.0` with `removesuffix`. The review's `align-items: baseline` and `:has()` suggestions were not taken, for the reasons the entries give; its check of the phone council's tap targets (`.cc` keeps `position: relative` from `layout.css` and `.cc-dissent` its `z-index: 1`, so the dissent link stays above the stretched member link) and of the Jinja whitespace in the rest span found nothing to change. No milestone text, acceptance command, or test description changed.
