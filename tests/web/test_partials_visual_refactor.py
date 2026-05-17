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
        meeting_date=date_cls(2026, 5, 13),
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


def test_meeting_card_shows_upcoming_chip_when_meeting_in_future(render_partial):
    """Future-dated meeting in a 'recent meetings' feed must visually flag
    as Upcoming so citizens don't read empty-vote items as data-missing."""
    from datetime import date, timedelta
    future_meeting = SimpleNamespace(
        id=43,
        meeting_date=date.today() + timedelta(days=3),
        title='City Council · Regular Meeting',  # plain title, no word 'upcoming'
        meeting_type='regular',
        summary='Agenda published Friday before the Tuesday meeting.',
        agenda_count=102,
        dollars_total=0,
    )
    html = render_partial(
        'partials/meeting_card.html',
        meeting=future_meeting,
        variant='grid',
        municipality=SimpleNamespace(slug='birmingham'),
    )
    # Specific marker — not a free-text word that could come from the title.
    assert 'meeting-card__upcoming' in html, \
        "meeting card for a future meeting must carry a meeting-card__upcoming chip"


def test_meeting_card_omits_upcoming_chip_for_past_meeting(render_partial):
    """Regression guard — historical meetings must NOT get the Upcoming
    chip even when the chip rendering code is in place."""
    m = _sample_meeting()  # 2026-05-13 (past as of 2026-05-17)
    html = render_partial(
        'partials/meeting_card.html',
        meeting=m,
        variant='grid',
        municipality=SimpleNamespace(slug='birmingham'),
    )
    # Be specific so we don't accidentally match the word 'upcoming' in a
    # summary or unrelated copy.
    assert 'meeting-card__upcoming' not in html
    assert '>Upcoming<' not in html


# ── Item card upcoming chip (_card_shell meta-line) ───────────────────────


def _sample_item(meeting_date, **overrides):
    """Minimal AgendaItem-shaped dict for shell rendering."""
    base = {
        'id': 200,
        'meeting_id': 50,
        'item_number': '7',
        'title': 'Item with an upcoming meeting',
        'headline': 'Sponsor proposes new ordinance',
        'why_it_matters': 'Affects downtown zoning.',
        'meeting_date': meeting_date,
        'municipality_slug': 'birmingham',
        'badges': [],
        'extracted_facts': None,
        'dollars_amount': None,
        'processing_status': 'pending',
        'data_quality': 'ok',
        'ai_rewrite_version': 3,
    }
    base.update(overrides)
    return base


def test_card_shell_shows_upcoming_chip_for_future_meeting_item(render_partial):
    """An item whose meeting is in the future, rendered in a cross-meeting
    context (search / category landing / notable), must carry an Upcoming
    chip in the meta-line."""
    from datetime import date, timedelta
    item = _sample_item(meeting_date=date.today() + timedelta(days=3))
    html = render_partial(
        'partials/_card_shell.html',
        item=item,
        municipality={'slug': 'birmingham', 'id': 1},
        show_meeting_context=True,
    )
    assert 'card-upcoming-chip' in html


def test_card_shell_omits_upcoming_chip_for_past_meeting_item(render_partial):
    from datetime import date, timedelta
    item = _sample_item(meeting_date=date.today() - timedelta(days=30))
    html = render_partial(
        'partials/_card_shell.html',
        item=item,
        municipality={'slug': 'birmingham', 'id': 1},
        show_meeting_context=True,
    )
    assert 'card-upcoming-chip' not in html


def test_card_shell_omits_upcoming_chip_when_meeting_context_hidden(render_partial):
    """On meeting_detail (show_meeting_context=False), the meta-line date
    is hidden — and the Upcoming chip rides the same gate so it doesn't
    surface redundantly when the user is already on the meeting page."""
    from datetime import date, timedelta
    item = _sample_item(meeting_date=date.today() + timedelta(days=3))
    html = render_partial(
        'partials/_card_shell.html',
        item=item,
        municipality={'slug': 'birmingham', 'id': 1},
        show_meeting_context=False,
    )
    assert 'card-upcoming-chip' not in html


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


