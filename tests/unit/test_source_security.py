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
