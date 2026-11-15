"""docket.adapters.committee_documents: fetching a committee page and a PDF.

Nothing here reaches the network: ``requests.get`` is replaced in every test,
and so is ``time.sleep``, whose calls are the record of the pause the module
kept. The functions are imported inside each test so the file collects before
they exist.

Plan `committee-documents`, M3.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

PAGE = "https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/public-safety-committee"
PDF = "https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/s3fs-public/2026-09/minutes.pdf"
MB = 1024 * 1024


def _response(*, text: str = "", chunks: list[bytes] | None = None, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.iter_content.side_effect = lambda chunk_size=None: iter(chunks or [])
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status} for url")
    return resp


@pytest.fixture
def net(monkeypatch):
    """The module with its network and its clock replaced: ``net.get`` is the
    stand-in for ``requests.get``, ``net.pauses`` the seconds slept, and
    ``net.clock`` the monotonic time, which a test moves by hand."""
    from docket.adapters import committee_documents as module

    class Net:
        pauses: list[float] = []
        clock = 1000.0
        get = MagicMock()

    state = Net()
    state.pauses = []
    state.get = MagicMock()
    monkeypatch.setattr(module.requests, "get", state.get)
    monkeypatch.setattr(module.time, "sleep", state.pauses.append)
    monkeypatch.setattr(module.time, "monotonic", lambda: state.clock)
    monkeypatch.setattr(module, "_last_request_at", None)
    return state


def test_fetch_page_returns_the_page_and_sends_a_browser_agent_and_a_timeout(net):
    from docket.adapters import city_calendar
    from docket.adapters.committee_documents import fetch_page

    net.get.return_value = _response(text="<html>the page</html>")

    assert fetch_page(PAGE) == "<html>the page</html>"

    (url,), kwargs = net.get.call_args
    assert url == PAGE
    assert kwargs["timeout"] == 60
    assert kwargs["headers"] == {"User-Agent": city_calendar._BROWSER_UA}, "the string city_calendar sends, copied"
    assert net.pauses == [], "the first request waits for nothing"


def test_fetch_page_raises_on_an_http_error(net):
    from docket.adapters.committee_documents import fetch_page

    net.get.return_value = _response(status=503)
    with pytest.raises(requests.HTTPError):
        fetch_page(PAGE)


def test_requests_are_a_second_apart_across_the_page_and_the_pdf(net):
    from docket.adapters.committee_documents import fetch_page, fetch_pdf

    net.get.side_effect = lambda url, **kwargs: _response(text="x", chunks=[b"%PDF-1.7 body"])

    fetch_page(PAGE)
    net.clock += 0.25
    assert fetch_pdf(PDF) == b"%PDF-1.7 body"
    assert net.pauses == [pytest.approx(0.75)], "one gap for both hosts: the PDF waits out the page's second"

    net.clock += 1.5
    fetch_page(PAGE)
    assert len(net.pauses) == 1, "a second already gone by is not waited again"


def test_the_gap_is_kept_after_a_request_that_failed(net):
    from docket.adapters.committee_documents import fetch_page

    net.get.side_effect = requests.ConnectionError("no route")
    with pytest.raises(requests.ConnectionError):
        fetch_page(PAGE)
    net.get.side_effect = None
    net.get.return_value = _response(text="x")
    fetch_page(PAGE)
    assert net.pauses == [pytest.approx(1.0)]


def test_fetch_pdf_streams_and_joins_the_body(net):
    from docket.adapters.committee_documents import fetch_pdf

    resp = _response(chunks=[b"%PDF-", b"1.7\n", b"the rest"])
    net.get.return_value = resp

    assert fetch_pdf(PDF) == b"%PDF-1.7\nthe rest"
    assert net.get.call_args.kwargs["stream"] is True
    assert net.get.call_args.kwargs["timeout"] == 60
    resp.close.assert_called_once()


def test_fetch_pdf_stops_past_forty_megabytes(net):
    from docket.adapters.committee_documents import fetch_pdf

    served: list[int] = []

    def chunks(chunk_size=None):
        for number in range(100):
            served.append(number)
            yield (b"%PDF-" if number == 0 else b"") + b"x" * MB

    resp = _response()
    resp.iter_content.side_effect = chunks
    net.get.return_value = resp

    assert fetch_pdf(PDF) is None
    assert len(served) == 40, "it stops at the chunk that passes forty megabytes, and takes no more of the body"
    resp.close.assert_called_once()

    # Exactly forty megabytes is not past the limit.
    net.get.return_value = _response(chunks=[b"%PDF-" + b"x" * (MB - 5)] + [b"x" * MB] * 39)
    body = fetch_pdf(PDF)
    assert body is not None and len(body) == 40 * MB


def test_fetch_pdf_is_none_when_the_body_breaks_off_part_way(net):
    from docket.adapters.committee_documents import fetch_pdf

    def chunks(chunk_size=None):
        yield b"%PDF-1.7 the first part"
        raise requests.exceptions.ChunkedEncodingError("connection broken")

    resp = _response()
    resp.iter_content.side_effect = chunks
    net.get.return_value = resp

    assert fetch_pdf(PDF) is None
    resp.close.assert_called_once()


def test_fetch_pdf_is_none_for_a_body_that_is_not_a_pdf(net):
    from docket.adapters.committee_documents import fetch_pdf

    net.get.return_value = _response(chunks=[b"<html><body>Access Denied</body></html>"])
    assert fetch_pdf(PDF) is None
    net.get.return_value = _response(chunks=[b" %PDF-1.7"])
    assert fetch_pdf(PDF) is None, "the body must begin with the mark, not merely hold it"
    net.get.return_value = _response(chunks=[])
    assert fetch_pdf(PDF) is None


def test_fetch_pdf_is_none_when_the_request_fails(net):
    from docket.adapters.committee_documents import fetch_pdf

    net.get.return_value = _response(status=404)
    assert fetch_pdf(PDF) is None
    net.get.side_effect = requests.ConnectionError("no route")
    assert fetch_pdf(PDF) is None
    net.get.side_effect = requests.Timeout("60 s")
    assert fetch_pdf(PDF) is None
