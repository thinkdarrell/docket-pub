"""The ``search_submit`` analytics event must fire after the deferred scripts.

``base.html`` loads the Umami script and ``track.js`` with ``defer``. An inline
``<script>`` in the body runs during parsing, before any deferred script has
executed, so an emit written as a top-level call finds no ``docketTrack`` and
silently returns. Deferred scripts finish before ``DOMContentLoaded`` fires,
so the emit has to be registered there. Found 2026-11-11: the event had zero
rows in ``v_event_counts_daily`` across six months of real search traffic.
"""

from __future__ import annotations

import re


def _search_submit_script(html: str) -> str | None:
    """Return the inline script that emits ``search_submit``, or None."""
    for m in re.finditer(r"<script>(.*?)</script>", html, re.S):
        if "search_submit" in m.group(1):
            return m.group(1)
    return None


def test_emit_is_deferred_to_domcontentloaded(client):
    r = client.get("/search?q=zoning")
    assert r.status_code == 200
    script = _search_submit_script(r.data.decode())
    assert script is not None, "no search_submit script on the first results page"
    assert "docketTrack('search_submit'" in script
    # The call must be inside a function handed to DOMContentLoaded, never a
    # bare top-level invocation that runs before track.js has executed.
    assert "addEventListener('DOMContentLoaded', emit)" in script
    assert "document.readyState === 'loading'" in script


def test_emit_absent_on_later_pages(client):
    for url in ("/search?q=zoning&page=2", "/search?q=zoning&tpage=2"):
        r = client.get(url)
        assert r.status_code == 200
        assert _search_submit_script(r.data.decode()) is None, url


def test_emit_absent_without_query(client):
    r = client.get("/search")
    assert r.status_code == 200
    assert _search_submit_script(r.data.decode()) is None
