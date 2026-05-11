"""DB-backed AI response cache (decision #91).

Cache table: `ai_response_cache` (created by Migration 013).
Cache key: sha256(model + prompt_version + canonical_input) — decision #42.
Cleanup: nightly task drops entries older than 90 days.

Spec: section 2.5 (revised), decisions #18, #42, #91.
"""

from __future__ import annotations

import hashlib
import json

from docket.db import db


def cache_key(model_id: str, prompt_version: int, canonical_input: str) -> str:
    """Returns sha256 hex for (model, prompt_version, canonical_input) triple."""
    blob = f"{model_id}|v{prompt_version}|{canonical_input}".encode('utf-8')
    return hashlib.sha256(blob).hexdigest()


def cache_get(key: str) -> dict | None:
    """Returns the cached response payload, or None on miss.
    Side effect: bumps `accessed_at` on hit (informs cleanup TTL)."""
    with db() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE ai_response_cache
            SET accessed_at = NOW()
            WHERE cache_key = %s
            RETURNING response_json
        """, [key])
        row = cur.fetchone()
        return row[0] if row else None


def cache_put(key: str, *, model: str, prompt_version: int, payload: dict) -> None:
    """Insert or update a cache entry."""
    with db() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO ai_response_cache
              (cache_key, model, prompt_version, response_json)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (cache_key) DO UPDATE
              SET response_json = EXCLUDED.response_json,
                  accessed_at = NOW()
        """, [key, model, prompt_version, json.dumps(payload, default=str)])


def cache_cleanup(max_age_days: int = 90) -> int:
    """Delete entries older than max_age_days (decision #91 cleanup policy).
    Called by the nightly calibration_report cron task. Returns rows deleted."""
    with db() as conn, conn.cursor() as cur:
        cur.execute("""
            DELETE FROM ai_response_cache
            WHERE accessed_at < NOW() - (%s || ' days')::interval
        """, [str(max_age_days)])
        return cur.rowcount
