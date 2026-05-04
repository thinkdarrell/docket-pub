# Vote-Matcher v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lift the substantive vote→agenda match rate above today's 10.7% by fixing the wrong-haystack bug, extracting more resolution numbers, and adding a structured-fact tier plus a rank-aware keyword tier to the matcher.

**Architecture:** Four compounding changes to `src/docket/analysis/vote_matcher.py`'s substantive ladder, supported by two new modules — `vote_resolution_extractor.py` (extracts resolution / ordinance numbers from `votes.raw_text`) and `structured_facts.py` (extracts proper nouns + dollar amounts). A backfill script reapplies the new logic to ~8,867 existing unmatched votes on Railway.

**Tech Stack:** Python 3.10+, PostgreSQL 16 (local) / 18 (Railway), psycopg2, pytest. No new dependencies.

**Spec:** [docs/superpowers/specs/2026-05-04-vote-matcher-v2-design.md](../specs/2026-05-04-vote-matcher-v2-design.md)

---

## File map

**New files:**
- `src/docket/analysis/vote_resolution_extractor.py` — pure extractor for resolution / ordinance numbers from raw_text
- `src/docket/analysis/structured_facts.py` — pure extractor for proper nouns + dollar amounts
- `tests/unit/test_vote_resolution_extractor.py`
- `tests/unit/test_structured_facts.py`
- `tests/unit/test_vote_matcher_v2.py` — new tier tests
- `tests/fixtures/vote_matcher_v2.py` — captured vote-1342 + agenda-item fixture
- `scripts/backfill_vote_resolution_numbers.py` — populate `votes.resolution_number` over the existing corpus
- `scripts/run_v2_backfill.py` — orchestrator for the local-then-Railway data push

**Modified files:**
- `src/docket/analysis/vote_matcher.py` — Tier 0 haystack swap, expanded stop words, new structured-fact tier, rank-aware keyword tier
- `src/docket/analysis/minutes_parser.py` — call new extractor inline during ingest

---

## Task 1: Branch setup and spec commit

**Files:**
- Modify: working tree (already has uncommitted footer/about-pages work)
- Create: `feat/vote-matcher-v2` branch

- [ ] **Step 1: Verify clean separation of in-flight work**

Run:
```bash
cd ~/docket-pub && git status
```

Expected: shows uncommitted footer/about-pages changes (`public.py`, `footer.html`, 4 new templates) plus untracked spec doc.

- [ ] **Step 2: Stage and commit the footer/about-pages work to main**

This work is already verified end-to-end (routes return 200, footer links resolve). It's unrelated to the matcher change and should land on main as a self-contained commit.

```bash
cd ~/docket-pub && git add \
  src/docket/web/public.py \
  src/docket/web/templates/partials/footer.html \
  src/docket/web/templates/about.html \
  src/docket/web/templates/about_methodology.html \
  src/docket/web/templates/about_corrections.html \
  src/docket/web/templates/councilors.html
git commit -m "$(cat <<'EOF'
feat(web): collapse footer to 2 columns and stub about pages

Replaces dead href="#" footer links with real destinations:
- /about/, /about/how-we-read-minutes/, /about/corrections/ now render
  simple direct text describing the project, methodology, and corrections
  policy
- /councilors/ city-picker links into existing per-city council pages
- footer reduced from 4 columns to 2 (About + For citizens), GitHub link
  preserved

Contact link is mailto:hello@docket.pub as a placeholder; swap when a
real address exists.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: clean commit on `main` with 6 files changed.

- [ ] **Step 3: Create the feature branch from main**

```bash
cd ~/docket-pub && git checkout -b feat/vote-matcher-v2
```

Expected: `Switched to a new branch 'feat/vote-matcher-v2'`.

- [ ] **Step 4: Commit the spec to the feature branch**

```bash
cd ~/docket-pub && git add docs/superpowers/specs/2026-05-04-vote-matcher-v2-design.md
git commit -m "$(cat <<'EOF'
docs: add vote-matcher v2 design spec

Proposes 4 compounding fixes to lift the 10.7% substantive match rate:
- Tier 0: read raw_text instead of match_context (fixes wrong-haystack bug)
- Aggressive resolution/ordinance number extraction with persistence
- New structured-fact tier (proper noun + dollar) above keyword overlap
- Rank-aware keyword tier with margin gate

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Commit this implementation plan to the feature branch**

```bash
cd ~/docket-pub && git add docs/superpowers/plans/2026-05-04-vote-matcher-v2.md
git commit -m "$(cat <<'EOF'
docs: add vote-matcher v2 implementation plan

12 tasks covering TDD of new matcher tiers, backfill of resolution
numbers, and rollout to Railway with snapshot/rollback.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Capture vote-1342 fixture

**Files:**
- Create: `tests/fixtures/__init__.py` (if not present)
- Create: `tests/fixtures/vote_matcher_v2.py`

- [ ] **Step 1: Ensure fixtures package exists**

```bash
cd ~/docket-pub && mkdir -p tests/fixtures && touch tests/fixtures/__init__.py
```

- [ ] **Step 2: Write the fixture file**

Create `tests/fixtures/vote_matcher_v2.py` with the captured Birmingham 2025-12-16 vote 1342 data:

```python
"""Captured fixture data for vote-matcher v2 regression tests.

Source: Birmingham Regular City Council Meeting, 2025-12-16 (meeting_id 26).
Vote 1342 — 7-0 approval of a quitclaim deed to Shield Property Solutions, LLC
for property at 609 4th Ave N for $11,155.25.

This is the canonical wrong-haystack failure case: raw_text contains the
substance, match_context contains only procedural language, and the v1
matcher does not link them.
"""

VOTE_1342_RAW_TEXT = """\
at Shield Property
Solutions, LLC has an interest in the Property, and accordingly, recommends that Shield
Property Solutions, LLC be allowed to purchase the Property for the amount of Eleven
Thousand One Hundred Fifty-Five and 25/100 Dollars ($11,155.25), which represents the total
amount of the original assessments plus costs, fees, and interest thereon at the rate of six
percent (6%) per annum.
NOW, THEREFORE, BE IT ORDAINED by the Council of the City of Birmingham
that the mayor be and hereby is authorized to execute, on behalf of the City of Birmingham, a
Quitclaim Deed conveying the Property to Shield Property Solutions, LLC upon payment of
the amount of $11,155.25 to the City within ninety (90) days of City Council approval.
NAME OF GRANTEE PROPERTY DESCRIPTION AMOUNT
Shield Property Solutions, LLC THE WEST 30 FEET OF LOT 7 AND $11,155.25
THE EAST 5 FEET OF LOTS 8 AND 10,
BLOCK 354, ACCORDING TO THE
PRESENT PLAN AND SURVEY OF THE
CITY OF BIRMINGHAMAS MADE BY
ELYTON LAND COMPANY, SITUATED
IN JEFFERSON COUNTY, ALABAMA.
PARCEL ID 22 00 35 3 032 004.000
City Account: 5332
PHYSICAL ADDRESS
609 4th Ave N
Birmingham, AL 35203
BE IT FURTHER ORDAINED that, in the judgment of said Council, the Property is not
needed for public or municipal purposes.
The resolution was read by the City Clerk, whereupon Councilmember Smitherman
made a motion that unanimous consent be granted to adopt said ordinance, which motion was
seconded by Councilmember Tate , and upon the roll being called, the vote was as follows:
Ayes: Gunn, Smith, Smitherman, Williams, Woods, Tate, Alexander
Nays: None
The vote was then announced by the City Clerk, whereupon the Presiding Officer
declared the motion to give unanimous consent for adoption of said ordinance adopted.
DEC 16 2025 6
Whereupon Councilmemb"""

VOTE_1342_MATCH_CONTEXT = (
    "ity Clerk, whereupon Councilmember Smitherman\n"
    "made a motion that unanimous consent be granted to adopt said ordinance, which motion was\n"
    "seconded by Councilmember Tate , and upon the roll being called,"
)

# Birmingham council surnames that appear in vote 1342's raw_text (used to
# verify the proper-noun denylist filters them out).
BIRMINGHAM_COUNCIL_SURNAMES_DEC_2025 = frozenset({
    "Gunn", "Smith", "Smitherman", "Williams", "Woods", "Tate", "Alexander",
})

