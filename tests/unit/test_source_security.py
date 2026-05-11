"""Unit tests for ``docket.web.source_security``.

Covers the URL safety helper that gates the source-anchor button
(spec §6.4). Two surfaces:

* ``is_url_safe(url, allowed_domains)`` — pure function used by the
  Jinja global. Static + dynamic concerns are exercised against a
  fixed allowlist.
* ``load_municipality_hosts(db_cursor_fn)`` /
  ``build_allowlist(db_cursor_fn)`` — DB-loading helpers. Tested with
  a fake cursor that mimics ``docket.db.db_cursor`` enough to avoid
  needing a live PostgreSQL.

No network, no DB, no Flask app — pure unit coverage.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from docket.web import source_security
from docket.web.source_security import (
    STATIC_ALLOWED_DOMAINS,
    build_allowlist,
    is_url_safe,
    load_municipality_hosts,
)


# ---------------------------------------------------------------------------
# Static allowlist behavior — exercised through is_url_safe with the
# production STATIC_ALLOWED_DOMAINS frozenset.
# ---------------------------------------------------------------------------


class TestStaticAllowlistAcceptance:
    def test_static_allowlist_accepts_granicus(self):
        assert is_url_safe(
            "https://granicus.com/whatever", STATIC_ALLOWED_DOMAINS
        )

    def test_static_allowlist_accepts_youtube(self):
        assert is_url_safe(
            "https://www.youtube.com/watch?v=abc", STATIC_ALLOWED_DOMAINS
        )

    def test_static_allowlist_accepts_youtu_be(self):
        assert is_url_safe(
            "https://youtu.be/abcdef", STATIC_ALLOWED_DOMAINS
        )

    def test_static_allowlist_accepts_subdomain(self):
        """``bhamal.granicus.com`` matches ``granicus.com`` via leading-
        dot suffix match — that's the whole point of suffix matching,
        we don't want a per-tenant entry per Granicus city."""
        assert is_url_safe(
            "https://bhamal.granicus.com/MediaPlayer.php?clip_id=42",
            STATIC_ALLOWED_DOMAINS,
        )


class TestStaticAllowlistRejection:
    def test_static_allowlist_rejects_unknown_domain(self):
        assert not is_url_safe(
            "https://evil.tld/x", STATIC_ALLOWED_DOMAINS
        )

    def test_static_allowlist_rejects_subdomain_attack(self):
        """Classic anchor-without-leading-dot bypass: ``granicus.com.evil.tld``
        ends with ``granicus.com`` but is not a granicus.com subdomain."""
        assert not is_url_safe(
            "https://granicus.com.evil.tld/x", STATIC_ALLOWED_DOMAINS
        )

    def test_static_allowlist_rejects_protocol_relative(self):
        """``//evil.tld/x`` parses with empty scheme — must be rejected."""
        assert not is_url_safe(
            "//evil.tld/x", STATIC_ALLOWED_DOMAINS
        )

    def test_static_allowlist_rejects_javascript_scheme(self):
        assert not is_url_safe(
            "javascript:alert(1)", STATIC_ALLOWED_DOMAINS
        )

    def test_static_allowlist_rejects_data_scheme(self):
        assert not is_url_safe(
            "data:text/html,<script>alert(1)</script>",
            STATIC_ALLOWED_DOMAINS,
        )

    def test_static_allowlist_rejects_file_scheme(self):
        assert not is_url_safe(
            "file:///etc/passwd", STATIC_ALLOWED_DOMAINS
        )

    @pytest.mark.parametrize("bad", [None, 42, [], {}, object()])
    def test_static_allowlist_rejects_non_string(self, bad):
        """Defensive: anything that isn't a str is False, no traceback."""
        assert not is_url_safe(bad, STATIC_ALLOWED_DOMAINS)

    def test_static_allowlist_rejects_empty_string(self):
        assert not is_url_safe("", STATIC_ALLOWED_DOMAINS)

    def test_static_allowlist_rejects_url_with_no_host(self):
        """``http:///path`` parses but has empty netloc — reject."""
        assert not is_url_safe("http:///path", STATIC_ALLOWED_DOMAINS)


