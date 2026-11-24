"""Unit tests for ``docket.web.source_security``.

Covers the URL safety helper that gates the source-anchor button
(spec §6.4). Two surfaces:

* ``is_url_safe(url, allowed_domains)`` — pure function used by the
  Jinja global. Static + dynamic concerns are exercised against a
  fixed allowlist.
* ``load_municipality_hosts(urls_fn)`` /
  ``build_allowlist(urls_fn)`` — helpers that read the stored base
  addresses. Tested with a plain function standing in for
  ``docket.services.query.list_active_base_urls``, so no live
  PostgreSQL is needed.

No network, no DB, no Flask app — pure unit coverage.
"""

from __future__ import annotations

import logging
import socket
import threading
import time

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
# Dynamic allowlist — load_municipality_hosts with an injected function
# ---------------------------------------------------------------------------


def _make_urls_fn(urls):
    """Return a ``urls_fn`` replacement: a function returning the list it
    was given, as ``docket.services.query.list_active_base_urls`` returns
    the stored values."""

    def _fn():
        return list(urls)

    return _fn


class TestDynamicAllowlist:
    def test_dynamic_allowlist_extracts_municipality_hosts(self):
        rows = [
            "https://bhamal.granicus.com",
            "https://vestaviahillsal.api.civicclerk.com",
        ]
        hosts = load_municipality_hosts(_make_urls_fn(rows))
        assert "bhamal.granicus.com" in hosts
        assert "vestaviahillsal.api.civicclerk.com" in hosts

    def test_dynamic_allowlist_skips_null_urls(self):
        """A row whose ``adapter_config->>'base_url'`` is None
        shouldn't poison the result."""
        rows = [
            None,
            "https://bhamal.granicus.com",
        ]
        hosts = load_municipality_hosts(_make_urls_fn(rows))
        assert hosts == frozenset({"bhamal.granicus.com"})

    def test_dynamic_allowlist_skips_malformed_urls(self):
        """A row whose URL doesn't have a host (or fails urlparse) is
        skipped silently — one bad config row doesn't break the
        whole allowlist."""
        rows = [
            "not-a-url-at-all",
            "http:///",  # parses, empty netloc
            "https://granicus.com",
        ]
        hosts = load_municipality_hosts(_make_urls_fn(rows))
        assert hosts == frozenset({"granicus.com"})

    def test_dynamic_allowlist_normalizes_case_and_port(self):
        rows = [
            "https://BhamAL.granicus.com:8443",
        ]
        hosts = load_municipality_hosts(_make_urls_fn(rows))
        assert hosts == frozenset({"bhamal.granicus.com"})

    def test_dynamic_allowlist_empty_when_no_rows(self):
        hosts = load_municipality_hosts(_make_urls_fn([]))
        assert hosts == frozenset()


# ---------------------------------------------------------------------------
# build_allowlist — combines static + dynamic
# ---------------------------------------------------------------------------


class TestBuildAllowlist:
    def test_build_allowlist_combines_static_and_dynamic(self):
        rows = [
            "https://bhamal.granicus.com",
            "https://homewoodal.gov",
        ]
        merged = build_allowlist(_make_urls_fn(rows))
        # Static set is a subset.
        assert STATIC_ALLOWED_DOMAINS <= merged
        # Dynamic hosts are present.
        assert "bhamal.granicus.com" in merged
        assert "homewoodal.gov" in merged

    def test_build_allowlist_returns_frozenset(self):
        merged = build_allowlist(_make_urls_fn([]))
        assert isinstance(merged, frozenset)

    def test_build_allowlist_falls_back_safely_on_empty_dynamic(self):
        """No municipalities yet — merged set equals the static set."""
        merged = build_allowlist(_make_urls_fn([]))
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
# clean up after itself via ``forget_allowlist()`` in setup_method (the
# full reset: ``invalidate_cache()`` keeps the last list that loaded).
# Otherwise an earlier test's primed cache would leak into the next test
# and we'd assert on stale state.


