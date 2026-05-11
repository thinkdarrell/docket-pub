"""Tests for policy badge matcher (docket.ai.badges_policy) and service
layer (docket.services.badges).

Coverage:
- deterministic_policy_match: all trigger paths + guard paths
- resolve_policy_badge_confidence: all 4 cases
- resolve_source: all 3 valid cases + ValueError
- compute_policy_badges: hint merging, hallucination filtering, metadata shapes
- Service layer (real DB): hint merging, kind filtering, enabled flag, tuple
  return, lru_cache invalidation
"""
from __future__ import annotations

import pytest

from docket.ai.badges_policy import (
    compute_policy_badges,
    deterministic_policy_match,
    resolve_policy_badge_confidence,
    resolve_source,
)
from docket.ai.extraction_schema import NextSteps, StructuredFacts


# ===========================================================================
# Helpers / fixtures
# ===========================================================================

def make_item(**kw):
    """Duck-typed agenda item for policy matcher tests."""
    defaults = {'title': 'Standard agenda item', 'description': None, 'topic': None}
    defaults.update(kw)
    return type('Item', (), defaults)()


def make_facts(**kw) -> StructuredFacts:
    defaults = dict(
        funding_source='general_fund',
        counterparty=None,
        procurement_method='competitive',
        location=None,
        action_type='contract_award',
        next_steps=NextSteps(),
        parcels_affected=None,
        acres_affected=None,
    )
    defaults.update(kw)
    return StructuredFacts(**defaults)


def make_rewrite(**kw):
    """Duck-typed ItemRewrite with suggested_badge_slugs."""
    defaults = {'suggested_badge_slugs': []}
    defaults.update(kw)
    return type('ItemRewrite', (), defaults)()


# ===========================================================================
# deterministic_policy_match — guard: excluded_action_types
# ===========================================================================

class TestExcludedActionTypes:
    def test_excluded_action_types_blocks_match(self):
        """facts.action_type in excluded_action_types → False even with keyword match."""
        item = make_item(title='blight removal project')
        facts = make_facts(action_type='proclamation')
        hints = {
            'excluded_action_types': ['proclamation'],
            'keywords': ['blight'],
        }
        matched, meta = deterministic_policy_match(item, facts, make_rewrite(), hints)
        assert matched is False
        assert meta == {}

    def test_non_excluded_action_type_still_matches(self):
        """Same keyword, different (non-excluded) action_type → matches."""
        item = make_item(title='blight removal project')
        facts = make_facts(action_type='contract_award')
        hints = {
            'excluded_action_types': ['proclamation'],
            'keywords': ['blight'],
        }
        matched, meta = deterministic_policy_match(item, facts, make_rewrite(), hints)
        assert matched is True


# ===========================================================================
# deterministic_policy_match — guard: excluded_phrases
# ===========================================================================

class TestExcludedPhrases:
    def test_excluded_phrases_blocks_match(self):
        """Text contains excluded phrase → (False, {}) even with keyword."""
        item = make_item(title='This is not blight, just a cleanup')
        facts = make_facts()
        hints = {
            'excluded_phrases': ['this is not blight'],
            'keywords': ['blight'],
        }
        matched, meta = deterministic_policy_match(item, facts, make_rewrite(), hints)
        assert matched is False
        assert meta == {}

    def test_excluded_phrase_case_insensitive(self):
        """Excluded phrase check is case-insensitive (both lowercased)."""
        item = make_item(title='ROUTINE MAINTENANCE ONLY — not an emergency')
        facts = make_facts()
        hints = {
            'excluded_phrases': ['routine maintenance only'],
            'keywords': ['emergency'],
        }
        matched, meta = deterministic_policy_match(item, facts, make_rewrite(), hints)
        assert matched is False

    def test_non_matching_excluded_phrase_allows_match(self):
        """Excluded phrase NOT present → keyword match fires normally."""
        item = make_item(title='blight removal contract')
        facts = make_facts()
        hints = {
            'excluded_phrases': ['routine maintenance'],
            'keywords': ['blight'],
        }
        matched, meta = deterministic_policy_match(item, facts, make_rewrite(), hints)
        assert matched is True


