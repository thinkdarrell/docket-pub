# 0098 — A committee's action is its minutes' own words and a category, read by rule, and never a vote

## Decision

A committee's action is stored as the words of its minutes plus one of a closed list of twelve categories, the last of which is `other`. It is never stored or shown as a vote, a tally, "passed" or "failed". The reading is by fixed rules and patterns in `src/docket/adapters/committee_documents.py`; no language model reads a committee document.

## Rationale

Committee minutes record a motion and a second, not a roll call. Showing "passed" or a count would state something the record does not contain (`docs/PRINCIPLES.md`, "Source or silence"), and a committee does not decide: it recommends, and the page says so. An action that fits no category keeps its words and the category `other`, so nothing is forced into a label.

The obvious alternative for the reading is a model, which would cope with the minutes' misspellings and odd cases. The outcome wordings are few and regular: 753 of the 768 actions in the survey of 2026-11-13 fell into a category by pattern. A model's reading could not be traced to the line of the page it came from, and would differ between runs; a pattern's can, and a misread is corrected by mending the pattern, raising `PARSER_VERSION`, and letting `reparse` run. The mover and seconder patterns are matched in the case the minutes print them, because a surname is given to a reader as a fact and the stricter reading says nothing where the minutes print something unexpected.

## Date

2026-11-13, the plan author, and 2026-11-15 (the case of the mover and seconder), the M2 session, in plan `committee-documents`.

## Status

accepted