class TestAllowlistCache:
    def setup_method(self):
        source_security.forget_allowlist()

    def teardown_method(self):
        source_security.forget_allowlist()

    def _counting_cursor_fn(self, urls, counter):
        """Like ``_make_urls_fn`` but increments ``counter[0]`` on each
        call of the function so we can assert how many DB reads happened."""

        def _fn():
            counter[0] += 1
            return list(urls)

        return _fn

    def test_first_call_hits_db_and_returns_merged_allowlist(self):
        """Cold cache → DB read → static + dynamic merged."""
        calls = [0]
        fn = self._counting_cursor_fn(
            ["https://newcity.example.gov"], calls
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
            ["https://newcity.example.gov"], calls
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
            ["https://newcity.example.gov"], calls
        )
        source_security.get_allowlist(fn)
        source_security.invalidate_cache()
        source_security.get_allowlist(fn)
        assert calls[0] == 2

    def test_db_failure_falls_back_to_static_allowlist(self):
        """If the DB raises, return the static set rather than an empty
        allowlist — better to render every link via the static set than
        to silently suppress every source-anchor button."""

        def _failing_fn():
            raise RuntimeError("DB down")

        result = source_security.get_allowlist(_failing_fn)
        assert result == STATIC_ALLOWED_DOMAINS

    def test_db_failure_is_not_asked_again_at_once(self):
        """A failed DB read still populates the cache (with what is
        served in its place), so we don't slam the DB with retry traffic
        when it's already down. The query is asked again once the retry
        interval (``_RETRY_SECONDS``, 30) has passed, or at once after an
        admin invalidate."""
        calls = [0]

        def _failing_fn():
            calls[0] += 1
            raise RuntimeError("DB down")

        source_security.get_allowlist(_failing_fn)
        source_security.get_allowlist(_failing_fn)
        assert calls[0] == 1  # second call served from cache

    def test_is_url_safe_uses_cached_allowlist_when_no_arg_given(self):
        """When ``allowed_domains`` is omitted, ``is_url_safe`` consults
        the cache — that's the production code path the Jinja global
        flows through."""
        # Prime the cache with a fake municipality.
        fn = _make_urls_fn(["https://newcity.example.gov"])
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
        source_security.forget_allowlist()

    def teardown_method(self):
        source_security.forget_allowlist()

    def _make_app(self):
        from docket.web import create_app

        app = create_app()
        app.config["SECRET_KEY"] = "test-only"
        return app

    def test_post_invalidates_cache(self):
        """Authenticated POST clears ``_CACHE``."""
        app = self._make_app()
        # Prime the cache with a fake DB read so we have something to clear.
        fn = _make_urls_fn(["https://newcity.example.gov"])
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


# ---------------------------------------------------------------------------
# When the allowlist's query fails (plan
# `source-links-and-blog-survive-a-slow-db`, M2): the error is logged, the
# last list the database gave is kept, and the query is asked again after
# ``_RETRY_SECONDS``. A list is made to expire by rewriting the pair in
# ``_CACHE``; no test patches the clock.
# ---------------------------------------------------------------------------

_LOGGER = "docket.web.source_security"
_A = "https://newcity.example.gov"
_B = "https://othercity.example.org"


def _failing_fn():
    raise RuntimeError("DB down")


def _expire():
    """Make the list being served due for a re-read."""
    source_security._CACHE = (0.0, source_security._CACHE[1])


def _records(caplog):
    return [r for r in caplog.records if r.name == _LOGGER]