# ===========================================================================
# deterministic_policy_match — keyword matching
# ===========================================================================

class TestKeywordMatching:
    def test_keyword_string_matches_word_boundary(self):
        """Keyword 'blight' matches 'blight removal' but NOT 'blightful'."""
        hints = {'keywords': ['blight']}
        item_match = make_item(title='blight removal plan')
        item_no_match = make_item(title='blightful conditions')
        facts = make_facts()
        rewrite = make_rewrite()

        matched, _ = deterministic_policy_match(item_match, facts, rewrite, hints)
        assert matched is True

        not_matched, _ = deterministic_policy_match(item_no_match, facts, rewrite, hints)
        assert not_matched is False

    def test_keyword_string_case_insensitive(self):
        """Keyword='Blight' matches 'BLIGHT' in title (both lowercased)."""
        item = make_item(title='BLIGHT REMEDIATION')
        facts = make_facts()
        hints = {'keywords': ['Blight']}
        matched, meta = deterministic_policy_match(item, facts, make_rewrite(), hints)
        assert matched is True
        assert 'Blight' in meta['matched_keywords']

    def test_keyword_in_description_matches(self):
        """Keyword match scans both title AND description."""
        item = make_item(title='Property action', description='blight demolition approved')
        facts = make_facts()
        hints = {'keywords': ['blight']}
        matched, _ = deterministic_policy_match(item, facts, make_rewrite(), hints)
        assert matched is True

    def test_keyword_regex_matches(self):
        """Dict entry with is_regex=True uses pattern directly."""
        item = make_item(title='building demolition order')
        facts = make_facts()
        hints = {'keywords': [{'pattern': r'demolitio', 'is_regex': True}]}
        matched, meta = deterministic_policy_match(item, facts, make_rewrite(), hints)
        assert matched is True

    def test_keyword_regex_label_used_in_metadata(self):
        """When label provided, metadata records the label (not raw pattern)."""
        item = make_item(title='structure demolition contract')
        facts = make_facts()
        hints = {'keywords': [{'pattern': r'demolitio\w+', 'is_regex': True, 'label': 'demolition'}]}
        matched, meta = deterministic_policy_match(item, facts, make_rewrite(), hints)
        assert matched is True
        assert 'demolition' in meta['matched_keywords']
        assert r'demolitio\w+' not in meta['matched_keywords']

    def test_keyword_regex_without_label_uses_pattern_in_metadata(self):
        """When no label, the raw pattern string is recorded."""
        item = make_item(title='demo of blight structure')
        facts = make_facts()
        hints = {'keywords': [{'pattern': r'blight', 'is_regex': True}]}
        matched, meta = deterministic_policy_match(item, facts, make_rewrite(), hints)
        assert matched is True
        assert r'blight' in meta['matched_keywords']

    def test_invalid_regex_logs_warning_and_continues(self):
        """Invalid regex pattern doesn't crash; matcher continues to other rules."""
        item = make_item(title='blight removal approved')
        facts = make_facts()
        hints = {'keywords': [
            {'pattern': '[unclosed', 'is_regex': True},
            'blight',  # valid string keyword follows
        ]}
        # Should not raise; the valid keyword should still fire
        matched, meta = deterministic_policy_match(item, facts, make_rewrite(), hints)
        assert matched is True
        assert 'blight' in meta['matched_keywords']

    def test_metadata_records_all_matched_keywords(self):
        """Multiple keywords matching → matched_keywords is a list of all matches."""
        item = make_item(title='blight and housing instability crisis')
        facts = make_facts()
        hints = {'keywords': ['blight', 'housing', 'crisis']}
        matched, meta = deterministic_policy_match(item, facts, make_rewrite(), hints)
        assert matched is True
        kws = meta['matched_keywords']
        assert 'blight' in kws
        assert 'housing' in kws
        assert 'crisis' in kws
        assert len(kws) == 3

    def test_keyword_takes_precedence_over_action_type(self):
        """When keyword fires, metadata records keyword path not action_type."""
        item = make_item(title='blight demolition')
        facts = make_facts(action_type='zoning')
        hints = {
            'keywords': ['blight'],
            'action_types': ['zoning'],
        }
        matched, meta = deterministic_policy_match(item, facts, make_rewrite(), hints)
        assert matched is True
        assert 'matched_keywords' in meta
        assert 'matched_action_type' not in meta


