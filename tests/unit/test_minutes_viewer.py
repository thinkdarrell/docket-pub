"""Unit tests for ``docket.services.minutes_viewer``.

A page of a stored minutes address handed to a caller from a small
in-memory cache: one fetch for callers who ask for the same file at once,
a second between requests to one host, and a memory of failures that stops
repeats. No database and no network: the fetch is a counting fake, the
clock is a fake whose ``sleep`` advances it, and the fetched bytes are the
four-page committee minutes already in the fixtures.

The tests near the end start a real second thread. Every wait and every
``join`` in them carries a timeout, so a wrong implementation fails the
test and cannot hang the run.

The module is imported inside each test (through the ``mv`` fixture) so
that this file collects, and each test fails by itself, before the module
exists.

Plan `minutes-open-at-the-vote-page`, M2.
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
from pathlib import Path

import pytest

from docket.adapters.source_file import SourceFileError
from docket.analysis import pdf_page

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "committee_documents"
    / "ps_minutes_2026-09-22.pdf"
)
NOT_A_PDF = b"%PDF-1.4 not a pdf"
URL = "https://a.example/minutes.pdf"
JOIN_S = 5


class _Clock:
    def __init__(self):
        self.t = 100.0
        self.sleeps = []
        self.during_sleep = None

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        if self.during_sleep is not None:
            self.during_sleep()
        self.t += seconds


class _Fetch:
    """A fetch that counts. ``answers`` maps an address to bytes, or to an
    exception to raise; any other address gets the fixture."""

    def __init__(self, data):
        self.data = data
        self.calls = []
        self.answers = {}
        self.during = None

    def __call__(self, url):
        self.calls.append(url)
        if self.during is not None:
            self.during(url)
        answer = self.answers.get(url, self.data)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture(scope="module")
def fixture_pdf() -> bytes:
    return FIXTURE.read_bytes()


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def mv(monkeypatch, clock):
    module = importlib.import_module("docket.services.minutes_viewer")
    module.clear()
    monkeypatch.setattr(module, "_now", clock.now)
    monkeypatch.setattr(module, "_sleep", clock.sleep)
    yield module
    module.clear()


@pytest.fixture
def fetch(mv, monkeypatch, fixture_pdf):
    fake = _Fetch(fixture_pdf)
    monkeypatch.setattr(mv, "_fetch", fake)
    return fake


def _unavailable(mv, url, page=1):
    with pytest.raises(mv.Unavailable):
        mv.page_view(url, page)


# The constants, and what the module is.


def test_the_constants_are_the_plans(mv):
    assert mv.MAX_PAGE == 2000
    assert mv.CACHE_FILES == 4
    assert mv.CACHE_BYTES == 40 * 1024 * 1024
    assert mv.CACHE_TTL_S == 3600.0
    assert mv.FAILURE_TTL_S == 60.0
    assert mv.HOST_GAP_S == 1.0
    assert mv.WAIT_S == 13.0
    assert mv.SLOW_FETCH_S == 3.0


def test_the_fetch_is_the_adapters_until_a_test_replaces_it(mv):
    from docket.adapters import source_file

    assert mv._fetch is source_file.fetch_pdf


def test_the_module_reads_no_database_and_nothing_of_the_web_layer(mv):
    source = Path(mv.__file__).read_text()
    lines = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    assert lines, "the module has imports"
    for line in lines:
        assert "docket.web" not in line
        assert "docket.db" not in line
        assert "query" not in line
    for word in ("db_cursor", "db()", "execute("):
        assert word not in source


# A page, from one fetch.


def test_a_page_is_drawn_after_one_fetch_of_exactly_the_address(mv, fetch):
    view = mv.page_view(URL, 2)

    assert isinstance(view, mv.PageView)
    assert view.page == 2
    assert view.page_count == 4
    assert view.mime == "image/webp"
    assert view.image[:4] == b"RIFF"
    assert (view.width, view.height) == (1200, 1553)
    assert fetch.calls == [URL]


def test_the_page_drawn_is_the_page_asked_for(mv, fetch, fixture_pdf):
    assert mv.page_view(URL, 2).image == pdf_page.render_page(fixture_pdf, 2).image
    assert mv.page_view(URL, 3).image == pdf_page.render_page(fixture_pdf, 3).image


def test_a_second_page_of_the_same_address_fetches_nothing_more(mv, fetch):
    mv.page_view(URL, 2)
    view = mv.page_view(URL, 3)

    assert view.page == 3
    assert fetch.calls == [URL]


def test_the_last_page_and_the_first_are_pages(mv, fetch):
    assert mv.page_view(URL, 1).page == 1
    assert mv.page_view(URL, 4).page == 4


@pytest.mark.parametrize("page", [0, -1, 2001])
def test_a_page_outside_the_bound_is_no_such_page_with_no_fetch(mv, fetch, page):
    with pytest.raises(mv.NoSuchPage):
        mv.page_view(URL, page)

    assert fetch.calls == []


def test_the_bound_is_read_when_the_page_is_asked_for(mv, fetch, monkeypatch):
    monkeypatch.setattr(mv, "MAX_PAGE", 2)

    with pytest.raises(mv.NoSuchPage):
        mv.page_view(URL, 3)
    assert fetch.calls == []
    assert mv.page_view(URL, 2).page == 2


def test_a_page_past_the_files_end_is_no_such_page_after_one_fetch_and_is_not_drawn(
    mv, fetch, monkeypatch
):
    drawn = []
    real = pdf_page.render_page

    def counting(data, page, **kwargs):
        drawn.append(page)
        return real(data, page, **kwargs)

    monkeypatch.setattr(pdf_page, "render_page", counting)

    with pytest.raises(mv.NoSuchPage):
        mv.page_view(URL, 5)
    assert fetch.calls == [URL]

    with pytest.raises(mv.NoSuchPage):
        mv.page_view(URL, 5)
    assert fetch.calls == [URL]
    assert drawn == []


def test_a_file_is_fetched_again_after_an_hour(mv, fetch, clock):
    mv.page_view(URL, 1)

    clock.t += 3599
    mv.page_view(URL, 1)
    assert len(fetch.calls) == 1

    clock.t += 2
    mv.page_view(URL, 1)
    assert len(fetch.calls) == 2


def test_the_hour_counts_from_the_fetch_and_not_from_the_last_use(mv, fetch, clock):
    mv.page_view(URL, 1)
    clock.t += 3000
    mv.page_view(URL, 1)
    clock.t += 601
    mv.page_view(URL, 1)

    assert len(fetch.calls) == 2


# Failures.


def test_a_failure_about_the_one_file_is_remembered_for_that_address_for_a_minute(
    mv, fetch, clock
):
    other = "https://a.example/other.pdf"
    fetch.answers[URL] = SourceFileError("gone", host_down=False)

    _unavailable(mv, URL)
    assert fetch.calls == [URL]

    clock.t = 110.0
    _unavailable(mv, URL)
    assert fetch.calls == [URL]

    assert mv.page_view(other, 1).page == 1
    assert fetch.calls == [URL, other]

    clock.t = 159.0
    _unavailable(mv, URL)
    assert len(fetch.calls) == 2

    clock.t = 161.0
    del fetch.answers[URL]
    assert mv.page_view(URL, 1).page == 1
    assert fetch.calls == [URL, other, URL]


def test_a_host_that_did_not_answer_is_remembered_for_every_address_on_it(mv, fetch, clock):
    one = "https://a.example/one.pdf"
    two = "https://a.example/two.pdf"
    three = "https://b.example/three.pdf"
    fetch.answers[one] = SourceFileError("timed out", host_down=True)

    _unavailable(mv, one)
    assert fetch.calls == [one]

    _unavailable(mv, two)
    _unavailable(mv, "https://A.EXAMPLE:443/four.pdf")
    _unavailable(mv, one)
    assert fetch.calls == [one]

    assert mv.page_view(three, 1).page == 1
    assert fetch.calls == [one, three]

    clock.t = 161.0
    assert mv.page_view(two, 1).page == 1
    assert fetch.calls == [one, three, two]


def test_bytes_that_are_not_a_pdf_are_unavailable_not_kept_and_not_fetched_again_for_a_minute(
    mv, fetch, clock
):
    fetch.answers[URL] = NOT_A_PDF

    _unavailable(mv, URL)
    assert fetch.calls == [URL]
    assert URL not in mv._files

    clock.t = 159.0
    _unavailable(mv, URL)
    assert len(fetch.calls) == 1

    # Another address on that host is still fetched: the failure is the file's.
    assert mv.page_view("https://a.example/good.pdf", 1).page == 1
    assert len(fetch.calls) == 2

    clock.t = 161.0
    _unavailable(mv, URL)
    assert len(fetch.calls) == 3


def test_a_page_that_cannot_be_drawn_is_unavailable_and_the_file_is_dropped(
    mv, fetch, clock, monkeypatch
):
    def broken(data, page, **kwargs):
        raise pdf_page.UnreadablePdf("the picture could not be written")

    with monkeypatch.context() as patch:
        patch.setattr(pdf_page, "render_page", broken)
        _unavailable(mv, URL, 2)
        assert fetch.calls == [URL]
        assert URL not in mv._files

    # Remembered as a failure: a minute passes before the address is tried again.
    clock.t = 159.0
    _unavailable(mv, URL, 2)
    assert len(fetch.calls) == 1

    clock.t = 161.0
    assert mv.page_view(URL, 2).page == 2
    assert len(fetch.calls) == 2


def test_a_page_the_drawing_says_is_out_of_range_is_no_such_page(mv, fetch, monkeypatch):
    def out_of_range(data, page, **kwargs):
        raise pdf_page.PageOutOfRange(page, 1)

    monkeypatch.setattr(pdf_page, "render_page", out_of_range)

    with pytest.raises(mv.NoSuchPage):
        mv.page_view(URL, 2)
    assert URL in mv._files


def test_a_failed_fetch_is_logged_with_the_address_the_reason_and_the_time(
    mv, fetch, clock, caplog
):
    def takes_a_while(url):
        clock.t += 0.25

    fetch.during = takes_a_while
    fetch.answers[URL] = SourceFileError("status 404", host_down=False)

    with caplog.at_level(logging.WARNING, logger="docket.services.minutes_viewer"):
        _unavailable(mv, URL)

    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(messages) == 1
    assert messages[0].startswith("minutes viewer:")
    assert not messages[0].startswith("minutes viewer: slow fetch")
    assert URL in messages[0]
    assert "status 404" in messages[0]
    assert "250" in messages[0]


def test_a_slow_fetch_that_succeeds_is_logged_and_a_quick_one_is_not(mv, fetch, clock, caplog):
    slow = "https://a.example/slow.pdf"

    def takes_a_while(url):
        clock.t += 3.5 if url == slow else 2.9

    fetch.during = takes_a_while

    with caplog.at_level(logging.WARNING, logger="docket.services.minutes_viewer"):
        mv.page_view("https://b.example/quick.pdf", 1)
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
        mv.page_view(slow, 1)

    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(messages) == 1
    assert messages[0].startswith("minutes viewer: slow fetch")
    assert slow in messages[0]
    assert str(len(fetch.data)) in messages[0]
    assert "3500" in messages[0]


def test_bytes_that_are_not_a_pdf_are_logged(mv, fetch, caplog):
    fetch.answers[URL] = NOT_A_PDF

    with caplog.at_level(logging.WARNING, logger="docket.services.minutes_viewer"):
        _unavailable(mv, URL)

    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(messages) == 1
    assert messages[0].startswith("minutes viewer:")
    assert URL in messages[0]


# The cache.


def test_the_cache_drops_the_least_recently_used_file(mv, fetch):
    a, b, c, d, e = (f"https://{name}.example/minutes.pdf" for name in "abcde")

    for url in (a, b, c, d):
        mv.page_view(url, 1)
    assert len(fetch.calls) == 4

    mv.page_view(a, 1)
    assert len(fetch.calls) == 4

    mv.page_view(e, 1)
    assert len(fetch.calls) == 5

    # A was used more recently than B, so B was the one dropped.
    mv.page_view(a, 1)
    assert len(fetch.calls) == 5

    mv.page_view(b, 1)
    assert len(fetch.calls) == 6


def test_the_cache_holds_four_files(mv, fetch):
    a, b, c, d = (f"https://{name}.example/minutes.pdf" for name in "abcd")

    for url in (a, b, c, d):
        mv.page_view(url, 1)
    for url in (a, b, c, d):
        mv.page_view(url, 2)

    assert len(fetch.calls) == 4
    assert len(mv._files) == 4


def test_the_cache_is_bounded_in_bytes(mv, fetch, monkeypatch, fixture_pdf):
    a = "https://a.example/minutes.pdf"
    b = "https://b.example/minutes.pdf"
    monkeypatch.setattr(mv, "CACHE_BYTES", len(fixture_pdf) + 1)

    mv.page_view(a, 1)
    mv.page_view(b, 1)
    mv.page_view(a, 1)

    assert fetch.calls == [a, b, a]


def test_two_files_that_fit_the_byte_bound_are_both_kept(mv, fetch, monkeypatch, fixture_pdf):
    a = "https://a.example/minutes.pdf"
    b = "https://b.example/minutes.pdf"
    monkeypatch.setattr(mv, "CACHE_BYTES", 2 * len(fixture_pdf))

    mv.page_view(a, 1)
    mv.page_view(b, 1)
    mv.page_view(a, 1)

    assert fetch.calls == [a, b]


def test_the_entry_just_stored_is_never_the_one_dropped(mv, fetch, monkeypatch):
    monkeypatch.setattr(mv, "CACHE_BYTES", 10)

    assert mv.page_view(URL, 2).page == 2
    assert mv.page_view(URL, 3).page == 3
    assert fetch.calls == [URL]


def test_clear_forgets_files_failures_and_host_times(mv, fetch, clock):
    bad = "https://a.example/bad.pdf"
    fetch.answers[bad] = SourceFileError("timed out", host_down=True)
    mv.page_view("https://b.example/minutes.pdf", 1)
    _unavailable(mv, bad)

    mv.clear()

    assert not mv._files and not mv._failures and not mv._inflight and not mv._hosts
    del fetch.answers[bad]
    mv.page_view(bad, 1)
    mv.page_view("https://b.example/minutes.pdf", 1)
    assert len(fetch.calls) == 4
    assert clock.sleeps == []


# The gap between requests to one host.


def test_requests_to_one_host_are_a_second_apart(mv, fetch, clock):
    mv.page_view("https://a.example/one.pdf", 1)
    assert clock.t == 100.0

    clock.t = 100.3
    mv.page_view("https://a.example/two.pdf", 1)
    assert clock.sleeps == [pytest.approx(0.7)]
    assert clock.t == pytest.approx(101.0)

    # The host is compared without its port and without regard to case.
    mv.page_view("https://A.EXAMPLE:443/three.pdf", 1)
    assert clock.sleeps == [pytest.approx(0.7), pytest.approx(1.0)]

    mv.page_view("https://b.example/four.pdf", 1)
    assert clock.sleeps == [pytest.approx(0.7), pytest.approx(1.0)]


def test_a_host_last_asked_more_than_a_second_ago_is_asked_at_once(mv, fetch, clock):
    mv.page_view("https://a.example/one.pdf", 1)
    clock.t += 1.0
    mv.page_view("https://a.example/two.pdf", 1)

    assert clock.sleeps == []


def test_the_gap_counts_from_the_end_of_the_last_request(mv, fetch, clock):
    def takes_two_seconds(url):
        clock.t += 2.0

    fetch.during = takes_two_seconds

    mv.page_view("https://a.example/one.pdf", 1)  # sent at 100.0, ended at 102.0
    clock.t = 102.4
    mv.page_view("https://a.example/two.pdf", 1)

    assert clock.sleeps == [pytest.approx(0.6)]


def test_the_gap_counts_from_a_request_that_failed_too(mv, fetch, clock):
    bad = "https://a.example/bad.pdf"
    fetch.answers[bad] = SourceFileError("status 404", host_down=False)

    _unavailable(mv, bad)
    clock.t = 100.25
    mv.page_view("https://a.example/good.pdf", 1)

    assert clock.sleeps == [pytest.approx(0.75)]


def test_a_cached_page_waits_for_no_gap(mv, fetch, clock):
    mv.page_view(URL, 1)
    mv.page_view(URL, 2)
    mv.page_view(URL, 3)

    assert clock.sleeps == []


# The locks, seen from one thread.


def test_the_state_lock_is_not_held_across_a_sleep_a_fetch_or_a_draw(
    mv, fetch, clock, monkeypatch
):
    held = []
    real_count, real_render = pdf_page.page_count, pdf_page.render_page

    def note(where):
        held.append((where, mv._state_lock.locked()))

    def counting(data):
        note("count")
        return real_count(data)

    def rendering(data, page, **kwargs):
        note("draw")
        return real_render(data, page, **kwargs)

    fetch.during = lambda url: note("fetch")
    clock.during_sleep = lambda: note("sleep")
    monkeypatch.setattr(pdf_page, "page_count", counting)
    monkeypatch.setattr(pdf_page, "render_page", rendering)

    mv.page_view("https://a.example/one.pdf", 1)
    mv.page_view("https://a.example/two.pdf", 1)

    assert held == [
        ("fetch", False),
        ("count", False),
        ("draw", False),
        ("sleep", False),
        ("fetch", False),
        ("count", False),
        ("draw", False),
    ]


def test_the_hosts_lock_is_held_across_its_wait_and_its_fetch_and_then_released(
    mv, fetch, clock, monkeypatch
):
    held = []
    real_render = pdf_page.render_page

    def note(where):
        lock, _last = mv._hosts["a.example"]
        held.append((where, lock.locked()))

    def rendering(data, page, **kwargs):
        note("draw")
        return real_render(data, page, **kwargs)

    fetch.during = lambda url: note("fetch")
    clock.during_sleep = lambda: note("sleep")
    monkeypatch.setattr(pdf_page, "render_page", rendering)

    mv.page_view("https://a.example/one.pdf", 1)
    mv.page_view("https://a.example/two.pdf", 1)

    assert held == [
        ("fetch", True),
        ("draw", False),
        ("sleep", True),
        ("fetch", True),
        ("draw", False),
    ]


def test_the_hosts_lock_is_released_and_no_fetch_left_in_flight_when_the_fetch_fails(
    mv, fetch
):
    fetch.answers[URL] = SourceFileError("status 404", host_down=False)

    _unavailable(mv, URL)

    lock, _last = mv._hosts["a.example"]
    assert not lock.locked()
    assert mv._inflight == {}


def test_nothing_is_left_in_flight_when_the_fetch_raises_something_unexpected(mv, fetch):
    fetch.answers[URL] = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        mv.page_view(URL, 1)

    lock, _last = mv._hosts["a.example"]
    assert not lock.locked()
    assert mv._inflight == {}


# Two threads.


class _Slow:
    """A fetch whose answer for ``slow`` waits until the test releases it."""

    def __init__(self, data, slow, answer=None):
        self.data = data
        self.slow = slow
        self.answer = data if answer is None else answer
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, url):
        self.calls.append(url)
        if url != self.slow:
            return self.data
        self.entered.set()
        assert self.release.wait(JOIN_S), "the test never released the slow fetch"
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _start(mv, results, key, url, page):
    def run():
        try:
            results[key] = mv.page_view(url, page)
        except Exception as exc:  # the test asserts on what was raised
            results[key] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def _join(*threads):
    for thread in threads:
        thread.join(JOIN_S)
        assert not thread.is_alive(), "a caller never returned"


def _wait_until(condition):
    deadline = time.monotonic() + JOIN_S
    while not condition():
        assert time.monotonic() < deadline, "the other thread never got there"
        time.sleep(0.005)


def test_two_callers_of_one_file_share_one_fetch(mv, monkeypatch, fixture_pdf):
    slow = "https://slow.example/minutes.pdf"
    fake = _Slow(fixture_pdf, slow)
    monkeypatch.setattr(mv, "_fetch", fake)
    results = {}

    first = _start(mv, results, "first", slow, 1)
    assert fake.entered.wait(JOIN_S)
    second = _start(mv, results, "second", slow, 2)
    _wait_until(lambda: not second.is_alive() or mv._inflight.get(slow) is not None)
    time.sleep(0.05)  # let the second caller reach its wait
    fake.release.set()
    _join(first, second)

    assert isinstance(results["first"], mv.PageView) and results["first"].page == 1
    assert isinstance(results["second"], mv.PageView) and results["second"].page == 2
    assert fake.calls == [slow]
    assert mv._inflight == {}


def test_a_cached_page_is_served_while_another_file_is_being_fetched(
    mv, monkeypatch, fixture_pdf
):
    slow = "https://slow.example/minutes.pdf"
    other = "https://other.example/minutes.pdf"
    fake = _Slow(fixture_pdf, slow)
    monkeypatch.setattr(mv, "_fetch", fake)
    monkeypatch.setattr(mv, "WAIT_S", 2.0)
    results = {}

    assert mv.page_view(other, 1).page == 1
    thread = _start(mv, results, "slow", slow, 1)
    assert fake.entered.wait(JOIN_S)

    # The slow fetch has not returned, and this is answered all the same.
    view = mv.page_view(other, 2)
    assert isinstance(view, mv.PageView) and view.page == 2
    assert not fake.release.is_set()

    fake.release.set()
    _join(thread)
    assert isinstance(results["slow"], mv.PageView)
    assert fake.calls == [other, slow]


def test_a_wait_that_times_out_is_unavailable_and_is_not_remembered_as_a_failure(
    mv, monkeypatch, fixture_pdf
):
    slow = "https://slow.example/minutes.pdf"
    fake = _Slow(fixture_pdf, slow)
    monkeypatch.setattr(mv, "_fetch", fake)
    monkeypatch.setattr(mv, "WAIT_S", 0.05)
    results = {}

    thread = _start(mv, results, "slow", slow, 1)
    assert fake.entered.wait(JOIN_S)

    _unavailable(mv, slow)
    assert mv._failures == {}

    fake.release.set()
    _join(thread)
    assert isinstance(results["slow"], mv.PageView)

    assert isinstance(mv.page_view(slow, 1), mv.PageView)
    assert fake.calls == [slow]


def test_a_caller_who_waited_on_a_fetch_that_failed_is_unavailable_without_a_second_fetch(
    mv, monkeypatch, fixture_pdf
):
    slow = "https://slow.example/minutes.pdf"
    fake = _Slow(fixture_pdf, slow, answer=SourceFileError("status 404", host_down=False))
    monkeypatch.setattr(mv, "_fetch", fake)
    results = {}

    first = _start(mv, results, "first", slow, 1)
    assert fake.entered.wait(JOIN_S)
    second = _start(mv, results, "second", slow, 2)
    _wait_until(lambda: not second.is_alive() or mv._inflight.get(slow) is not None)
    time.sleep(0.05)
    fake.release.set()
    _join(first, second)

    assert isinstance(results["first"], mv.Unavailable)
    assert isinstance(results["second"], mv.Unavailable)
    assert fake.calls == [slow]


def test_a_second_address_on_a_host_waits_for_the_first_and_is_not_sent_once_the_host_is_down(
    mv, monkeypatch, fixture_pdf
):
    one = "https://slow.example/one.pdf"
    two = "https://slow.example/two.pdf"
    fake = _Slow(fixture_pdf, one, answer=SourceFileError("timed out", host_down=True))
    monkeypatch.setattr(mv, "_fetch", fake)
    results = {}

    first = _start(mv, results, "one", one, 1)
    assert fake.entered.wait(JOIN_S)
    second = _start(mv, results, "two", two, 1)
    # The second caller is past the failure memory (nothing is remembered yet)
    # and is the fetcher of its own address, waiting for the host.
    _wait_until(lambda: two in mv._inflight)
    time.sleep(0.05)
    assert fake.calls == [one]

    fake.release.set()
    _join(first, second)

    assert isinstance(results["one"], mv.Unavailable)
    assert isinstance(results["two"], mv.Unavailable)
    assert fake.calls == [one]
    assert mv._inflight == {}


def test_a_fetcher_that_cannot_get_the_host_in_time_is_unavailable_and_nothing_is_remembered(
    mv, monkeypatch, fixture_pdf
):
    one = "https://slow.example/one.pdf"
    two = "https://slow.example/two.pdf"
    fake = _Slow(fixture_pdf, one)
    monkeypatch.setattr(mv, "_fetch", fake)
    monkeypatch.setattr(mv, "WAIT_S", 0.05)
    results = {}

    thread = _start(mv, results, "one", one, 1)
    assert fake.entered.wait(JOIN_S)

    _unavailable(mv, two)
    assert fake.calls == [one]
    assert mv._failures == {}
    assert two not in mv._inflight

    fake.release.set()
    _join(thread)
    assert isinstance(results["one"], mv.PageView)

    # Nothing was remembered against the second address: it is fetched now.
    assert isinstance(mv.page_view(two, 1), mv.PageView)
    assert fake.calls == [one, two]
