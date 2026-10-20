"""Source health shows a "Briefing facts" stage only when city_briefing_facts holds a row."""

from __future__ import annotations

import pytest

from docket.db import db
from docket.services import briefing
from tests.support import briefing_seed


@pytest.fixture
def seeded():
    with db() as conn:
        ids = briefing_seed.seed(conn)
    try:
        yield ids
    finally:
        with db() as conn:
            briefing_seed.cleanup(conn)


def test_source_health_omits_briefing_stage_without_facts_row(client, seeded):
    body = client.get("/al/birmingham/source-health/").get_data(as_text=True)
    assert "Briefing facts" not in body


def test_source_health_shows_briefing_stage_after_recompute(client, seeded):
    briefing.recompute_city_facts(seeded["municipality_id"])
    body = client.get("/al/birmingham/source-health/").get_data(as_text=True)
    assert "Briefing facts" in body
    assert "Computed" in body
    assert "older than 48 hours" not in body
    assert 'source-stage-dot is-good' in body