class TestAllowlistWhenTheQueryFails:
    def setup_method(self):
        source_security.forget_allowlist()

    def teardown_method(self):
        source_security.forget_allowlist()

    def test_a_failed_query_keeps_the_list_that_had_loaded(self):
        source_security.get_allowlist(_make_urls_fn([_A]))
        _expire()
        result = source_security.get_allowlist(_failing_fn)
        assert "newcity.example.gov" in result
        assert source_security.is_url_safe("https://newcity.example.gov/page")

    def test_a_failed_query_is_logged_with_the_error_it_raised(self, caplog):
        source_security.get_allowlist(_make_urls_fn([_A]))
        _expire()
        with caplog.at_level(logging.DEBUG, logger=_LOGGER):
            source_security.get_allowlist(_failing_fn)
        records = _records(caplog)
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.WARNING
        message = record.getMessage()
        assert message.startswith("source allowlist:")
        assert "RuntimeError" in message
        assert "DB down" in message
        assert "last list" in message
        assert "next try in 30 s" in message
        assert "\n" not in message

    def test_a_failed_query_with_no_list_loaded_serves_the_fixed_domains_and_logs_an_error(
        self, caplog
    ):
        with caplog.at_level(logging.DEBUG, logger=_LOGGER):
            result = source_security.get_allowlist(_failing_fn)
        assert result == STATIC_ALLOWED_DOMAINS
        records = _records(caplog)
        assert len(records) == 1
        assert records[0].levelno == logging.ERROR
        message = records[0].getMessage()
        assert message.startswith("source allowlist:")
        assert "RuntimeError" in message
        assert "no list has loaded" in message

    def test_a_failed_query_is_asked_again_after_the_retry_interval_and_not_before(self):
        calls = [0]

        def _counting_failing_fn():
            calls[0] += 1
            raise RuntimeError("DB down")

        source_security.get_allowlist(_counting_failing_fn)
        remaining = source_security._CACHE[0] - time.monotonic()
        assert 0 < remaining <= source_security._RETRY_SECONDS
        assert source_security._RETRY_SECONDS < source_security._CACHE_TTL_SECONDS
        source_security.get_allowlist(_counting_failing_fn)
        assert calls[0] == 1
        _expire()
        source_security.get_allowlist(_counting_failing_fn)
        assert calls[0] == 2

    def test_the_retry_interval_is_counted_from_the_end_of_the_failed_query(self):
        def _slow_failing_fn():
            time.sleep(0.3)
            raise RuntimeError("DB down")

        source_security.get_allowlist(_slow_failing_fn)
        t = time.monotonic()
        assert source_security._CACHE[0] - t > source_security._RETRY_SECONDS - 0.1

    def test_the_list_the_database_gives_again_replaces_the_kept_one(self, caplog):
        source_security.get_allowlist(_make_urls_fn([_A]))
        _expire()
        source_security.get_allowlist(_failing_fn)
        _expire()

        def _slow_working_fn():
            time.sleep(0.3)
            return [_B]

        with caplog.at_level(logging.DEBUG, logger=_LOGGER):
            result = source_security.get_allowlist(_slow_working_fn)
        t = time.monotonic()
        assert "othercity.example.org" in result
        assert "newcity.example.gov" not in result
        assert source_security._CACHE[0] - t > source_security._RETRY_SECONDS
        # The ten minutes too are counted from the end of the read.
        assert (
            source_security._CACHE[0] - t
            > source_security._CACHE_TTL_SECONDS - 0.1
        )
        recovered = [
            r for r in _records(caplog) if "answered again" in r.getMessage()
        ]
        assert len(recovered) == 1
        assert recovered[0].levelno == logging.WARNING
        assert recovered[0].getMessage().startswith("source allowlist:")

    def test_the_kept_list_is_the_last_one_loaded_and_no_wider(self):
        source_security.get_allowlist(_make_urls_fn([_A]))
        source_security.invalidate_cache()
        source_security.get_allowlist(_make_urls_fn([_B]))
        _expire()
        result = source_security.get_allowlist(_failing_fn)
        assert result == STATIC_ALLOWED_DOMAINS | {"othercity.example.org"}

    def test_invalidate_cache_keeps_the_last_list_for_a_reread_that_fails(self):
        calls = [0]

        def _counting_failing_fn():
            calls[0] += 1
            raise RuntimeError("DB down")

        source_security.get_allowlist(_make_urls_fn([_A]))
        source_security.invalidate_cache()
        result = source_security.get_allowlist(_counting_failing_fn)
        assert calls[0] == 1
        assert "newcity.example.gov" in result

    def test_forget_allowlist_drops_the_last_list(self, caplog):
        source_security.get_allowlist(_make_urls_fn([_A]))
        source_security.forget_allowlist()
        result = source_security.get_allowlist(_failing_fn)
        assert result == STATIC_ALLOWED_DOMAINS
        source_security.forget_allowlist()
        with caplog.at_level(logging.DEBUG, logger=_LOGGER):
            source_security.get_allowlist(_make_urls_fn([_A]))
        assert not [
            r for r in _records(caplog) if "answered again" in r.getMessage()
        ]

    def test_a_reread_that_follows_no_failure_logs_nothing(self, caplog):
        with caplog.at_level(logging.DEBUG, logger=_LOGGER):
            source_security.get_allowlist(_make_urls_fn([_A]))
            _expire()
            source_security.get_allowlist(_make_urls_fn([_B]))
            source_security.invalidate_cache()
            source_security.get_allowlist(_make_urls_fn([_B]))
        assert _records(caplog) == []

    def test_a_refresh_while_the_query_fails_does_not_hide_the_recovery_line(
        self, caplog
    ):
        source_security.get_allowlist(_make_urls_fn([_A]))
        _expire()
        source_security.get_allowlist(_failing_fn)
        source_security.invalidate_cache()
        with caplog.at_level(logging.DEBUG, logger=_LOGGER):
            source_security.get_allowlist(_make_urls_fn([_A]))
        recovered = [
            r for r in _records(caplog) if "answered again" in r.getMessage()
        ]
        assert len(recovered) == 1
        assert recovered[0].levelno == logging.WARNING

    def test_the_viewer_predicate_follows_the_kept_list(self):
        from docket.web.source_security import is_viewer_url

        source_security.get_allowlist(
            _make_urls_fn(["https://minutes.example.org"])
        )
        _expire()
        source_security.get_allowlist(_failing_fn)
        assert is_viewer_url("https://minutes.example.org/f.pdf")
        assert not is_viewer_url("https://other.example.org/f.pdf")

    def test_a_caller_with_a_list_does_not_wait_for_a_reread_in_flight(self):
        source_security.get_allowlist(_make_urls_fn([_A]))
        _expire()
        asking = threading.Event()
        release = threading.Event()

        def _blocking_fn():
            asking.set()
            release.wait(3)  # bounded, so a tree where callers wait fails
            return [_A]

        called = [0]

        def _must_not_be_called():
            called[0] += 1
            return [_A]

        thread = threading.Thread(
            target=source_security.get_allowlist, args=(_blocking_fn,)
        )
        thread.start()
        try:
            assert asking.wait(3)
            started = time.monotonic()
            result = source_security.get_allowlist(_must_not_be_called)
            elapsed = time.monotonic() - started
            # After a refresh the list in hand is the last one loaded,
            # and that caller does not wait either.
            source_security.invalidate_cache()
            started = time.monotonic()
            after_refresh = source_security.get_allowlist(_must_not_be_called)
            elapsed_after_refresh = time.monotonic() - started
        finally:
            release.set()
            thread.join(5)
        assert elapsed < 0.5
        assert elapsed_after_refresh < 0.5
        assert called[0] == 0
        assert "newcity.example.gov" in result
        assert "newcity.example.gov" in after_refresh

        # A caller with nothing to serve waits for the read in flight and
        # takes the list that read stored, asking nothing itself.
        source_security.forget_allowlist()
        asking.clear()
        release.clear()
        thread = threading.Thread(
            target=source_security.get_allowlist, args=(_blocking_fn,)
        )
        thread.start()
        try:
            assert asking.wait(3)
            threading.Timer(0.3, release.set).start()
            started = time.monotonic()
            result = source_security.get_allowlist(_must_not_be_called)
            elapsed = time.monotonic() - started
        finally:
            release.set()
            thread.join(5)
        assert elapsed > 0.2
        assert called[0] == 0
        assert "newcity.example.gov" in result

    def test_a_database_that_never_answers_is_logged_and_the_loaded_list_is_kept(
        self, monkeypatch, caplog
    ):
        """The real service function and the real driver, against a local
        socket that accepts a connection and never answers."""
        source_security.get_allowlist(_make_urls_fn([_A]))
        _expire()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen(8)  # never accepted
            port = s.getsockname()[1]
            monkeypatch.setattr(
                "docket.db.DATABASE_URL",
                f"postgresql://u:p@127.0.0.1:{port}/x",
            )
            monkeypatch.setenv("PGCONNECT_TIMEOUT", "2")
            with caplog.at_level(logging.DEBUG, logger=_LOGGER):
                started = time.monotonic()
                result = source_security.get_allowlist()
                elapsed = time.monotonic() - started
        assert 1 < elapsed < 8
        assert "newcity.example.gov" in result
        warnings = [
            r for r in _records(caplog) if r.levelno == logging.WARNING
        ]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "OperationalError" in message
        assert "timeout expired" in message
        assert "\n" not in message


