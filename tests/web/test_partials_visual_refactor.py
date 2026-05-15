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
from types import SimpleNamespace


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