# The agenda item this vote should match against.
AGENDA_ITEM_1256 = {
    "id": 1256,
    "item_number": "64",
    "title": (
        "P\t\tITEM 20. \n"
        "An Ordinance authorizing the Mayor, upon receipt of payment in the "
        "amount of $11,155.25, to execute a quitclaim deed to Shield Property "
        "Solutions, LLC, for the sale of property legally described as THE "
        "WEST 30 FEET OF LOT 7 AND THE EAST 5 FEE"
    ),
    "description": "",
}

# Distractor agenda items in the same meeting that should NOT match.
DISTRACTOR_AGENDA_ITEMS = [
    {
        "id": 1200,
        "item_number": "1",
        "title": "An Ordinance approving the City of Birmingham FY2026 budget",
        "description": "",
    },
    {
        "id": 1201,
        "item_number": "2",
        "title": "A Resolution honoring the Birmingham Public Library staff",
        "description": "",
    },
]
```

- [ ] **Step 3: Commit the fixture**

```bash
cd ~/docket-pub && git add tests/fixtures/__init__.py tests/fixtures/vote_matcher_v2.py
git commit -m "test: capture vote 1342 fixture for matcher v2 regression tests

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Resolution-number extractor module — TDD

**Files:**
- Create: `src/docket/analysis/vote_resolution_extractor.py`
- Test: `tests/unit/test_vote_resolution_extractor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_vote_resolution_extractor.py`:

```python
"""Tests for analysis/vote_resolution_extractor.py."""

from docket.analysis.vote_resolution_extractor import extract_resolution_number


def test_extracts_simple_resolution_number():
    text = "RESOLUTION 1854-25 A Resolution authorizing the Mayor..."
    assert extract_resolution_number(text) == "1854-25"


def test_extracts_ordinance_with_no_dot():
    text = "ORDINANCE NO 23-101 An Ordinance approving..."
    assert extract_resolution_number(text) == "23-101"


def test_extracts_ordinance_with_dot():
    text = "ORDINANCE NO. 23-101 An Ordinance approving..."
    assert extract_resolution_number(text) == "23-101"


def test_extracts_resolution_with_letter_prefix():
    text = "Resolution No. R-2024-0419 honoring the staff"
    assert extract_resolution_number(text) == "R-2024-0419"


def test_extracts_with_slash_separator():
    text = "ORDINANCE 22/2024 was adopted"
    assert extract_resolution_number(text) == "22/2024"


def test_returns_none_when_no_match():
    text = "The City Clerk read the minutes from last meeting."
    assert extract_resolution_number(text) is None


def test_returns_none_for_empty_input():
    assert extract_resolution_number("") is None
    assert extract_resolution_number(None) is None  # type: ignore[arg-type]


def test_picks_last_match_before_tally_marker():
    """When raw_text references multiple resolutions, pick the one being voted on."""
    text = (
        "Resolution 1100-25 was adopted last week. "
        "Today, RESOLUTION 1854-25 is presented for approval. "
        "Upon the roll being called, the vote was as follows: "
        "Ayes: All. Nays: None."
    )
    # Substring before the tally marker contains both 1100-25 and 1854-25;
    # we want the rightmost (1854-25, the one being voted on).
    assert extract_resolution_number(text) == "1854-25"


def test_falls_back_to_full_text_when_no_tally_marker():
    text = "RESOLUTION 1854-25 A Resolution authorizing..."
    assert extract_resolution_number(text) == "1854-25"


def test_case_insensitive_keyword():
    text = "resolution 1854-25 A Resolution authorizing..."
    assert extract_resolution_number(text) == "1854-25"


def test_does_not_match_bare_numbers():
    text = "The amount was $11,155.25 paid in 2025."
    assert extract_resolution_number(text) is None


def test_does_not_glue_onto_adjacent_text():
    """[-/] are the only separators; spaces and other chars don't extend the number."""
    text = "RESOLUTION 1854-25.adopted"
    # Stops at .adopted — not a separator
    assert extract_resolution_number(text) == "1854-25"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd ~/docket-pub && venv/bin/pytest tests/unit/test_vote_resolution_extractor.py -v
```

Expected: `ModuleNotFoundError: No module named 'docket.analysis.vote_resolution_extractor'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/docket/analysis/vote_resolution_extractor.py`:

```python
"""Extract resolution / ordinance numbers from a vote's raw_text.

Used by:
- analysis/minutes_parser.py (inline extraction during ingest)
- scripts/backfill_vote_resolution_numbers.py (one-shot over existing rows)

Design: prefer the rightmost identifier that appears BEFORE any vote-tally
marker, since that's the one being acted on. If no tally marker is found,
scan the full text.
"""

from __future__ import annotations

import re

_VOTE_RES_RE = re.compile(
    r"\b(?:RESOLUTION|ORDINANCE)\s+(?:NO\.?\s*)?"
    r"(?P<num>(?:R|O)?-?\d{1,5}(?:[-/]\d{2,4})?)\b",
    re.IGNORECASE,
)

_TALLY_MARKERS = (
    "the vote was as follows",
    "upon the roll being called",
    "ayes:",
    "yeas:",
    "roll call:",
    "roll being called",
)


def _truncate_at_tally(text: str) -> str:
    """Return the substring of `text` ending at the earliest tally marker.

    If no marker is present, return the full text.
    """
    lowered = text.lower()
    earliest = len(text)
    for marker in _TALLY_MARKERS:
        idx = lowered.find(marker)
        if idx != -1 and idx < earliest:
            earliest = idx
    return text[:earliest]


def extract_resolution_number(text: str | None) -> str | None:
    """Return the rightmost RESOLUTION/ORDINANCE number before the tally, or None."""
    if not text:
        return None
    pre_tally = _truncate_at_tally(text)
    matches = list(_VOTE_RES_RE.finditer(pre_tally))
    if not matches:
        return None
    return matches[-1].group("num")
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd ~/docket-pub && venv/bin/pytest tests/unit/test_vote_resolution_extractor.py -v
```

Expected: all 11 tests pass.

- [ ] **Step 5: Commit**

```bash
cd ~/docket-pub && git add src/docket/analysis/vote_resolution_extractor.py tests/unit/test_vote_resolution_extractor.py
git commit -m "feat(analysis): vote-resolution-number extractor

Pure regex pass over raw_text. Picks the rightmost RESOLUTION/ORDINANCE
identifier before any vote-tally marker (or in full text if no marker
appears). 11 unit tests covering separators, prefixes, multi-match
sequencing, and no-match fallthrough.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Wire resolution extractor into minutes parser

**Files:**
- Modify: `src/docket/analysis/minutes_parser.py`

- [ ] **Step 1: Read minutes_parser.py to find the vote-construction site**

Run:
```bash
cd ~/docket-pub && grep -n "resolution_number" src/docket/analysis/minutes_parser.py
```

Inspect the surrounding code so the extractor call is added at the right point — after `raw_text` is set on the vote dict, before the row is yielded/inserted.

- [ ] **Step 2: Write a failing test for the inline integration**

Append to `tests/unit/test_vote_resolution_extractor.py`:

```python
def test_minutes_parser_populates_resolution_number_from_raw_text(monkeypatch):
    """When the parser builds a vote whose raw_text contains a RESOLUTION number,
    the constructed vote dict should have resolution_number filled in."""
    from docket.analysis import minutes_parser as mp

    raw_text = (
        "RESOLUTION 1854-25 A Resolution authorizing the purchase of equipment. "
        "Upon the roll being called, the vote was as follows: Ayes: All."
    )

    # Use the parser's vote-construction helper directly. Replace the
    # function name below with the actual one once Step 1 identifies it.
    vote = mp._build_vote_from_section(raw_text=raw_text, match_context="", header_result=None)
    assert vote["resolution_number"] == "1854-25"
```

(If the parser doesn't have a `_build_vote_from_section` helper today, the integration test instead asserts on `parse_minutes_for_votes` output. Update the test name accordingly after Step 1.)

- [ ] **Step 3: Run test to verify it fails**

Run:
```bash
cd ~/docket-pub && venv/bin/pytest tests/unit/test_vote_resolution_extractor.py::test_minutes_parser_populates_resolution_number_from_raw_text -v
```

Expected: assertion failure (resolution_number is None or missing).

- [ ] **Step 4: Add the call site in minutes_parser.py**

At the vote-construction site identified in Step 1, add (preserving the existing logic — only fill if not already populated by the legacy narrow extractor):

```python
from docket.analysis.vote_resolution_extractor import extract_resolution_number

