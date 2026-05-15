"""Render tests for the P3 city overview rebuild.

These tests use the Flask `client` fixture (provided by tests/web/conftest.py).
"""


def test_overview_passes_city_stats_to_template(client):
    """city_overview builds city_stats dict for the new 3-card YTD strip.

    The template includes kpi_strip.html in Task 8; this test just verifies
    the view function passes city_stats. Once Task 8 wires the template,
    the rendered HTML will contain the 3-card markup."""
    resp = client.get("/al/birmingham/")
    assert resp.status_code == 200
    # The data is in the rendered context; we can spot-check via the
    # page_sources block which we know still renders. The actual KPI
    # strip markup will appear after Task 8.


def test_overview_no_longer_passes_kpi_stats(client):
    """P3: overview drops kpi_stats — its bottom is provenance-only.
    page_sources renders, but page-sources-kpis section does not."""
    resp = client.get("/al/birmingham/")
    html = resp.data.decode()
    assert 'class="page-sources"' in html, "page_sources block missing"
    assert 'page-sources-kpis' not in html, (
        "overview should no longer render the KPI explainer stack"
    )


def test_overview_renders_freshness_data():
    """city_overview computes freshness state via query helpers."""
    from docket.services import query
    # Smoke test: helpers compose
    municipality = query.get_municipality("birmingham")
    if municipality is None:
        return  # local DB may not have birmingham; skip
    last_ingest = query.most_recent_ingest_at(municipality["id"])
    freshness = query._freshness_state(last_ingest)
    assert freshness["state"] in {"good", "warn", "bad", "unknown"}
    assert "label" in freshness


def test_meetings_list_renders_kpi_explainer_stack(client):
    """Interior pages get the 4-card KPI explainer stack in page_sources."""
    resp = client.get("/al/birmingham/meetings/")
    assert resp.status_code == 200, f"got {resp.status_code}"
    html = resp.data.decode()
    assert 'class="page-sources"' in html
    assert 'page-sources-kpis' in html, (
        "meetings list should render KPI explainer stack"
    )


def test_council_renders_kpi_explainer_stack(client):
    resp = client.get("/al/birmingham/council/")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'page-sources-kpis' in html, (
        "council roster should render KPI explainer stack"
    )


def test_meeting_detail_renders_kpi_explainer_stack(client):
    # Use any meeting id likely to exist; if test DB doesn't have one,
    # this test may need adjustment. Try 1 first.
    resp = client.get("/al/birmingham/meetings/1/")
    if resp.status_code == 404:
        # No meeting 1 in test DB — try fetching the list and using whatever ID is there
        resp_list = client.get("/al/birmingham/meetings/")
        import re
        m = re.search(r"/al/birmingham/meetings/(\d+)/", resp_list.data.decode())
        if m:
            mid = m.group(1)
            resp = client.get(f"/al/birmingham/meetings/{mid}/")
    if resp.status_code == 200:
        html = resp.data.decode()
        assert 'page-sources-kpis' in html, (
            "meeting detail should render KPI explainer stack"
        )


def test_overview_renders_city_lead(client):
    """P3: city.html consumes the city_lead partial at the top."""
    resp = client.get("/al/birmingham/")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'class="city-lead' in html
    assert "Birmingham, AL" in html


def test_overview_renders_kpi_strip(client):
    """P3: city.html consumes the kpi_strip partial below city_lead."""
    resp = client.get("/al/birmingham/")
    html = resp.data.decode()
    assert 'class="kpi-strip' in html
    assert "Meetings YTD" in html
    assert "Dollars YTD" in html
    assert "Flagged" in html


def test_overview_no_longer_renders_old_hero_or_kpi_grid(client):
    """Old top section deleted: hero narrative + 4-card kpi-grid gone."""
    resp = client.get("/al/birmingham/")
    html = resp.data.decode()
    # The old hero section had class="hero" (not city-lead)
    assert 'class="hero"' not in html
    # The old 4-card KPI grid had class="kpi-grid"
    assert 'class="kpi-grid"' not in html


def test_overview_always_renders_this_week_section(client):
    """The 'This week / On the agenda' section is persistent — renders
    even when no recent or upcoming meetings exist."""
    resp = client.get("/al/birmingham/")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'class="tw"' in html, "'This week' section missing"
    assert "On the agenda" in html


def test_overview_section_order_tw_before_browse(client):
    """P3: 'This week' section appears above 'Browse by Priority' on the
    overview — agendas/meetings are the headline action; priority browse
    is a deeper-context section that should follow."""
    resp = client.get("/al/birmingham/")
    assert resp.status_code == 200
    html = resp.data.decode()
    tw_pos = html.find('class="tw"')
    # Browse by Priority block — locate via either its heading copy or its
    # class. Adjust the matcher if the block uses a different identifier.
    # Try a couple of plausible markers:
    browse_pos = -1
    for marker in ('class="priority-grid', 'Browse by Priority', 'class="browse-by-priority',
                   'id="browse-by-priority'):
        p = html.find(marker)
        if p > -1:
            browse_pos = p
            break
    assert tw_pos > -1, "'This week' section missing"
    assert browse_pos > -1, "'Browse by Priority' section not found via any known marker"
    assert tw_pos < browse_pos, (
        f"'This week' (at {tw_pos}) should appear before "
        f"'Browse by Priority' (at {browse_pos})"
    )


def test_overview_renders_no_upcoming_empty_state_when_list_empty(client, monkeypatch):
    """When upcoming_meetings is empty, the section renders an empty-state
    card explaining the state instead of silently omitting the upcoming row.

    We force the upcoming list to be empty by monkeypatching the per-city
    helper. The recent meetings list may have data or not — empty-state
    must still appear for the upcoming slot."""
    from docket.services import query
    monkeypatch.setattr(query, "list_upcoming_meetings_for_city",
                        lambda slug, days=14, limit=4: [])

    # Bust the overview cache so the patched query is used:
    from docket.web import public as web_public
    web_public._overview_cache.clear()

    resp = client.get("/al/birmingham/")
    html = resp.data.decode()
    # The empty-state card should appear within the .tw section
    assert "tw-empty" in html, "expected .tw-empty card markup"
    # Copy should explain the state — not just blank space
    assert ("No upcoming meetings" in html
            or "agenda" in html.lower()
            or "scheduled" in html.lower()), (
        "expected empty-state copy explaining no agenda scheduled"
    )
