"""Smoke tests for P2a Jinja partials.

``render_partial`` fixture lives in ``tests/web/conftest.py`` and lets
each partial get a standalone render test with a sample context — no DB
needed, no live routes required.

This file starts with a single smoke test against ``partials/footer.html``
(which already existed before P2) to validate the fixture itself works
with templates that have conditional logic and ``url_for`` calls.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_render_partial_fixture_works(render_partial):
    html = render_partial(
        'partials/footer.html',
        municipality=SimpleNamespace(
            slug='birmingham',
            name='Birmingham',
            adapter_class='GranicusAdapter',
        ),
        now=datetime(2026, 5, 14),
    )
    assert 'docket.pub' in html


def test_num_stat_renders_label_and_value(render_partial):
    html = render_partial(
        'partials/num_stat.html',
        label='Meetings YTD',
        value='42',
    )
    assert 'Meetings YTD' in html
    assert '42' in html
    assert 'num-stat' in html  # CSS hook class

def test_num_stat_renders_sub_when_provided(render_partial):
    html = render_partial(
        'partials/num_stat.html',
        label='Meetings',
        value='1,003',
        sub='Since 2017',
    )
    assert 'Since 2017' in html

def test_num_stat_omits_sub_when_absent(render_partial):
    html = render_partial(
        'partials/num_stat.html',
        label='Votes',
        value='12',
    )
    # No <div class="num-stat-sub"> when sub is not passed.
    assert 'num-stat-sub' not in html

def test_num_stat_accent_modifier_class(render_partial):
    html = render_partial(
        'partials/num_stat.html',
        label='Flagged',
        value='4',
        accent=True,
    )
    assert 'is-accent' in html


def test_freshness_chip_renders_state_and_timestamp(render_partial):
    html = render_partial(
        'partials/freshness_chip.html',
        state='good',
        last_synced='2 hours ago',
        source_health_url='/al/birmingham/source-health/',
    )
    assert 'freshness-chip' in html
    assert 'is-good' in html
    assert '2 hours ago' in html
    assert 'href="/al/birmingham/source-health/"' in html

def test_freshness_chip_state_classes(render_partial):
    for state in ('good', 'warn', 'bad'):
        html = render_partial(
            'partials/freshness_chip.html',
            state=state,
            last_synced='just now',
            source_health_url='/al/test/source-health/',
        )
        assert f'is-{state}' in html

def test_freshness_chip_dot_aria_hidden(render_partial):
    """The visual dot must be aria-hidden so screen readers
    hear only the state label + timestamp."""
    html = render_partial(
        'partials/freshness_chip.html',
        state='good',
        last_synced='now',
        source_health_url='/al/test/source-health/',
    )
    assert 'aria-hidden="true"' in html

def test_freshness_chip_unknown_state_falls_back_to_neutral_copy(render_partial):
    """Unknown state must NOT inherit the 'bad' copy ('Broken · feed down').
    That would mislead citizens into thinking the feed is confirmed-broken
    when in fact the caller didn't pass a valid state. Render neutral
    'unknown' copy instead. The default --ink-3 dot meets WCAG SC 1.4.11
    contrast on --paper (~5.5:1)."""
    html = render_partial(
        'partials/freshness_chip.html',
        state='unknown',
        last_synced='now',
        source_health_url='/al/test/source-health/',
    )
    assert 'Broken · feed down' not in html
    assert 'unknown' in html.lower() or 'status' in html.lower()


def test_topic_row_renders_pills(render_partial):
    topics = [
        {'slug': 'budget', 'label': 'Budget', 'count': 42, 'color': '#1a73e8'},
        {'slug': 'housing', 'label': 'Housing', 'count': 18, 'color': '#34a853'},
    ]
    html = render_partial('partials/topic_row.html', topics=topics, city_slug='birmingham')
    assert 'topic-row' in html
    assert 'Budget' in html
    assert 'Housing' in html
    assert '42' in html
    # Pills link into the city-scoped topic page
    assert '/topics/budget/' in html
    assert 'topic-pill' in html

def test_topic_row_handles_empty_list(render_partial):
    """No topics → render empty (or with a 'no topics yet' affordance)."""
    html = render_partial('partials/topic_row.html', topics=[], city_slug='birmingham')
    # Render must not crash; container may or may not be present.
    # Spec choice: when topics is empty, render nothing (empty string after stripping)
    # so the row's vertical space isn't reserved for a missing element.
    assert 'topic-row' in html or html.strip() == ''


def test_topic_row_renders_zero_count(render_partial):
    """count=0 is valid data (topic exists, nothing chaptered yet). The
    template must render '0' rather than falsy-suppress it."""
    topics = [{'slug': 'transit', 'label': 'Transit', 'count': 0, 'color': '#aaaaaa'}]
    html = render_partial('partials/topic_row.html', topics=topics, city_slug='birmingham')
    assert 'Transit' in html
    assert '>0<' in html  # the count span specifically renders the literal 0


def test_topic_row_tolerates_missing_color_key(render_partial):
    """Topics dicts may not have a 'color' key (vs. having color=None).
    The Jinja `or` fallback handles None; the dot's CSS fallback
    (var(--topic-color, var(--ink-3))) handles undefined too."""
    topics = [{'slug': 'parks', 'label': 'Parks', 'count': 4}]  # no 'color' key
    html = render_partial('partials/topic_row.html', topics=topics, city_slug='birmingham')
    assert 'Parks' in html
    assert 'topic-pill' in html


def test_kpi_explainer_renders_value_and_label(render_partial):
    html = render_partial(
        'partials/kpi_explainer.html',
        label='Meetings lifetime',
        value='1,003',
        sub='Since 2017',
        sql_display='SELECT count(*) FROM meetings WHERE municipality_id = $1',
    )
    assert 'kpi-explainer' in html
    assert 'Meetings lifetime' in html
    assert '1,003' in html
    assert 'Since 2017' in html
    assert 'SELECT count(*)' in html
    assert 'municipality_id' in html

def test_kpi_explainer_sql_in_details(render_partial):
    """SQL display lives inside <details> so it's collapsible
    without JS. Summary is the chevron/CTA."""
    html = render_partial(
        'partials/kpi_explainer.html',
        label='Votes YTD',
        value='123',
        sub=None,
        sql_display='SELECT count(*) FROM votes',
    )
    assert '<details' in html
    assert '<summary' in html

def test_kpi_explainer_omits_sub_when_none(render_partial):
    html = render_partial(
        'partials/kpi_explainer.html',
        label='Votes',
        value='12',
        sub=None,
        sql_display='SELECT 1',
    )
    assert 'kpi-explainer-sub' not in html


from datetime import date as date_cls


def _sample_meeting():
    return SimpleNamespace(
        id=42,
        date=date_cls(2026, 5, 13),
        title='City Council · Regular Meeting',
        meeting_type='regular',
        summary='Routine agenda; one large procurement item.',
        agenda_count=18,
        dollars_total=2_400_000,
    )


def test_meeting_card_strip_variant_renders(render_partial):
    m = _sample_meeting()
    html = render_partial(
        'partials/meeting_card.html',
        meeting=m,
        variant='strip',
        municipality=SimpleNamespace(slug='birmingham'),
    )
    assert 'meeting-card' in html
    assert 'meeting-card--strip' in html
    assert 'City Council' in html
    # Strip variant should reference the date and item count compactly.
    assert '18' in html


def test_meeting_card_grid_variant_renders(render_partial):
    m = _sample_meeting()
    html = render_partial(
        'partials/meeting_card.html',
        meeting=m,
        variant='grid',
        municipality=SimpleNamespace(slug='birmingham'),
    )
    assert 'meeting-card--grid' in html
    assert 'Routine agenda' in html  # Summary visible in grid, not strip


def test_meeting_card_link_to_meeting_detail(render_partial):
    m = _sample_meeting()
    html = render_partial(
        'partials/meeting_card.html',
        meeting=m,
        variant='grid',
        municipality=SimpleNamespace(slug='birmingham'),
    )
    assert '/al/birmingham/meetings/42/' in html


def test_meeting_card_handles_zero_dollars(render_partial):
    m = _sample_meeting()
    m.dollars_total = 0
    html = render_partial(
        'partials/meeting_card.html',
        meeting=m,
        variant='grid',
        municipality=SimpleNamespace(slug='birmingham'),
    )
    # Card should still render — zero dollars is valid data, not missing.
    assert 'meeting-card' in html


def test_source_rail_includes_provenance_and_kpis(render_partial):
    muni = SimpleNamespace(
        slug='birmingham',
        name='Birmingham',
        state='AL',
        adapter_class='GranicusAdapter',
    )
    kpi_stats = [
        {'label': 'Meetings lifetime', 'value': '1,003', 'sub': 'Since 2017',
         'sql_display': 'SELECT count(*) FROM meetings WHERE municipality_id = $1'},
        {'label': 'Agenda items YTD', 'value': '14,212', 'sub': None,
         'sql_display': 'SELECT count(*) FROM agenda_items ai JOIN meetings m ...'},
        {'label': 'Votes YTD', 'value': '892', 'sub': None,
         'sql_display': 'SELECT count(*) FROM votes v JOIN meetings m ...'},
        {'label': 'Dollars pending', 'value': '$48.2M', 'sub': 'vs $112M settled',
         'sql_display': 'SELECT sum(dollars_amount) FROM agenda_items ...'},
    ]
    html = render_partial(
        'partials/source_rail.html',
        municipality=muni,
        meeting_count=1003,
        kpi_stats=kpi_stats,
    )
    # Provenance section comes through from rail_default include
    assert 'GranicusAdapter' in html
    assert 'Birmingham' in html
    # All 4 KPI explainers render
    assert 'Meetings lifetime' in html
    assert 'Agenda items YTD' in html
    assert 'Votes YTD' in html
    assert 'Dollars pending' in html
    # Sample SQL substrings show up (autoescape will render `<` → `&lt;`
    # if present; the strings above don't contain those characters)
    assert 'FROM agenda_items' in html


def test_source_rail_handles_empty_kpi_stats(render_partial):
    """Rail renders even when stats are missing (defensive)."""
    muni = SimpleNamespace(
        slug='birmingham', name='Birmingham', state='AL',
        adapter_class='GranicusAdapter',
    )
    html = render_partial(
        'partials/source_rail.html',
        municipality=muni,
        meeting_count=1003,
        kpi_stats=[],
    )
    # Provenance still renders
    assert 'GranicusAdapter' in html
    # KPI section is absent or empty — no card chrome
    assert 'Meetings lifetime' not in html


def test_source_rail_tolerates_missing_stat_keys(render_partial):
    """A stats dict missing optional keys (e.g., 'sub') should not raise.
    Implementation uses stat.get('key') to be defensive under strict_undefined."""
    muni = SimpleNamespace(
        slug='birmingham', name='Birmingham', state='AL',
        adapter_class='GranicusAdapter',
    )
    kpi_stats = [
        # 'sub' deliberately omitted entirely
        {'label': 'Meetings YTD', 'value': '42',
         'sql_display': 'SELECT count(*) FROM meetings'},
    ]
    html = render_partial(
        'partials/source_rail.html',
        municipality=muni,
        meeting_count=42,
        kpi_stats=kpi_stats,
    )
    assert 'Meetings YTD' in html


# ── P2b Task 2: CSS bloat cleanup ───────────────────────────────────────────


def test_stat_card_base_class_exists_in_layout_css():
    """.stat-card-base is the shared base for num_stat and kpi_explainer cards.
    Both partials' root element should carry this class so common rules
    (padding, border, background) live in one selector."""
    css = (PROJECT_ROOT / "src/docket/web/static/layout.css").read_text()
    assert ".stat-card-base" in css, ".stat-card-base shared rule missing"


def test_num_stat_renders_t_tnum_on_value(render_partial):
    """num_stat's value span carries both t-tnum (tabular numerics) and
    t-display (serif display sizing). Replacing one with the other drops
    the Source Serif display font — both must be present."""
    html = render_partial(
        'partials/num_stat.html',
        label='Meetings YTD',
        value='42',
    )
    # Both t-tnum (tabular numerics) and t-display (serif display sizing) must be present.
    assert 't-tnum' in html, "t-tnum class missing from num-stat value"
    assert 't-display' in html, "t-display class missing from num-stat value"


def test_kpi_explainer_renders_t_display_and_t_tnum_on_value(render_partial):
    """kpi_explainer's value span carries both t-tnum and t-display,
    mirroring num_stat. Dropping t-display silently switches the value
    to the mono fallback font."""
    html = render_partial(
        'partials/kpi_explainer.html',
        label='Meetings',
        value='42',
        sub=None,
        sql_display='SELECT count(*) FROM meetings',
    )
    assert 't-tnum' in html, "t-tnum class missing from kpi-explainer value"
    assert 't-display' in html, "t-display class missing from kpi-explainer value"
