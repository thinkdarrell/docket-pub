"""Unit tests for ``docket.analysis.pdf_page``.

One page of a PDF drawn as a picture in memory, its size bounded whatever
the page's shape. The real-file cases read the four-page committee minutes
already in the fixtures; pages of odd shapes are blank one-page PDFs the
tests make with the PDF library itself.

The module is imported inside each test (through the ``pp`` fixture) so
that this file collects, and each test fails by itself, before the module
exists.

Plan `minutes-open-at-the-vote-page`, M1; M2b moved the encoding of the
picture outside the module's lock.
"""

from __future__ import annotations

import importlib
import io
from pathlib import Path

import pypdfium2
import pytest
from PIL import Image

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "committee_documents"
    / "ps_minutes_2026-09-22.pdf"
)
NOT_A_PDF = b"%PDF-1.4 not a pdf"


@pytest.fixture
def pp():
    return importlib.import_module("docket.analysis.pdf_page")


@pytest.fixture(scope="module")
def fixture_pdf() -> bytes:
    return FIXTURE.read_bytes()


def _blank_pdf(width, height, rotation=0) -> bytes:
    pdf = pypdfium2.PdfDocument.new()
    page = pdf.new_page(width, height)
    if rotation:
        page.set_rotation(rotation)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def test_the_fixture_has_four_pages(pp, fixture_pdf):
    assert pp.page_count(fixture_pdf) == 4


def test_page_one_of_the_fixture_is_a_lossless_webp_1200_wide(pp, fixture_pdf):
    rendered = pp.render_page(fixture_pdf, 1)

    assert rendered.page_count == 4
    assert (rendered.width, rendered.height) == (1200, 1553)
    assert rendered.mime == "image/webp"
    assert rendered.image[:4] == b"RIFF"
    assert rendered.image[8:12] == b"WEBP"

    picture = Image.open(io.BytesIO(rendered.image))
    assert picture.size == (1200, 1553)
    darkest, _lightest = picture.convert("L").getextrema()
    assert darkest < 128  # the page's ink was drawn, not a blank sheet


def test_the_last_page_renders(pp, fixture_pdf):
    rendered = pp.render_page(fixture_pdf, 4)

    assert rendered.page_count == 4
    assert rendered.image[:4] == b"RIFF"


def test_each_page_is_its_own_picture(pp, fixture_pdf):
    assert pp.render_page(fixture_pdf, 1).image != pp.render_page(fixture_pdf, 2).image


@pytest.mark.parametrize("page", [0, 5])
def test_a_page_outside_the_file_is_out_of_range(pp, fixture_pdf, page):
    with pytest.raises(pp.PageOutOfRange) as raised:
        pp.render_page(fixture_pdf, page)

    assert raised.value.page == page
    assert raised.value.page_count == 4


def test_bytes_that_are_not_a_pdf_are_unreadable(pp):
    with pytest.raises(pp.UnreadablePdf):
        pp.render_page(NOT_A_PDF, 1)
    with pytest.raises(pp.UnreadablePdf):
        pp.page_count(NOT_A_PDF)


def test_a_blank_page_is_drawn_on_white(pp):
    rendered = pp.render_page(_blank_pdf(612, 792), 1)

    assert (rendered.width, rendered.height) == (1200, 1553)
    picture = Image.open(io.BytesIO(rendered.image))
    assert picture.convert("RGB").getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize(
    "width, height, rotation, expected",
    [
        (1224, 792, 0, (1836, 1188)),   # a wide sheet: the minimum scale
        (3000, 792, 0, (4000, 1056)),   # the cap on the width
        (612, 14400, 0, (170, 4000)),   # the cap on the height
        (20, 20, 0, (1200, 1200)),      # a tiny page: the target width
        (612, 792, 90, (1200, 928)),    # a rotated page: its displayed size
    ],
)
def test_the_pictures_size_is_bounded_whatever_the_pages_shape(pp, width, height, rotation, expected):
    rendered = pp.render_page(_blank_pdf(width, height, rotation), 1)

    assert (rendered.width, rendered.height) == expected
    assert Image.open(io.BytesIO(rendered.image)).size == expected


