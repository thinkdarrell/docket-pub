"""Versioned prompt strings + version constants.

Bumping a version constant is the trigger for re-summarization. The git
history of this file IS the audit trail — write a commit message
explaining why the rubric changed when bumping a version.
"""

from __future__ import annotations

ITEM_PROMPT_VERSION = 1
MEETING_PROMPT_VERSION = 1


ITEM_SYSTEM = """You are summarizing a single agenda item from a municipal
government meeting. You will only see fields from the agenda item itself.
Do not invent facts.

For substantive items, write the rationale BEFORE any numeric values.
Then assign 0-10 numeric values grounded in the rationale you just wrote:

- significance_score: How impactful is this item? 0 = trivial, 10 = major.
- consent_placement_score: How appropriate is consent-agenda placement?
  0 = should never be on consent (high public interest), 10 = perfect
  consent candidate (routine, non-controversial).

If the item is procedural (motion to adjourn, approval of prior minutes,
roll call), set is_substantive=false and return null for both numeric values.

Confidence: "high" if the item's text is unambiguous, "medium" if title
is clear but details are sparse, "low" if you had to guess at intent.

Summary: 1-2 sentences describing what was proposed. Plain prose, no jargon.
"""


ITEM_USER_TEMPLATE = """Title: {title}
Description: {description}
Sponsor: {sponsor}
Dollar amount: {dollars_amount}
Topic: {topic}
Is on consent agenda: {is_consent}"""


MEETING_SYSTEM = """You are writing a 2-3 sentence executive summary of a
municipal meeting. You will only see substantive agenda items from this
meeting (each represented by its own AI-generated summary).

If phase is "adopted": lead with what the council DECIDED (votes are final).
If phase is "provisional": lead with what the council CONSIDERED (votes
not yet ratified).

Do not invent facts not present in the items. Do not list every item —
identify the 1-3 most consequential decisions or debates and frame the
meeting around those.

Confidence: "high" if items are clear and substantive; "medium" if items
are vague; "low" if synthesis required guessing.
"""


MEETING_USER_TEMPLATE = """Meeting: {meeting_type} on {meeting_date}
Phase: {phase}
Substantive items ({count}):
{items_block}"""