# ---------------------------------------------------------------------------
# is_viewer_url: an address the minutes page viewer may fetch (plan
# `minutes-open-at-the-vote-page`, M3). Stricter than is_url_safe, because
# its yes lets the web process make a request and not only print a link.
# The predicate is imported inside each test so that this file still
# collects where the function does not exist.
# ---------------------------------------------------------------------------

_CIVICCLERK = frozenset({"civicclerk.com"})
_MOBILE_MINUTES = (
    "https://mobileal.api.civicclerk.com/v1/Meetings/"
    "GetMeetingFileStream(fileId=3854,plainText=false)"
)
_VIEWER_YES = [
    _MOBILE_MINUTES,
    _MOBILE_MINUTES + "#page=5",
    "HTTPS://MobileAL.api.civicclerk.com/x",
    "https://mobileal.api.civicclerk.com:443/x",
]
# Each passes is_url_safe and is refused by is_viewer_url.
_VIEWER_NO_THOUGH_SAFE = [
    "http://" + _MOBILE_MINUTES[len("https://"):],
    "https://user:pw@mobileal.api.civicclerk.com/x",
    "https://user@mobileal.api.civicclerk.com/x",
    "https://mobileal.api.civicclerk.com:8443/x",
    r"https://evil.example\@mobileal.api.civicclerk.com/x",
    r"https://mobileal.api.civicclerk.com/a\b.pdf",  # only the backslash rule refuses this one
    " " + _MOBILE_MINUTES,
    _MOBILE_MINUTES + "\n",
    "https://mobileal.api.civicclerk.com/a file.pdf",
    "https://mobileal.api.civicclerk.com/x\x7f",
    "https://mobileal.api.civicclerk.com:abc/x",
]