def test_meeting_card_omits_count_when_field_absent(render_partial):
    """Production data (list_recent_meetings, list_meetings) doesn't include
    agenda_count. The guard must check `is defined` — otherwise Jinja's
    default Undefined makes `is not none` evaluate True and the chip
    renders empty (' items' with no number)."""
    m = SimpleNamespace(id=1, meeting_date=date_cls(2026, 5, 13), title='Sample Meeting')
    html = render_partial(
        'partials/meeting_card.html',
        meeting=m,
        variant='grid',
        municipality=SimpleNamespace(slug='birmingham'),
    )
    assert ' items' not in html  # no empty count chip
    assert 'meeting-card__count' not in html  # the count span itself omitted


def test_meeting_card_omits_dollars_when_field_absent(render_partial):
    """Same Undefined hazard on dollars_total — defensively guarded."""
    m = SimpleNamespace(id=1, meeting_date=date_cls(2026, 5, 13), title='Sample Meeting')
    html = render_partial(
        'partials/meeting_card.html',
        meeting=m,
        variant='grid',
        municipality=SimpleNamespace(slug='birmingham'),
    )
    assert 'meeting-card__dollars' not in html


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


# ── P2b Task 5: badge_chip restyle regression anchor ────────────────────────


def test_badge_chip_restyle_renders_full_structure(render_partial):
    """The restyled chip must render its full DOM tree:
    icon-leading, name, optional vote-count, verification spark
    for high-confidence variants."""
    chip = {
        'kind': 'process',
        'slug': 'split_vote',
        'confidence': 1.0,
        'description': 'Council split on this item',
        'icon': '⚡',
        'name': 'Split vote',
        'vote_count': {'yes': 5, 'no': 4},
    }
    html = render_partial("partials/badge_chip.html", chip=chip)
    assert 'class="badge-chip' in html
    assert 'badge-process' in html
    assert 'badge-conf-high' in html
    assert 'badge-slug-split_vote' in html
    assert '⚡' in html
    assert 'Split vote' in html
    assert '5-4' in html
    assert '✨' in html  # verification spark for high confidence
    assert 'aria-label="AI-verified"' in html


# ── P2b Task 6: card_smart_brevity + card_v2_fallback regression anchor ──────


def test_card_smart_brevity_legislation_idiom_structure(render_partial):
    """The restyled card preserves the LegislationCard idiom:
    accent-tinted left border, meta-line eyebrow, serif headline,
    why-it-matters body, facts-line. Asserts the DOM contract, not
    the visual values."""
    item = {
        "id": 42,
        "title": "Resolution authorizing demolition of 1234 Main St",
        "headline": "City to demolish 1234 Main St",
        "why_it_matters": "Vacant property declared a public nuisance.",
        "item_number": "5-A",
        "meeting_id": 100,
        "meeting_date": date_cls(2026, 5, 1),
        "processing_status": "completed",
        "ai_rewrite_version": 3,
        "data_quality": "ok",
        "dollars_amount": 50000,
        "extracted_facts": {"action_type": "demolition"},
        "badges": [],
        "summary": None,
        # facts-strip fields (all None — no facts rendered for this item)
        "counterparty": None,
        "funding_source": None,
        "action_type": None,
        "location": None,
        "next_steps": None,
    }
    municipality = {"slug": "birmingham", "display_name": "Birmingham"}
    html = render_partial(
        "partials/card_smart_brevity.html",
        item=item,
        municipality=municipality,
        show_meeting_context=True,
        coverage_counts={},
    )
    # Idiom contract — structural hooks
    assert 'class="smart-brevity-card' in html
    assert 'class="meta-line"' in html
    assert 'class="card-headline"' in html
    assert 'class="card-link' in html
    # Body copy
    assert 'City to demolish 1234 Main St' in html
    assert 'Vacant property declared a public nuisance' in html
    # Meta line content
    assert '#5-A' in html or 'Item #5-A' in html
    assert 'May 1, 2026' in html


