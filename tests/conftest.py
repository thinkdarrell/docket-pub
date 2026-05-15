"""Root pytest configuration shared across unit + integration tests.

Two env-var hygiene fixes for the local test environment:

1. ``ANTHROPIC_API_KEY`` — set to a dummy value if unset so tests that
   construct an ``AIClient`` (e.g. ``test_run_once_refuses_over_budget``)
   clear ``AIClient.__init__``'s "is set" check. Every test that
   exercises the SDK mocks ``anthropic.Anthropic``/``anthropic_client``,
   so the dummy value is never sent over the wire — but the constructor
   still needs a truthy string. The dummy value is intentionally
   recognizable so an accidental real-API call surfaces a clear error.

2. ``PGTZ=UTC`` — match the Railway production environment's
   PostgreSQL session timezone. ``worker._today_spend`` uses
   ``date_trunc('day', NOW() AT TIME ZONE 'UTC')`` which returns a
   naive timestamp; when compared to a ``timestamptz`` column,
   Postgres reinterprets it using the *session* TZ. On Railway
   (UTC session) this is correct; on a developer's Mac (often
   Central/Pacific) it shifts the comparison by several hours and
   newly-inserted ai_runs rows don't match "today UTC" — breaking
   ``test_run_once_refuses_over_budget`` and any local query that
   relies on the same trick.

Both use ``os.environ.setdefault`` so an operator can override from
the shell (e.g. ``PGTZ=America/Chicago pytest …`` to reproduce a
local-only bug).
"""

from __future__ import annotations

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-dummy-key-not-for-real-api-calls")
os.environ.setdefault("PGTZ", "UTC")
# TZ is paired with PGTZ so Python's ``date.today()`` and Postgres's
# ``CURRENT_DATE`` agree on which calendar day "today" is. Without
# this, tests that seed via ``date.today() - timedelta(days=N)`` and
# query against ``CURRENT_DATE - N`` flip by one day during the
# cross-midnight window (e.g. 21:30 Central is already 02:30 UTC).
os.environ.setdefault("TZ", "UTC")
import time  # noqa: E402 — apply TZ immediately so tests see UTC dates
time.tzset()