class TestViewerUrl:
    @pytest.mark.parametrize("url", _VIEWER_YES)
    def test_an_https_address_on_the_allowlist_is_a_viewer_address(self, url):
        from docket.web.source_security import is_viewer_url

        assert is_viewer_url(url, _CIVICCLERK) is True

    @pytest.mark.parametrize("url", _VIEWER_NO_THOUGH_SAFE)
    def test_an_address_the_allowlist_passes_can_still_be_refused(self, url):
        from docket.web.source_security import is_viewer_url

        assert is_url_safe(url, _CIVICCLERK)
        assert is_viewer_url(url, _CIVICCLERK) is False

    def test_an_address_outside_the_allowlist_is_not_a_viewer_address(self):
        from docket.web.source_security import is_viewer_url

        assert is_viewer_url("https://minutes.example.org/file.pdf", _CIVICCLERK) is False

    def test_the_allowlist_given_is_the_one_asked(self):
        from docket.web.source_security import is_viewer_url

        url = "https://minutes.example.org/file.pdf"
        assert is_viewer_url(url, frozenset({"example.org"})) is True
        assert is_viewer_url(_MOBILE_MINUTES, frozenset({"example.org"})) is False

    @pytest.mark.parametrize("bad", [None, 42, [], b"https://mobileal.api.civicclerk.com/x", ""])
    def test_what_is_not_an_address_is_not_a_viewer_address(self, bad):
        from docket.web.source_security import is_viewer_url

        assert is_viewer_url(bad, _CIVICCLERK) is False

    def test_a_port_that_cannot_be_read_is_a_no_and_does_not_raise(self):
        from docket.web.source_security import is_viewer_url

        assert is_viewer_url("https://mobileal.api.civicclerk.com:99999999/x", _CIVICCLERK) is False

    @pytest.mark.parametrize("url", _VIEWER_YES)
    def test_the_host_fetched_is_the_host_the_allowlist_judged(self, url):
        """`requests` connects to the host urllib3 reads; the service and the
        allowlist read the address with urllib.parse. They must agree on every
        address the predicate says yes to."""
        from urllib.parse import urlsplit

        from urllib3.util import parse_url

        from docket.web.source_security import is_viewer_url

        assert is_viewer_url(url, _CIVICCLERK) is True
        assert parse_url(url).host.lower() == urlsplit(url).hostname

    def test_the_allowlist_defaults_to_the_cached_one(self, monkeypatch):
        from docket.web.source_security import is_viewer_url

        monkeypatch.setattr(source_security, "get_allowlist", lambda: _CIVICCLERK)
        assert is_viewer_url(_MOBILE_MINUTES) is True
        monkeypatch.setattr(source_security, "get_allowlist", lambda: frozenset())
        assert is_viewer_url(_MOBILE_MINUTES) is False