def test_the_scaling_constants_are_the_ones_the_plan_states(pp):
    assert (pp.WIDTH_PX, pp.MIN_SCALE, pp.MAX_SIDE_PX) == (1200, 1.5, 4000)
    assert pp.FORMATS == (
        ("WEBP", "image/webp", {"lossless": True}),
        ("PNG", "image/png", {}),
    )


def test_a_narrower_width_can_be_asked_for(pp):
    # 612 points at 918 pixels is the minimum scale of 1.5; below that the
    # minimum scale decides, so 600 gives 918 too.
    assert pp.render_page(_blank_pdf(612, 792), 1, width_px=1000).width == 1000
    assert pp.render_page(_blank_pdf(612, 792), 1, width_px=600).width == 918


def test_png_is_used_when_webp_cannot_be_written(pp, fixture_pdf, monkeypatch):
    monkeypatch.setattr(pp, "FORMATS", (("NOPE", "image/nope", {}),) + pp.FORMATS[-1:])

    rendered = pp.render_page(fixture_pdf, 1)

    assert rendered.mime == "image/png"
    assert rendered.image[:8] == b"\x89PNG\r\n\x1a\n"
    assert (rendered.width, rendered.height) == (1200, 1553)


def test_no_format_that_can_be_written_is_unreadable(pp, fixture_pdf, monkeypatch):
    monkeypatch.setattr(pp, "FORMATS", (("NOPE", "image/nope", {}),))

    with pytest.raises(pp.UnreadablePdf):
        pp.render_page(fixture_pdf, 1)


def test_a_pdf_library_that_will_not_load_is_unreadable(pp, fixture_pdf, monkeypatch):
    import sys

    # ``None`` in sys.modules makes ``import pypdfium2`` raise ImportError,
    # which is what a missing bundled binary looks like to the caller.
    monkeypatch.setitem(sys.modules, "pypdfium2", None)

    with pytest.raises(pp.UnreadablePdf):
        pp.render_page(fixture_pdf, 1)
    with pytest.raises(pp.UnreadablePdf):
        pp.page_count(fixture_pdf)


def test_the_module_does_not_load_the_pdf_library_when_imported(pp):
    # The library is imported inside the functions, so a binary that will
    # not load cannot take the site down at import time.
    source = Path(pp.__file__).read_text()
    top_level = [line for line in source.splitlines() if line.startswith(("import ", "from "))]

    assert not any("pypdfium2" in line or "PIL" in line for line in top_level)


def _watched_library(pp, monkeypatch, picture=None):
    """Put a stand-in for the PDF library in place whose documents record
    whether the module's lock was held when they were opened, and that they
    were closed. Everything else is the real library's, unless ``picture``
    is given: then every page of a document is a stand-in whose
    ``render(...).to_pil()`` returns that picture."""
    import sys
    import types

    seen = {"locked": [], "closed": 0}

    class _Bitmap:
        def to_pil(self):
            seen.setdefault("to_pil_locked", []).append(pp._lock.locked())
            return picture

    class _Page:
        def get_size(self):
            return (612.0, 792.0)

        def render(self, scale=1):
            seen.setdefault("scales", []).append(scale)
            return _Bitmap()

        def close(self):
            seen["page_closed_locked"] = pp._lock.locked()

    class _Watched(pypdfium2.PdfDocument):
        def __init__(self, *args, **kwargs):
            seen["locked"].append(pp._lock.locked())
            super().__init__(*args, **kwargs)

        def __getitem__(self, index):
            if picture is None:
                return super().__getitem__(index)
            return _Page()

        def close(self):
            seen["closed"] += 1
            seen["closed_locked"] = pp._lock.locked()
            super().close()

    monkeypatch.setitem(sys.modules, "pypdfium2", types.SimpleNamespace(PdfDocument=_Watched))
    return seen


