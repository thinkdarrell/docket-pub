"""Integration tests for B5 — worker dispatch via IMPACT_FIRST_ENABLED.

Confirms that ``run_once(stage="items", ...)`` routes to:
  - ``_process_items_v3`` when ``IMPACT_FIRST_ENABLED=True``
  - ``_process_items`` (v2 legacy) when ``False`` (default)

Tests the gating, not the orchestration itself (Task 1 covers that).
"""

from __future__ import annotations

import pytest

from docket.config import DATABASE_URL


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run B5 worker-dispatch tests against Railway DB.",
)


def test_run_once_dispatches_to_v3_when_flag_enabled(monkeypatch):
    """IMPACT_FIRST_ENABLED=True routes to _process_items_v3."""
    from docket.ai import worker

    v2_calls = []
    v3_calls = []
    monkeypatch.setattr(worker, "IMPACT_FIRST_ENABLED", True)
    monkeypatch.setattr(
        worker, "_process_items",
        lambda *a, **kw: v2_calls.append(("v2", a, kw)),
    )
    monkeypatch.setattr(
        worker, "_process_items_v3",
        lambda *a, **kw: v3_calls.append(("v3", a, kw)),
    )
    # Prevent budget gate from interfering.
    monkeypatch.setattr(worker, "_today_spend", lambda conn: 0.0)
    # Mock the AI client factory to avoid network.
    monkeypatch.setattr(worker, "_make_client", lambda: None)

    worker.run_once(stage="items", limit=10, notes="test_v3_dispatch")
    assert len(v3_calls) == 1
    assert len(v2_calls) == 0


def test_run_once_dispatches_to_v2_when_flag_disabled(monkeypatch):
    """Default (IMPACT_FIRST_ENABLED=False) routes to legacy v2 worker."""
    from docket.ai import worker

    v2_calls = []
    v3_calls = []
    monkeypatch.setattr(worker, "IMPACT_FIRST_ENABLED", False)
    monkeypatch.setattr(
        worker, "_process_items",
        lambda *a, **kw: v2_calls.append(("v2", a, kw)),
    )
    monkeypatch.setattr(
        worker, "_process_items_v3",
        lambda *a, **kw: v3_calls.append(("v3", a, kw)),
    )
    monkeypatch.setattr(worker, "_today_spend", lambda conn: 0.0)
    monkeypatch.setattr(worker, "_make_client", lambda: None)

    worker.run_once(stage="items", limit=10, notes="test_v2_dispatch")
    assert len(v2_calls) == 1
    assert len(v3_calls) == 0


def test_run_once_dispatch_preserves_meeting_path(monkeypatch):
    """Flag only affects 'items' stage. 'meetings' always uses v2 path."""
    from docket.ai import worker

    meetings_calls = []
    monkeypatch.setattr(worker, "IMPACT_FIRST_ENABLED", True)
    monkeypatch.setattr(
        worker, "_process_meetings",
        lambda *a, **kw: meetings_calls.append(("m", a, kw)),
    )
    monkeypatch.setattr(worker, "_today_spend", lambda conn: 0.0)
    monkeypatch.setattr(worker, "_make_client", lambda: None)

    worker.run_once(stage="meetings", limit=5, notes="test_meeting_passthrough")
    assert len(meetings_calls) == 1


def test_run_once_v3_dispatch_does_not_construct_ai_client(monkeypatch):
    """v3 path doesn't need an AIClient (extract/rewrite create their
    own anthropic_client at module level). Confirm _make_client is
    NOT invoked when v3 is chosen."""
    from docket.ai import worker

    client_factory_calls = []
    monkeypatch.setattr(worker, "IMPACT_FIRST_ENABLED", True)
    monkeypatch.setattr(
        worker, "_make_client",
        lambda: client_factory_calls.append("called") or None,
    )
    monkeypatch.setattr(worker, "_today_spend", lambda conn: 0.0)
    monkeypatch.setattr(worker, "_process_items_v3", lambda *a, **kw: None)
    monkeypatch.setattr(worker, "_process_meetings", lambda *a, **kw: None)

    worker.run_once(stage="items", limit=10, notes="test_v3_no_client")
    # Optional: this assertion documents the design choice. If the
    # implementer prefers to always construct the client (for
    # consistency with v2), flip to assert len(client_factory_calls)==1.
    assert client_factory_calls == [], (
        "v3 path should not construct AIClient (extract/rewrite have "
        "their own module-level clients)"
    )
