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
