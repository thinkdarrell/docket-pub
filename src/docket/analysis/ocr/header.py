"""Read the header text of a vote frame to decide if the vote has finalized.

The header band sits in the top ~18% of a Birmingham vote frame and shows
one of a small set of statuses:

- "Voting in Progress…" — the tally is still animating / changing; this
  frame is NOT a terminal frame and must not be parsed as a final vote.
- "Motion Passes" — terminal, yeas > nays.
- "Motion Fails" — terminal, nays > yeas.
- "Motion Tabled" — terminal, vote deferred.

Detection is deliberately fuzzy: we crop the header band, threshold to
isolate the white text, OCR with Tesseract PSM 7 (single line), then
keyword-match lowercase substrings. Anything we cannot classify returns
``HeaderState.UNKNOWN`` rather than guessing.
"""

from __future__ import annotations

from enum import Enum

import cv2
import numpy as np
import pytesseract
from PIL import Image

# --- Tuning constants ------------------------------------------------------

# Fraction of frame height consumed by the header band. The Birmingham
# title bar is taller than it looks — tuned up to 0.22 because cropping
# any tighter clips the bottoms of the letters and Tesseract starts
# reading "Passes" as "Paccac" (top half of "s" looks like "c").
HEADER_BAND_TOP = 0.0
HEADER_BAND_BOTTOM = 0.22

# White-text threshold — header text is bright white on dark gray, so a
# simple grayscale cutoff isolates it cleanly without color work.
WHITE_THRESHOLD = 160

# Upscale factor; Tesseract reads the big header font well at 2x.
HEADER_UPSCALE = 2


class HeaderState(str, Enum):
    """Discrete states a vote-screen header can be in.

    Values are stable strings — they get persisted to the ``votes.header_result``
    column and compared in cross-verification.
    """

    VOTING_IN_PROGRESS = "voting_in_progress"
    PASSED = "passed"
    FAILED = "failed"
    TABLED = "tabled"
    UNKNOWN = "unknown"

    def is_terminal(self) -> bool:
        """True when the header indicates the vote has finalized."""
        return self in (HeaderState.PASSED, HeaderState.FAILED, HeaderState.TABLED)


def read_header(frame: np.ndarray) -> HeaderState:
    """Crop the header band, OCR it, and classify the result."""
    text = _ocr_header_text(frame)
    return _classify(text)


def _ocr_header_text(frame: np.ndarray) -> str:
    h = frame.shape[0]
    y1 = int(h * HEADER_BAND_TOP)
    y2 = int(h * HEADER_BAND_BOTTOM)
    band = frame[y1:y2, :]

    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    _, white = cv2.threshold(gray, WHITE_THRESHOLD, 255, cv2.THRESH_BINARY)
    # Invert so Tesseract sees black text on white.
    inverted = cv2.bitwise_not(white)
    if HEADER_UPSCALE != 1:
        inverted = cv2.resize(
            inverted,
            (inverted.shape[1] * HEADER_UPSCALE, inverted.shape[0] * HEADER_UPSCALE),
            interpolation=cv2.INTER_CUBIC,
        )

    return pytesseract.image_to_string(
        Image.fromarray(inverted), config="--psm 7"
    ).strip()


def _classify(text: str) -> HeaderState:
    lowered = text.lower()
    # Check voting-in-progress first — it contains neither "pass" nor "fail".
    if "progress" in lowered or "voting" in lowered:
        return HeaderState.VOTING_IN_PROGRESS
    if "pass" in lowered:
        return HeaderState.PASSED
    if "fail" in lowered:
        return HeaderState.FAILED
    if "table" in lowered:
        return HeaderState.TABLED
    return HeaderState.UNKNOWN