# ... where the vote dict is being built ...
if not vote.get("resolution_number"):
    vote["resolution_number"] = extract_resolution_number(raw_text)
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd ~/docket-pub && venv/bin/pytest tests/unit/test_vote_resolution_extractor.py -v
```

Expected: all tests pass, including the new integration test.

- [ ] **Step 6: Run the full minutes_parser test suite to confirm no regressions**

Run:
```bash
cd ~/docket-pub && venv/bin/pytest tests/unit/test_minutes_parser.py -v
```

Expected: all existing tests still pass.

- [ ] **Step 7: Commit**

```bash
cd ~/docket-pub && git add src/docket/analysis/minutes_parser.py tests/unit/test_vote_resolution_extractor.py
git commit -m "feat(analysis): wire resolution-number extractor into minutes parser

New votes get resolution_number populated inline from raw_text when the
existing narrow extractor didn't fire.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Structured-facts module — TDD

**Files:**
- Create: `src/docket/analysis/structured_facts.py`
- Test: `tests/unit/test_structured_facts.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_structured_facts.py`:

```python
"""Tests for analysis/structured_facts.py."""

from docket.analysis.structured_facts import (
    extract_dollar_amounts,
    extract_proper_nouns,
)


def test_extract_dollar_amounts_simple():
    text = "Pay $11,155.25 to the vendor."
    assert extract_dollar_amounts(text) == {11155.25}


def test_extract_dollar_amounts_multiple():
    text = "Two contracts: $50,000 and $1,250.75."
    assert extract_dollar_amounts(text) == {50000.0, 1250.75}


def test_extract_dollar_amounts_none():
    text = "No money mentioned here."
    assert extract_dollar_amounts(text) == set()


def test_extract_proper_nouns_finds_company():
    text = "Pay Shield Property Solutions for the work."
    surnames: set[str] = set()
    result = extract_proper_nouns(text, council_surnames=surnames)
    assert "Shield Property Solutions" in result


def test_extract_proper_nouns_excludes_council_surnames():
    text = "Councilmember Smitherman seconded the motion by Tate."
    surnames = {"Smitherman", "Tate"}
    result = extract_proper_nouns(text, council_surnames=surnames)
    # Surnames should be filtered. "Councilmember Smitherman" wouldn't match
    # the regex shape (Councilmember is filtered as procedural), but if any
    # surnames slipped through they'd be removed.
    assert "Smitherman" not in result
    assert "Tate" not in result


def test_extract_proper_nouns_excludes_procedural_phrases():
    text = "The City Clerk read the resolution."
    result = extract_proper_nouns(text, council_surnames=set())
    assert "City Clerk" not in result


def test_extract_proper_nouns_excludes_month_names():
    text = "On December 16, the council met."
    result = extract_proper_nouns(text, council_surnames=set())
    assert not any("December" in p for p in result)


def test_extract_proper_nouns_handles_ampersand():
    text = "The contract with Smith & Jones LLC was approved."
    result = extract_proper_nouns(text, council_surnames=set())
    assert any("Smith & Jones" in p for p in result)


def test_extract_proper_nouns_min_two_tokens():
    """Single capitalized words should not be treated as proper-noun phrases."""
    text = "The Mayor signed it."
    result = extract_proper_nouns(text, council_surnames=set())
    # "Mayor" alone is not a multi-token phrase
    assert "Mayor" not in result


def test_extract_proper_nouns_real_world_vote_1342():
    """Vote 1342: must extract 'Shield Property Solutions' and not surnames."""
    from tests.fixtures.vote_matcher_v2 import (
        VOTE_1342_RAW_TEXT,
        BIRMINGHAM_COUNCIL_SURNAMES_DEC_2025,
    )
    result = extract_proper_nouns(
        VOTE_1342_RAW_TEXT,
        council_surnames=BIRMINGHAM_COUNCIL_SURNAMES_DEC_2025,
    )
    assert "Shield Property Solutions" in result
    # Surnames must not leak through
    for surname in BIRMINGHAM_COUNCIL_SURNAMES_DEC_2025:
        assert surname not in result, f"council surname {surname} leaked into proper nouns"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd ~/docket-pub && venv/bin/pytest tests/unit/test_structured_facts.py -v
```

Expected: `ModuleNotFoundError: No module named 'docket.analysis.structured_facts'`.

- [ ] **Step 3: Inspect docket.enrichment.dollars to confirm API**

Before writing the structured_facts module, check the actual function name and return shape in the existing dollars extractor:

```bash
cd ~/docket-pub && grep -n "^def " src/docket/enrichment/dollars.py
```

Note the function name (likely `extract_dollar_amounts` per CLAUDE.md, but verify) and what it returns (likely `list[tuple[float, str]]` of `(amount, raw_match)` — but verify by reading the function). Adjust the import and call site in Step 4 accordingly if the actual API differs.

- [ ] **Step 4: Write minimal implementation**

Create `src/docket/analysis/structured_facts.py`:

```python
"""Extract high-signal structured facts from vote raw_text.

Two extractors:
- extract_dollar_amounts: numeric dollar values
- extract_proper_nouns: multi-token capitalized phrases (filtered against
  council surnames, procedural phrases, and month names)

Used by the structured-fact tier of the substantive vote matcher.
"""

from __future__ import annotations

import re

# NOTE: function name and return shape verified in Step 3 above.
# Adjust the import and unpacking below if the dollars module's API differs.
from docket.enrichment.dollars import extract_dollar_amounts as _dollars_from_text


_PROPER_NOUN_RE = re.compile(
    r"\b(?:[A-Z][a-zA-Z&]+(?:\s+(?:&\s+)?[A-Z][a-zA-Z&]*)?(?:\s+[A-Z][a-zA-Z&]+){0,3})\b"
)

_MULTI_TOKEN_RE = re.compile(r"\s")  # any whitespace splits tokens

_PROCEDURAL_DENYLIST = frozenset({
    "City Clerk", "Presiding Officer", "Council Chamber", "City Council",
    "City Hall", "Mayor's Office", "The City", "The Council", "The Mayor",
    "City of", "City of Birmingham", "Birmingham As Made",
    "Roll Call", "Roll Being",
})

_MONTH_NAMES = frozenset({
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
})


def extract_dollar_amounts(text: str | None) -> set[float]:
    """Return the set of dollar amounts in text as floats."""
    if not text:
        return set()
    # enrichment.dollars returns a list of (amount, raw_match) tuples; flatten
    items = _dollars_from_text(text)
    return {float(amount) for amount, _raw in items}


def _is_multi_token(phrase: str) -> bool:
    return bool(_MULTI_TOKEN_RE.search(phrase))


def extract_proper_nouns(text: str | None, *, council_surnames: set[str]) -> set[str]:
    """Return multi-token capitalized phrases, filtered for noise.

    Filters: council surnames (single-word match against any token), procedural
    phrases (full-phrase match), month names (any token match).
    """
    if not text:
        return set()
    raw = {m.group(0) for m in _PROPER_NOUN_RE.finditer(text)}
    result: set[str] = set()
    for phrase in raw:
        if not _is_multi_token(phrase):
            continue
        if phrase in _PROCEDURAL_DENYLIST:
            continue
        tokens = phrase.split()
        if any(tok in council_surnames for tok in tokens):
            continue
        if any(tok in _MONTH_NAMES for tok in tokens):
            continue
        result.add(phrase)
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd ~/docket-pub && venv/bin/pytest tests/unit/test_structured_facts.py -v
```

Expected: all 10 tests pass.

If the regex misses "Shield Property Solutions" (the regex group structure is fiddly), iterate on the pattern until the real-world vote-1342 test passes. The real-world test is the load-bearing one.

- [ ] **Step 6: Commit**

```bash
cd ~/docket-pub && git add src/docket/analysis/structured_facts.py tests/unit/test_structured_facts.py
git commit -m "feat(analysis): structured-facts extractor (proper nouns + dollars)

Pure deterministic extraction. Filters council surnames, procedural
phrases, and month names from proper-noun candidates. Includes
real-world regression case (vote 1342, 'Shield Property Solutions').

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Tier 0 — haystack swap + stop-word expansion

**Files:**
- Modify: `src/docket/analysis/vote_matcher.py`
- Test: `tests/unit/test_vote_matcher_v2.py`

- [ ] **Step 1: Write failing test for the haystack swap**

Create `tests/unit/test_vote_matcher_v2.py`:

```python
"""Tier-by-tier tests for vote_matcher v2 changes.

Each test exercises one tier in isolation. Integration test for the full
flow lives at tests/integration/test_vote_matcher_v2_integration.py.
"""

