"""The blog's posts when the database does not answer as the process starts.

Plan `source-links-and-blog-survive-a-slow-db`, M3. `create_app` reads the
posts once; when that read fails the process starts with an empty blog, says
so in the log at error level, and a later request to a blog address reads
them again, at most once per ``BLOG_RETRY_SECONDS`` and one thread at a time.

Every test builds its own application over a content root in ``tmp_path``
that holds one post with no shortcode and no related id, so the only
database call of a load is ``docket.services.query.list_municipalities()``
and nothing here depends on the posts under ``content/blog/``. Names that
``docket.web.blog`` gains in M3 are imported inside the tests.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from pathlib import Path

import psycopg2
import pytest

from docket.web import create_app

BLOG_LOGGER = "docket.web.blog"
POST_FILE = "2026-01-05-still-here.md"
LINK = 'href="/blog/still-here"'
LIST_MUNICIPALITIES = "docket.services.query.list_municipalities"

_POST_WITH_TITLE = (
    "---\n"
    "title: Still here\n"
    "date: 2026-01-05\n"
    "summary: A post the tests load.\n"
    "---\n"
    "Body with no shortcode.\n"
)
_POST_WITHOUT_TITLE = (
    "---\n"
    "date: 2026-01-05\n"
    "summary: A post the tests load.\n"
    "---\n"
    "Body with no shortcode.\n"
)


@pytest.fixture
def content_root(tmp_path: Path, monkeypatch, caplog) -> Path:
    """A content root with one post, named to ``create_app`` in place of the tree's."""
    root = tmp_path / "content"
    (root / "_shared").mkdir(parents=True)
    (root / "_shared" / POST_FILE).write_text(_POST_WITH_TITLE)
    authors = tmp_path / "authors.yaml"
    authors.write_text("darrell:\n  display_name: Darrell\n")
    monkeypatch.setattr("docket.web.BLOG_CONTENT_ROOT", str(root))
    monkeypatch.setattr("docket.web.BLOG_AUTHORS_YAML", str(authors))
    caplog.set_level(logging.DEBUG, logger=BLOG_LOGGER)
    return root


