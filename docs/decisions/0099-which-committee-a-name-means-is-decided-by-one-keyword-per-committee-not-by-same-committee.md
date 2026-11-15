# 0099 — Which committee a name means is decided by one keyword per committee, not by `same_committee`

## Decision

For committee documents, the committee a text refers to (a document's header, a meeting row's `body_name`) is decided by `committees_named` in `src/docket/adapters/committee_documents.py`: one pattern per canonical committee. `committee_of` gives a meeting's committee only when its `body_name` names exactly one. `same_committee` in `src/docket/services/meeting_types.py` is not used for this.

## Rationale

`same_committee` already exists and looks like the function to call. Run on 2026-11-13 against the fifteen committee `body_name` spellings in production, it matched thirteen and failed "Economic Development & Tourism Committee" and "Economic Development & Tourism Committee Work Session" against the canonical "Economic and Workforce Development / Tourism", because neither is a prefix of the other. That committee is the one with the most minutes and the fewest meeting rows, so the failure would have created a second row beside each of its existing ones. A keyword per committee matched all fifteen spellings and every document title in the survey.

The cost is known: a keyword can be found inside another word (the bare `ARTS` is found in "STARTS"; `D141` in `docs/DEBT.md`), and a text naming two committees names two, which is why a row whose `body_name` names none or several is no candidate for a document. An adapter may not import a service, so the adapter holds its own tuple of the eight names and a test asserts it equals `BIRMINGHAM_COMMITTEES`.

## Date

2026-11-13, the plan author, in plan `committee-documents` (built in its M1 and M4).

## Status

accepted