# ===========================================================================
# deterministic_policy_match — action_type and topic matching
# ===========================================================================

class TestActionTypeAndTopicMatching:
    def test_action_type_match_records_metadata(self):
        """facts.action_type in action_types → metadata['matched_action_type']."""
        item = make_item(title='Some zoning decision')
        facts = make_facts(action_type='zoning')
        hints = {'action_types': ['zoning']}
        matched, meta = deterministic_policy_match(item, facts, make_rewrite(), hints)
        assert matched is True
        assert meta == {'matched_action_type': 'zoning'}

    def test_topic_match(self):
        """item.topic in topics → matched with matched_topic."""
        item = make_item(title='Public safety program', topic='public_safety')
        facts = make_facts()
        hints = {'topics': ['public_safety']}
        matched, meta = deterministic_policy_match(item, facts, make_rewrite(), hints)
        assert matched is True
        assert meta == {'matched_topic': 'public_safety'}

    def test_topic_none_does_not_match(self):
        """item.topic=None → topic guard skips safely."""
        item = make_item(title='General item', topic=None)
        facts = make_facts()
        hints = {'topics': ['public_safety']}
        matched, _ = deterministic_policy_match(item, facts, make_rewrite(), hints)
        assert matched is False

    def test_no_match_returns_false(self):
        """No keywords, no action_type match, no topic → (False, {})."""
        item = make_item(title='Routine personnel update')
        facts = make_facts(action_type='other')
        hints = {'keywords': ['blight'], 'action_types': ['zoning'], 'topics': ['housing']}
        matched, meta = deterministic_policy_match(item, facts, make_rewrite(), hints)
        assert matched is False
        assert meta == {}

    def test_empty_hints_returns_false(self):
        """Empty hints dict → (False, {})."""
        item = make_item(title='Whatever')
        facts = make_facts()
        matched, meta = deterministic_policy_match(item, facts, make_rewrite(), {})
        assert matched is False
        assert meta == {}


# ===========================================================================
# resolve_policy_badge_confidence
# ===========================================================================

class TestResolvePolicyBadgeConfidence:
    def test_both_returns_high_confidence(self):
        assert resolve_policy_badge_confidence('blight', True, True) == 1.0

    def test_llm_only_returns_medium(self):
        assert resolve_policy_badge_confidence('blight', True, False) == pytest.approx(0.6)

    def test_det_only_returns_medium(self):
        assert resolve_policy_badge_confidence('blight', False, True) == pytest.approx(0.6)

    def test_neither_returns_none(self):
        assert resolve_policy_badge_confidence('blight', False, False) is None


# ===========================================================================
# resolve_source
# ===========================================================================

class TestResolveSource:
    def test_resolve_source_both(self):
        assert resolve_source(True, True) == 'both'

    def test_resolve_source_llm(self):
        assert resolve_source(True, False) == 'llm'

    def test_resolve_source_deterministic(self):
        assert resolve_source(False, True) == 'deterministic'

    def test_resolve_source_neither_raises(self):
        with pytest.raises(ValueError):
            resolve_source(False, False)


# ===========================================================================
# compute_policy_badges — unit tests (mocked service layer)
# ===========================================================================