class _DatabaseDown:
    """Stands in for ``list_municipalities``: counts its calls and raises the driver's error."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise psycopg2.OperationalError("timeout expired")


class _Counting:
    """Wraps the real ``list_municipalities`` and counts its calls."""

    def __init__(self, real) -> None:
        self.calls = 0
        self._real = real

    def __call__(self):
        self.calls += 1
        return self._real()


def _records(caplog, level: int) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == BLOG_LOGGER and r.levelno == level]


def _hub(app) -> tuple[int, str]:
    resp = app.test_client().get("/blog")
    return resp.status_code, resp.get_data(as_text=True)


def _start_without_the_database(monkeypatch):
    """Build an application while ``list_municipalities`` raises.

    Returns the application, the failing stand-in and the real function.
    """
    from docket.services import query

    real = query.list_municipalities
    down = _DatabaseDown()
    monkeypatch.setattr(LIST_MUNICIPALITIES, down)
    return create_app(), down, real


def test_a_start_without_the_database_is_logged_and_the_blog_is_empty(
    content_root, monkeypatch, caplog
):
    app, down, _real = _start_without_the_database(monkeypatch)

    errors = _records(caplog, logging.ERROR)
    assert len(errors) == 1
    message = errors[0].getMessage()
    assert message.startswith("blog:")
    assert "posts not loaded when the process started" in message
    assert "OperationalError" in message
    assert "timeout expired" in message
    assert "next try in 30 s" in message
    assert "\n" not in message
    assert errors[0].exc_info

    assert app.config["BLOG_STATE"].posts == []
    status, html = _hub(app)
    assert status == 200
    assert LINK not in html
    assert down.calls == 1


def test_the_posts_return_on_a_later_request_once_the_database_answers(
    content_root, monkeypatch, caplog
):
    app, _down, real = _start_without_the_database(monkeypatch)
    monkeypatch.setattr(LIST_MUNICIPALITIES, real)
    app.config["BLOG_STATE_PENDING"].next_try = 0.0

    status, html = _hub(app)
    assert status == 200
    assert LINK in html
    assert app.config.get("BLOG_STATE_PENDING") is None
    warnings = [
        r.getMessage() for r in _records(caplog, logging.WARNING)
        if "posts loaded" in r.getMessage()
    ]
    assert warnings == ["blog: posts loaded on a later request (1 posts)"]
    assert app.test_client().get("/blog/still-here").status_code == 200


def test_a_request_before_the_retry_interval_does_not_load_again(
    content_root, monkeypatch
):
    from docket.web.blog import BLOG_RETRY_SECONDS

    app, down, _real = _start_without_the_database(monkeypatch)
    pending = app.config["BLOG_STATE_PENDING"]
    assert 0 < pending.next_try - time.monotonic() <= BLOG_RETRY_SECONDS

    assert _hub(app)[0] == 200
    assert _hub(app)[0] == 200
    assert down.calls == 1


def test_a_retry_that_fails_is_logged_and_waits_the_interval_again(
    content_root, monkeypatch, caplog
):
    from docket.web.blog import BLOG_RETRY_SECONDS

    app, down, _real = _start_without_the_database(monkeypatch)
    pending = app.config["BLOG_STATE_PENDING"]
    pending.next_try = 0.0

    status, html = _hub(app)
    assert status == 200
    assert LINK not in html
    assert down.calls == 2

    errors = _records(caplog, logging.ERROR)
    assert len(errors) == 2
    message = errors[1].getMessage()
    assert message.startswith("blog: posts not loaded on a later request")
    assert "OperationalError" in message
    assert "timeout expired" in message
    assert "next try in 30 s" in message
    assert "\n" not in message
    # The same type of error as the start raised: one line, no traceback.
    assert not errors[1].exc_info

    assert app.config["BLOG_STATE_PENDING"] is pending
    assert BLOG_RETRY_SECONDS - 5 < pending.next_try - time.monotonic() <= BLOG_RETRY_SECONDS
    assert _hub(app)[0] == 200
    assert down.calls == 2


def test_a_retry_that_fails_with_a_different_error_is_logged_with_its_traceback(
    content_root, monkeypatch, caplog
):
    app, _down, real = _start_without_the_database(monkeypatch)
    monkeypatch.setattr(LIST_MUNICIPALITIES, real)
    (content_root / "_shared" / POST_FILE).write_text(_POST_WITHOUT_TITLE)
    pending = app.config["BLOG_STATE_PENDING"]
    pending.next_try = 0.0

    status, html = _hub(app)
    assert status == 200
    assert LINK not in html

    later = [
        r for r in _records(caplog, logging.ERROR)
        if "on a later request" in r.getMessage()
    ]
    assert len(later) == 1
    assert "LoaderError" in later[0].getMessage()
    assert later[0].exc_info

    # The same error a second time is one line again.
    pending.next_try = 0.0
    assert _hub(app)[0] == 200
    later = [
        r for r in _records(caplog, logging.ERROR)
        if "on a later request" in r.getMessage()
    ]
    assert len(later) == 2
    assert not later[1].exc_info


def test_an_error_that_is_not_the_databases_is_logged_and_bounded_the_same_way(
    content_root, monkeypatch, caplog
):
    from docket.services import query

    (content_root / "_shared" / POST_FILE).write_text(_POST_WITHOUT_TITLE)
    counting = _Counting(query.list_municipalities)
    monkeypatch.setattr(LIST_MUNICIPALITIES, counting)

    app = create_app()

    errors = _records(caplog, logging.ERROR)
    assert len(errors) == 1
    message = errors[0].getMessage()
    assert message.startswith("blog: posts not loaded when the process started")
    assert "LoaderError" in message
    assert POST_FILE in message

    assert LINK not in _hub(app)[1]
    assert LINK not in _hub(app)[1]
    assert counting.calls == 1

    (content_root / "_shared" / POST_FILE).write_text(_POST_WITH_TITLE)
    app.config["BLOG_STATE_PENDING"].next_try = 0.0
    status, html = _hub(app)
    assert status == 200
    assert LINK in html
    assert counting.calls == 2


def test_a_start_with_the_database_leaves_nothing_pending(
    content_root, monkeypatch, caplog
):
    from docket.services import query

    counting = _Counting(query.list_municipalities)
    monkeypatch.setattr(LIST_MUNICIPALITIES, counting)

    app = create_app()

    assert app.config.get("BLOG_STATE_PENDING") is None
    assert LINK in _hub(app)[1]
    assert LINK in _hub(app)[1]
    assert counting.calls == 1
    assert _records(caplog, logging.ERROR) == []


def test_the_asset_route_is_served_while_the_posts_are_pending(
    content_root, monkeypatch
):
    app, down, _real = _start_without_the_database(monkeypatch)
    asset_dir = content_root / "_shared" / "still-here"
    asset_dir.mkdir()
    (asset_dir / "cover.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    address = "/blog/assets/_shared/still-here/cover.svg"

    resp = app.test_client().get(address)
    assert resp.status_code == 200
    resp.close()

    pending = app.config["BLOG_STATE_PENDING"]
    pending.next_try = 0.0
    resp = app.test_client().get(address)
    assert resp.status_code == 200
    resp.close()
    # An asset request never repeats the load.
    assert down.calls == 1
    assert app.config["BLOG_STATE_PENDING"] is pending


def test_only_one_thread_loads_again_and_the_others_do_not_wait(
    content_root, monkeypatch, caplog
):
    app, _down, real = _start_without_the_database(monkeypatch)
    started = threading.Event()
    release = threading.Event()
    calls = []

    def answers_late():
        calls.append(1)
        started.set()
        # At most 3 seconds, so a tree where requests wait fails and does not hang.
        release.wait(3)
        return real()

    monkeypatch.setattr(LIST_MUNICIPALITIES, answers_late)
    app.config["BLOG_STATE_PENDING"].next_try = 0.0

    answered = {}

    def first_request():
        answered["hub"] = _hub(app)

    thread = threading.Thread(target=first_request)
    thread.start()
    try:
        assert started.wait(3), "the first request did not repeat the load"
        before = time.monotonic()
        status, html = _hub(app)
        waited = time.monotonic() - before
        assert status == 200
        assert LINK not in html
        assert waited < 0.5
    finally:
        release.set()
        thread.join(10)

    assert not thread.is_alive()
    assert answered["hub"][0] == 200
    assert LINK in answered["hub"][1]
    assert len(calls) == 1
    loaded = [
        r for r in _records(caplog, logging.WARNING)
        if "posts loaded" in r.getMessage()
    ]
    assert len(loaded) == 1


def test_a_database_that_never_answers_at_start_then_answers(
    content_root, monkeypatch, caplog
):
    """The real driver against a local socket that accepts and never answers."""
    import docket.db

    real_address = docket.db.DATABASE_URL
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        port = listener.getsockname()[1]
        monkeypatch.setattr(
            "docket.db.DATABASE_URL", f"postgresql://u:p@127.0.0.1:{port}/x"
        )
        monkeypatch.setenv("PGCONNECT_TIMEOUT", "2")

        before = time.monotonic()
        app = create_app()
        took = time.monotonic() - before

        assert 1 < took < 8
        assert app.config["BLOG_STATE"].posts == []
        errors = _records(caplog, logging.ERROR)
        assert len(errors) == 1
        message = errors[0].getMessage()
        assert message.startswith("blog: posts not loaded when the process started")
        assert "OperationalError" in message
        assert "timeout expired" in message
        assert "\n" not in message

        monkeypatch.setattr("docket.db.DATABASE_URL", real_address)
        app.config["BLOG_STATE_PENDING"].next_try = 0.0
        status, html = _hub(app)
        assert status == 200
        assert LINK in html