class TestStaticAllowlistNormalization:
    def test_static_allowlist_strips_whitespace(self):
        assert is_url_safe(
            "  https://granicus.com/x  ", STATIC_ALLOWED_DOMAINS
        )

    def test_static_allowlist_normalizes_case(self):
        """DNS is case-insensitive; ``HTTPS://Granicus.Com`` should match."""
        assert is_url_safe(
            "HTTPS://Granicus.Com/path", STATIC_ALLOWED_DOMAINS
        )

    def test_static_allowlist_strips_port(self):
        """Host match should ignore port — ``granicus.com:8080`` is
        still ``granicus.com`` for allowlist purposes."""
        assert is_url_safe(
            "https://granicus.com:8080/x", STATIC_ALLOWED_DOMAINS
        )

    def test_static_allowlist_strips_userinfo(self):
        """``user:pass@host`` — host extraction must drop the userinfo."""
        assert is_url_safe(
            "https://user:pass@granicus.com/path",
            STATIC_ALLOWED_DOMAINS,
        )

    def test_static_allowlist_strips_userinfo_and_port(self):
        """Combined: ``user@host:port``."""
        assert is_url_safe(
            "https://user:pass@granicus.com:8080/path",
            STATIC_ALLOWED_DOMAINS,
        )


# ---------------------------------------------------------------------------
# Dynamic allowlist — load_municipality_hosts with a fake cursor
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Minimal cursor mimic that supports ``.execute`` / ``.fetchall``
    and is usable as a context manager via ``_FakeCursorFactory``."""

    def __init__(self, rows):
        self._rows = rows
        self.last_query: str | None = None

    def execute(self, query, params=None):
        self.last_query = query

    def fetchall(self):
        return list(self._rows)


def _make_cursor_fn(rows):
    """Return a ``db_cursor_fn`` replacement yielding a ``_FakeCursor``."""

    @contextmanager
    def _fn():
        yield _FakeCursor(rows)

    return _fn


class TestDynamicAllowlist:
    def test_dynamic_allowlist_extracts_municipality_hosts(self):
        rows = [
            {"url": "https://bhamal.granicus.com"},
            {"url": "https://vestaviahillsal.api.civicclerk.com"},
        ]
        hosts = load_municipality_hosts(_make_cursor_fn(rows))
        assert "bhamal.granicus.com" in hosts
        assert "vestaviahillsal.api.civicclerk.com" in hosts

    def test_dynamic_allowlist_skips_null_urls(self):
        """A row whose ``adapter_config->>'base_url'`` is None
        shouldn't poison the result."""
        rows = [
            {"url": None},
            {"url": "https://bhamal.granicus.com"},
        ]
        hosts = load_municipality_hosts(_make_cursor_fn(rows))
        assert hosts == frozenset({"bhamal.granicus.com"})

    def test_dynamic_allowlist_skips_malformed_urls(self):
        """A row whose URL doesn't have a host (or fails urlparse) is
        skipped silently — one bad config row doesn't break the
        whole allowlist."""
        rows = [
            {"url": "not-a-url-at-all"},
            {"url": "http:///"},  # parses, empty netloc
            {"url": "https://granicus.com"},
        ]
        hosts = load_municipality_hosts(_make_cursor_fn(rows))
        assert hosts == frozenset({"granicus.com"})

    def test_dynamic_allowlist_normalizes_case_and_port(self):
        rows = [
            {"url": "https://BhamAL.granicus.com:8443"},
        ]
        hosts = load_municipality_hosts(_make_cursor_fn(rows))
        assert hosts == frozenset({"bhamal.granicus.com"})

    def test_dynamic_allowlist_empty_when_no_rows(self):
        hosts = load_municipality_hosts(_make_cursor_fn([]))
        assert hosts == frozenset()


# ---------------------------------------------------------------------------
# build_allowlist — combines static + dynamic
# ---------------------------------------------------------------------------


