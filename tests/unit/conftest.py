"""Shared test fixtures + helpers for unit tests.

Currently exports:

- ``make_agenda_item(**overrides)`` — build a fully-populated
  ``AgendaItem`` dataclass instance with sensible defaults so individual
  tests only have to specify the fields they actually care about.

This helper exists so partial-rendering tests (``test_engagement_strip``,
``test_smart_brevity_card_dispatcher``, ``test_dollar_tier``, etc.) can
feed real ``AgendaItem`` instances into Jinja templates. The previous
test pattern used bare dicts shaped like ``{"extracted_facts": {...}}``,
which forced the v3 partials to keep an ``or facts.<key>`` fallback
alongside the lifted top-level ``item.<key>`` access (see commit
``ff6cabb``). Converting fixtures to AgendaItem lets us drop that
fallback and keep the partials reading exclusively from the lifted
top-level columns — production parity with what ``list_agenda_items``
actually returns.
"""

from __future__ import annotations

from docket.models.agenda import AgendaItem


def make_agenda_item(**overrides) -> AgendaItem:
    """Build an ``AgendaItem`` with sensible defaults; override what you need.

    The dataclass has 13 required positional fields and ~25 optional ones.
    Defaults here match what an empty/old row would look like — title is
    "Test item", everything else None/False/empty so the caller only has
    to set the fields the test actually exercises.
    """
    base = dict(
        id=1,
        meeting_id=1,
        external_id=None,
        item_number=None,
        title="Test item",
        description=None,
        section=None,
        is_consent=False,
        sponsor=None,
        dollars_amount=None,
        topic=None,
        significance_score=None,
        consent_placement_score=None,
    )
    base.update(overrides)
    return AgendaItem(**base)
