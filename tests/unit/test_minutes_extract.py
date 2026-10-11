from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from docket.ai.transcripts.minutes import download_minutes, extract_pages, page_for_offset

AGENDA_PDF = Path("tests/fixtures/granicus_bham_agenda_2026_05_19.pdf")


def test_extract_pages_offsets_line_up_with_text():
    text, offsets = extract_pages(AGENDA_PDF.read_bytes())
    assert offsets[0] == 0 and len(text) > 500
    assert offsets == sorted(offsets) and all(o <= len(text) for o in offsets)
    import pdfplumber, io
    with pdfplumber.open(io.BytesIO(AGENDA_PDF.read_bytes())) as pdf:
        assert len(offsets) == len(pdf.pages)
        first_line = (pdf.pages[0].extract_text() or "").splitlines()[0]
    assert text.startswith(first_line)
    assert "\f" not in text


def test_page_for_offset_is_one_based_and_bisects():
    assert page_for_offset([0, 100, 250], 0) == 1
    assert page_for_offset([0, 100, 250], 99) == 1
    assert page_for_offset([0, 100, 250], 100) == 2
    assert page_for_offset([0, 100, 250], 9999) == 3


def _resp(content: bytes, headers: dict | None = None, chunk: int = 0):
    r = MagicMock(status_code=200, headers=headers or {})
    r.raise_for_status = lambda: None
    parts = [content[i:i + chunk] for i in range(0, len(content), chunk)] if chunk else [content]
    r.iter_content.return_value = parts
    return r


@patch("docket.ai.transcripts.minutes.requests.get")
def test_download_sends_browser_user_agent_and_rejects_html(get):
    get.return_value = _resp(b"<html>login</html>")
    assert download_minutes("https://bhamal.granicus.com/MinutesViewer.php?clip_id=1") is None
    assert get.call_args.kwargs["headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert get.call_args.kwargs["stream"] is True
    get.return_value = _resp(b"%PDF-1.4 ...")
    assert download_minutes("https://x") == b"%PDF-1.4 ..."
    get.return_value.close.assert_called_once()
    get.side_effect = requests.ConnectionError("boom")
    assert download_minutes("https://x") is None


@patch("docket.ai.transcripts.minutes.requests.get")
def test_download_gives_up_past_the_byte_cap(get):
    body = b"%PDF-" + b"x" * 100
    get.return_value = _resp(body, headers={"Content-Length": str(len(body))})
    assert download_minutes("https://x", max_bytes=50) is None            # declared size over the cap: no body read
    get.return_value.iter_content.assert_not_called()
    get.return_value = _resp(body, chunk=16)                               # no Content-Length: stops while streaming
    assert download_minutes("https://x", max_bytes=50) is None
    get.return_value.close.assert_called_once()
    get.return_value = _resp(body, chunk=16)
    assert download_minutes("https://x", max_bytes=200) == body