from __future__ import annotations

from tests.fixtures.vote_matcher_v2 import (
    VOTE_1342_RAW_TEXT,
    VOTE_1342_MATCH_CONTEXT,
    AGENDA_ITEM_1256,
    DISTRACTOR_AGENDA_ITEMS,
)


def _make_vote(*, raw_text=VOTE_1342_RAW_TEXT, match_context=VOTE_1342_MATCH_CONTEXT,
               resolution_number=None):
    return {
        "id": 1342,
        "raw_text": raw_text,
        "match_context": match_context,
        "resolution_number": resolution_number,
    }


def test_keyword_tier_reads_raw_text_not_match_context():
    """The wrong-haystack regression: substance lives in raw_text, not match_context."""
    from docket.analysis.vote_matcher import _try_keyword_match

    vote = _make_vote()
    items = [AGENDA_ITEM_1256] + DISTRACTOR_AGENDA_ITEMS
    result = _try_keyword_match(vote, items)
    assert result is not None, "expected keyword tier to match item 1256 from raw_text"
    item_id, conf, method = result
    assert item_id == 1256
    assert method == "text_similarity"
    assert 0.5 <= conf <= 0.75


def test_keyword_tier_falls_back_to_match_context_when_raw_text_null():
    """Legacy rows without raw_text should still get the old behavior."""
    from docket.analysis.vote_matcher import _try_keyword_match

    # An older vote with strong substance in match_context (unrealistic for v1
    # rows, but shows the fallback logic works).
    vote = _make_vote(raw_text=None,
                      match_context="Shield Property Solutions $11,155.25 Quitclaim deed")
    items = [AGENDA_ITEM_1256]
    result = _try_keyword_match(vote, items)
    assert result is not None


def test_stop_words_filter_procedural_noise():
    """Vote with only procedural words should NOT match an item with the same
    procedural words but different substance."""
    from docket.analysis.vote_matcher import _try_keyword_match

    vote = _make_vote(
        raw_text=(
            "councilmember motion seconded ordinance resolution mayor "
            "ayes nays council presiding officer whereupon hereby"
        ),
        match_context="",
    )
    items = [{
        "id": 999,
        "item_number": "1",
        "title": "An Ordinance approving the council's resolution by the Mayor",
        "description": "",
    }]
    result = _try_keyword_match(vote, items)
    assert result is None, "procedural overlap alone should not produce a match"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd ~/docket-pub && venv/bin/pytest tests/unit/test_vote_matcher_v2.py -v
```

Expected: `test_keyword_tier_reads_raw_text_not_match_context` fails (today's matcher reads match_context). The other tests may also fail depending on existing stop words.

- [ ] **Step 3: Apply the haystack swap and stop-word expansion**

Edit `src/docket/analysis/vote_matcher.py`:

Replace the body of `_try_item_number_match` (around line 347):

```python
def _try_item_number_match(vote, items) -> tuple[int, float, str] | None:
    """Match by item number patterns found in vote raw_text."""
    text = vote.get("raw_text") or vote.get("match_context") or ""
    if not text:
        return None

    m = re.search(r'(?:Item|ITEM)\s+(?:No\.?\s*)?(\d+)', text)
    if not m:
        m = re.search(r'#(\d+)', text)
    if not m:
        return None

    target_num = m.group(1)
    for item in items:
        if item["item_number"] == target_num:
            return (item["id"], 0.7, "item_number")

    return None
```

Replace the body of `_try_keyword_match` (around line 368):

```python
def _try_keyword_match(vote, items) -> tuple[int, float, str] | None:
    """Match by keyword overlap between vote raw_text and agenda item title.

    Rank-aware: requires the best item to beat the second-best by margin,
    else defers (Task 8 implements this; for Tier 0 alone, today's behavior
    is preserved).
    """
    text = vote.get("raw_text") or vote.get("match_context") or ""
    if not text:
        return None

    text_words = _significant_words(text)
    if len(text_words) < 3:
        return None

    best_item_id = None
    best_overlap = 0.0

    for item in items:
        title = item["title"] or ""
        title_words = _significant_words(title)
        if not title_words:
            continue
        overlap = len(text_words & title_words) / max(len(text_words), len(title_words))
        if overlap > best_overlap:
            best_overlap = overlap
            best_item_id = item["id"]

    if best_overlap >= 0.3 and best_item_id is not None:
        return (best_item_id, round(min(0.5 + best_overlap * 0.3, 0.8), 2), "text_similarity")

    return None
