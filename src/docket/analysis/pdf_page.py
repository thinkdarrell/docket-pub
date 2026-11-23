"""One page of a PDF drawn as a picture, in memory.

A domain module: no database, no network, and no import from
``docket.services`` or ``docket.web``. It is given the bytes of a PDF and
returns one page as picture bytes with the file's page count; nothing is
written to disk.

The picture is ``WIDTH_PX`` wide unless that would draw the page below
``MIN_SCALE`` (a wide sheet), and neither side is ever over ``MAX_SIDE_PX``,
whatever the page's shape. It is saved in the first format of ``FORMATS``
the image library can write: lossless WebP, then PNG.

``pypdfium2`` and ``PIL`` are imported inside the functions, not at the top
of the module, so that a bundled binary that will not load is an
``UnreadablePdf`` for the one caller and not an import error for the site.
The PDF library is not safe to call from two threads at once, so both
functions run under one lock. The constants are read at call time, so a
test can change them.

Plan `minutes-open-at-the-vote-page`, M1.
"""

from __future__ import annotations

import io
import threading
from dataclasses import dataclass

WIDTH_PX = 1200
MIN_SCALE = 1.5
MAX_SIDE_PX = 4000
FORMATS = (("WEBP", "image/webp", {"lossless": True}), ("PNG", "image/png", {}))

_lock = threading.Lock()


@dataclass(frozen=True)
class RenderedPage:
    image: bytes
    mime: str  # "image/webp", or "image/png" when WebP could not be written
    page_count: int
    width: int
    height: int


class UnreadablePdf(Exception):
    """The bytes could not be opened as a PDF, or the page could not be drawn."""


class PageOutOfRange(Exception):
    """The file has no such page."""

    def __init__(self, page: int, page_count: int):
        super().__init__(f"page {page} of {page_count}")
        self.page = page
        self.page_count = page_count


def page_count(pdf_bytes: bytes) -> int:
    """How many pages the PDF has. UnreadablePdf if it cannot be opened."""
    with _lock:
        try:
            import pypdfium2

            pdf = pypdfium2.PdfDocument(pdf_bytes)
            try:
                return len(pdf)
            finally:
                pdf.close()
        except Exception as exc:
            raise UnreadablePdf(f"{type(exc).__name__}: {exc}") from exc


def render_page(pdf_bytes: bytes, page: int, *, width_px: int = WIDTH_PX) -> RenderedPage:
    """Page `page` (1-based) of a PDF as a picture, with the file's page count."""
    with _lock:
        try:
            return _render(pdf_bytes, page, width_px)
        except PageOutOfRange:
            raise
        except Exception as exc:
            raise UnreadablePdf(f"{type(exc).__name__}: {exc}") from exc


def _render(pdf_bytes: bytes, page: int, width_px: int) -> RenderedPage:
    import pypdfium2

    pdf = pypdfium2.PdfDocument(pdf_bytes)
    try:
        count = len(pdf)
        if not 1 <= page <= count:
            raise PageOutOfRange(page, count)
        pdf_page = pdf[page - 1]
        try:
            # The size as displayed: a rotated page's width is its displayed width.
            w, h = pdf_page.get_size()
            if not (w > 0 and h > 0):
                raise UnreadablePdf(f"page {page} has no size ({w} by {h})")
            scale = max(width_px / w, MIN_SCALE)
            scale = min(scale, MAX_SIDE_PX / w, MAX_SIDE_PX / h)
            # The library fills the page with opaque white by default.
            image = pdf_page.render(scale=scale).to_pil()
        finally:
            pdf_page.close()
    finally:
        pdf.close()

    if image.mode != "RGB":
        image = image.convert("RGB")
    width, height = image.size
    for name, mime, options in FORMATS:
        buf = io.BytesIO()
        try:
            image.save(buf, name, **options)
        except Exception:
            continue
        return RenderedPage(
            image=buf.getvalue(), mime=mime, page_count=count, width=width, height=height
        )
    raise UnreadablePdf("the picture could not be written in any format")