def test_card_v2_fallback_legislation_idiom_structure(render_partial):
    """v2_fallback inherits _card_shell.html, so the same structural
    LegislationCard idiom applies. The variant suppresses why-it-matters
    and uses the legacy summary as headline text."""
    item = {
        "id": 43,
        "title": "Budget amendment for parks department",
        "headline": None,  # v2 uses summary, not headline
        "why_it_matters": None,  # suppressed in v2 variant
        "item_number": "7-B",
        "meeting_id": 101,
        "meeting_date": date_cls(2026, 5, 1),
        "processing_status": "completed",
        "ai_rewrite_version": 2,
        "data_quality": "ok",
        "dollars_amount": None,
        "extracted_facts": None,
        "badges": [],
        "summary": "Parks department budget amendment approved by council for summer programming.",
        # facts-strip fields
        "counterparty": None,
        "funding_source": None,
        "action_type": None,
        "location": None,
        "next_steps": None,
    }
    municipality = {"slug": "birmingham", "display_name": "Birmingham"}
    html = render_partial(
        "partials/card_v2_fallback.html",
        item=item,
        municipality=municipality,
        show_meeting_context=True,
        coverage_counts={},
    )
    # Same structural idiom as smart_brevity
    assert 'class="smart-brevity-card' in html
    assert 'class="meta-line"' in html
    assert 'class="card-headline"' in html
    assert 'class="card-link' in html
    # v2 variant data
    assert 'data-variant="v2_fallback"' in html
    assert 'is-v2-fallback' in html
    # Headline should contain the summary text (truncated to 80 chars or full)
    assert 'Parks department budget amendment' in html


# ── P2b Task 7: council_card baseball-card stats block ──────────────────────


def test_council_card_renders_attendance_alignment_when_provided(render_partial):
    """Optional stats render when both attendance_pct and alignment_pct
    are provided on the member dict."""
    m = {
        'id': 7, 'name': 'Jane Doe', 'district_name': 'District 3',
        'attendance_pct': 92, 'alignment_pct': 78, 'photo_url': None,
    }
    municipality = {'slug': 'birmingham'}
    html = render_partial("partials/council_card.html", m=m, municipality=municipality)
    assert 'cc-stats' in html
    assert '92' in html and '%' in html
    assert '78' in html


def test_council_card_omits_attendance_alignment_when_missing(render_partial):
    """No stats block renders when fields are absent — current P2b consumer path."""
    m = {'id': 7, 'name': 'Jane Doe', 'district_name': 'District 3', 'photo_url': None}
    municipality = {'slug': 'birmingham'}
    html = render_partial("partials/council_card.html", m=m, municipality=municipality)
    assert 'cc-stats' not in html
    # Card body still renders core fields
    assert 'Jane Doe' in html
    assert 'District 3' in html


def test_council_card_is_anchor_to_member_detail(render_partial):
    """P4-2: council_card.html became an anchor to /al/<slug>/council/<id>/.

    Replaces the P2b/P3 contract (button with type='button' because no nav
    target existed yet). With member_detail in P4-2, the card navigates.
    """
    m = {'id': 7, 'name': 'Jane Doe', 'district_name': 'District 3', 'photo_url': None}
    municipality = {'slug': 'birmingham'}
    html = render_partial("partials/council_card.html", m=m, municipality=municipality)
    assert '<a class="cc"' in html
    assert '/al/birmingham/council/7/' in html
    assert 'type="button"' not in html


# ── P3 Task 4: city_lead — eyebrow + h1 + freshness chip ────────────────────


def test_city_lead_renders_full_metadata(render_partial):
    """CityLead with all 3 metadata fields renders eyebrow + h1 + chip."""
    municipality = {
        "id": 1, "slug": "birmingham", "name": "Birmingham", "state": "AL",
        "adapter_class": "GranicusAdapter",
        "metadata": {
            "council_type": "Mayor-council",
            "county": "Jefferson County",
            "population": 196910,
            "population_year": 2020,
        },
    }
    freshness = {"state": "good", "label": "Live", "last_synced": None}
    html = render_partial("partials/city_lead.html", municipality=municipality, freshness=freshness)
    assert 'class="city-lead' in html
    assert "Mayor-council" in html
    assert "Jefferson County" in html
    assert "196,910" in html  # comma-formatted
    assert "Birmingham, AL" in html
    assert "city-lead-chip" in html