class TestBuildAllowlist:
    def test_build_allowlist_combines_static_and_dynamic(self):
        rows = [
            {"url": "https://bhamal.granicus.com"},
            {"url": "https://homewoodal.gov"},
        ]
        merged = build_allowlist(_make_cursor_fn(rows))
        # Static set is a subset.
        assert STATIC_ALLOWED_DOMAINS <= merged
        # Dynamic hosts are present.
        assert "bhamal.granicus.com" in merged
        assert "homewoodal.gov" in merged

    def test_build_allowlist_returns_frozenset(self):
        merged = build_allowlist(_make_cursor_fn([]))
        assert isinstance(merged, frozenset)

    def test_build_allowlist_falls_back_safely_on_empty_dynamic(self):
        """No municipalities yet — merged set equals the static set."""
        merged = build_allowlist(_make_cursor_fn([]))
        assert merged == STATIC_ALLOWED_DOMAINS


# ---------------------------------------------------------------------------
# _normalize_host — internal helper, exposed for documentation parity
# ---------------------------------------------------------------------------


class TestNormalizeHost:
    """Light coverage of the internal ``_normalize_host`` helper. Most
    of its logic is also exercised through ``is_url_safe`` above; these
    tests pin the contract explicitly."""

    def test_lowercases(self):
        assert source_security._normalize_host("Granicus.Com") == "granicus.com"

    def test_strips_port(self):
        assert source_security._normalize_host("granicus.com:8080") == "granicus.com"

    def test_strips_userinfo(self):
        assert (
            source_security._normalize_host("user:pass@granicus.com")
            == "granicus.com"
        )

    def test_strips_userinfo_and_port(self):
        assert (
            source_security._normalize_host(
                "user:pass@granicus.com:8080"
            )
            == "granicus.com"
        )


# ---------------------------------------------------------------------------
# Allowlist TTL cache + admin refresh endpoint
# ---------------------------------------------------------------------------
#
# The cache is module-level state, so each test in this class has to
# clean up after itself via ``invalidate_cache()`` in setup_method.
# Otherwise an earlier test's primed cache would leak into the next test
# and we'd assert on stale state.


