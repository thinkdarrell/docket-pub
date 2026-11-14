# 0094 — Every quotation that names a saved source is checked against it each time the content is loaded

## Decision

A rule's `quote` in a "How it works" explainer must name a `source_file` under the city's `sources/` directory, and the loader refuses the file unless the quoted words are in that saved copy: whitespace collapsed, curly quotation marks straightened, case kept, and a quotation that elides with "…" checked piece by piece, each piece after the end of the one before. A journey stop's quotation is held to the same check when the stop names a source file. The check is part of loading, so it runs at application start and in `./tools/verify`, not only in one test.

## Rationale

The design's first test of the page is that a reviewer can find every quoted word in its source. Without a mechanical check that holds on the day the content is written and decays with every later edit; with it, a quotation cannot drift from its source without stopping the build. The check earned its place while the content was being written: of the design's own rule statements, one quoted a sentence with the wrong capital, one quoted a sentence the saved copy holds only as damaged text, and one cited a notice period the cited section does not contain, and each was found by the check or by reading the saved file it forced open (plan `how-it-works-explainer`, M1).

The obvious alternative was a test over the Birmingham file alone. Putting the check in the loader makes it hold for every city and for content edited after the tests were written, and makes "the quotation is in the source" a property of any `Explainer` object the application holds.

Elided quotations are checked in pieces because the rules elide ("every ordinance or resolution … shall be submitted to a committee"): a whole-string comparison would fail on them, and forbidding ellipses would force long quotations onto the page. The comparison is case-sensitive and normalises only what a saved PDF changes (line breaks, typographic quotes), so that the check cannot pass a quotation that was tidied.

What the check does not do: it compares against the saved copy, not the public address, so a source the city has since amended passes until someone re-reads it (the read date is on the page); and a journey quotation whose record has no saved copy, and a journey's title, are outside it (`D126` in `docs/DEBT.md`). A `source_file` must be a bare file name inside `sources/`, so a quotation cannot be "found" in the content file that states it. The trap is loosening the comparison (ignoring case, punctuation, or order) to make a quotation pass; the fix for a quotation that fails is to quote what the source prints.

## Date

2026-11-12 (the check) and 2026-11-13 (piecewise checking of elided quotations; the check moved into the loader and extended to journey stops), the operator and Claude, in plan `how-it-works-explainer` (built in its M1 and M3).

## Status

accepted