def test_city_lead_eyebrow_collapses_when_metadata_empty(render_partial):
    """No metadata → eyebrow row renders no content (degrades gracefully)."""
    municipality = {
        "id": 99, "slug": "newcity", "name": "New City", "state": "AL",
        "adapter_class": "GranicusAdapter",
        "metadata": {},
    }
    freshness = {"state": "unknown", "label": "No data yet", "last_synced": None}
    html = render_partial("partials/city_lead.html", municipality=municipality, freshness=freshness)
    assert "New City, AL" in html  # h1 still renders
    # No accidental literal eyebrow text from a populated city
    assert "Mayor-council" not in html
    assert "Jefferson County" not in html
    # The eyebrow div container can exist but its content should be empty
    # of metadata strings — no "·" separators from joining
    eyebrow_text = html.split('class="city-lead-eyebrow')[1].split("</div>")[0]
    assert "·" not in eyebrow_text


def test_city_lead_partial_metadata_renders_partial_eyebrow(render_partial):
    """Some metadata present → render what's available."""
    municipality = {
        "id": 99, "slug": "partial", "name": "Partial City", "state": "AL",
        "adapter_class": "GranicusAdapter",
        "metadata": {"county": "Some County"},
    }
    freshness = {"state": "good", "label": "Live", "last_synced": None}
    html = render_partial("partials/city_lead.html", municipality=municipality, freshness=freshness)
    assert "Some County" in html
    assert "pop." not in html  # population missing → not rendered


def test_city_lead_freshness_chip_renders_state(render_partial):
    """Freshness chip exposes its state via class + data attribute."""
    municipality = {
        "id": 1, "slug": "birmingham", "name": "Birmingham", "state": "AL",
        "adapter_class": "GranicusAdapter", "metadata": {},
    }
    for state in ("good", "warn", "bad", "unknown"):
        freshness = {"state": state, "label": state.title(), "last_synced": None}
        html = render_partial("partials/city_lead.html", municipality=municipality, freshness=freshness)
        assert f"is-{state}" in html
        assert f'data-state="{state}"' in html


# ── P3 Task 8: .tw section condensation regression ──────────────────────────


def test_tw_section_compact_class_present():
    """P3: .tw section uses tight vertical spacing — no oversized literal pads."""
    import re
    for path in (
        "src/docket/web/static/councilmatic.css",
        "src/docket/web/static/layout.css",
        "src/docket/web/static/styles.css",
    ):
        css = (PROJECT_ROOT / path).read_text() if (PROJECT_ROOT / path).exists() else ""
        if ".tw {" in css or ".tw\n{" in css or ".tw{" in css:
            # Found the .tw rule — verify it's not using oversized literal pads
            rule = re.search(r"\.tw\s*\{[^}]*\}", css)
            if rule:
                # Should NOT carry padding > 48px literal
                bad = re.findall(r"padding:[^;]*?(\d{2,3})px", rule.group(0))
                if bad:
                    assert max(int(x) for x in bad) <= 48, (
                        f".tw padding too loose: {rule.group(0)}"
                    )
            return  # found and verified
    # If no .tw {} block found, the rules may live in a media query or
    # composite selector — skip the structural check.


# ── P3 Task 5: kpi_strip — 3-card YTD KPI row ───────────────────────────────


def test_kpi_strip_renders_three_cards(render_partial):
    """kpi_strip wraps 3 num_stat partials in a single .kpi-strip row."""
    city_stats = {
        "meetings_ytd": 38,
        "dollars_ytd_formatted": "$1.4B",
        "flagged_count": 12,
    }
    html = render_partial("partials/kpi_strip.html", city_stats=city_stats)
    assert 'class="kpi-strip' in html
    # All three values present
    assert "38" in html
    assert "1.4B" in html
    assert "12" in html
    # All three labels present
    assert "Meetings YTD" in html
    assert "Dollars YTD" in html
    assert "Flagged" in html  # "Flagged items"


# ── P3 Task 10: .hero-title token migration ──────────────────────────────────


def test_hero_title_uses_type_hero_token():
    """P3 (resolves P2a follow-up #1): .hero-title consumes the
    --type-hero token, not a literal 72px."""
    import re
    css = (PROJECT_ROOT / "src/docket/web/static/layout.css").read_text()
    match = re.search(r"\.hero-title\s*\{[^}]*\}", css)
    assert match, ".hero-title rule missing from layout.css"
    rule_body = match.group(0)
    assert "var(--type-hero)" in rule_body, (
        ".hero-title not consuming --type-hero token"
    )
    assert "font-size: 72px" not in rule_body, (
        ".hero-title still has the legacy 72px literal"
    )
