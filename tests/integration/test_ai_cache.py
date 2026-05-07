"""Tests for the DB-backed AI response cache (`docket.ai.cache`)."""

from __future__ import annotations

import pytest

from docket.ai.cache import cache_key, cache_get, cache_put, cache_cleanup
from docket.db import db, db_cursor


def test_cache_key_deterministic():
    k1 = cache_key('claude-haiku-4-5-20251001', 3, '{"title": "X"}')
    k2 = cache_key('claude-haiku-4-5-20251001', 3, '{"title": "X"}')
    assert k1 == k2


def test_cache_key_includes_model_version():
    k1 = cache_key('claude-haiku-4-5-20251001', 3, '{"title": "X"}')
    k2 = cache_key('claude-haiku-4-5-20251002', 3, '{"title": "X"}')
    assert k1 != k2


def test_cache_key_includes_prompt_version():
    k1 = cache_key('claude-haiku-4-5-20251001', 3, '{"title": "X"}')
    k2 = cache_key('claude-haiku-4-5-20251001', 4, '{"title": "X"}')
    assert k1 != k2


def test_cache_get_miss():
    assert cache_get('nonexistent_key_xyz') is None


def test_cache_put_and_get():
    key = 'test_key_abc123'
    payload = {'response': {'content': 'hello'}, 'model': 'claude-haiku-4-5-20251001'}
    cache_put(key, model='claude-haiku-4-5-20251001', prompt_version=3, payload=payload)
    got = cache_get(key)
    assert got == payload

    # Cleanup
    with db_cursor() as cur:
        cur.execute("DELETE FROM ai_response_cache WHERE cache_key = %s", [key])


def test_cache_get_updates_accessed_at():
    """cache_get bumps accessed_at — for the cleanup task."""
    key = 'test_accessed_xyz'
    payload = {'response': {'x': 1}}
    cache_put(key, model='claude-haiku-4-5-20251001', prompt_version=3, payload=payload)

    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT accessed_at FROM ai_response_cache WHERE cache_key = %s", [key])
        before = cur.fetchone()[0]

    cache_get(key)

    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT accessed_at FROM ai_response_cache WHERE cache_key = %s", [key])
        after = cur.fetchone()[0]

    assert after >= before

    # Cleanup
    with db_cursor() as cur:
        cur.execute("DELETE FROM ai_response_cache WHERE cache_key = %s", [key])


def test_cache_cleanup_removes_old_entries():
    """cache_cleanup deletes entries older than max_age_days."""
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO ai_response_cache
              (cache_key, model, prompt_version, response_json, cached_at, accessed_at)
            VALUES
              ('cleanup_test_old', 'claude-haiku-4-5-20251001', 3, '{}'::jsonb,
               NOW() - INTERVAL '120 days', NOW() - INTERVAL '120 days')
        """)

    n_deleted = cache_cleanup(max_age_days=90)
    assert n_deleted >= 1

    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM ai_response_cache WHERE cache_key = 'cleanup_test_old'")
        assert cur.fetchone()[0] == 0