class TestComputePolicyBadges:
    """Unit tests for compute_policy_badges using monkeypatched service layer."""

    def _make_badge(self, slug, hints=None):
        """Create a minimal EnabledBadge-like object."""
        return type('EnabledBadge', (), {
            'slug': slug,
            'name': f'{slug} name',
            'description': f'{slug} description',
            'icon': 'icon',
            'kind': 'policy',
            'matcher_hints': hints or {},
        })()

    def test_returns_empty_when_no_badges_enabled(self, monkeypatch):
        """No rows in priority_badges_config → returns []."""
        import docket.services.badges as svc
        monkeypatch.setattr(svc, 'list_enabled_policy_badges', lambda city_id: ())

        item = make_item(title='Whatever')
        facts = make_facts()
        rewrite = make_rewrite()
        result = compute_policy_badges(item, facts, rewrite, 1)
        assert result == []

    def test_filters_llm_hallucinations_to_enabled_set(self, monkeypatch):
        """LLM suggests a slug not in enabled list → dropped silently."""
        import docket.services.badges as svc
        enabled_badge = self._make_badge('blight_accountability')
        monkeypatch.setattr(svc, 'list_enabled_policy_badges', lambda city_id: (enabled_badge,))

        item = make_item(title='Regular item')
        facts = make_facts()
        # LLM suggests a badge not in the enabled set
        rewrite = make_rewrite(suggested_badge_slugs=['hallucinated_badge', 'blight_accountability'])

        # blight_accountability is enabled but won't det-match on this item
        # hallucinated_badge should be dropped
        result = compute_policy_badges(item, facts, rewrite, 1)
        slugs = [r[0] for r in result]
        assert 'hallucinated_badge' not in slugs
        # blight_accountability fired via LLM only
        assert 'blight_accountability' in slugs

    def test_returns_4_tuple_per_match(self, monkeypatch):
        """Each entry in result is (slug, confidence, source, metadata)."""
        import docket.services.badges as svc
        badge = self._make_badge('blight_accountability', hints={'keywords': ['blight']})
        monkeypatch.setattr(svc, 'list_enabled_policy_badges', lambda city_id: (badge,))

        item = make_item(title='blight removal')
        facts = make_facts()
        rewrite = make_rewrite()
        result = compute_policy_badges(item, facts, rewrite, 1)

        assert len(result) == 1
        slug, conf, source, metadata = result[0]
        assert slug == 'blight_accountability'
        assert isinstance(conf, float)
        assert isinstance(source, str)
        assert isinstance(metadata, dict)

    def test_metadata_distinguishes_both_vs_llm_only_vs_det_only(self, monkeypatch):
        """Verify metadata shape across the 3 firing cases."""
        import docket.services.badges as svc

        badge_both = self._make_badge('slug_both', hints={'keywords': ['blight']})
        badge_llm = self._make_badge('slug_llm', hints={})
        badge_det = self._make_badge('slug_det', hints={'keywords': ['housing']})

        monkeypatch.setattr(svc, 'list_enabled_policy_badges',
                            lambda city_id: (badge_both, badge_llm, badge_det))

        item = make_item(title='blight and housing issues')
        facts = make_facts()
        rewrite = make_rewrite(suggested_badge_slugs=['slug_both', 'slug_llm'])

        result = compute_policy_badges(item, facts, rewrite, 1)
        by_slug = {r[0]: r for r in result}

        assert 'slug_both' in by_slug
        assert 'slug_llm' in by_slug
        assert 'slug_det' in by_slug

        _, _, source_both, meta_both = by_slug['slug_both']
        assert source_both == 'both'
        assert meta_both.get('both') is True

        _, _, source_llm, meta_llm = by_slug['slug_llm']
        assert source_llm == 'llm'
        assert meta_llm == {'llm_only': True}

        _, _, source_det, meta_det = by_slug['slug_det']
        assert source_det == 'deterministic'
        assert 'matched_keywords' in meta_det

    def test_confidence_both_is_1_0(self, monkeypatch):
        """LLM + deterministic = 1.0 confidence."""
        import docket.services.badges as svc
        badge = self._make_badge('blight_accountability', hints={'keywords': ['blight']})
        monkeypatch.setattr(svc, 'list_enabled_policy_badges', lambda city_id: (badge,))

        item = make_item(title='blight demolition')
        facts = make_facts()
        rewrite = make_rewrite(suggested_badge_slugs=['blight_accountability'])

        result = compute_policy_badges(item, facts, rewrite, 1)
        assert len(result) == 1
        _, conf, source, _ = result[0]
        assert conf == pytest.approx(1.0)
        assert source == 'both'

    def test_confidence_single_source_is_0_6(self, monkeypatch):
        """LLM only → 0.6. det only → 0.6."""
        import docket.services.badges as svc
        badge = self._make_badge('blight_accountability', hints={'keywords': ['blight']})
        monkeypatch.setattr(svc, 'list_enabled_policy_badges', lambda city_id: (badge,))

        item = make_item(title='blight removal')
        facts = make_facts()
        rewrite = make_rewrite()  # no LLM suggestion
        result = compute_policy_badges(item, facts, rewrite, 1)
        assert len(result) == 1
        _, conf, source, _ = result[0]
        assert conf == pytest.approx(0.6)
        assert source == 'deterministic'