class TestAllowlistCache:
    def setup_method(self):
        source_security.invalidate_cache()

    def teardown_method(self):
        source_security.invalidate_cache()

    def _counting_cursor_fn(self, rows, counter):
        """Like ``_make_cursor_fn`` but increments ``counter[0]`` on each
        ``execute()`` so we can assert how many DB queries happened."""

        @contextmanager
        def _fn():
            counter[0] += 1
            yield _FakeCursor(rows)

        return _fn

    def test_first_call_hits_db_and_returns_merged_allowlist(self):
        """Cold cache → DB read → static + dynamic merged."""
        calls = [0]
        fn = self._counting_cursor_fn(
            [{"url": "https://newcity.example.gov"}], calls
        )
        result = source_security.get_allowlist(fn)
        assert calls[0] == 1
        assert "newcity.example.gov" in result
        # Static set is still present — the cache holds the merged set.
        assert STATIC_ALLOWED_DOMAINS <= result

    def test_second_call_within_ttl_returns_cached_value(self):
        """Warm cache → no DB query."""
        calls = [0]
        fn = self._counting_cursor_fn(
            [{"url": "https://newcity.example.gov"}], calls
        )
        first = source_security.get_allowlist(fn)
        second = source_security.get_allowlist(fn)
        assert calls[0] == 1  # only the first call hit the DB
        assert first is second  # same frozenset object — cached, not rebuilt

    def test_invalidate_cache_forces_next_call_to_refresh(self):
        """Admin refresh endpoint contract: invalidate clears the cache,
        the very next ``get_allowlist`` re-runs the DB query."""
        calls = [0]
        fn = self._counting_cursor_fn(
            [{"url": "https://newcity.example.gov"}], calls
        )
        source_security.get_allowlist(fn)
        source_security.invalidate_cache()
        source_security.get_allowlist(fn)
        assert calls[0] == 2

    def test_db_failure_falls_back_to_static_allowlist(self):
        """If the DB raises, return the static set rather than an empty
        allowlist — better to render every link via the static set than
        to silently suppress every source-anchor button."""

        @contextmanager
        def _failing_fn():
            raise RuntimeError("DB down")
            yield  # unreachable, but keeps the contextmanager shape

        result = source_security.get_allowlist(_failing_fn)
        assert result == STATIC_ALLOWED_DOMAINS

    def test_db_failure_caches_static_fallback_for_ttl(self):
        """A failed DB read still populates the cache (with the static
        fallback), so we don't slam the DB with retry traffic when it's
        already down. The next refresh cycle / admin invalidate retries."""
        calls = [0]

        @contextmanager
        def _failing_fn():
            calls[0] += 1
            raise RuntimeError("DB down")
            yield  # unreachable

        source_security.get_allowlist(_failing_fn)
        source_security.get_allowlist(_failing_fn)
        assert calls[0] == 1  # second call served from cache

    def test_is_url_safe_uses_cached_allowlist_when_no_arg_given(self):
        """When ``allowed_domains`` is omitted, ``is_url_safe`` consults
        the cache — that's the production code path the Jinja global
        flows through."""
        # Prime the cache with a fake municipality.
        fn = _make_cursor_fn([{"url": "https://newcity.example.gov"}])
        source_security.get_allowlist(fn)
        # No second arg → use cache → newcity should be allowed.
        assert source_security.is_url_safe("https://newcity.example.gov/page")
        # Static domain still works through the cache.
        assert source_security.is_url_safe("https://granicus.com/x")
        # Unknown domain still rejected.
        assert not source_security.is_url_safe("https://evil.tld/x")

    def test_is_url_safe_arity_2_form_is_unchanged(self):
        """Existing callers that pass an explicit allowlist (tests, the
        production Jinja registration of older code) keep working — the
        explicit second arg overrides the cache."""
        explicit = frozenset({"explicit.example"})
        # The cache is empty / would fall back to STATIC, but the
        # explicit arg takes precedence — granicus.com (in STATIC) should
        # NOT pass when the explicit set is the tight one.
        assert not source_security.is_url_safe(
            "https://granicus.com/x", explicit
        )
        assert source_security.is_url_safe(
            "https://explicit.example/x", explicit
        )


class TestRefreshSourceSecurityRoute:
    """End-to-end check on the admin endpoint that invalidates the cache.

    Uses ``create_app()`` directly (not the lighter test-only Flask app
    other partial tests build) because the endpoint lives on the real
    admin blueprint and we want the auth gate exercised."""

    def setup_method(self):
        source_security.invalidate_cache()

    def teardown_method(self):
        source_security.invalidate_cache()

    def _make_app(self):
        from docket.web import create_app

        app = create_app()
        app.config["SECRET_KEY"] = "test-only"
        return app

    def test_post_invalidates_cache(self):
        """Authenticated POST clears ``_CACHE``."""
        app = self._make_app()
        # Prime the cache with a fake DB read so we have something to clear.
        fn = _make_cursor_fn([{"url": "https://newcity.example.gov"}])
        source_security.get_allowlist(fn)
        assert source_security._CACHE is not None

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["admin_user"] = "tester"
            resp = client.post("/admin/source-security/refresh")
        assert resp.status_code == 200
        assert source_security._CACHE is None

    def test_get_returns_405(self):
        """GET is rejected — the endpoint is POST-only so it can't be
        triggered by accidental browser prefetches."""
        app = self._make_app()
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["admin_user"] = "tester"
            resp = client.get("/admin/source-security/refresh")
        assert resp.status_code == 405

    def test_unauthed_post_redirects_to_login(self):
        """No session → blueprint ``before_request`` redirects to the
        auth login page (same as every other admin route)."""
        app = self._make_app()
        with app.test_client() as client:
            resp = client.post("/admin/source-security/refresh")
        assert resp.status_code in (302, 303)
        assert "/admin/login" in resp.headers.get("Location", "")