def test_render_page_holds_the_lock_and_closes_the_document(pp, fixture_pdf, monkeypatch):
    seen = _watched_library(pp, monkeypatch)

    assert pp.render_page(fixture_pdf, 2).page_count == 4

    assert (seen["locked"], seen["closed"]) == ([True], 1)
    assert not pp._lock.locked()


def test_page_count_holds_the_lock_and_closes_the_document(pp, fixture_pdf, monkeypatch):
    seen = _watched_library(pp, monkeypatch)

    assert pp.page_count(fixture_pdf) == 4

    assert (seen["locked"], seen["closed"]) == ([True], 1)
    assert not pp._lock.locked()


def test_the_lock_is_released_when_the_page_is_out_of_range(pp, fixture_pdf, monkeypatch):
    seen = _watched_library(pp, monkeypatch)

    with pytest.raises(pp.PageOutOfRange):
        pp.render_page(fixture_pdf, 9)

    assert (seen["locked"], seen["closed"]) == ([True], 1)
    assert not pp._lock.locked()


class _Picture:
    """A stand-in for the drawn picture that records, when it is saved,
    whether the module's lock is held."""

    mode = "RGB"
    size = (1200, 1553)

    def __init__(self, pp):
        self._pp = pp
        self.saved_locked = []
        self.saved_as = []

    def save(self, buf, name, **options):
        self.saved_locked.append(self._pp._lock.locked())
        self.saved_as.append((name, options))
        buf.write(b"stand-in")


def test_the_picture_is_encoded_after_the_lock_is_released(pp, fixture_pdf, monkeypatch):
    picture = _Picture(pp)
    seen = _watched_library(pp, monkeypatch, picture=picture)

    rendered = pp.render_page(fixture_pdf, 2)

    assert rendered.image == b"stand-in"
    assert rendered.mime == "image/webp"
    assert (rendered.page_count, rendered.width, rendered.height) == (4, 1200, 1553)
    # The PDF library's work is under the lock: open, draw, to_pil, close.
    assert (seen["locked"], seen["closed"]) == ([True], 1)
    assert seen["to_pil_locked"] == [True]
    assert seen["page_closed_locked"] is True
    assert seen["closed_locked"] is True
    # The encoding is not.
    assert picture.saved_locked == [False]
    assert picture.saved_as == [("WEBP", {"lossless": True})]
    assert not pp._lock.locked()


def test_a_picture_no_format_can_write_is_unreadable_with_the_lock_released(
    pp, fixture_pdf, monkeypatch
):
    class _Unwritable(_Picture):
        def save(self, buf, name, **options):
            self.saved_locked.append(self._pp._lock.locked())
            raise OSError("cannot write " + name)

    picture = _Unwritable(pp)
    _watched_library(pp, monkeypatch, picture=picture)

    with pytest.raises(pp.UnreadablePdf):
        pp.render_page(fixture_pdf, 2)

    assert picture.saved_locked == [False, False]
    assert not pp._lock.locked()


def test_an_error_while_the_picture_is_encoded_is_unreadable_with_the_lock_released(
    pp, fixture_pdf, monkeypatch
):
    class _Unconvertible(_Picture):
        mode = "L"

        def convert(self, mode):
            self.saved_locked.append(self._pp._lock.locked())
            raise ValueError("cannot convert to " + mode)

    picture = _Unconvertible(pp)
    _watched_library(pp, monkeypatch, picture=picture)

    # Outside the lock, and still UnreadablePdf: what render_page raises
    # does not depend on where the lock ends.
    with pytest.raises(pp.UnreadablePdf, match="ValueError: cannot convert to RGB"):
        pp.render_page(fixture_pdf, 2)

    assert picture.saved_locked == [False]
    assert not pp._lock.locked()