# ===========================================================================
# Service layer — real DB integration tests
# ===========================================================================

TEST_CITY_SLUG = 'test_policy_badges_city'


def _setup_city(cur):
    """Insert or reuse test municipality. Returns city_id (plain tuple cursor)."""
    cur.execute(
        """
        INSERT INTO municipalities (slug, name, state, county, adapter_class, adapter_config)
        VALUES (%s, 'Test Policy Badges City', 'AL', 'Test', 'TestAdapter', '{}')
        ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        (TEST_CITY_SLUG,),
    )
    return cur.fetchone()[0]


def _insert_template(cur, slug, kind='policy', default_hints=None):
    """Insert a minimal badge template."""
    import json
    cur.execute(
        """
        INSERT INTO priority_badge_templates (slug, name, description, icon, kind, default_matcher_hints)
        VALUES (%s, %s, %s, 'icon', %s, %s::jsonb)
        ON CONFLICT (slug) DO UPDATE SET kind = EXCLUDED.kind, default_matcher_hints = EXCLUDED.default_matcher_hints
        """,
        (slug, f'{slug} name', f'{slug} desc', kind, json.dumps(default_hints or {})),
    )


def _insert_config(cur, city_id, slug, enabled=True, name_override=None,
                   description_override=None, hints_override=None):
    """Insert a badge config row for a city."""
    import json
    cur.execute(
        """
        INSERT INTO priority_badges_config
            (city_id, template_slug, name_override, description_override, matcher_hints_override, enabled)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s)
        ON CONFLICT (city_id, template_slug) DO UPDATE
          SET enabled = EXCLUDED.enabled,
              name_override = EXCLUDED.name_override,
              matcher_hints_override = EXCLUDED.matcher_hints_override
        """,
        (city_id, slug, name_override, description_override,
         json.dumps(hints_override) if hints_override else None, enabled),
    )


def _cleanup(cur, city_id, template_slugs):
    """Remove test data."""
    cur.execute("DELETE FROM priority_badges_config WHERE city_id = %s", (city_id,))
    for slug in template_slugs:
        cur.execute("DELETE FROM priority_badge_templates WHERE slug = %s", (slug,))
    cur.execute("DELETE FROM municipalities WHERE id = %s", (city_id,))


class TestListEnabledPolicyBadgesDB:
    """Integration tests for list_enabled_policy_badges against real DB."""

    def test_list_enabled_policy_badges_merges_hints(self):
        """Config matcher_hints_override merges over default_matcher_hints."""
        from docket.db import db
        from docket.services.badges import cache_clear_for_city, list_enabled_policy_badges

        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                slug = 'test_policy_merge_hints'
                try:
                    _insert_template(cur, slug, kind='policy',
                                     default_hints={'keywords': ['default_kw'], 'action_types': ['zoning']})
                    _insert_config(cur, city_id, slug, enabled=True,
                                   hints_override={'keywords': ['override_kw']})
                    conn.commit()

                    cache_clear_for_city(city_id)
                    badges = list_enabled_policy_badges(city_id)
                    badge = next((b for b in badges if b.slug == slug), None)
                    assert badge is not None
                    # Override replaces keywords list entirely
                    assert badge.matcher_hints['keywords'] == ['override_kw']
                    # Non-overridden key preserved
                    assert badge.matcher_hints['action_types'] == ['zoning']
                finally:
                    _cleanup(cur, city_id, [slug])
                    conn.commit()

    def test_list_enabled_policy_badges_filters_by_kind(self):
        """Only kind='policy' rows returned; process templates excluded."""
        from docket.db import db
        from docket.services.badges import cache_clear_for_city, list_enabled_policy_badges

        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                policy_slug = 'test_policy_kind_policy'
                process_slug = 'test_policy_kind_process'
                try:
                    _insert_template(cur, policy_slug, kind='policy')
                    _insert_template(cur, process_slug, kind='process')
                    _insert_config(cur, city_id, policy_slug)
                    _insert_config(cur, city_id, process_slug)
                    conn.commit()

                    cache_clear_for_city(city_id)
                    badges = list_enabled_policy_badges(city_id)
                    slugs = {b.slug for b in badges}
                    assert policy_slug in slugs
                    assert process_slug not in slugs
                finally:
                    _cleanup(cur, city_id, [policy_slug, process_slug])
                    conn.commit()

    def test_list_enabled_policy_badges_filters_by_enabled_flag(self):
        """Rows with enabled=FALSE are excluded."""
        from docket.db import db
        from docket.services.badges import cache_clear_for_city, list_enabled_policy_badges

        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                enabled_slug = 'test_policy_enabled_yes'
                disabled_slug = 'test_policy_enabled_no'
                try:
                    _insert_template(cur, enabled_slug, kind='policy')
                    _insert_template(cur, disabled_slug, kind='policy')
                    _insert_config(cur, city_id, enabled_slug, enabled=True)
                    _insert_config(cur, city_id, disabled_slug, enabled=False)
                    conn.commit()

                    cache_clear_for_city(city_id)
                    badges = list_enabled_policy_badges(city_id)
                    slugs = {b.slug for b in badges}
                    assert enabled_slug in slugs
                    assert disabled_slug not in slugs
                finally:
                    _cleanup(cur, city_id, [enabled_slug, disabled_slug])
                    conn.commit()

    def test_get_enabled_policy_slugs_returns_tuple(self):
        """get_enabled_policy_slugs returns a tuple (for lru_cache compatibility)."""
        from docket.db import db
        from docket.services.badges import cache_clear_for_city, get_enabled_policy_slugs

        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                slug = 'test_policy_slugs_tuple'
                try:
                    _insert_template(cur, slug, kind='policy')
                    _insert_config(cur, city_id, slug)
                    conn.commit()

                    cache_clear_for_city(city_id)
                    result = get_enabled_policy_slugs(city_id)
                    assert isinstance(result, tuple)
                    assert slug in result
                finally:
                    _cleanup(cur, city_id, [slug])
                    conn.commit()

    def test_cache_clear_for_city(self):
        """cache_clear_for_city causes subsequent call to re-query DB."""
        from docket.db import db
        from docket.services.badges import cache_clear_for_city, list_enabled_policy_badges

        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                slug1 = 'test_policy_cache_before'
                slug2 = 'test_policy_cache_after'
                try:
                    # First: only slug1 enabled
                    _insert_template(cur, slug1, kind='policy')
                    _insert_config(cur, city_id, slug1)
                    conn.commit()

                    cache_clear_for_city(city_id)
                    badges_before = list_enabled_policy_badges(city_id)
                    slugs_before = {b.slug for b in badges_before}
                    assert slug1 in slugs_before
                    assert slug2 not in slugs_before

                    # Add slug2 and clear cache
                    _insert_template(cur, slug2, kind='policy')
                    _insert_config(cur, city_id, slug2)
                    conn.commit()
                    cache_clear_for_city(city_id)

                    badges_after = list_enabled_policy_badges(city_id)
                    slugs_after = {b.slug for b in badges_after}
                    assert slug1 in slugs_after
                    assert slug2 in slugs_after
                finally:
                    _cleanup(cur, city_id, [slug1, slug2])
                    conn.commit()

    def test_get_resolved_badge_returns_badge(self):
        """get_resolved_badge returns the correct EnabledBadge or None."""
        from docket.db import db
        from docket.services.badges import (
            cache_clear_for_city,
            get_resolved_badge,
        )

        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                slug = 'test_policy_get_resolved'
                try:
                    _insert_template(cur, slug, kind='policy')
                    _insert_config(cur, city_id, slug)
                    conn.commit()

                    cache_clear_for_city(city_id)
                    badge = get_resolved_badge(city_id, slug)
                    assert badge is not None
                    assert badge.slug == slug

                    missing = get_resolved_badge(city_id, 'does_not_exist')
                    assert missing is None
                finally:
                    _cleanup(cur, city_id, [slug])
                    conn.commit()