```

Expand `_STOP_WORDS` (around line 398):

```python
_STOP_WORDS = frozenset(
    "a an the of to in for on and or by at is was be are with that this from"
    " it its no not but as has had have been do does did will shall may can"
    " upon said being hereby"
    # v2: procedural noise from the wider raw_text window
    " councilmember councilmembers motion seconded ordinance resolution mayor"
    " ayes nays council presiding officer chairperson whereupon thereupon"
    " adopted approved granted item agenda".split()
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd ~/docket-pub && venv/bin/pytest tests/unit/test_vote_matcher_v2.py -v
```

Expected: all 3 tier-0 tests pass.

- [ ] **Step 5: Run the full vote_matcher test suite for regressions**

Run:
```bash
cd ~/docket-pub && venv/bin/pytest tests/unit/test_vote_matcher.py -v
```

Expected: all existing v1 tests pass. If any fail because of the stop-word expansion, evaluate whether the test's expectation was correct under v1 but wrong under v2. Update the test only if you can articulate why v2's behavior is more correct.

- [ ] **Step 6: Commit**

```bash
cd ~/docket-pub && git add src/docket/analysis/vote_matcher.py tests/unit/test_vote_matcher_v2.py
git commit -m "fix(matcher): tier 0 — substantive matcher reads raw_text, not match_context

Root cause for the 10.7% substantive match rate. raw_text contains the
full pre-vote substance; match_context is a 200-char procedural window
that only captures floor language ('made a motion that unanimous consent
be granted'). Adding a fallback to match_context preserves behavior for
legacy rows where raw_text is NULL.

Also expands _STOP_WORDS with procedural terms now leaking through the
wider window (councilmember, motion, seconded, etc.).

Regression test uses captured fixture from vote 1342 (Shield Property
Solutions, 2025-12-16).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Structured-fact tier in vote_matcher

**Files:**
- Modify: `src/docket/analysis/vote_matcher.py`
- Test: `tests/unit/test_vote_matcher_v2.py`

- [ ] **Step 1: Write failing tests for the structured-fact tier**

Append to `tests/unit/test_vote_matcher_v2.py`:

```python
def test_structured_fact_tier_matches_proper_noun_plus_dollar():
    """Vote 1342 baseline: proper noun + dollar match → conf 0.9."""
    from docket.analysis.vote_matcher import _try_structured_fact_match

    vote = _make_vote()
    items = [AGENDA_ITEM_1256] + DISTRACTOR_AGENDA_ITEMS
    result = _try_structured_fact_match(
        vote, items,
        council_surnames={"Gunn", "Smith", "Smitherman", "Williams", "Woods", "Tate", "Alexander"},
    )
    assert result is not None
    item_id, conf, method = result
    assert item_id == 1256
    assert method == "structured_fact"
    assert conf == 0.9


def test_structured_fact_tier_proper_noun_only_lower_confidence():
    """Item title without the dollar amount → conf 0.8."""
    from docket.analysis.vote_matcher import _try_structured_fact_match

    items = [{
        "id": 200,
        "item_number": "1",
        "title": "An Ordinance about Shield Property Solutions activities",
        "description": "",
    }]
    vote = _make_vote()  # raw_text contains both proper noun and dollar
    result = _try_structured_fact_match(vote, items, council_surnames=set())
    assert result is not None
    item_id, conf, method = result
    assert item_id == 200
    assert conf == 0.8


def test_structured_fact_tier_dollar_only_no_match():
    """Same dollar amount in two unrelated items must not match by dollar alone."""
    from docket.analysis.vote_matcher import _try_structured_fact_match

    items = [{
        "id": 300,
        "item_number": "1",
        "title": "A Resolution paying $11,155.25 to a totally unrelated vendor",
        "description": "",
    }]
    vote = _make_vote()
    result = _try_structured_fact_match(vote, items, council_surnames=set())
    assert result is None


def test_structured_fact_tier_tied_proper_nouns_no_match():
    """If two items share the proper noun, defer."""
    from docket.analysis.vote_matcher import _try_structured_fact_match

    items = [
        {"id": 401, "item_number": "1",
         "title": "Item about Shield Property Solutions",
         "description": ""},
        {"id": 402, "item_number": "2",
         "title": "Another Shield Property Solutions matter",
         "description": ""},
    ]
    vote = _make_vote()
    result = _try_structured_fact_match(vote, items, council_surnames=set())
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd ~/docket-pub && venv/bin/pytest tests/unit/test_vote_matcher_v2.py::test_structured_fact_tier_matches_proper_noun_plus_dollar -v
```

Expected: `AttributeError: module 'docket.analysis.vote_matcher' has no attribute '_try_structured_fact_match'`.

- [ ] **Step 3: Add `_try_structured_fact_match`**

In `src/docket/analysis/vote_matcher.py`, after `_try_item_number_match` (around line 365), add:

```python
def _try_structured_fact_match(
    vote, items, *, council_surnames: set[str]
) -> tuple[int, float, str] | None:
    """Match by proper-noun + optional dollar overlap.

    High-precision tier requiring at least one proper-noun anchor.
    Returns (item_id, confidence, method) or None.
    """
    from docket.analysis.structured_facts import (
        extract_dollar_amounts,
        extract_proper_nouns,
    )

    text = vote.get("raw_text") or vote.get("match_context") or ""
    if not text:
        return None

    vote_proper_nouns = extract_proper_nouns(text, council_surnames=council_surnames)
    if not vote_proper_nouns:
        return None
    vote_dollars = extract_dollar_amounts(text)

    best_item_id = None
    best_proper_noun_count = 0
    best_has_dollar = False

    for item in items:
        haystack = (item["title"] or "") + " " + (item.get("description") or "")
        item_proper_nouns = extract_proper_nouns(haystack, council_surnames=council_surnames)
        item_dollars = extract_dollar_amounts(haystack)

        proper_noun_overlap = vote_proper_nouns & item_proper_nouns
        if not proper_noun_overlap:
            continue

        has_dollar = bool(vote_dollars & item_dollars)

        # Prefer more proper-noun overlap; tie-breaker is dollar match.
        if (
            len(proper_noun_overlap) > best_proper_noun_count
            or (len(proper_noun_overlap) == best_proper_noun_count and has_dollar and not best_has_dollar)
        ):
            best_item_id = item["id"]
            best_proper_noun_count = len(proper_noun_overlap)
            best_has_dollar = has_dollar
        elif len(proper_noun_overlap) == best_proper_noun_count and has_dollar == best_has_dollar:
            # Genuine tie — defer.
            return None

    if best_item_id is None:
        return None

    conf = 0.9 if best_has_dollar else 0.8
    return (best_item_id, conf, "structured_fact")
```

Then wire it into `_match_substantive` (around line 215):

```python
# In _match_substantive, build council_surnames once per meeting:
cur.execute(
    """SELECT cm.last_name FROM council_members cm
       JOIN meetings m ON m.municipality_id = cm.municipality_id
       WHERE m.id = %s AND cm.is_active = TRUE""",
    (meeting_id,),
)
council_surnames = {r["last_name"] for r in cur.fetchall() if r["last_name"]}

# ... then in the per-vote loop, change the tier ladder:
result = (
    _try_resolution_match(vote, items)
    or _try_item_number_match(vote, items)
    or _try_structured_fact_match(vote, items, council_surnames=council_surnames)
    or _try_keyword_match(vote, items)
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd ~/docket-pub && venv/bin/pytest tests/unit/test_vote_matcher_v2.py -v
```

Expected: all tests in the file pass (3 tier-0 + 4 structured-fact = 7 total).

- [ ] **Step 5: Commit**

```bash
cd ~/docket-pub && git add src/docket/analysis/vote_matcher.py tests/unit/test_vote_matcher_v2.py
git commit -m "feat(matcher): structured-fact tier (proper noun + dollar)

New tier between item-number and keyword. Requires a proper-noun anchor;
dollar match upgrades confidence from 0.8 to 0.9. Defers on tied
proper-noun overlap rather than guessing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Rank-aware keyword tier

**Files:**
- Modify: `src/docket/analysis/vote_matcher.py`
- Test: `tests/unit/test_vote_matcher_v2.py`

- [ ] **Step 1: Write failing tests for rank-awareness**

Append to `tests/unit/test_vote_matcher_v2.py`:

```python
def test_rank_aware_keyword_rejects_close_runner_up():
    """Best 0.4 vs second 0.39 → no match (margin gate)."""
    from docket.analysis.vote_matcher import _try_keyword_match

    vote = {
        "raw_text": "alpha beta gamma delta epsilon zeta eta theta iota kappa",
        "match_context": "",
    }
    items = [
        {"id": 1, "item_number": "1",
         "title": "alpha beta gamma delta",
         "description": ""},
        {"id": 2, "item_number": "2",
         "title": "alpha beta gamma kappa",
         "description": ""},
    ]
    result = _try_keyword_match(vote, items)
    assert result is None, "near-tie should not commit"


def test_rank_aware_keyword_accepts_clear_winner():
    """Best clearly beats second → match."""
    from docket.analysis.vote_matcher import _try_keyword_match

    vote = {
        "raw_text": "alpha beta gamma delta epsilon zeta eta theta",
        "match_context": "",
    }
    items = [
        {"id": 1, "item_number": "1",
         "title": "alpha beta gamma delta epsilon",
         "description": ""},
        {"id": 2, "item_number": "2",
         "title": "completely different unrelated text",
         "description": ""},
    ]
    result = _try_keyword_match(vote, items)
    assert result is not None
    item_id, _conf, _method = result
    assert item_id == 1


def test_rank_aware_keyword_single_candidate_falls_back_to_absolute_threshold():
    """Single-item meeting has no second-best; use today's 0.3 floor."""
    from docket.analysis.vote_matcher import _try_keyword_match

    vote = {
        "raw_text": "alpha beta gamma delta",
        "match_context": "",
    }
    items = [
        {"id": 1, "item_number": "1",
         "title": "alpha beta gamma",
         "description": ""},
    ]
    result = _try_keyword_match(vote, items)
    assert result is not None


def test_upsert_link_respects_manual_shield_after_v2_changes():
    """A vote_agenda_items row with is_manual=TRUE must not be overwritten
    even when one of the new tiers (structured-fact) would otherwise commit
    a different link."""
    from docket.analysis.vote_matcher import _upsert_link
    from docket.db import db_cursor

    # This test uses real DB but ephemeral fixture rows. Wrap in cleanup.
    MEETING_ID = 99500
    VOTE_ID = 995000
    ITEM_ID = 995100
    try:
        with db_cursor() as cur:
            cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham' LIMIT 1")
            muni = cur.fetchone()
            cur.execute(
                """INSERT INTO meetings (id, municipality_id, meeting_date, title, source_url)
                   VALUES (%s, %s, '2025-01-01', 't', '') ON CONFLICT (id) DO NOTHING""",
                (MEETING_ID, muni["id"]),
            )
            cur.execute(
                """INSERT INTO agenda_items (id, meeting_id, item_number, title, description, is_consent)
                   VALUES (%s, %s, '1', 'manual title', '', FALSE)
                   ON CONFLICT (id) DO NOTHING""",
                (ITEM_ID, MEETING_ID),
            )
            cur.execute(
                """INSERT INTO votes (id, meeting_id, source, raw_text, yeas, nays, abstentions, result)
                   VALUES (%s, %s, 'minutes_text', 'irrelevant', 5, 0, 0, 'passed')
                   ON CONFLICT (id) DO NOTHING""",
                (VOTE_ID, MEETING_ID),
            )
            # Insert a manually-locked link first
            cur.execute(
                """INSERT INTO vote_agenda_items
                    (vote_id, agenda_item_id, association_type, match_method,
                     match_confidence, is_manual, is_active, provisional)
                   VALUES (%s, %s, 'explicit', 'manual', 1.0, TRUE, TRUE, FALSE)""",
                (VOTE_ID, ITEM_ID),
            )

            # Now try to overwrite via _upsert_link (simulating any v2 tier)
            _upsert_link(
                cur,
                vote_id=VOTE_ID,
                agenda_item_id=ITEM_ID,
                association_type="explicit",
                match_method="structured_fact",
                match_confidence=0.9,
                excerpt_context="should not appear",
                provisional=False,
            )

            cur.execute(
                "SELECT match_method, match_confidence, excerpt_context FROM vote_agenda_items "
                "WHERE vote_id = %s AND agenda_item_id = %s",
                (VOTE_ID, ITEM_ID),
            )
            row = cur.fetchone()
            assert row["match_method"] == "manual", "manual shield was breached"
            assert row["match_confidence"] == 1.0
            assert row["excerpt_context"] != "should not appear"
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM vote_agenda_items WHERE vote_id = %s", (VOTE_ID,))
            cur.execute("DELETE FROM votes WHERE id = %s", (VOTE_ID,))
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (ITEM_ID,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (MEETING_ID,))
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd ~/docket-pub && venv/bin/pytest tests/unit/test_vote_matcher_v2.py::test_rank_aware_keyword_rejects_close_runner_up -v
```

Expected: fails (today's matcher commits the close winner).

- [ ] **Step 3: Replace `_try_keyword_match` with the rank-aware version**

In `src/docket/analysis/vote_matcher.py`, replace `_try_keyword_match`:

```python
def _try_keyword_match(vote, items) -> tuple[int, float, str] | None:
    """Match by keyword overlap, rank-aware.

    Commits only when:
      - best score >= 0.25 (lowered floor; rank gate provides safety), AND
      - best >= 1.5 * second_best  OR  best - second_best >= 0.15

    Single-candidate meetings fall back to the v1 absolute threshold (>= 0.3).
    """
    text = vote.get("raw_text") or vote.get("match_context") or ""
    if not text:
        return None

    text_words = _significant_words(text)
    if len(text_words) < 3:
        return None

    scored: list[tuple[float, int]] = []
    for item in items:
        title = item["title"] or ""
        title_words = _significant_words(title)
        if not title_words:
            continue
        overlap = len(text_words & title_words) / max(len(text_words), len(title_words))
        scored.append((overlap, item["id"]))

    if not scored:
        return None

    scored.sort(reverse=True)

    best_score, best_id = scored[0]

    # Single-candidate fallback: use absolute threshold.
    if len(scored) == 1:
        if best_score >= 0.3:
            return (best_id, round(min(0.5 + best_score * 0.3, 0.75), 2), "text_similarity")
        return None

    second_score = scored[1][0]

    if best_score < 0.25:
        return None

    margin_ratio_ok = best_score >= second_score * 1.5
    margin_abs_ok = (best_score - second_score) >= 0.15
    if not (margin_ratio_ok or margin_abs_ok):
        logger.debug(
            "keyword tier deferred: best=%.3f second=%.3f no margin", best_score, second_score
        )
        return None

    margin = best_score - second_score
    conf = round(min(0.5 + best_score * 0.3 + margin * 0.5, 0.75), 2)
    return (best_id, conf, "text_similarity")
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd ~/docket-pub && venv/bin/pytest tests/unit/test_vote_matcher_v2.py -v
```

Expected: all 10 tier tests pass.

- [ ] **Step 5: Run the full unit test suite to confirm no regressions**

Run:
```bash
cd ~/docket-pub && venv/bin/pytest tests/unit/ -v
```

Expected: all tests pass. Investigate any failures: if a v1 test relied on an aggressive keyword match that's now correctly rejected by the rank gate, update the test (and document the v1 → v2 behavior change in the commit message).

- [ ] **Step 6: Commit**

```bash
cd ~/docket-pub && git add src/docket/analysis/vote_matcher.py tests/unit/test_vote_matcher_v2.py
git commit -m "feat(matcher): rank-aware keyword tier

Lowered absolute floor (0.3 → 0.25) but added a margin gate: best must
beat second-best by 1.5x ratio OR +0.15 absolute. Single-candidate
meetings fall back to v1 absolute behavior. Confidence capped at 0.75
to keep the ladder coherent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Integration test on captured fixture

**Files:**
- Create: `tests/integration/test_vote_matcher_v2_integration.py`

- [ ] **Step 1: Inspect the existing integration-test pattern**

Run:
```bash
cd ~/docket-pub && ls tests/integration/ && cat tests/integration/conftest.py 2>/dev/null
```

Look at one or two existing integration tests to see how they set up DB state (likely a `conftest.py` `test_db` fixture that wraps a transaction or truncates between tests). Match that pattern. If no `test_db` fixture exists, the integration test below uses a `db_cursor()` pattern that wraps everything in a single transaction-like block — adjust per the project's actual convention.

- [ ] **Step 2: Write the integration test**

Create `tests/integration/test_vote_matcher_v2_integration.py`:

```python
"""End-to-end test of the v2 substantive matcher against captured fixture data.

Inserts vote 1342 + agenda items into a test database, runs match_votes_for_meeting,
and asserts the expected link appears.
"""

from __future__ import annotations

import pytest

from tests.fixtures.vote_matcher_v2 import (
    VOTE_1342_RAW_TEXT,
    VOTE_1342_MATCH_CONTEXT,
    AGENDA_ITEM_1256,
    DISTRACTOR_AGENDA_ITEMS,
)


@pytest.mark.integration
def test_match_votes_links_vote_1342_to_quitclaim_item():
    """Vote 1342 (Shield Property Solutions, $11,155.25) must link to item 1256.

    Uses the project's local docket_db. Reads the actual `municipalities` row
    for Birmingham (created by migration 002) rather than inserting one; uses
    fixed high-numbered IDs (98026, 991256, etc.) to avoid clashing with any
    real ingested data, and cleans up after itself in a finally block.
    """
    from docket.analysis.vote_matcher import match_votes_for_meeting
    from docket.db import db_cursor

    MEETING_ID = 98026
    VOTE_ID = 991342
    ITEM_OFFSET = 990000  # add to fixture IDs to avoid collisions

    try:
        with db_cursor() as cur:
            cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
            row = cur.fetchone()
            assert row, "Birmingham municipality must be seeded (migration 002)"
            muni_id = row["id"]

            cur.execute(
                """INSERT INTO meetings (id, municipality_id, meeting_date, title, source_url)
                   VALUES (%s, %s, '2025-12-16', 'Regular City Council Meeting', '')
                   ON CONFLICT (id) DO NOTHING""",
                (MEETING_ID, muni_id),
            )
            for item in [AGENDA_ITEM_1256] + DISTRACTOR_AGENDA_ITEMS:
                cur.execute(
                    """INSERT INTO agenda_items (id, meeting_id, item_number, title, description, is_consent)
                       VALUES (%s, %s, %s, %s, %s, FALSE)
                       ON CONFLICT (id) DO NOTHING""",
                    (item["id"] + ITEM_OFFSET, MEETING_ID, item["item_number"],
                     item["title"], item.get("description", "")),
                )
            cur.execute(
                """INSERT INTO votes
                    (id, meeting_id, source, raw_text, match_context, yeas, nays, abstentions, result)
                   VALUES (%s, %s, 'minutes_text', %s, %s, 7, 0, 0, 'passed')
                   ON CONFLICT (id) DO NOTHING""",
                (VOTE_ID, MEETING_ID, VOTE_1342_RAW_TEXT, VOTE_1342_MATCH_CONTEXT),
            )

        # Run the matcher
        result = match_votes_for_meeting(MEETING_ID)
        assert result["substantive_matched"] >= 1, (
            f"Expected at least one substantive match, got {result}"
        )

        # Assert the expected link
        with db_cursor() as cur:
            cur.execute(
                """SELECT agenda_item_id, match_method, match_confidence
                   FROM vote_agenda_items WHERE vote_id = %s AND is_active = TRUE""",
                (VOTE_ID,),
            )
            rows = cur.fetchall()

        linked_item_ids = {r["agenda_item_id"] for r in rows}
        expected_item_id = AGENDA_ITEM_1256["id"] + ITEM_OFFSET
        assert expected_item_id in linked_item_ids, (
            f"Expected link to item {expected_item_id} (Shield Property Solutions); "
            f"got links to {linked_item_ids}"
        )

        # Distractors must NOT be linked
        distractor_ids = {it["id"] + ITEM_OFFSET for it in DISTRACTOR_AGENDA_ITEMS}
        assert not (linked_item_ids & distractor_ids), (
            f"Distractor items got linked: {linked_item_ids & distractor_ids}"
        )
    finally:
        # Cleanup — order matters (FK chain)
        with db_cursor() as cur:
            cur.execute("DELETE FROM vote_agenda_items WHERE vote_id = %s", (VOTE_ID,))
            cur.execute("DELETE FROM votes WHERE id = %s", (VOTE_ID,))
            cur.execute("DELETE FROM agenda_items WHERE meeting_id = %s", (MEETING_ID,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (MEETING_ID,))
```

- [ ] **Step 2: Run the integration test**

Run:
```bash
cd ~/docket-pub && venv/bin/pytest tests/integration/test_vote_matcher_v2_integration.py -v
```

Expected: test passes (proves the full v2 ladder hangs together end-to-end).

If the test fails because of test_db fixture mechanics — adjust the setup to match the project's existing integration test pattern (look at other files in `tests/integration/` for the canonical setup).

- [ ] **Step 3: Commit**

```bash
cd ~/docket-pub && git add tests/integration/test_vote_matcher_v2_integration.py
git commit -m "test(matcher): integration test for vote-1342 → quitclaim item link

End-to-end verification that the v2 substantive ladder (with all four
changes active) correctly links vote 1342 to agenda item 1256 and
ignores distractors.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Backfill script for resolution numbers

**Files:**
- Create: `scripts/backfill_vote_resolution_numbers.py`

- [ ] **Step 1: Write the script**

Create `scripts/backfill_vote_resolution_numbers.py`:

```python
"""Backfill votes.resolution_number from raw_text.

Idempotent: skips rows where resolution_number is already populated.
Idiomatic batched UPDATE — does not stream per-row updates against Railway.

Usage:
    venv/bin/python scripts/backfill_vote_resolution_numbers.py [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import logging
import sys

from docket.analysis.vote_resolution_extractor import extract_resolution_number
from docket.db import db, db_cursor

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would change, don't write")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap the number of rows processed")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    sql = """
        SELECT id, raw_text FROM votes
        WHERE resolution_number IS NULL
          AND raw_text IS NOT NULL
          AND raw_text <> ''
    """
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"

    updates: list[tuple[str, int]] = []
    with db_cursor() as cur:
        cur.execute(sql)
        for row in cur.fetchall():
            res_num = extract_resolution_number(row["raw_text"])
            if res_num:
                updates.append((res_num, row["id"]))

    logger.info("Extracted %d resolution numbers across %d candidate rows.",
                len(updates), cur.rowcount if cur.rowcount else 0)

    if args.dry_run:
        for res_num, vote_id in updates[:20]:
            logger.info("dry-run: vote %d -> %s", vote_id, res_num)
        if len(updates) > 20:
            logger.info("(... %d more)", len(updates) - 20)
        return 0

    if not updates:
        logger.info("Nothing to update.")
        return 0

    # Batched UPDATE via VALUES list (single round trip).
    with db() as conn:
        with conn.cursor() as cur:
            args_str = ",".join(
                cur.mogrify("(%s::text, %s::int)", (n, vid)).decode()
                for n, vid in updates
            )
            cur.execute(
                f"""UPDATE votes
                    SET resolution_number = v.num
                    FROM (VALUES {args_str}) AS v(num, id)
                    WHERE votes.id = v.id"""
            )
        conn.commit()
    logger.info("Updated %d rows.", len(updates))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-test against local DB (dry-run)**

Run:
```bash
cd ~/docket-pub && venv/bin/python scripts/backfill_vote_resolution_numbers.py --dry-run --limit 10
```

Expected: prints zero updates (local DB has no votes), exit 0.

- [ ] **Step 3: Smoke-test against Railway (dry-run, limited)**

Run:
```bash
cd ~/docket-pub && DATABASE_URL="$(railway variables --service docket-web --kv | grep '^DATABASE_PUBLIC_URL=' | cut -d= -f2-)" \
  venv/bin/python scripts/backfill_vote_resolution_numbers.py --dry-run --limit 50
```

Expected: prints up to 20 sample updates, summary line shows total extracted count. Spot-check the output: each printed `vote_id -> resolution_number` should look like a plausible Birmingham resolution / ordinance identifier.

- [ ] **Step 4: Commit**

```bash
cd ~/docket-pub && git add scripts/backfill_vote_resolution_numbers.py
git commit -m "feat(scripts): backfill_vote_resolution_numbers

Populates votes.resolution_number from raw_text using the new extractor.
Idempotent. Single batched UPDATE (no per-row stream against Railway).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Local backfill execution

**Files:** none (operations task)

- [ ] **Step 1a: Verify local `docket` role permissions before dumping**

Schema mismatches at load time usually trace to the local `docket` user lacking the privileges needed to recreate objects from the dump. Before running pg_dump, confirm `docket` is a SUPERUSER (simplest) or at minimum has CREATE on the target DB and owns it:

```bash
/opt/homebrew/opt/postgresql@18/bin/psql -d postgres -c "\du docket"
```

Expected: shows `docket` with `Superuser` in its attributes. If not, run (one-time):

```bash
/opt/homebrew/opt/postgresql@18/bin/psql -d postgres -c "ALTER ROLE docket WITH SUPERUSER"
```

This avoids the common failure mode where the dump tries to create extensions or set GUCs the local role can't write.

- [ ] **Step 1b: Sync Railway → local**

Run:
```bash
cd ~/docket-pub && /opt/homebrew/opt/postgresql@18/bin/pg_dump \
  "$(railway variables --service docket-web --kv | grep '^DATABASE_PUBLIC_URL=' | cut -d= -f2-)" \
  --no-owner --no-acl \
  -t municipalities -t meetings -t agenda_items -t votes -t vote_agenda_items \
  -t council_members -t schema_migrations \
  > /tmp/railway_dump.sql

# Drop & recreate local docket_db owned by docket, then load
/opt/homebrew/opt/postgresql@18/bin/dropdb docket_db && \
  /opt/homebrew/opt/postgresql@18/bin/createdb -O docket docket_db && \
  /opt/homebrew/opt/postgresql@18/bin/psql -U docket -d docket_db -f /tmp/railway_dump.sql
```

Note: `--no-owner --no-acl` on the dump strips Railway's ownership/grant directives so the local `docket` role doesn't need to match Railway's `postgres` superuser. The `-U docket` on psql confirms we're loading as the database owner. If the load emits any `permission denied` errors, halt and resolve before proceeding — partial loads create the exact schema-mismatch class this step is designed to avoid.

Expected: clean dump and restore with no permission errors. Spot-check counts:

```bash
cd ~/docket-pub && venv/bin/python -c "
from docket.db import db_cursor
with db_cursor() as cur:
    cur.execute('SELECT COUNT(*) AS n FROM votes')
    print('votes:', cur.fetchone())
    cur.execute('SELECT COUNT(*) AS n FROM vote_agenda_items WHERE is_active')
    print('active vai:', cur.fetchone())
"
```

Expected: `votes: ~10011`, `active vai: ~33303`.

- [ ] **Step 2: Run resolution-number backfill locally (live)**

Run:
```bash
cd ~/docket-pub && venv/bin/python scripts/backfill_vote_resolution_numbers.py
```

Expected: log line `Updated N rows.` where N is the count of newly populated `resolution_number` values.

- [ ] **Step 3: Spot-check 50 random backfilled rows**

Run:
```bash
cd ~/docket-pub && venv/bin/python -c "
from docket.db import db_cursor
with db_cursor() as cur:
    cur.execute('''
        SELECT v.id, v.resolution_number, LEFT(v.raw_text, 200) AS preview
        FROM votes v WHERE v.resolution_number IS NOT NULL
        ORDER BY random() LIMIT 50
    ''')
    for r in cur.fetchall():
        print(r['id'], '|', r['resolution_number'], '|', r['preview'][:120])
"
```

Manually verify: the printed `resolution_number` should appear in the printed raw_text preview. If 50/50 look correct, proceed. If 1-3 look suspicious, investigate. If more than 3 look wrong, halt and revisit the regex.

- [ ] **Step 4: Run full matcher on previously-unmatched votes locally**

Run:
```bash
cd ~/docket-pub && venv/bin/python -c "
from docket.analysis.vote_matcher import match_all_unmatched
result = match_all_unmatched()
print(result)
"
```

Expected: log shows totals — substantive matches should now be materially higher than today's 1,067.

- [ ] **Step 5: Capture the delta to push to Railway**

Run:
```bash
cd ~/docket-pub && /opt/homebrew/opt/postgresql@18/bin/pg_dump \
  postgresql://docket@localhost:5432/docket_db \
  --no-owner --no-acl --data-only \
  -t vote_agenda_items \
  > /tmp/local_vai_after_v2.sql

# Also dump just the resolution_number updates as a CSV
/opt/homebrew/opt/postgresql@18/bin/psql -d docket_db -c "\\copy (SELECT id, resolution_number FROM votes WHERE resolution_number IS NOT NULL) TO '/tmp/local_resolution_numbers.csv' WITH CSV HEADER"
```

Expected: dump file is non-empty.

---

## Task 12: Push to Railway with snapshot/rollback

**Files:** none (operations task)

- [ ] **Step 1: Snapshot Railway tables before push**

Run:
```bash
cd ~/docket-pub && DATABASE_URL="$(railway variables --service docket-web --kv | grep '^DATABASE_PUBLIC_URL=' | cut -d= -f2-)"

/opt/homebrew/opt/postgresql@18/bin/psql "$DATABASE_URL" <<'EOF'
CREATE TABLE vote_agenda_items_backup_2026_05_04 AS SELECT * FROM vote_agenda_items;
CREATE TABLE votes_backup_2026_05_04 AS SELECT * FROM votes;
EOF
```

Expected: `CREATE TABLE` confirmations.

- [ ] **Step 2: Push resolution_number updates via staging table**

```bash
cd ~/docket-pub && /opt/homebrew/opt/postgresql@18/bin/psql "$DATABASE_URL" <<'EOF'
CREATE TEMP TABLE staging_res_nums (id INT PRIMARY KEY, resolution_number TEXT);
\copy staging_res_nums FROM '/tmp/local_resolution_numbers.csv' WITH CSV HEADER

UPDATE votes
SET resolution_number = s.resolution_number
FROM staging_res_nums s
WHERE votes.id = s.id AND votes.resolution_number IS NULL;
EOF
```

Expected: `UPDATE N` row count matching the local backfill total.

- [ ] **Step 3: Push new vote_agenda_items via INSERT … ON CONFLICT**

The local dump from Task 11 Step 5 is a full table dump. Filter it to just the new rows that don't yet exist on Railway:

```bash
cd ~/docket-pub && venv/bin/python -c "
from docket.db import db_cursor
import os
os.environ['DATABASE_URL'] = '$DATABASE_URL'
# (skip — use psql instead per below)
"

# Simpler approach: do the INSERT inside Railway from a CSV diff
/opt/homebrew/opt/postgresql@18/bin/psql -d docket_db -c "\\copy (SELECT vote_id, agenda_item_id, association_type, match_method, match_confidence, excerpt_context, provisional, is_active, is_manual FROM vote_agenda_items WHERE created_at > NOW() - INTERVAL '1 day') TO '/tmp/local_new_vai.csv' WITH CSV HEADER"

/opt/homebrew/opt/postgresql@18/bin/psql "$DATABASE_URL" <<'EOF'
CREATE TEMP TABLE staging_vai (
    vote_id INT, agenda_item_id INT, association_type TEXT,
    match_method TEXT, match_confidence FLOAT, excerpt_context TEXT,
    provisional BOOLEAN, is_active BOOLEAN, is_manual BOOLEAN
);
\copy staging_vai FROM '/tmp/local_new_vai.csv' WITH CSV HEADER

INSERT INTO vote_agenda_items
    (vote_id, agenda_item_id, association_type, match_method,
     match_confidence, excerpt_context, provisional, is_active, is_manual)
SELECT vote_id, agenda_item_id, association_type, match_method,
       match_confidence, excerpt_context, provisional, is_active, is_manual
FROM staging_vai
ON CONFLICT (vote_id, agenda_item_id) DO NOTHING;
EOF
```

Expected: `INSERT 0 N` where N is the count of newly-matched links.

- [ ] **Step 4: Validate counts on Railway**

```bash
cd ~/docket-pub && /opt/homebrew/opt/postgresql@18/bin/psql "$DATABASE_URL" <<'EOF'
-- Match-method breakdown after backfill
SELECT match_method, COUNT(*) FROM vote_agenda_items WHERE is_active GROUP BY match_method ORDER BY 2 DESC;

-- Resolution-number coverage
SELECT
  COUNT(*) FILTER (WHERE resolution_number IS NOT NULL) AS with_res,
  COUNT(*) FILTER (WHERE resolution_number IS NULL) AS without_res
FROM votes;

-- Manual-shield sanity check: backup vs live should be identical for is_manual=TRUE
SELECT
  (SELECT COUNT(*) FROM vote_agenda_items WHERE is_manual = TRUE) AS live_manual,
  (SELECT COUNT(*) FROM vote_agenda_items_backup_2026_05_04 WHERE is_manual = TRUE) AS backup_manual;
EOF
```

Expected: `live_manual == backup_manual`. New `match_method` values include `structured_fact` and `text_similarity` (from rank-aware tier).

- [ ] **Step 5: Spot-check 20 newly-linked votes via the production UI**

```bash
cd ~/docket-pub && /opt/homebrew/opt/postgresql@18/bin/psql "$DATABASE_URL" -c "
SELECT v.id, v.meeting_id, vai.match_method, vai.match_confidence,
       'https://docket-web-production-6110.up.railway.app/al/birmingham/meetings/' || v.meeting_id || '/' AS url
FROM vote_agenda_items vai
JOIN votes v ON v.id = vai.vote_id
WHERE vai.match_method IN ('structured_fact', 'text_similarity')
  AND vai.is_active
ORDER BY random() LIMIT 20;
"
```

Open each URL, find the linked vote, and verify the agenda item it points to is plausibly the one being voted on. If 20/20 look right, the backfill is complete. If 1-3 look wrong, log them as known false positives but proceed (the rate is acceptable). If more than 3 look wrong, halt — see rollback step.

- [ ] **Step 6: Drop the snapshot tables (after a 7-day stability window)**

This step runs **one week later**, not immediately. Mark this task complete and create a calendar reminder.

```bash
# After 7 days of stable production behavior:
cd ~/docket-pub && /opt/homebrew/opt/postgresql@18/bin/psql "$DATABASE_URL" <<'EOF'
DROP TABLE vote_agenda_items_backup_2026_05_04;
DROP TABLE votes_backup_2026_05_04;
EOF
```

- [ ] **Rollback (only if Step 5 finds widespread false positives):**

```bash
cd ~/docket-pub && /opt/homebrew/opt/postgresql@18/bin/psql "$DATABASE_URL" <<'EOF'
BEGIN;
TRUNCATE vote_agenda_items;
INSERT INTO vote_agenda_items SELECT * FROM vote_agenda_items_backup_2026_05_04;

UPDATE votes v SET resolution_number = b.resolution_number
FROM votes_backup_2026_05_04 b WHERE v.id = b.id;
COMMIT;
EOF
```

---

## Task 13: PR + merge to main

**Files:** none (git operations)

- [ ] **Step 1: Push the feature branch**

```bash
cd ~/docket-pub && git push -u origin feat/vote-matcher-v2
```

- [ ] **Step 2: Open the PR**

```bash
cd ~/docket-pub && gh pr create --title "Vote-matcher v2: lift substantive match rate above 10.7%" --body "$(cat <<'EOF'
## Summary
- Tier 0 fix: substantive matcher now reads `raw_text` instead of the 200-char `match_context`. This was the root cause of the low substantive match rate.
- New extractor for resolution / ordinance numbers, persisted to `votes.resolution_number`.
- New structured-fact tier (proper-noun + dollar) between item-number and keyword tiers.
- Rank-aware keyword tier: lowered floor + margin gate.
- Backfill applied to all unmatched votes on Railway with snapshot/rollback safety.

Spec: `docs/superpowers/specs/2026-05-04-vote-matcher-v2-design.md`
Plan: `docs/superpowers/plans/2026-05-04-vote-matcher-v2.md`

## Test plan
- [ ] Unit tests pass (`venv/bin/pytest tests/unit/`)
- [ ] Integration test passes (`venv/bin/pytest tests/integration/test_vote_matcher_v2_integration.py`)
- [ ] Spot-check 20 random new links on production looks correct
- [ ] Manual-shield (`is_manual=TRUE`) row count is unchanged before/after backfill

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: After PR review/approval, merge**

(User confirms in PR; merge via GitHub UI or `gh pr merge --merge`.)

---

## Self-review checklist

After completing all tasks, verify:

- [ ] Spec coverage: every section of `2026-05-04-vote-matcher-v2-design.md` maps to at least one task
- [ ] Manual-shield regression test passes (`is_manual=TRUE` rows untouched)
- [ ] Snapshot tables `vote_agenda_items_backup_2026_05_04` and `votes_backup_2026_05_04` exist on Railway
- [ ] Production smoke check: open `/al/birmingham/meetings/26/` and confirm vote 1342 now shows the Shield Property Solutions link
